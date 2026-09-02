#!/usr/bin/env python3
"""Hermetic Track B collector/report invariants. No network and no credentials."""

from __future__ import annotations

import sqlite3
import tempfile
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from collectors.collect_track_b import (  # noqa: E402
    parse_rtds_ticks, selftest as collector_selftest,
)
from collectors.track_b_core import (  # noqa: E402
    BidBook, Storage, TwoSidedBook, WindowMarket, combine_pm_books, imbalance, parse_pm_market,
)
from collectors.report_track_b import phase_a, phase_b  # noqa: E402
from lib.kilos_data import connect_ro  # noqa: E402


def test_kalshi_bids_only_fold_and_depth():
    b = BidBook()
    b.snapshot({"seq": 1, "msg": {"yes_dollars_fp": [["0.40", "3"], ["0.39", "4"]],
                                    "no_dollars_fp": [["0.55", "5"], ["0.54", "6"]]}}, 10)
    q = b.quote()
    assert q["yes_bid"] == .40 and math.isclose(q["yes_ask"], .45)
    assert q["yes_ask_size"] == 5
    assert q["yes_bid_depth_1c"] == 7
    assert q["yes_ask_depth_1c"] == 11
    assert q["quote_crossed"] == 0


def test_kalshi_delta_is_additive_and_locked_not_crossed():
    b = BidBook()
    b.snapshot({"msg": {"yes_dollars_fp": [["0.45", "2"]],
                         "no_dollars_fp": [["0.55", "3"]]}}, 10)
    assert b.quote()["quote_crossed"] == 0
    b.delta({"seq": 2, "msg": {"side": "yes", "price_dollars": "0.45",
                                  "delta_fp": "-2", "ts_ms": 11_000}}, 11)
    assert b.quote()["yes_bid"] is None


def test_imbalance_antisymmetric_under_relabel():
    value = imbalance(12, 7)
    assert abs(value + imbalance(7, 12)) < 1e-15


def test_pm_book_and_market_orientation():
    raw = {"conditionId": "c", "slug": "eth-updown-15m-1000",
           "clobTokenIds": '["down-token","up-token"]', "outcomes": '["Down","Up"]'}
    m = parse_pm_market(raw, "eth", 1000)
    assert m and m.yes_token == "up-token" and m.no_token == "down-token"
    yes, no = TwoSidedBook(), TwoSidedBook()
    yes.snapshot({"bids": [{"price": ".4", "size": "2"}],
                  "asks": [{"price": ".42", "size": "3"}], "timestamp": "10000"}, 10)
    no.snapshot({"bids": [{"price": ".58", "size": "4"}],
                 "asks": [{"price": ".6", "size": "5"}], "timestamp": "10000"}, 10)
    q = combine_pm_books(yes, no)
    assert math.isclose(q["spread"], .02) and q["no_bid"] == .58


def test_rtds_updates_and_backfills_normalize():
    live = parse_rtds_ticks({"topic": "crypto_prices_chainlink", "payload": {
        "symbol": "BTC/USD", "timestamp": 1_700_000_000_000, "value": "123.4"}}, 11)
    assert live == [("chainlink", "btc/usd", 123.4, 1_700_000_000.0, 11)]
    backfill = parse_rtds_ticks({"topic": "equity_prices", "payload": {
        "symbol": "XAUUSD", "data": [
            {"timestamp": 1_700_000_000_000, "value": 100},
            {"timestamp": 1_700_000_001_000, "value": 101, "full_accuracy_value": "101.25"},
        ]}}, 12)
    assert backfill[-1] == ("pyth", "xauusd", 101.25, 1_700_000_001.0, 12)


def test_storage_reason_codes_missing_offsets():
    with tempfile.TemporaryDirectory() as td:
        st = Storage(Path(td) / "x.sqlite")
        m = WindowMarket("kalshi", "T", "T", "KXETH15M", 100, 1000)
        st.upsert_market(m)
        st.insert_episode(m, 0, None, status="gap", reason="book_unavailable",
                          source="none", sample_ts=100)
        row = st.con.execute("SELECT status,reason FROM episodes").fetchone()
        assert tuple(row) == ("gap", "book_unavailable")
        st.close()


def test_storage_event_writes_flush_as_one_transaction():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "x.sqlite"
        st = Storage(path)
        st.insert_trade("kalshi", "T", "T", 1, 1, "yes", .5, 1, "trade-1")
        assert sqlite3.connect(path).execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0
        st.flush()
        assert sqlite3.connect(path).execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1
        st.close()


def test_reports_refuse_phase_b_before_72h_gate():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db = root / "x.sqlite"
        st = Storage(db)
        m = WindowMarket("kalshi", "T", "T", "KXETH15M", 100, 1000, asset="eth")
        st.upsert_market(m)
        st.ensure_expectations("kalshi", "KXETH15M", 100)
        quote = {"book_receive_ts": 100, "exchange_ts": 100, "yes_bid": .4,
                 "yes_ask": .5, "no_bid": .5, "no_ask": .6, "spread": .1,
                 "quote_crossed": 0}
        for off in (0, .5, 1, 2, 3, 5, 8, 13, 21, 34, 60):
            st.insert_episode(m, off, quote, status="captured", reason=None, source="fixture",
                              sample_ts=100 + off,
                              reference=("chainlink", "eth/usd", 100 + off / 100,
                                         100 + off, 100 + off))
        st.close()
        a = phase_a(db, root / "a")
        assert a["verdict"] == "PENDING_INSUFFICIENT_DURATION"
        b = phase_b(db, a, root / "b")
        assert b["verdict"] == "BLOCKED_PHASE_A"


def test_kilos_spent_episode_table_is_mechanically_denied():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "k.sqlite"
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE kalshi_open_episode_samples(x INTEGER)")
        con.execute("INSERT INTO kalshi_open_episode_samples VALUES (1)")
        con.commit(); con.close()
        ro = connect_ro(path)
        try:
            try:
                ro.execute("SELECT * FROM kalshi_open_episode_samples").fetchall()
            except sqlite3.DatabaseError as exc:
                assert any(word in str(exc).lower() for word in ("not authorized", "prohibited"))
            else:
                raise AssertionError("spent BTC episode table was readable")
        finally:
            ro.close()


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn(); print(f"PASS {fn.__name__}")
    collector_selftest()
    print(f"\n{len(tests)}/{len(tests)} passed")


if __name__ == "__main__":
    main()
