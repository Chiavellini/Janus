#!/usr/bin/env python3
"""Kalshi's wire format. Every trap here produces a confident wrong number, never an error."""
from __future__ import annotations

import pytest

from nodes.stream_kalshi.protocol import TickerBook, parse, subscribe_frame, ticker_of

SNAP = {"type": "orderbook_snapshot", "seq": 1,
        "msg": {"market_ticker": "T", "yes": [[0.40, 100], [0.39, 50]], "no": [[0.55, 200]]}}


def snap(books=None):
    books = books if books is not None else {}
    parse(SNAP, books)
    return books, books["T"]


def test_both_ladders_are_bids_and_asks_are_folded_from_the_other_side():
    """Read yes/no as bid/ask and you see half the market and invent a spread."""
    _b, t = snap()
    bids, asks = t.project("yes")
    assert bids[0] == (0.40, 100.0)
    assert asks == [(pytest.approx(0.45), 200.0)], "a NO bid at 0.55 IS a YES ask at 0.45"


def test_projecting_the_no_side_mirrors_it():
    _b, t = snap()
    bids, asks = t.project("no")
    assert bids[0] == (0.55, 200.0)
    assert asks[0][0] == pytest.approx(0.60), "best YES bid 0.40 is a NO ask at 0.60"


def test_a_delta_is_a_signed_change_not_a_new_size():
    """Treating delta as absolute silently rewrites the level to the last change."""
    books, t = snap()
    parse({"type": "orderbook_delta", "seq": 2,
           "msg": {"market_ticker": "T", "side": "yes", "price": 0.40, "delta": -30}}, books)
    assert t.yes[0.40] == 70.0


def test_a_delta_to_zero_removes_the_level():
    books, t = snap()
    parse({"type": "orderbook_delta", "seq": 2,
           "msg": {"market_ticker": "T", "side": "yes", "price": 0.40, "delta": -100}}, books)
    assert 0.40 not in t.yes


def test_one_delta_moves_both_sides_of_the_projected_book():
    """The reason project_in exists: a NO-side delta changes the YES book's ASKS."""
    books, t = snap()
    before = t.project("yes")[1]
    parse({"type": "orderbook_delta", "seq": 2,
           "msg": {"market_ticker": "T", "side": "no", "price": 0.55, "delta": -200}}, books)
    assert before and t.project("yes")[1] == [], "removing a NO bid removed a YES ask"


def test_alternate_field_spellings_are_all_accepted():
    books = {}
    parse({"type": "orderbook_snapshot", "seq": 1,
           "msg": {"market_ticker": "T", "yes_dollars_fp": [[0.4, 10]], "no_dollars_fp": [[0.5, 10]]}},
          books)
    assert books["T"].yes == {0.4: 10.0}
    parse({"type": "orderbook_delta", "seq": 2,
           "msg": {"market_ticker": "T", "side": "yes", "price_dollars": 0.4, "delta_fp": 5}}, books)
    assert books["T"].yes[0.4] == 15.0


def test_prices_are_probabilities_and_a_cents_payload_is_rejected():
    """Kalshi snapshot prices are in [0,1]. A 40 means someone changed the API, not a 40c level."""
    books = {}
    got = parse({"type": "orderbook_snapshot", "seq": 1,
                 "msg": {"market_ticker": "T", "yes": [[40, 100]], "no": []}}, books)
    assert got.kind == "error" and "outside [0,1]" in got.detail


def test_an_unknown_side_is_an_error_not_a_silent_drop():
    books, _t = snap()
    got = parse({"type": "orderbook_delta", "seq": 2,
                 "msg": {"market_ticker": "T", "side": "maybe", "price": 0.4, "delta": 1}}, books)
    assert got.kind == "error"


def test_an_unhandled_orderbook_type_is_reported_not_ignored_silently():
    got = parse({"type": "orderbook_something_new", "seq": 9, "msg": {"market_ticker": "T"}}, {})
    assert got.kind == "ignored" and "unhandled" in got.detail


def test_an_orderbook_message_without_a_ticker_is_an_error():
    assert parse({"type": "orderbook_delta", "seq": 1, "msg": {}}, {}).kind == "error"


def test_subscribe_frame_shape():
    f = subscribe_frame(["B", "A"])
    assert f["cmd"] == "subscribe"
    assert f["params"]["channels"] == ["orderbook_delta"]
    assert f["params"]["market_tickers"] == ["A", "B"], "sorted, so the frame is deterministic"


def test_zero_size_levels_are_dropped_on_snapshot():
    books = {}
    parse({"type": "orderbook_snapshot", "seq": 1,
           "msg": {"market_ticker": "T", "yes": [[0.4, 0]], "no": [[0.5, 10]]}}, books)
    assert books["T"].yes == {}
