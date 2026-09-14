#!/usr/bin/env python3
"""L115: the maker cost counterfactual, and the trap that would silently defeat it."""
from __future__ import annotations

from nodes.fees.models import Fill
from nodes.fees.registry import model_for, params_for

#: Polymarket's own pinned schedule on a live event, read off the box 2026-09-14.
LIVE_PM = {"fee_rate": 0.05, "credit_rebate": False, "rebate_rate": 0.15}


def test_a_polymarket_maker_pays_exactly_zero_and_a_taker_does_not():
    """`taker_only: True` is the venue's word, in the fee params the lane pinned from it."""
    pm = model_for("polymarket")
    taker = [Fill("polymarket", "m", "o", "buy", 0.38, 10.0, "taker", 0)]
    maker = [Fill("polymarket", "m", "o", "buy", 0.38, 10.0, "maker", 0)]
    assert pm.entry_cost(maker, params_for("polymarket", LIVE_PM)) == 0.0
    assert pm.entry_cost(taker, params_for("polymarket", LIVE_PM)) > 0.0


def test_the_model_reproduces_the_venues_own_recorded_fee_to_the_cent():
    """Not a unit test of our arithmetic -- a check against cash the venue actually charged.

    `research/sports/2026-09-10_limited-live-f20-bounded-taker/observation_1.md`: Polymarket filled
    10 contracts as 10.763158 shares at 0.3799999963 and charged **$0.12679**. If this drifts, the
    shadow number is measuring something other than the fee we would stop paying.
    """
    pm = model_for("polymarket")
    fills = [Fill("polymarket", "m", "o", "buy", 0.38, 10.763158, "taker", 0)]
    assert round(pm.entry_cost(fills, params_for("polymarket", LIVE_PM)), 5) == 0.12679


def test_setting_liquidity_in_params_alone_does_not_change_the_fee():
    """THE TRAP, pinned so it cannot be rediscovered the expensive way.

    `entry_cost` reads `liquidity` from the FILL; `screening_coeff` reads it from `params`. A
    shadow computed by passing `params_for(venue, {"liquidity": "maker"})` and reusing taker Fills
    silently returns the TAKER number, and every downstream conclusion would be wrong in the
    direction that flatters the maker case.
    """
    pm = model_for("polymarket")
    taker = [Fill("polymarket", "m", "o", "buy", 0.38, 10.0, "taker", 0)]
    honest = pm.entry_cost(taker, params_for("polymarket", LIVE_PM))
    trapped = pm.entry_cost(taker, params_for("polymarket", {**LIVE_PM, "liquidity": "maker"}))
    assert trapped == honest, "params reaching entry_cost would mean this test is now the wrong guard"
    # ...while the screening path DOES read params, which is the asymmetry itself.
    assert pm.screening_coeff(params_for("polymarket", {**LIVE_PM, "liquidity": "maker"})) == 0.0


def test_a_priced_cover_carries_the_maker_counterfactual_and_it_is_cheaper():
    """The cover records both numbers, and the gap is the whole Polymarket entry fee."""
    from kernel.schema import Book, Quote
    from nodes.cover import cover as C
    from nodes.cover.tests.test_cover import MLB2

    def bk(levels):
        return Book(asks=tuple(Quote(p, s) for p, s in levels), fetched_utc=1000.0)

    # The 2026-08-17 divergence from test_cover: Kalshi 0.47 + Polymarket 0.51 at depth.
    offers = {"A": [C.Leg("kalshi", "kalshi_clob", "a", "m", bk([(0.47, 10_000)]))],
              "B": [C.Leg("polymarket", "pm_clob", "b", "m", bk([(0.51, 10_000)]), {"fee_rate": 0.05})]}
    cov = C.best_cover(offers, 500, now_utc=1000.0, proof=MLB2)

    assert cov.ok and cov.fee_per_contract is not None
    assert cov.maker_fee_per_contract is not None
    assert cov.maker_fee_per_contract < cov.fee_per_contract, (
        "a Polymarket maker pays nothing, so the counterfactual must be strictly cheaper")
    # The gap IS the Polymarket entry fee and nothing else: Kalshi is untouched because its
    # schedule charges makers too, and the hedge must cross to be certain.
    pm_leg = [Fill("polymarket", "m", "b", "buy", 0.51, 500.0, "taker", 0)]
    pm_fee = model_for("polymarket").entry_cost(pm_leg, params_for("polymarket", {"fee_rate": 0.05}))
    gap = (cov.fee_per_contract - cov.maker_fee_per_contract) * 500.0
    assert abs(gap - pm_fee) < 1e-9, (gap, pm_fee)
    # And the real cover is unchanged -- this records, it does not price.
    assert cov.cost_per_contract > 1.0, "the fee floor still eats this one, exactly as before"
