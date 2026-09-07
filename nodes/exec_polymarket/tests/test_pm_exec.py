#!/usr/bin/env python3
"""Every outcome is its own token; matched is not settled; the library is optional until live."""
from __future__ import annotations

from pathlib import Path

import pytest

from kernel.execution_protocol import OrderRequest
from kernel.schema import FillState, Mode
from nodes.exec_polymarket.client import PolymarketExecution, PyClobTransport, TransportUnavailable
from nodes.execution.journal import Journal
from nodes.execution.testing import clearance_for
from nodes.store_tuples.store import TupleStore

T = 1000.0


class FakeTransport:
    def __init__(self, posts=(), orders=(), trades=()):
        self.posts, self.orders, self.tr = list(posts), list(orders), list(trades)
        self.calls = []
    def post_order(self, *, token_id, price, size, order_type):
        self.calls.append(("post", token_id, price, size, order_type))
        out = self.posts.pop(0)
        if isinstance(out, Exception): raise out
        return out
    def get_order(self, order_id):
        self.calls.append(("get", order_id)); return self.orders.pop(0)
    def cancel(self, order_id):
        self.calls.append(("cancel", order_id)); return {}
    def trades(self, *, after_ts): return list(self.tr)
    def balance_usd(self): return 123.0
    def cancel_all(self): return 0


def venue(tmp_path, tr, mode=Mode.LIMITED_LIVE):
    j = Journal(TupleStore(tmp_path / "t.sqlite", enforce_volume=False))
    return PolymarketExecution(tr, j, mode, clock=lambda: T), j


def req(**kw):
    base = dict(venue="polymarket", market_id="tok-1", outcome_id="home", side="buy_yes", price=0.44,
                contracts=10.0, time_in_force="fok", client_order_id="c1", opportunity_id="o1")
    base.update(kw)
    return OrderRequest(**base)


def cl(tmp_path):
    return clearance_for(tmp_path, mode=Mode.LIMITED_LIVE)


def test_buy_no_is_refused_with_the_explanation(tmp_path):
    v, j = venue(tmp_path, FakeTransport())
    ack = v.submit(req(side="buy_no"), cl(tmp_path))
    assert ack.state is FillState.REJECTED and "separate tokens" in ack.detail and j.get("c1") is None


def test_a_fok_match_is_confirmed_through_status_at_the_venues_size(tmp_path):
    """CLOB V2 fills a BUY by notional: the first real fill (2026-09-07) asked 5 @ 0.39 and got
    5.131577 @ 0.38. A match is therefore UNCONFIRMED until status() reports the venue's size;
    hedging the request size would have left the improvement unhedged."""
    tr = FakeTransport(posts=[{"success": True, "orderID": "0xabc", "status": "matched", "tradeIDs": ["t1"]}],
                       orders=[{"id": "0xabc", "status": "MATCHED", "size_matched": "10.263157", "price": "0.43"}])
    v, j = venue(tmp_path, tr)
    ack = v.submit(req(), cl(tmp_path))
    assert ack.state is FillState.UNCONFIRMED and ack.settlement_pending and "size via status" in ack.detail
    assert tr.calls[0] == ("post", "tok-1", 0.44, 10.0, "FOK")
    st = v.status("c1")
    assert st.state is FillState.FILLED and st.final and st.filled_contracts == 10.263157 and st.avg_price == 0.43
    assert j.get("c1")["state"] == "FILLED"


def test_a_taker_fill_the_venue_reports_without_a_fee_carries_the_pinned_fee(tmp_path):
    """The venue charged the taker fee against collateral and reported fee_rate_bps 0 on the trade
    (2026-09-07: balance moved by fills + exactly the pinned 0.0604). With fee params known, the fill
    carries the pinned fee, labelled; without them it stays 0."""
    tr = FakeTransport(trades=[{"id": "t1", "taker_order_id": "0xabc", "size": "5.131577", "price": "0.38",
                                "fee_rate_bps": "0", "trader_side": "TAKER", "match_time": T, "status": "CONFIRMED"}])
    v, j = venue(tmp_path, tr)
    assert v.fills(since_utc=0)[0].fee_usd == 0.0 and v.last_fee_source == "venue"
    v.fee_params = {"fee_rate": 0.05, "fee_exponent": 1.0, "taker_only": True, "rebate_rate": 0.15}
    f = v.fills(since_utc=0)[0]
    assert f.fee_usd > 0 and v.last_fee_source.startswith("pinned")


def test_a_fak_match_is_unconfirmed_until_status_reports_the_size(tmp_path):
    tr = FakeTransport(posts=[{"success": True, "orderID": "0xabc", "status": "matched"}],
                       orders=[{"id": "0xabc", "status": "MATCHED", "size_matched": "6", "price": "0.44"}])
    v, j = venue(tmp_path, tr)
    ack = v.submit(req(time_in_force="ioc"), cl(tmp_path))
    assert ack.state is FillState.UNCONFIRMED
    st = v.status("c1")
    assert st.state is FillState.PARTIAL and st.filled_contracts == 6.0 and st.final and st.settlement_pending


def test_a_rejection_and_a_transport_failure_are_different_facts(tmp_path):
    v, j = venue(tmp_path, FakeTransport(posts=[{"success": False, "errorMsg": "not enough balance / allowance"}]))
    ack = v.submit(req(), cl(tmp_path))
    assert ack.state is FillState.REJECTED and "allowance" in ack.detail
    v2, j2 = venue(tmp_path / "b", FakeTransport(posts=[TimeoutError("slow")]))
    ack2 = v2.submit(req(), cl(tmp_path / "b"))
    assert ack2.state is FillState.UNCONFIRMED and j2.get("c1")["state"] == "UNCONFIRMED" and v2.unconfirmed == 1


def test_only_confirmed_trades_are_final_and_failed_ones_are_not_fills(tmp_path):
    tr = FakeTransport(trades=[{"id": "t1", "taker_order_id": "0xabc", "size": "10", "price": "0.44", "fee_rate_bps": "500",
                                "status": "MATCHED", "trader_side": "TAKER", "match_time": "999"},
                               {"id": "t2", "taker_order_id": "0xabc", "size": "10", "price": "0.44", "fee_rate_bps": "500",
                                "status": "CONFIRMED", "trader_side": "TAKER", "match_time": "999"},
                               {"id": "t3", "taker_order_id": "0xdef", "size": "5", "price": "0.5", "fee_rate_bps": "500",
                                "status": "FAILED", "trader_side": "TAKER", "match_time": "999"}])
    v, j = venue(tmp_path, tr)
    fs = v.fills(since_utc=0)
    assert [(f.fill_id, f.final) for f in fs] == [("t1", False), ("t2", True)]
    assert fs[1].fee_usd == pytest.approx(10 * 0.44 * 0.05)
    assert v.balance().available_usd == 123.0


def test_the_mode_gate_and_the_optional_library(tmp_path, monkeypatch):
    v, _ = venue(tmp_path, FakeTransport(), mode=Mode.DEMO_EXECUTION)
    assert v.submit(req(), clearance_for(tmp_path, mode=Mode.DEMO_EXECUTION)).raw_status == "MODE", \
        "Polymarket has no demo: a real order needs LIMITED_LIVE"
    import builtins
    real = builtins.__import__
    def no_clob(name, *a, **k):
        if name.startswith("py_clob_client"):
            raise ImportError(name)
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_clob)
    with pytest.raises(TransportUnavailable, match="pip install"):
        PyClobTransport()
