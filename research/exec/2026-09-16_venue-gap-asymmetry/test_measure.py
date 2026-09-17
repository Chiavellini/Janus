"""L144 pins.

The registered criteria require these proved by test rather than asserted: the offline walk is the
lane's own walk, the apparent edge is the Candidate arithmetic the clearance screened on, a missing
hedge confirmation is reported missing rather than imputed, and the registered thresholds are the
ones in the spec.
"""
from __future__ import annotations

import importlib.util
import random
from pathlib import Path

from kernel.schema import Book, Quote
from nodes.execute.plan import marginal_price

_spec = importlib.util.spec_from_file_location("l144_measure", Path(__file__).with_name("measure.py"))
measure = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(measure)


def _ladder(rng: random.Random) -> list[list[float]]:
    price, out = rng.uniform(0.01, 0.30), []
    for _ in range(rng.randint(1, 6)):
        price = min(0.99, price + rng.uniform(0.001, 0.08))
        out.append([round(price, 4), round(rng.uniform(0.5, 60.0), 4)])
    return out


def test_offline_walk_is_identical_to_the_lanes_marginal_price():
    """The same walk at the same size must serve BOTH legs, or the comparison is not paired."""
    rng = random.Random(144)
    for _ in range(400):
        rows = _ladder(rng)
        book = Book(asks=tuple(Quote(p, s) for p, s in rows))
        for q in (0.5, 1.0, 7.0, 25.0, 100.0, sum(s for _, s in rows)):
            assert measure.walk(rows, q)[0] == marginal_price(book, q)


def test_apparent_edge_is_the_candidate_arithmetic_the_clearance_screened_on():
    """grid.py:1149-1157: taker uses limit_price; cost adds hedge vwap, fee and settlement buffer."""
    first = {"contracts": 25.0, "limit_price": 0.55, "vwap": 0.54, "post_only": False}
    hedge = {"vwap": 0.40}
    plan = {"fee": 0.02, "settlement_buffer": 0.01}
    got = measure.apparent_edge(first, hedge, plan)
    assert got["planned_cost"] == 0.98
    assert round(got["net_profit_usd"], 6) == round(25.0 * (1 - 0.98), 6)
    assert round(got["locked_return"], 6) == round((25.0 * 0.02) / (25.0 * 0.98), 6)


def test_apparent_edge_uses_vwap_for_a_maker_first_leg():
    """The same line branches on post_only; keep the branch even though L144 is taker-scoped."""
    first = {"contracts": 10.0, "limit_price": 0.60, "vwap": 0.50, "post_only": True}
    got = measure.apparent_edge(first, {"vwap": 0.30}, {"fee": 0.01, "settlement_buffer": 0.0})
    assert got["planned_cost"] == 0.81


def test_apparent_edge_refuses_rather_than_guessing_on_missing_fields():
    assert measure.apparent_edge({"contracts": 25.0}, {"vwap": 0.4}, {})["locked_return"] is None
    assert measure.apparent_edge({"contracts": 0.0, "limit_price": 0.5, "post_only": False},
                                 {"vwap": 0.4}, {})["planned_cost"] is None


def test_sign_convention_and_counts_are_exclusive_and_total():
    gaps = [-2.0, 0.0, 1.0, 3.0]
    counts = measure.sign_counts(gaps)
    assert counts == {"adverse": 2, "zero": 1, "favourable": 1}
    assert sum(counts.values()) == len(gaps)
    assert measure.favourable_fraction(gaps) == 0.25


def test_leg_match_requires_all_three_identity_fields():
    """Matching on venue alone would pair the wrong outcome on a two-outcome event."""
    books = {"o1": [{"venue": "kalshi", "market_id": "M", "outcome_id": "YES", "asks": [[0.4, 9.0]]}]}
    leg = {"venue": "kalshi", "market_id": "M", "outcome_id": "YES"}
    assert measure._leg_from_books(books, leg)["asks"] == [[0.4, 9.0]]
    assert measure._leg_from_books(books, {**leg, "outcome_id": "NO"}) is None
    assert measure._leg_from_books(books, {**leg, "market_id": "OTHER"}) is None


def test_registered_thresholds_are_the_ones_in_the_spec():
    assert measure.KALSHI_FAVOURABLE_SYMMETRIC == 0.30
    assert measure.PM_FAVOURABLE_ONESIDED == 0.10
    assert measure.MEDIAN_BAND_C == 1.5
    assert measure.MIN_PAIRED_ROWS == 40
    assert (measure.RHO_MARGINAL, measure.RHO_STRATUM) == (0.25, 0.15)
    assert measure.SCHEMA == "janus.l144.venue_gap_asymmetry.v1"


def test_reconciliation_target_is_l143s_retained_result():
    assert (measure.L143_PM_ADVERSE, measure.L143_PM_ZERO,
            measure.L143_PM_FAVOURABLE) == (155, 46, 1)


def test_stratified_declines_rather_than_inventing_strata_on_thin_data():
    rows = [{"pm_gap_c": float(i), "a": float(i), "b": float(i)} for i in range(5)]
    out = measure.stratified(rows, "pm_gap_c", "a", "b")
    assert "note" in out["strata"]
    assert "load_bearing" not in out
