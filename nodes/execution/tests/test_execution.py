#!/usr/bin/env python3
"""The journal is written before the wire; the clearance is consumed once; paper and shadow venues
behave like real ones from the coordinator's side."""
from __future__ import annotations

from pathlib import Path

import pytest

from kernel.execution_protocol import FillRecord, OrderRequest
from kernel.schema import Book, FillState, Mode, Quote
from nodes.execution.gate import admit
from nodes.execution.journal import Journal
from nodes.execution.paper import PaperVenue, RefusingVenue
from nodes.execution.testing import clearance_for
from nodes.store_tuples.store import TupleStore

T = 1000.0


def req(**kw):
    base = dict(venue="polymarket", market_id="tok", outcome_id="home", side="buy_yes", price=0.45,
                contracts=10.0, time_in_force="fok", client_order_id="c1", opportunity_id="o1")
    base.update(kw)
    return OrderRequest(**base)


@pytest.fixture
def journal(tmp_path):
    return Journal(TupleStore(tmp_path / "t.sqlite", enforce_volume=False))


def test_an_order_request_refuses_nonsense_before_it_can_be_journaled():
    with pytest.raises(ValueError):
        req(side="sell")
    with pytest.raises(ValueError):
        req(price=1.0)
    with pytest.raises(ValueError):
        req(client_order_id="")


def test_pending_is_journaled_as_unconfirmed_and_a_duplicate_id_is_refused(journal):
    journal.pending(req(), mode="PAPER_EXECUTION", now=T)
    row = journal.get("c1")
    assert row["state"] == "UNCONFIRMED" and row["submitted_utc"] == T
    with pytest.raises(ValueError, match="already journaled"):
        journal.pending(req(), mode="PAPER_EXECUTION", now=T + 1)
    assert [r["client_order_id"] for r in journal.unconfirmed()] == ["c1"]


def test_a_later_authoritative_fill_read_repairs_the_fee_fifo(journal):
    """Polymarket can first report fee 0 and later be priced by the event's pinned schedule.
    Re-reading the same fill id must repair accounting, not preserve the first incomplete row."""
    first = FillRecord("polymarket", "o1", "f1", 10.0, 0.63, 0.0, True, T, False,
                       market_id="tok", side="buy_yes")
    corrected = FillRecord("polymarket", "o1", "f1", 10.0, 0.63, 0.11655, True, T, True,
                           market_id="tok", side="buy_yes")
    journal.record_fill(first)
    journal.record_fill(corrected)
    row = journal.store.con.execute(
        "SELECT contracts,price,fee_usd,is_taker,ts,final FROM venue_fills WHERE fill_id='f1'"
    ).fetchone()
    assert row == pytest.approx((10.0, 0.63, 0.11655, 1, T, 1))


def test_the_gate_needs_a_live_matching_clearance_and_spends_it(tmp_path):
    c = clearance_for(tmp_path)
    r = req()
    assert admit(r, None, venue="polymarket", mode=Mode.PAPER_EXECUTION, needs=Mode.PAPER_EXECUTION).raw_status == "NO_CLEARANCE"
    assert admit(r, c, venue="polymarket", mode=Mode.SHADOW_LIVE, needs=Mode.PAPER_EXECUTION).raw_status == "MODE"
    assert admit(req(opportunity_id="other"), c, venue="polymarket", mode=Mode.PAPER_EXECUTION,
                 needs=Mode.PAPER_EXECUTION, now_mono=100.1).raw_status == "CLEARANCE_MISMATCH"
    assert admit(r, c, venue="polymarket", mode=Mode.PAPER_EXECUTION, needs=Mode.PAPER_EXECUTION, now_mono=100.1) is None
    assert admit(r, c, venue="polymarket", mode=Mode.PAPER_EXECUTION, needs=Mode.PAPER_EXECUTION, now_mono=100.2).raw_status == "CLEARANCE_SPENT"


def test_paper_fills_against_the_priced_book_and_fok_is_all_or_nothing(journal, tmp_path):
    v = PaperVenue("polymarket", journal, clock=lambda: T)
    v.books["tok"] = Book(asks=(Quote(0.44, 6.0), Quote(0.46, 6.0)), fetched_utc=T)
    ack = v.submit(req(price=0.46), clearance_for(tmp_path))
    assert ack.state is FillState.FILLED and ack.filled_contracts == 10.0
    assert ack.avg_price == pytest.approx((0.44 * 6 + 0.46 * 4) / 10)
    assert journal.get("c1")["state"] == "FILLED" and journal.get("c1")["venue_order_id"] == "paper-c1"
    fok = v.submit(req(client_order_id="c2", price=0.44, contracts=10.0), clearance_for(tmp_path))
    assert fok.state is FillState.UNFILLED, "6 at 0.44 is not 10: FOK fills nothing"
    ioc = v.submit(req(client_order_id="c3", price=0.44, contracts=10.0, time_in_force="ioc"), clearance_for(tmp_path))
    assert ioc.state is FillState.UNFILLED, "c1 consumed the 6 at 0.44 and the 4 at 0.46: nothing is left at 0.44"
    assert v.books["tok"].asks == (Quote(0.46, 2.0),), "liquidity is consumed, as on a real book"
    assert v.status("c1").final and v.fills(since_utc=0)[0].final


def test_paper_adverse_move_is_applied_and_labelled_by_the_frontier_elsewhere(journal, tmp_path):
    v = PaperVenue("kalshi", journal, clock=lambda: T, adverse_move=0.02)
    v.books["K"] = Book(asks=(Quote(0.44, 100.0),), fetched_utc=T)
    assert v.submit(req(venue="kalshi", market_id="K", price=0.45), clearance_for(tmp_path)).state is FillState.UNFILLED
    assert v.submit(req(venue="kalshi", market_id="K", price=0.46, client_order_id="c2"),
                    clearance_for(tmp_path)).avg_price == pytest.approx(0.46)


def test_shadow_records_the_intent_and_sends_nothing(journal, tmp_path):
    v = RefusingVenue("kalshi", journal, clock=lambda: T)
    ack = v.submit(req(venue="kalshi", market_id="K"), clearance_for(tmp_path))
    assert ack.state is FillState.REJECTED and ack.raw_status == "SHADOW" and v.intents == 1
    assert journal.get("c1")["state"] == "REJECTED" and journal.get("c1")["mode"] == "SHADOW_LIVE"
    assert v.balance() is None and v.fills(since_utc=0) == []
