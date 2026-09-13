#!/usr/bin/env python3
"""The one write path the supervisor and the replay share."""
from __future__ import annotations

import json
from pathlib import Path

from kernel.schema import OpportunityStatus as S
from nodes.game_poller.tests.test_poller import FEES, mlb, sync_all
from nodes.opportunity.record import record_evaluation
from nodes.store_tuples.store import TupleStore

T = 1000.0


def test_a_priced_evaluation_lands_with_the_venues_own_hurdle(tmp_path: Path):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    p = mlb()
    sync_all(p, kh=0.44, ka=0.99, ph=0.99, pa=0.44)
    ev = p.on_event("kalshi", "K_H", now=T)[-1]        # the 100-contract rung (the venues' smallest size, 3, is priced first since 2026-09-07)
    rec = record_evaluation(store, ev, league="mlb", fee_params=FEES, hurdle=0.01)
    assert rec.status is S.PROFITABLE_UNEXECUTED and rec.wrote
    row = store.con.execute("SELECT status, gross, cost, required_ask_sum, cents_from_actionable, legs_json "
                            "FROM stream_evaluations").fetchone()
    assert row[0] == "PROFITABLE_UNEXECUTED" and abs(row[1] - 0.88) < 1e-9
    # the hurdle was priced through the SAME 0.5x / 0.05 schedules as the cover, so the distance
    # to actionable is consistent with the cover's own cost
    assert row[3] is not None and row[4] < 0, "already past actionable: negative distance"
    assert '"kalshi"' in row[5] and '"polymarket"' in row[5]
    assert not record_evaluation(store, ev, league="mlb", fee_params=FEES, hurdle=0.01).wrote, "gated"


def test_a_blocked_evaluation_lands_with_its_reason(tmp_path: Path):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    p = mlb()
    ev = p.on_event("kalshi", "K_H", now=T)[0]
    rec = record_evaluation(store, ev, league="mlb", fee_params=FEES, hurdle=0.01)
    assert rec.status is S.BLOCKED_STALE and rec.cost is None and rec.wrote
    assert store.con.execute("SELECT blocked_by FROM stream_evaluations").fetchone()[0]


def _single_venue_best(kh=0.40, ka=0.45, ph=0.60, pa=0.62):
    """Books on which the CHEAPEST cover is both legs on Kalshi: the branch that produces
    BLOCKED_MATCH and, until L98, wrote that unsendable cover's numbers into the row."""
    p = mlb()
    sync_all(p, kh=kh, ka=ka, ph=ph, pa=pa)
    ev = p.on_event("kalshi", "K_H", now=T)[-1]
    assert ev.cover.ok and ev.cover.single_venue, "fixture must produce a single-venue best"
    return p, ev


def test_a_single_venue_best_records_the_cover_the_lane_could_actually_send(tmp_path: Path):
    """L98: the row's gross / required_ask_sum / cents_from_actionable must describe the two-venue
    cover the send path would route, not the intra-venue best that can never leave the building."""
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    _p, ev = _single_venue_best()
    rec = record_evaluation(store, ev, league="mlb", fee_params=FEES, hurdle=0.01)
    assert rec.status is S.BLOCKED_MATCH, "L98 must not change what is blocked"
    sendable = ev.sendable_cover()
    assert sendable.ok and not sendable.single_venue
    row = store.con.execute("SELECT status, gross, cost, fees, return_locked, required_ask_sum, "
                            "cents_from_actionable, legs_json FROM stream_evaluations").fetchone()
    assert row[0] == "BLOCKED_MATCH"
    assert abs(row[1] - sendable.gross_per_contract) < 1e-12, "gross must be the sendable cover's"
    assert abs(row[2] - sendable.cost_per_contract) < 1e-12, "cost must be the sendable cover's"
    # the intra-venue best was CHEAPER, which is exactly why it used to win the row
    assert ev.cover.gross_per_contract < sendable.gross_per_contract
    # and the distance-to-actionable must flip sign: the single-venue read said "already past it"
    assert row[6] > 0, "the sendable cover is SHORT of actionable"
    assert '"polymarket"' in row[7] and '"kalshi"' in row[7]


def test_the_single_venue_best_survives_as_a_control_not_as_the_answer(tmp_path: Path):
    """The intra-venue cover is L1's no-arb control and must stay legible on the row -- beside the
    tradeable numbers, never on top of them."""
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    _p, ev = _single_venue_best()
    rec = record_evaluation(store, ev, league="mlb", fee_params=FEES, hurdle=0.01)
    assert rec.control_cost is not None
    assert abs(rec.control_cost - ev.cover.cost_per_contract) < 1e-12
    legs = json.loads(store.con.execute("SELECT legs_json FROM stream_evaluations").fetchone()[0])
    ctl = [l for l in legs if l.get("control") == "single_venue"]
    assert len(ctl) == 1, legs
    assert ctl[0]["venues"] == ["kalshi"]
    assert abs(ctl[0]["gross"] - ev.cover.gross_per_contract) < 1e-6
    assert abs(ctl[0]["cost"] - ev.cover.cost_per_contract) < 1e-6
    # the tradeable legs are the other entries, and they span the two venues
    assert {l["venue"] for l in legs if "control" not in l} == {"kalshi", "polymarket"}


def test_the_hurdle_on_a_reptriced_row_is_charged_against_cross_venue_prices(tmp_path: Path):
    """`cents_from_actionable` used to charge the Kalshi+Polymarket fee curve against the favourite
    leg of an all-Kalshi cover. The anchor price must come from the cover being measured."""
    from nodes.fees.targeting import hurdle_for
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    _p, ev = _single_venue_best()
    record_evaluation(store, ev, league="mlb", fee_params=FEES, hurdle=0.01)
    row = store.con.execute("SELECT required_ask_sum, gross, cents_from_actionable "
                            "FROM stream_evaluations").fetchone()
    sendable = ev.sendable_cover()
    want = hurdle_for(max(l.vwap for l in sendable.legs), hurdle=0.01,
                      overrides_a=FEES["kalshi"], overrides_b=FEES["polymarket"])
    assert abs(row[0] - want.required_ask_sum) < 1e-12
    stale = hurdle_for(max(l.vwap for l in ev.cover.legs), hurdle=0.01,
                       overrides_a=FEES["kalshi"], overrides_b=FEES["polymarket"])
    assert abs(row[0] - stale.required_ask_sum) > 1e-9, "must not be the intra-venue anchor's hurdle"
    assert abs(row[2] - round((row[1] - row[0]) * 100.0, 4)) < 1e-9


def test_a_cross_venue_best_is_not_repriced_and_its_row_is_byte_identical(tmp_path: Path):
    """The gate: ~24 % of rows already price a sendable cover and must not pay for a second
    best_cover call, nor change by a single field."""
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    p = mlb()
    sync_all(p, kh=0.44, ka=0.99, ph=0.99, pa=0.44)
    ev = p.on_event("kalshi", "K_H", now=T)[-1]
    assert ev.cover.ok and not ev.cover.single_venue
    calls = []
    original = ev.sendable_cover

    def spy():
        calls.append(1)
        return original()

    object.__setattr__(ev, "sendable_cover", spy)
    rec = record_evaluation(store, ev, league="mlb", fee_params=FEES, hurdle=0.01)
    assert calls == [], "a sendable best must not be re-priced"
    assert rec.control_cost is None
    assert rec.status is S.PROFITABLE_UNEXECUTED
    row = store.con.execute("SELECT gross, cost FROM stream_evaluations").fetchone()
    assert abs(row[0] - 0.88) < 1e-9 and abs(row[1] - ev.cover.cost_per_contract) < 1e-12


def test_no_sendable_cover_records_no_number_rather_than_an_unsendable_one(tmp_path: Path):
    """When the books hold a single-venue cover and no two-venue one, the honest row is NULL
    telemetry plus the control -- not the intra-venue cover's numbers wearing tradeable labels."""
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    _p, ev = _single_venue_best()
    object.__setattr__(ev, "sendable_cover", lambda: None)
    rec = record_evaluation(store, ev, league="mlb", fee_params=FEES, hurdle=0.01)
    assert rec.status is S.BLOCKED_MATCH and rec.gross is None and rec.cost is None
    assert rec.control_cost is not None
    row = store.con.execute("SELECT gross, cost, required_ask_sum, cents_from_actionable, legs_json "
                            "FROM stream_evaluations").fetchone()
    assert row[0] is None and row[1] is None and row[2] is None and row[3] is None
    assert json.loads(row[4])[0]["control"] == "single_venue"
