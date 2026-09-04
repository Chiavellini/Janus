#!/usr/bin/env python3
"""Nothing is believed until the venue says it; nothing is released until both have."""
from __future__ import annotations

from pathlib import Path

import pytest

from kernel.execution_protocol import FillRecord, OrderRequest
from kernel.schema import FillState
from nodes.execution.journal import Journal
from nodes.reconcile.reconcile import check_fees, releasable, resolve_unconfirmed, settle
from nodes.store_tuples.store import TupleStore


class V:
    def __init__(self, venue, state): self.venue, self.state = venue, state
    def status(self, cid):
        from kernel.execution_protocol import OrderState
        return OrderState(self.venue, cid, "v", self.state, 10.0 if self.state is FillState.FILLED else 0.0,
                          0.44, 0.1, self.state.value, 1.0, final=self.state is not FillState.UNCONFIRMED)


def test_unconfirmed_orders_are_asked_about_and_an_unresolved_poll_stays_unconfirmed(tmp_path: Path):
    j = Journal(TupleStore(tmp_path / "t.sqlite", enforce_volume=False))
    for cid, venue in (("a", "kalshi"), ("b", "polymarket"), ("c", "sxbet")):
        j.pending(OrderRequest(venue, "m", "o", "buy_yes", 0.44, 10.0, "fok", cid, "opp"), mode="PAPER_EXECUTION", now=1.0)
    got = resolve_unconfirmed(j, {"kalshi": V("kalshi", FillState.FILLED), "polymarket": V("polymarket", FillState.UNCONFIRMED)})
    assert got == {"a": "FILLED", "b": "UNCONFIRMED", "c": "UNCONFIRMED"}


def test_a_fee_above_the_pinned_curve_is_a_stop(tmp_path: Path):
    j = Journal(TupleStore(tmp_path / "t.sqlite", enforce_volume=False))
    fees = {"kalshi": {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 0.5}}
    # quadratic_with_maker_fees: the venue charges the full 0.07 (production fill 2026-09-04), so the
    # pin for 100 @ 0.50 is $1.75 exactly; a charge at or under it is fine, a cent over is a STOP.
    ok = FillRecord("kalshi", "v1", "f1", 100.0, 0.50, 1.75, True, 1.0, True)
    dear = FillRecord("kalshi", "v1", "f2", 100.0, 0.50, 1.76, True, 1.0, True)
    f = check_fees(j, [ok, dear], fees)
    assert not f[0].stop and f[0].pinned_usd == pytest.approx(1.75)
    assert f[1].stop and f[1].excess_usd == pytest.approx(0.01)


def test_settlement_uses_each_venues_own_result_and_a_no_leg_wins_when_its_ticker_loses():
    legs = [{"venue": "polymarket", "client_order_id": "a", "outcome_id": "P_H", "side": "buy_yes",
             "contracts": 100.0, "price": 0.44, "fee_usd": 1.1, "state": "FILLED", "final": True},
            {"venue": "kalshi", "client_order_id": "b", "outcome_id": "K_A:NO", "side": "buy_no",
             "contracts": 100.0, "price": 0.44, "fee_usd": 0.88, "state": "FILLED", "final": True}]
    r = settle(legs=legs, winners={"polymarket": "P_H", "kalshi": "K_H"}, now=1.0)
    assert r[0].realized_usd == pytest.approx(100 - 44 - 1.1)
    assert r[1].realized_usd == pytest.approx(100 - 44 - 0.88), "NO on K_A pays when K_A did not win"
    assert releasable(r)
    r2 = settle(legs=legs, winners={"polymarket": "P_H"}, now=1.0)          # Kalshi has not settled yet
    assert r2[1].state is FillState.UNCONFIRMED and not releasable(r2)
    r3 = settle(legs=[{**legs[0], "final": False}], winners={"polymarket": "P_H"}, now=1.0)
    assert r3[0].state is FillState.UNCONFIRMED, "a Polymarket fill not yet CONFIRMED on-chain is not realized"



def test_a_polymarket_no_leg_wins_when_its_yes_twin_loses():
    legs = [{"venue": "polymarket", "client_order_id": "a", "outcome_id": "P_H:NO", "side": "buy_yes",
             "contracts": 100.0, "price": 0.50, "fee_usd": 1.0, "state": "FILLED", "final": True},
            {"venue": "kalshi", "client_order_id": "b", "outcome_id": "K_H", "side": "buy_yes",
             "contracts": 100.0, "price": 0.40, "fee_usd": 1.0, "state": "FILLED", "final": True}]
    draw = settle(legs=legs, winners={"polymarket": "P_D", "kalshi": "K_D"})
    assert draw[0].realized_usd == 100 - 50 - 1 and draw[1].realized_usd == -40 - 1
    home = settle(legs=legs, winners={"polymarket": "P_H", "kalshi": "K_H"})
    assert home[0].realized_usd == -50 - 1 and home[1].realized_usd == 100 - 40 - 1
