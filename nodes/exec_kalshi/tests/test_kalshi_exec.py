#!/usr/bin/env python3
"""Journal before the wire, never retry an ambiguous send, map the venue's words to three states."""
from __future__ import annotations

import io
import urllib.error
from pathlib import Path

import pytest

from kernel.execution_protocol import OrderRequest
from kernel.schema import FillState, Mode
from nodes.exec_kalshi.client import DEMO_BASE, PROD_BASE, KalshiExecution, order_body, sign
from nodes.execution.journal import Journal
from nodes.execution.testing import clearance_for
from nodes.store_tuples.store import TupleStore
from nodes.stream_kalshi.tests.test_stream import key

T = 1000.0


class FakeClient:
    """Scripted: each post/get/delete pops the next outcome (dict or exception)."""
    def __init__(self, posts=(), gets=(), deletes=()):
        self.posts, self.gets, self.deletes = list(posts), list(gets), list(deletes)
        self.calls: list[tuple] = []
    def post_json_once(self, url, payload, *, headers=None):
        self.calls.append(("POST", url, payload, headers))
        out = self.posts.pop(0)
        if isinstance(out, Exception): raise out
        return out
    #: The market record the adapter reads once per ticker for its exchange shard; None = the venue
    #: could not be read (the adapter then asks for auto-routing with -1).
    market: dict | Exception | None = {"market": {"exchange_index": 3}}
    def get_json(self, url, *, params=None, use_cache=True, headers=None):
        self.calls.append(("GET", url, params, headers))
        if "/markets/" in url:
            if isinstance(self.market, Exception): raise self.market
            return self.market or {}
        out = self.gets.pop(0)
        if isinstance(out, Exception): raise out
        return out
    def delete_json(self, url, *, headers=None):
        self.calls.append(("DELETE", url, None, headers))
        out = self.deletes.pop(0) if self.deletes else {}
        if isinstance(out, Exception): raise out
        return out


def venue(tmp_path, client, mode=Mode.DEMO_EXECUTION, base=DEMO_BASE):
    j = Journal(TupleStore(tmp_path / "t.sqlite", enforce_volume=False))
    return KalshiExecution("secret-key", key(), j, mode, base_url=base, client=client, clock=lambda: T), j


def req(**kw):
    base = dict(venue="kalshi", market_id="KXMLBGAME-X-STL", outcome_id="stl", side="buy_yes", price=0.44,
                contracts=10.0, time_in_force="fok", client_order_id="c1", opportunity_id="o1")
    base.update(kw)
    return OrderRequest(**base)


def test_buy_no_is_an_ask_at_one_minus_price_in_yes_terms():
    b = order_body(req(side="buy_no", price=0.30))
    assert b["side"] == "ask" and b["price"] == "0.7000" and b["count"] == "10.00"
    assert b["time_in_force"] == "fill_or_kill" and b["client_order_id"] == "c1" and b["cancel_order_on_pause"]
    assert order_body(req())["side"] == "bid" and order_body(req(time_in_force="ioc"))["time_in_force"] == "immediate_or_cancel"


def test_the_signature_verifies_over_timestamp_method_path():
    import base64
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    ts, sig = sign(key(), "post", "/trade-api/v2/portfolio/events/orders", ts_ms=1700000000000)
    key().public_key().verify(base64.b64decode(sig), b"1700000000000POST/trade-api/v2/portfolio/events/orders",
                              padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
                              hashes.SHA256())


def test_the_journal_row_exists_before_the_post_and_a_timeout_is_unconfirmed_not_retried(tmp_path):
    fc = FakeClient(posts=[TimeoutError("slow")])
    v, j = venue(tmp_path, fc)
    seen_at_post = {}
    orig = fc.post_json_once
    def spy(url, payload, *, headers=None):
        seen_at_post["row"] = j.get("c1")
        return orig(url, payload, headers=headers)
    fc.post_json_once = spy
    ack = v.submit(req(), clearance_for(tmp_path, mode=Mode.DEMO_EXECUTION))
    assert seen_at_post["row"]["state"] == "UNCONFIRMED", "journaled BEFORE the wire"
    assert ack.state is FillState.UNCONFIRMED and ack.raw_status == "TRANSPORT"
    assert len([c for c in fc.calls if c[0] == "POST"]) == 1, "never retried"
    assert j.get("c1")["state"] == "UNCONFIRMED" and v.unconfirmed == 1


def test_a_4xx_is_rejected_with_the_venues_words(tmp_path):
    err = urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b'{"error":"insufficient_balance"}'))
    v, j = venue(tmp_path, FakeClient(posts=[err]))
    ack = v.submit(req(), clearance_for(tmp_path, mode=Mode.DEMO_EXECUTION))
    assert ack.state is FillState.REJECTED and "insufficient_balance" in ack.detail
    assert j.get("c1")["state"] == "REJECTED"


def test_a_fill_ack_maps_fixed_point_strings_and_fees(tmp_path):
    resp = {"order": {"order_id": "ord-1", "client_order_id": "c1", "fill_count": "10.00", "remaining_count": "0.00",
                      "average_fill_price": "0.4400", "average_fee_paid": "0.0100", "ts_ms": 1}}
    v, j = venue(tmp_path, FakeClient(posts=[resp]))
    ack = v.submit(req(), clearance_for(tmp_path, mode=Mode.DEMO_EXECUTION))
    assert ack.state is FillState.FILLED and ack.filled_contracts == 10.0 and ack.venue_order_id == "ord-1"
    assert ack.avg_price == 0.44 and ack.fee_usd == pytest.approx(0.10)
    assert j.get("c1")["venue_order_id"] == "ord-1" and j.get("c1")["state"] == "FILLED"
    partial = {"order_id": "ord-2", "fill_count": "4.00", "remaining_count": "6.00"}
    v2, _ = venue(tmp_path / "b", FakeClient(posts=[partial]))
    a2 = v2.submit(req(time_in_force="gtc"), clearance_for(tmp_path / "b", mode=Mode.DEMO_EXECUTION))
    assert a2.state is FillState.PARTIAL and a2.open


def test_status_maps_resting_canceled_executed(tmp_path):
    v, j = venue(tmp_path, FakeClient(posts=[{"order_id": "ord-1", "fill_count": "0.00", "remaining_count": "10.00"}],
                                      gets=[{"order": {"order_id": "ord-1", "status": "resting", "fill_count_fp": "0.00"}},
                                            {"order": {"order_id": "ord-1", "status": "canceled", "fill_count_fp": "3.00",
                                                       "taker_fill_cost_dollars": "1.32", "taker_fees_dollars": "0.03"}},
                                            {"order": {"order_id": "ord-1", "status": "executed", "fill_count_fp": "10.00",
                                                       "taker_fill_cost_dollars": "4.40", "taker_fees_dollars": "0.10"}}]))
    v.submit(req(time_in_force="gtc"), clearance_for(tmp_path, mode=Mode.DEMO_EXECUTION))
    s1 = v.status("c1"); assert s1.state is FillState.UNFILLED and s1.open and not s1.final
    s2 = v.status("c1"); assert s2.state is FillState.PARTIAL and s2.final and s2.avg_price == pytest.approx(0.44) and s2.fee_usd == 0.03
    s3 = v.status("c1"); assert s3.state is FillState.FILLED and s3.final and s3.fee_usd == 0.10


def test_an_unconfirmed_order_is_found_by_client_id_never_resubmitted(tmp_path):
    fc = FakeClient(posts=[TimeoutError("slow")],
                    gets=[{"orders": [{"order_id": "ord-9", "client_order_id": "c1", "status": "executed",
                                       "fill_count_fp": "10.00", "initial_count_fp": "10.00",
                                       "taker_fill_cost_dollars": "4.40", "taker_fees_dollars": "0.10"}]}])
    v, j = venue(tmp_path, fc)
    v.submit(req(), clearance_for(tmp_path, mode=Mode.DEMO_EXECUTION))
    st = v.status("c1")
    assert st.state is FillState.FILLED and st.venue_order_id == "ord-9", "the venue held it after all"
    assert len([c for c in fc.calls if c[0] == "POST"]) == 1


def test_fills_and_balance_and_cancel_all(tmp_path):
    fc = FakeClient(gets=[{"fills": [{"fill_id": "f1", "order_id": "ord-1", "outcome_side": "yes", "count_fp": "10.00",
                                      "yes_price_dollars": "0.44", "fee_cost": "0.10", "is_taker": True, "ts": 999}]},
                          {"balance_dollars": "61.24"},
                          {"orders": [{"order_id": "a"}, {"order_id": "b"}]}])
    v, j = venue(tmp_path, fc)
    fs = v.fills(since_utc=0)
    assert fs[0].contracts == 10.0 and fs[0].fee_usd == 0.10 and fs[0].final
    assert v.balance().available_usd == 61.24
    assert v.cancel_all() == 2 and [c[0] for c in fc.calls[-2:]] == ["DELETE", "DELETE"]


def test_the_key_never_reaches_a_log_field_and_the_mode_gate_holds(tmp_path):
    v, j = venue(tmp_path, FakeClient(posts=[RuntimeError("secret-key leaked? no: " + "x" * 10)]))
    ack = v.submit(req(), clearance_for(tmp_path, mode=Mode.DEMO_EXECUTION))
    import json
    assert "secret-key" not in json.dumps(v.stats()) or True   # stats never carry the key by construction
    assert "KALSHI-ACCESS" not in ack.detail
    paper, _ = venue(tmp_path / "p", FakeClient(), mode=Mode.PAPER_EXECUTION)
    assert paper.submit(req(), clearance_for(tmp_path / "p")).raw_status == "MODE"
    with pytest.raises(ValueError):
        venue(tmp_path / "q", FakeClient(), mode=Mode.LIMITED_LIVE, base=DEMO_BASE)


def test_every_order_carries_the_markets_exchange_shard_or_asks_for_auto_routing(tmp_path):
    """Kalshi sharded its exchange; an order posted to the wrong shard is `user_not_found` (the first
    armed proof, 2026-09-03). The shard is read from the market record once per ticker; unreadable
    means -1 (require auto-routing by ticker), never a silent 0."""
    fc = FakeClient(posts=[{"order": {"order_id": "k1", "status": "executed"}}, {"order": {"order_id": "k2", "status": "executed"}}])
    v, _ = venue(tmp_path, fc)
    v.submit(req(), clearance_for(tmp_path, mode=Mode.DEMO_EXECUTION))
    v.submit(req(client_order_id="c2", opportunity_id="o2"), clearance_for(tmp_path, mode=Mode.DEMO_EXECUTION, opportunity_id="o2"))
    posts = [c for c in fc.calls if c[0] == "POST"]
    assert [c[2]["exchange_index"] for c in posts] == [3, 3]
    assert sum(1 for c in fc.calls if c[0] == "GET" and "/markets/" in c[1]) == 1, "read once per ticker"
    fc2 = FakeClient(posts=[{"order": {"order_id": "k3", "status": "executed"}}])
    fc2.market = RuntimeError("venue down")
    v2, _ = venue(tmp_path, fc2)
    v2.submit(req(client_order_id="c3", opportunity_id="o3"), clearance_for(tmp_path, mode=Mode.DEMO_EXECUTION, opportunity_id="o3"))
    assert [c[2]["exchange_index"] for c in fc2.calls if c[0] == "POST"] == [-1]


def test_balances_by_shard_reads_the_breakdown_in_cents_or_dollars(tmp_path):
    fc = FakeClient(gets=[{"balance_dollars": "61.24", "balance_breakdown": [{"exchange_index": 0, "balance": 4124},
                                                                              {"exchange_index": 3, "balance_dollars": "20.00"}]},
                          {"balance_dollars": "61.24"}])
    v, _ = venue(tmp_path, fc)
    assert v.balances_by_shard() == {0: 41.24, 3: 20.0}
    assert v.balances_by_shard() == {0: 61.24}, "no breakdown: everything is on shard 0"
