"""L145 pins.

The registered criteria require these proved by test: the VWAP walk is the lane's own walk; REST
ladders go through the reviewed parsers; symmetry is measured given a move (the L144 correction);
the four verdict branches match the spec and cannot overlap; and pairing picks the nearest row.
"""
from __future__ import annotations

import importlib.util
import json
import random
import sqlite3
from pathlib import Path

from kernel.schema import Book, Quote
from nodes.execute.plan import vwap_for_size
from nodes.venue_kalshi.books import kalshi_book
from nodes.venue_polymarket.books import pm_book

_spec = importlib.util.spec_from_file_location("l145_measure", Path(__file__).with_name("measure.py"))
measure = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(measure)


def _ladder(rng: random.Random) -> list[tuple[float, float]]:
    price, out = rng.uniform(0.01, 0.30), []
    for _ in range(rng.randint(1, 8)):
        price = min(0.99, price + rng.uniform(0.001, 0.08))
        out.append((round(price, 4), round(rng.uniform(0.5, 60.0), 4)))
    return out


def test_walk_vwap_is_identical_to_the_lanes_vwap_for_size():
    rng = random.Random(145)
    for _ in range(400):
        rows = _ladder(rng)
        book = Book(asks=tuple(Quote(p, s) for p, s in rows))
        for q in (0.5, 1.0, 7.0, 25.0, 100.0, sum(s for _, s in rows)):
            assert measure.walk_vwap(rows, q) == vwap_for_size(book, q)


def test_polymarket_rest_ladder_goes_through_pm_book_best_price_last():
    """The payload puts the best ask LAST. Parsing must go through the reviewed pm_book."""
    payload = {"asks": [{"price": "0.60", "size": "5"}, {"price": "0.55", "size": "10"}],
               "bids": [{"price": "0.40", "size": "3"}, {"price": "0.45", "size": "7"}]}
    asks = [(q.price, q.size) for q in pm_book(payload, 0.0).asks]
    assert asks[0] == (0.55, 10.0)
    assert measure.walk_vwap(asks, 10.0) == 0.55


def test_kalshi_rest_ladder_goes_through_kalshi_book_folded_asks():
    """Both Kalshi arrays are BIDS; a YES ask exists only as a NO bid at 1-p."""
    payload = {"orderbook_fp": {"yes_dollars": [["0.40", "9"]], "no_dollars": [["0.55", "12"]]}}
    asks = [(q.price, q.size) for q in kalshi_book(payload, "yes", 0.0).asks]
    assert asks and abs(asks[0][0] - 0.45) < 1e-9


def test_plain_legs_excludes_no_projections_and_controls():
    legs = json.dumps([
        {"venue": "polymarket", "outcome": "tokA", "vwap": 0.5},
        {"venue": "kalshi", "outcome": "KX-A", "vwap": 0.4},
        {"venue": "kalshi", "outcome": "KX-B:NO", "vwap": 0.3},
        {"control": "single_venue", "venues": ["kalshi"], "gross": 0.9, "cost": 0.95},
    ])
    assert measure.plain_legs(legs) == [("polymarket", "tokA", 0.5), ("kalshi", "KX-A", 0.4)]
    assert measure.no_legs_in(legs) == 1
    assert measure.plain_legs("not json") == []


def test_symmetry_is_measured_given_a_move_not_over_all_pairs():
    """The L144 correction. Sixty unchanged pairs must not drag a symmetric venue below 0.35."""
    gaps = [0.0] * 60 + [-1.0] * 20 + [1.0] * 20
    s = measure.symmetry(gaps)
    assert s["moved"] == 40 and s["unchanged"] == 60
    assert s["favourable_given_move"] == 0.5
    naive = sum(1 for g in gaps if g < 0) / len(gaps)
    assert naive == 0.2          # the L144 statistic would have called this one-sided


def test_move_threshold_treats_sub_tick_noise_as_unchanged():
    s = measure.symmetry([0.01, -0.02, 0.04, 2.0])
    assert s["moved"] == 1 and s["unchanged"] == 3


def _sym(fav: float, n: int, median: float, magnitude: float = 1.0) -> dict:
    """A venue with `n` moved pairs, `fav` of them favourable, and a stated moved-pair median.

    The gap MAGNITUDE is kept separate from the reported median. A symmetric venue has a median near
    zero but individually nonzero gaps; conflating the two makes every gap zero, so nothing counts as
    moved and the fixture silently tests the minimum-sample guard instead of the branch it names.
    """
    moved = [(-magnitude if i < round(fav * n) else magnitude) for i in range(n)]
    s = measure.symmetry(moved)
    s["moved_gap_c"] = {**s["moved_gap_c"], "p50": median}
    return s


def test_classify_pm_feed_optimistic():
    assert measure.classify(_sym(0.05, 60, 4.0), _sym(0.55, 60, 0.0))[0] == "PM_FEED_OPTIMISTIC"


def test_classify_neither_optimistic_is_reportable_as_a_refutation():
    assert measure.classify(_sym(0.50, 60, 0.0), _sym(0.50, 60, 0.0))[0] == "NEITHER_OPTIMISTIC"


def test_classify_both_optimistic():
    assert measure.classify(_sym(0.05, 60, 4.0), _sym(0.05, 60, 3.0))[0] == "BOTH_OPTIMISTIC"


def test_classify_requires_the_moved_pair_minimum_on_each_venue():
    verdict, reason = measure.classify(_sym(0.05, 60, 4.0), _sym(0.55, 20, 0.0))
    assert verdict == "MIXED_OR_INCONCLUSIVE" and "minimum" in reason


def test_classify_declines_rather_than_rounding_to_a_neighbour():
    """PM one-sided but Kalshi in the dead zone (0.25-0.35): no branch, so no verdict."""
    assert measure.classify(_sym(0.05, 60, 4.0), _sym(0.30, 60, 0.0))[0] == "MIXED_OR_INCONCLUSIVE"


def test_the_verdict_branches_are_mutually_exclusive():
    """Every combination of the two favourable fractions satisfies at most one branch."""
    for pm_f in [i / 20 for i in range(21)]:
        for k_f in [i / 20 for i in range(21)]:
            pm, k = _sym(pm_f, 100, 4.0), _sym(k_f, 100, 4.0)
            hits = sum([
                measure.FAV_SYMMETRIC_LO <= pm["favourable_given_move"] <= measure.FAV_SYMMETRIC_HI
                and measure.FAV_SYMMETRIC_LO <= k["favourable_given_move"] <= measure.FAV_SYMMETRIC_HI,
                pm["favourable_given_move"] < measure.FAV_OPTIMISTIC
                and k["favourable_given_move"] < measure.FAV_OPTIMISTIC,
                pm["favourable_given_move"] < measure.FAV_OPTIMISTIC
                and k["favourable_given_move"] >= measure.FAV_SYMMETRIC_LO,
            ])
            assert hits <= 1, (pm_f, k_f)


def test_nearest_row_picks_the_closer_neighbour_on_either_side():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE stream_evaluations(seen_ts REAL, game_id TEXT, quantity REAL, "
                "status TEXT, legs_json TEXT)")
    con.executemany("INSERT INTO stream_evaluations VALUES(?,?,?,?,?)", [
        (100.0, "g", 25.0, "DISCOVERED", "[]"),
        (104.0, "g", 25.0, "PROFITABLE_UNEXECUTED", "[]"),
        (103.0, "g", 10.0, "DISCOVERED", "[]"),      # different quantity: must be ignored
    ])
    assert measure.nearest_row(con, "g", 25.0, 103.5)[0] == 104.0
    assert measure.nearest_row(con, "g", 25.0, 101.0)[0] == 100.0
    assert measure.nearest_row(con, "absent", 25.0, 101.0) is None


def test_registered_thresholds_are_the_ones_in_the_spec():
    assert measure.FRESH_S == 3.0
    assert measure.SENSITIVITY_FRESH_S == (1.0, 5.0)
    assert measure.MOVE_EPS_C == 0.05
    assert measure.FAV_OPTIMISTIC == 0.25
    assert (measure.FAV_SYMMETRIC_LO, measure.FAV_SYMMETRIC_HI) == (0.35, 0.65)
    assert measure.MEDIAN_OPTIMISTIC_C == 1.0
    assert measure.MIN_MOVED_PAIRS == 30
    assert measure.SCHEMA == "janus.l145.pm_feed_fidelity.v1"


def test_polymarket_runs_below_the_lane_reconcilers_bucket():
    """PM queues rather than rejects; this row must not starve the lane's own reconciliation."""
    assert measure.PM_RATE < 4.0
