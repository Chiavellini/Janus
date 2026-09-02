#!/usr/bin/env python3
"""The hurdle is a curve, not a constant. These tests pin its shape."""
from __future__ import annotations

import pytest

from nodes.fees.targeting import Hurdle, combined_fee, hurdle_for, rank


def test_fee_falls_monotonically_toward_the_wings():
    fees = [hurdle_for(p).fee_per_contract for p in (0.50, 0.60, 0.75, 0.90, 0.95, 0.99)]
    assert fees == sorted(fees, reverse=True)


def test_coin_flip_costs_an_order_of_magnitude_more_than_a_heavy_favourite():
    """The reason to hunt blowouts. Measured on the live lane: 2.49c median vs 0.06c best."""
    assert hurdle_for(0.50).fee_per_contract / hurdle_for(0.99).fee_per_contract > 10


def test_the_hurdle_is_symmetric_about_a_half():
    """A cover at p and at 1-p is the SAME cover. p(1-p) is symmetric, so the fee must agree."""
    for p in (0.05, 0.2, 0.35):
        assert abs(hurdle_for(p).fee_per_contract - hurdle_for(1 - p).fee_per_contract) < 1e-9


def test_required_ask_sum_actually_clears_the_hurdle():
    """Round trip: buy at exactly the required sum and the locked return must reach the hurdle."""
    for p in (0.50, 0.80, 0.95):
        h = hurdle_for(p, hurdle=0.01)
        cost = h.required_ask_sum + h.fee_per_contract
        assert (1.0 - cost) / cost == pytest.approx(0.01, abs=1e-9)


def test_a_tighter_hurdle_demands_a_bigger_gap():
    assert hurdle_for(0.5, hurdle=0.02).required_ask_sum < hurdle_for(0.5, hurdle=0.01).required_ask_sum


def test_ranking_prefers_cheap_fees_over_a_better_gross_price():
    """The finding from the first fee-aware run: gross alone picks the wrong game.

    BAL @ COL sat at gross 1.0000 -- perfect cross-venue parity -- and was still further from
    actionable than ATH @ TEX at gross 1.0060, because the coin-flip fee was 14x larger.
    """
    ranked = rank({"coinflip": 0.50, "blowout": 0.97})
    assert [g for g, _ in ranked] == ["blowout", "coinflip"]
    assert ranked[0][1].gap_needed_cents < ranked[1][1].gap_needed_cents


def test_is_cheap_flags_the_wings_only():
    assert hurdle_for(0.98).is_cheap
    assert not hurdle_for(0.50).is_cheap


def test_fee_comes_from_the_registry_not_a_local_copy():
    """A targeting heuristic that drifts from the pricer ranks by a cost nobody charges."""
    explicit = combined_fee(0.5, "kalshi", 0.5, "polymarket", 100.0,
                            overrides_b={"fee_rate": 0.05})
    assert explicit == pytest.approx((0.07 + 0.05) * 0.25, abs=5e-4)


def test_polymarket_rate_override_changes_the_hurdle():
    """The registry's measured distribution is 0.04/0.05/0.07; the rate must not be baked in."""
    cheap = hurdle_for(0.5, overrides_b={"fee_rate": 0.04})
    dear = hurdle_for(0.5, overrides_b={"fee_rate": 0.07})
    assert cheap.fee_per_contract < dear.fee_per_contract
