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


def test_server_time_is_parsed_from_ts_ms_or_iso_and_absent_is_none():
    from nodes.stream_kalshi.protocol import server_utc_of
    assert server_utc_of({"ts_ms": 1788410903579}) == 1788410903.579
    assert abs(server_utc_of({"ts": "2026-09-03T04:48:23.579602Z"}) - 1788410903.579602) < 1e-6
    assert server_utc_of({}) is None and server_utc_of({"ts_ms": "junk"}) is None


def test_sid_and_seq_are_ints_even_when_the_wire_sends_strings():
    from nodes.stream_kalshi.protocol import parse
    p = parse({"type": "orderbook_delta", "sid": "1", "seq": "3",
               "msg": {"market_ticker": "K1", "side": "yes", "price_dollars": "0.40", "delta_fp": "-1",
                       "ts_ms": 1788410903579}}, {"K1": __import__("nodes.stream_kalshi.protocol", fromlist=["TickerBook"]).TickerBook()})
    assert p.sid == 1 and p.seq == 3 and p.server_utc == 1788410903.579


def _uncached_project(book, outcome):
    """The original projection, retained as an independent equivalence oracle."""
    from kernel.schema import Quote, fold_complement_bids
    own, other = (book.yes, book.no) if outcome == "yes" else (book.no, book.yes)
    bids = tuple(Quote(p, s) for p, s in sorted(own.items(), reverse=True))
    other_bids = tuple(Quote(p, s) for p, s in sorted(other.items(), reverse=True))
    asks = fold_complement_bids(other_bids)
    return ([(q.price, q.size) for q in bids], [(q.price, q.size) for q in asks])


def test_projection_cache_matches_reference_through_ladder_mutations():
    import random
    rng = random.Random(51)
    book = TickerBook()
    for i in range(2000):
        side = rng.choice(("yes", "no"))
        levels = getattr(book, side)
        price = rng.randrange(101) / 100
        if i % 17 == 0:
            setattr(book, side, {rng.randrange(101) / 100: float(rng.randrange(100)) for _ in range(50)})
        elif i % 7 == 0:
            levels.pop(price, None)
        else:
            levels[price] = float(rng.randrange(1000))
        for outcome in ("yes", "no"):
            want = _uncached_project(book, outcome)
            got = book.project(outcome)
            assert got == want
            got[0].clear()
            got[1].append((0.5, 9999.0))
            assert book.project(outcome) == want, "caller mutation poisoned the cache"


@pytest.mark.parametrize("side", ["yes", "no"])
@pytest.mark.parametrize("price,size", [(float("nan"), 1.0), (float("inf"), 1.0),
                                         (-0.01, 1.0), (1.01, 1.0), (0.5, -1.0)])
def test_invalid_ladder_edit_cannot_hide_behind_a_cached_projection(side, price, size):
    book = TickerBook(yes={0.4: 10.0}, no={0.6: 20.0})
    book.project("yes")
    book.project("no")
    setattr(book, side, {price: size})
    for outcome in ("yes", "no"):
        with pytest.raises(ValueError):
            _uncached_project(book, outcome)
        with pytest.raises(ValueError):
            book.project(outcome)


def test_projection_cache_observes_partial_snapshot_failure_and_same_sequence_delta():
    books, book = snap()
    book.project("yes")
    # apply_snapshot changes YES before parsing NO. Even this partial failure must
    # expose the same book as the uncached implementation, never its old projection.
    failed = parse({"type": "orderbook_snapshot", "seq": 1,
                    "msg": {"market_ticker": "T", "yes": [[0.3, 2]], "no": [[40, 1]]}}, books)
    assert failed.kind == "error"
    for outcome in ("yes", "no"):
        assert book.project(outcome) == _uncached_project(book, outcome)
    parse({"type": "orderbook_delta", "seq": 1,
           "msg": {"market_ticker": "T", "side": "yes", "price": 0.3, "delta": 5}}, books)
    for outcome in ("yes", "no"):
        assert book.project(outcome) == _uncached_project(book, outcome)


def test_projection_cache_does_not_alias_equal_numbers_with_different_rendering():
    import json
    book = TickerBook(yes={-0.0: 1.0}, no={0.5: 2.0})
    book.project("yes")
    book.project("no")
    book.yes = {0.0: 1}
    for outcome in ("yes", "no"):
        assert json.dumps(book.project(outcome)) == json.dumps(_uncached_project(book, outcome))
