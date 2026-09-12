#!/usr/bin/env python3
"""Every outcome is its own token; matched is not settled; the library is optional until live."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from kernel.execution_protocol import OrderRequest
from kernel.schema import FillState, Mode
from nodes.exec_polymarket.client import PolymarketExecution, PolymarketUserStream, PyClobTransport, TransportUnavailable
from nodes.execution.journal import Journal
from nodes.execution.testing import clearance_for
from nodes.store_tuples.store import TupleStore

T = 1000.0


class FakeTransport:
    def buy_contract_cap_error(self):
        # Scripted offline transport: permits exercising historical response handling.
        # The real PyClobTransport always refuses the unbounded BUY wire.
        return None
    def __init__(self, posts=(), orders=(), trades=(), user_orders=()):
        self.posts, self.orders, self.tr = list(posts), list(orders), list(trades)
        self.user_orders = list(user_orders)
        self.calls = []
    def post_order(self, *, token_id, price, size, order_type, side="BUY", tick=None):
        self.calls.append(("post", token_id, price, size, order_type, side))
        out = self.posts.pop(0)
        if isinstance(out, Exception): raise out
        return out
    def get_order(self, order_id):
        self.calls.append(("get", order_id)); return self.orders.pop(0)
    def user_order(self, order_id):
        return self.user_orders.pop(0) if self.user_orders else None
    def cancel(self, order_id):
        self.calls.append(("cancel", order_id)); return {}
    def trades(self, *, after_ts): return list(self.tr)
    def balance_usd(self): return 123.0
    def cancel_all(self): return 0
    book_payload = {"bids": [{"price": "0.50", "size": "40"}, {"price": "0.55", "size": "10"}],
                    "asks": [{"price": "0.60", "size": "5"}, {"price": "0.58", "size": "20"}]}
    positions_payload = [{"asset": "tok-1", "size": "10.175", "avgPrice": "0.57"}, {"asset": "tok-9", "size": "0"}]
    allowance_calls = 0
    def book(self, token_id):
        self.calls.append(("book", token_id))
        if isinstance(self.book_payload, Exception): raise self.book_payload
        return self.book_payload
    def positions(self):
        if isinstance(self.positions_payload, Exception): raise self.positions_payload
        return self.positions_payload
    def ensure_sell_allowance(self, token_id):
        self.allowance_calls += 1; return True


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
    assert tr.calls[0] == ("post", "tok-1", 0.44, 10.0, "FOK", "BUY")
    st = v.status("c1")
    assert st.state is FillState.FILLED and st.final and st.filled_contracts == 10.263157 and st.avg_price == 0.43
    assert j.get("c1")["state"] == "FILLED"


def test_a_match_whose_response_carries_the_amounts_is_the_venues_size_at_once(tmp_path):
    """L84 (2026-09-12): LAA @ WSH answered `matched, takingAmount 32.142858, makingAmount 4.5`
    in the POST response itself; status() then took 6.4 s and gave up, and the hedge went out
    16 s later against a book that had moved. The response is the venue's size: FILLED / PARTIAL
    with the average from the two amounts, no status round trip before the hedge."""
    tr = FakeTransport(posts=[{"success": True, "orderID": "0xabc", "status": "matched",
                               "takingAmount": "32.142858", "makingAmount": "4.5"}])
    v, j = venue(tmp_path, tr)
    ack = v.submit(req(contracts=25.0, price=0.18), cl(tmp_path))
    assert ack.state is FillState.FILLED and ack.filled_contracts == 32.142858 and ack.avg_price == pytest.approx(0.14)
    assert ack.settlement_pending and "venue's response" in ack.detail
    assert not any(c[0] == "get" for c in tr.calls), "no status round trip before the hedge"
    assert j.get("c1")["state"] == "FILLED" and j.get("c1")["filled_contracts"] == 32.142858
    # a partial match reports the matched part; a SELL's shares are the making side
    tr = FakeTransport(posts=[{"orderID": "0xp", "status": "matched", "takingAmount": "7.0", "makingAmount": "3.08"},
                              {"orderID": "0xs", "status": "matched", "takingAmount": "5.5", "makingAmount": "10"}])
    v, _ = venue(tmp_path, tr)
    p = v.submit(req(contracts=10.0, price=0.44, client_order_id="p1"), cl(tmp_path))
    assert p.state is FillState.PARTIAL and p.filled_contracts == 7.0 and p.avg_price == pytest.approx(0.44)
    s = v.submit(req(side="sell_yes", price=0.55, time_in_force="ioc", client_order_id="s1", contracts=10.0), cl(tmp_path))
    assert s.state is FillState.FILLED and s.filled_contracts == 10.0 and s.avg_price == pytest.approx(0.55)
    # matched without amounts (a DELAYED answer that matched later) is still confirmed through status()
    tr = FakeTransport(posts=[{"orderID": "0xd", "status": "matched", "takingAmount": "", "makingAmount": ""}],
                       orders=[{"id": "0xd", "status": "MATCHED", "size_matched": "10", "price": "0.44"}])
    v, _ = venue(tmp_path, tr)
    d = v.submit(req(client_order_id="d1"), cl(tmp_path))
    assert d.state is FillState.UNCONFIRMED and "size via status" in d.detail


def test_a_taker_fill_the_venue_reports_without_a_fee_carries_the_pinned_fee(tmp_path):
    """The venue charged the taker fee against collateral and reported fee_rate_bps 0 on the trade
    (2026-09-07: balance moved by fills + exactly the pinned 0.0604). With fee params known, the fill
    carries the pinned fee, labelled; without them it stays 0."""
    tr = FakeTransport(trades=[{"id": "t1", "taker_order_id": "0xabc", "size": "5.131577", "price": "0.38",
                                "fee_rate_bps": "0", "trader_side": "TAKER", "match_time": T, "status": "CONFIRMED",
                                "side": "BUY", "asset_id": "tok-1", "maker_orders": [
                                    {"asset_id": "tok-1", "side": "SELL", "price": "0.38", "matched_amount": "5.131577"}]}])
    v, j = venue(tmp_path, tr)
    assert v.fills(since_utc=0)[0].fee_usd == 0.0 and "provisional" in v.last_fee_source
    v.fee_params = {"fee_rate": 0.05, "fee_exponent": 1.0, "taker_only": True, "rebate_rate": 0.15}
    f = v.fills(since_utc=0)[0]
    assert f.fee_usd > 0 and not f.final and "provisional" in v.last_fee_source


def test_live_fee_params_are_keyed_by_market_not_the_last_pollers_schedule(tmp_path):
    """One shared live client serves concurrent games whose Gamma fee schedules differ."""
    tr = FakeTransport(trades=[
        {"id": "t1", "taker_order_id": "o1", "asset_id": "tok-five", "size": "10", "price": "0.31",
         "fee_rate_bps": "0", "trader_side": "TAKER", "match_time": T, "status": "CONFIRMED"},
        {"id": "t2", "taker_order_id": "o2", "asset_id": "tok-seven", "size": "10", "price": "0.31",
         "fee_rate_bps": "0", "trader_side": "TAKER", "match_time": T, "status": "CONFIRMED"},
    ])
    for trade in tr.tr:
        trade.update(side="BUY", maker_orders=[{"asset_id": trade["asset_id"], "side": "SELL",
                                               "price": "0.31", "matched_amount": "10"}])
    v, _ = venue(tmp_path, tr)
    v.fee_params = {"fee_rate": 0.04}
    v.fee_params_by_market = {
        "tok-five": {"fee_rate": 0.05},
        "tok-seven": {"fee_rate": 0.07},
    }
    fills = v.fills(since_utc=0)
    assert fills[0].fee_usd == pytest.approx(10 * 0.05 * 0.31 * 0.69)
    assert fills[1].fee_usd == pytest.approx(10 * 0.07 * 0.31 * 0.69)


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
    assert [(f.fill_id, f.final) for f in fs] == [("t1", False), ("t2", False)], "CONFIRMED without cash is not accounting-final"
    assert fs[1].price == 1 and fs[1].fee_usd == pytest.approx(10 * 1 * 0.05), \
        "without maker legs or a journal ceiling, BUY cost uses the binary bound, not top-level .44"
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


def test_nominal_cent_exact_size_does_not_authorize_any_real_buy():
    """The old test checked SDK args only. No BUY may reach signing or posting."""
    class Client:
        def __init__(self): self.market = []; self.limit = []; self.posts = []
        def create_market_order(self, args): self.market.append(args); return "signed-market"
        def create_order(self, args): self.limit.append(args); return "signed-limit"
        def post_order(self, signed, typ, defer_exec):
            self.posts.append((signed, typ, defer_exec)); return {"status": "matched"}
    class Args:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    tr = PyClobTransport.__new__(PyClobTransport)
    tr._c = Client()
    tr._T = SimpleNamespace(OrderType=SimpleNamespace(FAK="FAK", FOK="FOK", GTC="GTC"),
                            MarketOrderArgsV2=Args, OrderArgsV2=Args)
    for order_type in ("FAK", "FOK", "GTC"):
        result = tr.post_order(token_id="tok", price=.481, size=5.0, order_type=order_type,
                               side="BUY", tick=.001)
        assert result["code"] == "QUANTITY_CAP_UNPROVEN" and result["prewire"]
    assert not tr._c.market and not tr._c.limit and not tr._c.posts


def test_dedicated_bounded_taker_signer_accepts_only_small_cent_exact_fak():
    class Args:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class Client:
        def __init__(self): self.args = None; self.posts = []
        def create_market_order(self, args): self.args = args; return "signed"
        def post_order(self, signed, typ, defer_exec):
            self.posts.append((signed, typ, defer_exec)); return {"status": "matched"}
    tr = PyClobTransport.__new__(PyClobTransport)
    tr._c = Client()
    tr._T = SimpleNamespace(OrderType=SimpleNamespace(FAK="FAK", FOK="FOK", GTC="GTC"),
                            MarketOrderArgsV2=Args)
    out = tr.post_bounded_taker_buy(token_id="tok", price=.36, size=10, order_type="FAK")
    assert out["status"] == "matched" and tr._c.args.amount == 3.6 and tr._c.args.side == "BUY"
    assert tr.post_bounded_taker_buy(token_id="tok", price=.36, size=10.01,
                                     order_type="FAK")["code"] == "BOUNDED_TAKER_CAP"
    assert tr.post_bounded_taker_buy(token_id="tok", price=.36, size=10,
                                     order_type="GTC")["code"] == "BOUNDED_TAKER_CAP"


def test_cent_exact_buy_never_increases_size_or_price_and_can_reduce_fractional_size():
    assert PyClobTransport._cent_exact_buy(size=5.0, price=.202, tick=.001) == (.202, 5.0)
    assert PyClobTransport._cent_exact_buy(size=5.24, price=.62, tick=.01) == (.62, 5.0)
    assert PyClobTransport._cent_exact_buy(size=10.0, price=.481, tick=.001) == (.481, 10.0)
    assert PyClobTransport._cent_exact_buy(size=5.26, price=.19, tick=.01) is None, \
        "do not grow quantity to cross the venue's $1 minimum"


def test_adjusted_wire_size_and_price_are_the_durable_order_record(tmp_path):
    tr = FakeTransport(posts=[{"success": False, "errorMsg": "no match"}])
    v, j = venue(tmp_path, tr)
    ack = v.submit(req(price=.481, contracts=5.0, time_in_force="ioc", tick=.001), cl(tmp_path))
    assert ack.state is FillState.REJECTED
    assert tr.calls[0] == ("post", "tok-1", .48, 5.0, "FAK", "BUY")
    assert j.get("c1")["price"] == .48 and j.get("c1")["contracts"] == 5.0


def test_impossible_cent_exact_buy_is_rejected_before_the_wire(tmp_path):
    tr = FakeTransport()
    v, j = venue(tmp_path, tr)
    ack = v.submit(req(price=.19, contracts=5.26, time_in_force="ioc", tick=.01), cl(tmp_path))
    assert ack.state is FillState.REJECTED and ack.raw_status == "PRECISION" and not tr.calls
    assert j.get("c1")["state"] == "REJECTED"


def test_a_venue_http_refusal_is_rejected_and_a_geoblock_latches(tmp_path):
    """2026-09-07, the box's first real order: 403 "Trading restricted in your region" was read as an
    ambiguous transport failure, held the reservation and polled status for 3 s."""
    class PolyApiException(Exception):
        def __init__(self, code, msg):
            super().__init__(f"PolyApiException[status_code={code}, error_message={msg!r}]")
            self.status_code = code
    v, j = venue(tmp_path, FakeTransport(posts=[PolyApiException(403, {"error": "Trading restricted in your region"})]))
    ack = v.submit(req(), cl(tmp_path))
    assert ack.state is FillState.REJECTED and ack.raw_status == "HTTP_403" and "region" in ack.detail
    assert j.get("c1")["state"] == "REJECTED" and v.unconfirmed == 0 and v.rejected_http == 1
    assert v.geoblocked and "region" in v.geoblocked
    v2, j2 = venue(tmp_path / "b", FakeTransport(posts=[PolyApiException(400, {"error": "invalid amount"})]))
    ack2 = v2.submit(req(), cl(tmp_path / "b"))
    assert ack2.state is FillState.REJECTED and ack2.raw_status == "HTTP_400" and v2.geoblocked is None
    v3, j3 = venue(tmp_path / "c", FakeTransport(posts=[PolyApiException(502, {"error": "bad gateway"})]))
    assert v3.submit(req(), cl(tmp_path / "c")).state is FillState.UNCONFIRMED, "a 5xx may still have taken the order"


def test_an_order_missing_from_both_endpoints_waits_for_finality_grace(tmp_path):
    """`not_found` alone is ambiguous: two FAKs later appeared in the trade feed."""
    v, j = venue(tmp_path, FakeTransport(posts=[{"success": True, "orderID": "0xabc", "status": "delayed"}],
                                         orders=[None, None]))
    ack = v.submit(req(), cl(tmp_path))
    assert ack.state is FillState.UNCONFIRMED and ack.open
    st = v.status("c1")
    assert st.state is FillState.UNCONFIRMED and not st.final and st.raw_status == "not_found_pending"
    v.clock = lambda: T + 121
    st = v.status("c1")
    assert st.state is FillState.UNFILLED and st.final and not st.open and st.raw_status == "not_found"


def test_a_not_found_order_is_filled_when_the_trade_feed_proves_it(tmp_path):
    tr = FakeTransport(posts=[{"success": True, "orderID": "0xabc", "status": "delayed"}], orders=[None],
                       trades=[{"id": "t1", "taker_order_id": "0xabc", "size": "10.15625", "price": "0.63",
                                "fee_rate_bps": "0", "trader_side": "TAKER", "match_time": T,
                                "status": "CONFIRMED", "asset_id": "tok-1", "side": "BUY"}])
    v, j = venue(tmp_path, tr)
    assert v.submit(req(time_in_force="ioc"), cl(tmp_path)).state is FillState.UNCONFIRMED
    st = v.status("c1")
    assert st.state is FillState.FILLED and st.filled_contracts == 10.15625 and st.avg_price == 0.44
    assert not st.final and st.settlement_pending, "fill quantity is proven but cash authority is missing"
    assert j.get("c1")["state"] == "FILLED" and j.get("c1")["filled_contracts"] == 10.15625


def test_the_authenticated_user_stream_proves_a_match_before_rest(tmp_path):
    feed = PolymarketUserStream(type("Creds", (), {"api_key": "k", "api_secret": "s", "api_passphrase": "p"})())
    assert feed.handle({"event_type": "trade", "id": "t1", "taker_order_id": "0xabc", "size": "10.15625",
                        "price": "0.63", "status": "MATCHED", "asset_id": "tok-1", "side": "BUY"}) == ["trade"]
    seen = feed.order("0xabc")
    assert seen["status"] == "MATCHED" and seen["size_matched"] == 10.15625
    assert seen["price"] is None, "without maker legs the top-level trade price is not a proven VWAP"

    tr = FakeTransport(posts=[{"success": True, "orderID": "0xabc", "status": "delayed"}],
                       orders=[None], user_orders=[seen])
    v, j = venue(tmp_path, tr)
    assert v.submit(req(time_in_force="ioc"), cl(tmp_path)).state is FillState.UNCONFIRMED
    st = v.status("c1")
    assert st.state is FillState.FILLED and st.filled_contracts == 10.15625 and st.settlement_pending
    assert not any(c[0] == "get" for c in tr.calls), "the real-time match removes the REST blind spot"


def test_the_authenticated_user_stream_proves_a_fak_zero_fill_before_rest(tmp_path):
    feed = PolymarketUserStream(type("Creds", (), {"api_key": "k", "api_secret": "s", "api_passphrase": "p"})())
    assert feed.handle({"topic": "user", "type": "order", "payload": {
        "id": "0xzero", "sizeMatched": "0", "price": "0.63", "orderType": "FAK",
        "orderEventType": "CANCELLATION", "status": "CANCELED"}}) == ["order"]
    seen = feed.order("0xzero")
    assert seen == {"id": "0xzero", "status": "CANCELED", "size_matched": 0.0,
                    "price": "0.63", "user_stream": True}

    tr = FakeTransport(posts=[{"success": True, "orderID": "0xzero", "status": "delayed"}],
                       orders=[None], user_orders=[seen])
    v, _ = venue(tmp_path, tr)
    assert v.submit(req(time_in_force="ioc"), cl(tmp_path)).state is FillState.UNCONFIRMED
    st = v.status("c1")
    assert st.state is FillState.UNFILLED and st.final and not st.settlement_pending
    assert not any(c[0] == "get" for c in tr.calls), "the cancellation removes the REST blind spot"


def test_a_sell_is_a_sell_of_the_token_after_the_allowance_and_other_sides_stay_refused(tmp_path):
    """2026-09-08: the protection layer sells a held token back (sell_yes). buy_no/sell_no are not
    Polymarket orders (each outcome is its own token) and are refused as before."""
    tr = FakeTransport(posts=[{"orderID": "o-s1", "status": "matched", "takingAmount": "5.5", "makingAmount": "10"}])
    v, j = venue(tmp_path, tr)
    ack = v.submit(req(side="sell_yes", price=0.55, time_in_force="ioc", client_order_id="s1", contracts=10.0), cl(tmp_path))
    assert tr.calls[0][:2] == ("post", "tok-1") and tr.calls[0][5] == "SELL"
    assert tr.allowance_calls == 1 and ack.state is not FillState.REJECTED
    assert j.get("s1")["side"] == "sell_yes"
    v.submit(req(side="sell_yes", price=0.55, time_in_force="ioc", client_order_id="s2"), cl(tmp_path)) if tr.posts else None
    assert tr.allowance_calls == 1, "the approval is set once per token"
    for side in ("buy_no", "sell_no"):
        a2 = v.submit(req(side=side, client_order_id=f"x-{side}"), cl(tmp_path))
        assert a2.state is FillState.REJECTED and a2.raw_status == "SIDE"


def test_orderbook_and_positions_come_from_the_transport_and_fail_to_none(tmp_path):
    tr = FakeTransport()
    v, _ = venue(tmp_path, tr)
    b = v.orderbook("tok-1", "sell_yes")
    assert [q.price for q in b.bids] == [0.55, 0.50] and [q.price for q in b.asks] == [0.58, 0.60], "best first on both sides"
    pos = v.positions()
    assert len(pos) == 1 and pos[0].market_id == "tok-1" and pos[0].contracts == 10.175 and pos[0].avg_price == 0.57
    tr.book_payload = RuntimeError("clob down"); tr.positions_payload = RuntimeError("data api down")
    assert v.orderbook("tok-1") is None and v.positions() is None


def test_fills_carry_the_asset_and_the_direction(tmp_path):
    trades = [{"id": "t1", "status": "CONFIRMED", "size": "10.175", "price": "0.57", "asset_id": "tok-1", "side": "BUY",
               "taker_order_id": "o1", "match_time": "1500", "fee_rate_bps": "0"},
              {"id": "t2", "status": "CONFIRMED", "size": "10", "price": "0.55", "asset_id": "tok-1", "side": "SELL",
               "taker_order_id": "o2", "match_time": "1600", "fee_rate_bps": "0"}]
    v, _ = venue(tmp_path, FakeTransport(trades=trades))
    fs = v.fills(since_utc=1000.0)
    assert [(f.market_id, f.side, f.contracts) for f in fs] == [("tok-1", "buy_yes", 10.175), ("tok-1", "sell_yes", 10.0)]


def test_an_immediate_order_the_engine_could_not_match_is_an_unfilled_zero_not_a_rejection(tmp_path):
    """2026-09-11 audit: two FAK submissions answered HTTP 400 "no orders found to match" sat in
    the journal as ORDER_REJECTED beside 18 economically identical ORDER_UNFILLED rows. The engine
    said nothing matched a well-formed immediate order: an authoritative zero fill. Any other 400,
    and the same text on a resting order, stay rejections."""
    class PolyApiException(Exception):
        def __init__(self, code, msg):
            super().__init__(f"PolyApiException[status_code={code}, error_message={msg!r}]")
            self.status_code = code
    v, j = venue(tmp_path, FakeTransport(posts=[PolyApiException(400, {"error": "no orders found to match"})]))
    ack = v.submit(req(time_in_force="ioc"), cl(tmp_path))
    assert ack.state is FillState.UNFILLED and ack.raw_status == "HTTP_400_NO_MATCH" and ack.filled_contracts == 0.0
    assert j.get("c1")["state"] == "UNFILLED" and v.unconfirmed == 0 and v.rejected_http == 1
    v2, j2 = venue(tmp_path / "b", FakeTransport(posts=[PolyApiException(400, {"error": "no orders found to match"})]))
    ack2 = v2.submit(req(time_in_force="gtc"), cl(tmp_path / "b"))
    assert ack2.state is FillState.REJECTED and ack2.raw_status == "HTTP_400", "a resting order is not a FAK zero fill"
    v3, j3 = venue(tmp_path / "c", FakeTransport(posts=[PolyApiException(400, {"error": "invalid amounts"})]))
    assert v3.submit(req(time_in_force="ioc"), cl(tmp_path / "c")).state is FillState.REJECTED
