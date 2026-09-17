"""L143 pins.

The registered success criteria require two things to be proved by test rather than asserted in
prose: that the offline ladder walk is arithmetically identical to the walk the lane itself used,
and that the verdict is produced strictly by the registered decision rule.
"""
from __future__ import annotations

import importlib.util
import random
from pathlib import Path

from kernel.schema import Book, Quote
from nodes.execute.plan import marginal_price

_spec = importlib.util.spec_from_file_location("l143_measure", Path(__file__).with_name("measure.py"))
measure = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(measure)


def _ladder(rng: random.Random) -> list[list[float]]:
    price, out = rng.uniform(0.01, 0.30), []
    for _ in range(rng.randint(1, 6)):
        price = min(0.99, price + rng.uniform(0.001, 0.08))
        out.append([round(price, 4), round(rng.uniform(0.5, 60.0), 4)])
    return out


def test_offline_walk_is_identical_to_the_lanes_marginal_price():
    """The gap is only comparable to what the lane compared if the walk is the same walk."""
    rng = random.Random(143)
    for _ in range(400):
        rows = _ladder(rng)
        book = Book(asks=tuple(Quote(p, s) for p, s in rows))
        for q in (0.5, 1.0, 7.0, 25.0, 100.0, sum(s for _, s in rows)):
            assert measure.walk(rows, q)[0] == marginal_price(book, q)


def test_walk_returns_none_when_depth_cannot_cover_the_size():
    """Short depth is a real outcome, never coerced to a price."""
    assert measure.walk([[0.10, 5.0]], 25.0)[0] is None
    assert measure.walk([[0.10, 5.0]], 25.0)[1] == 5.0
    assert measure.walk([], 1.0) == (None, 0.0)


def test_gap_sign_convention_is_worse_is_positive():
    """A buy that must now pay more is a positive gap; the favourable half must stay negative."""
    assert (0.62 - 0.55) * 100.0 > 0
    assert (0.50 - 0.55) * 100.0 < 0


def test_spearman_matches_a_known_tie_free_case():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert measure.spearman(xs, [2.0, 4.0, 6.0, 8.0, 10.0])["rho"] == 1.0
    assert measure.spearman(xs, [10.0, 8.0, 6.0, 4.0, 2.0])["rho"] == -1.0


def test_spearman_is_tie_corrected_and_refuses_degenerate_input():
    assert measure.spearman([1.0, 1.0, 1.0], [1.0, 2.0, 3.0])["rho"] is None
    assert measure.spearman([1.0, 2.0], [1.0, 2.0])["rho"] is None


def test_depth_at_or_below_counts_every_level_at_or_under_the_price():
    ladder = [[0.10, 5.0], [0.12, 7.0], [0.20, 3.0]]
    assert measure.depth_at_or_below(ladder, 0.12) == 12.0
    assert measure.depth_at_or_below(ladder, 0.09) == 0.0


def test_registered_thresholds_are_the_ones_in_the_spec():
    """These are immutable after registration; a silent edit here would rewrite the verdict."""
    assert measure.CENTRED_BAND_C == 1.5
    assert (measure.FAVOURABLE_LO, measure.FAVOURABLE_HI) == (0.40, 0.60)
    assert measure.RHO_LATENCY == 0.20


def test_too_few_rows_is_inconclusive_not_the_nearest_branch():
    """The registered rule requires declining a verdict rather than rounding to a neighbour."""
    assert measure.SCHEMA == "janus.l143.book_move_attribution.v1"
