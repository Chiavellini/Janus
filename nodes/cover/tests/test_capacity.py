#!/usr/bin/env python3
"""The size frontier. 'Is there an edge' and 'how much is it worth' are different questions."""
from __future__ import annotations

import pytest

from kernel.schema import Book, Quote, liquidity_source_for
from nodes.cover.capacity import frontier
from nodes.cover.cover import Leg
from nodes.settle_wedge.fixtures import mlb_cover_proof

T = 1000.0
PROOF = mlb_cover_proof(["a", "b"])


def bk(levels):
    return Book(asks=tuple(Quote(p, s) for p, s in levels), fetched_utc=T)


def two(a_levels, b_levels, *, free=True):
    ov_pm = {"fee_rate": 0.0} if free else {"fee_rate": 0.05}
    ov_k = {"fee_multiplier": 0.0} if free else {}
    return {"a": [Leg("polymarket", liquidity_source_for("polymarket"), "pm", "m",
                      bk(a_levels), ov_pm)],
            "b": [Leg("kalshi", liquidity_source_for("kalshi"), "k", "m2", bk(b_levels), ov_k)]}


def f(offers, **kw):
    kw.setdefault("slippage_per_contract", 0.0)
    kw.setdefault("slippage_modelled", False)
    return frontier(offers, now_utc=T, proof=PROOF, **kw)


def test_the_worked_example_reproduces():
    """Layered books: cheap at the touch, dear in the tail."""
    got = f(two([(0.51, 1000), (0.53, 2000), (0.58, 5000), (0.64, 10000)],
                [(0.32, 1000), (0.34, 2000), (0.38, 5000), (0.41, 10000)]))
    assert got.actionable
    assert got.rungs[0].contracts == 1000
    assert got.rungs[0].cost_per_contract == pytest.approx(0.83)
    assert got.rungs[0].profit == pytest.approx(170.0)


def test_n_star_is_not_n_max():
    """The whole point. Profit peaks before the frontier and you would trade the peak."""
    got = f(two([(0.51, 1000), (0.53, 2000), (0.58, 5000), (0.64, 10000)],
                [(0.32, 1000), (0.34, 2000), (0.38, 5000), (0.41, 10000)]))
    assert got.n_star < got.n_max
    assert got.best.profit == max(r.profit for r in got.rungs)
    deepest = got.rungs[-1]
    assert got.best.return_on_capital > deepest.return_on_capital


def test_every_rung_is_priced_below_one_all_in():
    got = f(two([(0.51, 1000), (0.53, 2000), (0.58, 5000), (0.64, 10000)],
                [(0.32, 1000), (0.34, 2000), (0.38, 5000), (0.41, 10000)]))
    assert all(r.cost_per_contract < 1.0 for r in got.rungs)


def test_cost_rises_monotonically_as_the_book_is_eaten():
    got = f(two([(0.40, 100), (0.45, 100), (0.49, 100)],
                [(0.40, 100), (0.45, 100), (0.49, 100)]))
    costs = [r.cost_per_contract for r in got.rungs]
    assert costs == sorted(costs)


def test_a_coherent_market_yields_no_frontier_at_all():
    """Both sides summing to 1.00 is the normal state, and must produce nothing."""
    got = f(two([(0.60, 10000)], [(0.40, 10000)]))
    assert not got.actionable and got.n_max == 0.0


def test_a_thin_touch_with_a_dear_tail_caps_capacity():
    """A great top-of-book with no size behind it is not a big opportunity."""
    got = f(two([(0.10, 50), (0.80, 100000)], [(0.10, 50), (0.80, 100000)]))
    assert got.actionable
    assert got.n_max <= 50, "capacity stops where the cheap size stops"


def test_fees_shrink_the_frontier():
    cheap = f(two([(0.45, 5000)], [(0.45, 5000)], free=True))
    dear = f(two([(0.45, 5000)], [(0.45, 5000)], free=False))
    assert dear.best.profit < cheap.best.profit


def test_same_venue_covers_are_excluded_as_the_control():
    """Both legs on one book is the intra-venue no-arb control, not an opportunity."""
    offers = {"a": [Leg("kalshi", "kalshi_clob", "k1", "m", bk([(0.40, 5000)]), {"fee_multiplier": 0.0})],
              "b": [Leg("kalshi", "kalshi_clob", "k2", "m", bk([(0.40, 5000)]), {"fee_multiplier": 0.0})]}
    assert not f(offers).actionable
    assert f(offers, cross_venue_only=False).actionable


def test_the_hurdle_truncates_the_frontier():
    offers = two([(0.40, 1000), (0.49, 9000)], [(0.40, 1000), (0.49, 9000)])
    loose, tight = f(offers, hurdle=0.0), f(offers, hurdle=0.10)
    assert tight.n_max <= loose.n_max


def test_an_unproven_outcome_set_yields_nothing():
    offers = two([(0.40, 5000)], [(0.40, 5000)])
    got = frontier(offers, now_utc=T, proof=None)
    assert not got.actionable
    assert got.limit_reason == "cover_proof_missing"


def test_capacity_is_reported_in_capital_not_just_contracts():
    """You deploy dollars; the frontier must say how many."""
    got = f(two([(0.51, 1000)], [(0.32, 1000)]))
    r = got.best
    assert r.capital == pytest.approx(r.contracts * r.cost_per_contract)
    assert r.return_on_capital == pytest.approx(r.profit / r.capital)


def test_the_frontier_stops_at_a_venue_balance_and_says_so():
    offers = two([(0.40, 1000), (0.45, 5000)], [(0.40, 1000), (0.45, 5000)])
    got = f(offers, balances={"polymarket": 800.0, "kalshi": 10_000.0})   # 1000 @ 0.40 fits; 6000 does not
    assert got.rungs and got.limit_reason == "balance"
    assert max(r.contracts for r in got.rungs) == 1000
    assert f(offers, balances={"polymarket": 0.0, "kalshi": 0.0}).rungs == ()


def test_fixed_costs_and_slippage_come_off_every_rung_and_are_labelled():
    offers = two([(0.45, 1000)], [(0.45, 1000)])
    plain = f(offers)
    dear = f(offers, fixed_cost_usd=20.0, slippage_per_contract=0.02, slippage_modelled=True)
    assert plain.best.profit == pytest.approx(100.0)
    assert dear.best.profit == pytest.approx(1000 * (1 - 0.92) - 20.0)
    assert dear.slippage_modelled and dear.slippage_per_contract == 0.02 and dear.fixed_cost_usd == 20.0
    assert not plain.slippage_modelled, "unmeasured is labelled, never assumed zero"
    assert f(offers, fixed_cost_usd=500.0).rungs == (), "a fixed cost larger than the edge is no frontier"


def test_rungs_below_a_legs_minimum_are_skipped_not_fatal():
    offers = two([(0.40, 3), (0.45, 1000)], [(0.40, 3), (0.45, 1000)])
    offers["a"][0] = Leg("polymarket", liquidity_source_for("polymarket"), "pm", "m", bk([(0.40, 3), (0.45, 1000)]),
                         {"fee_rate": 0.0}, min_order_contracts=5.0)
    got = f(offers)
    assert got.rungs and all(r.contracts >= 5.0 for r in got.rungs)


def test_the_registered_slippage_is_the_default_and_is_labelled_modelled():
    from nodes.cover.capacity import SLIPPAGE_MODELLED, SLIPPAGE_PER_CONTRACT, SLIPPAGE_RESEARCH_REF
    assert SLIPPAGE_MODELLED and SLIPPAGE_PER_CONTRACT == pytest.approx(0.04) and SLIPPAGE_RESEARCH_REF.startswith("research/")
    got = frontier(two([(0.45, 1000)], [(0.45, 1000)]), now_utc=T, proof=PROOF)
    assert got.slippage_modelled and got.slippage_per_contract == pytest.approx(0.04)
    assert got.best.cost_per_contract == pytest.approx(0.94), "0.90 gross + the registered 0.04 reserve (fees are zero in this fixture)"


def test_the_per_league_slippage_table_falls_back_to_the_pooled_pin():
    from nodes.cover import capacity
    assert capacity.slippage_for("mlb") == pytest.approx(capacity.SLIPPAGE_PER_CONTRACT)
    assert capacity.slippage_for(None) == pytest.approx(capacity.SLIPPAGE_PER_CONTRACT)
    capacity.SLIPPAGE_BY_LEAGUE["mlb"] = 0.01
    try:
        assert capacity.slippage_for("mlb") == pytest.approx(0.01)
        assert capacity.slippage_for("cfb") == pytest.approx(capacity.SLIPPAGE_PER_CONTRACT)
    finally:
        capacity.SLIPPAGE_BY_LEAGUE.pop("mlb", None)
