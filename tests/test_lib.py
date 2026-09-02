#!/usr/bin/env python3
"""Smoke + anchor tests for Janus lib/. Run: python3 tests/test_lib.py  (or pytest)

These are not a substitute for the Phase-4 execution battery. They assert that the copied stats
primitives behave, and that the cost pins still reproduce their real-world anchors — the latter is
the one that must never silently drift.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import stats, venue_costs  # noqa: E402


def test_cost_pins():
    """The pinned curves reproduce their published / on-chain-verified anchors."""
    venue_costs.selftest()


def test_perm_p_detects_nothing_when_there_is_nothing():
    """A coin-flip predictor must not look significant."""
    rng = np.random.default_rng(7)
    n = 400
    side = rng.integers(0, 2, n).astype(bool)
    outcome = rng.integers(0, 2, n)          # independent of side
    entry = np.full(n, 50.0)
    r = stats.permutation_pvalue(side, entry, outcome, n=2000, seed=0)
    assert 0.05 < r["p_value"] < 0.95, r


def test_perm_p_detects_a_real_edge():
    """A predictor right 70% of the time must be significant."""
    rng = np.random.default_rng(7)
    n = 400
    outcome = rng.integers(0, 2, n)
    flip = rng.random(n) < 0.30
    side = np.where(flip, 1 - outcome, outcome).astype(bool)
    entry = np.full(n, 50.0)
    r = stats.permutation_pvalue(side, entry, outcome, n=2000, seed=0)
    assert r["p_value"] < 0.01, r


def test_day_block_perm_p_runs_and_is_bounded():
    rng = np.random.default_rng(3)
    n = 300
    df = pd.DataFrame({
        "open_date": np.repeat(pd.date_range("2026-07-01", periods=30).astype(str), 10),
        "side_up": rng.integers(0, 2, n).astype(bool),
        "outcome_up": rng.integers(0, 2, n).astype(bool),
        "pnl_win": 47.0, "pnl_loss": -53.0,
    })
    p = stats.day_block_perm_p(df, n=500, seed=0)
    assert 0.0 < p <= 1.0, p


def test_block_bootstrap_ci_brackets_the_mean():
    rng = np.random.default_rng(1)
    vals = rng.normal(4.0, 10.0, 600)
    days = np.repeat(np.arange(30), 20)
    r = stats.block_bootstrap_ci(vals, days, n=2000, seed=0)
    assert r["ci_lo"] < r["mean"] < r["ci_hi"], r
    assert r["n_days"] == 30
    lo, hi = stats.day_block_ci(vals, days, n=2000, seed=0)
    assert (lo, hi) == (r["ci_lo"], r["ci_hi"])


def test_paired_sharpe_diff_sign():
    """An arm with the same mean but lower variance must have a higher SR."""
    rng = np.random.default_rng(5)
    days = np.repeat(np.arange(40), 15)
    n = len(days)
    a = rng.normal(2.0, 5.0, n)
    b = a + rng.normal(0.0, 15.0, n)          # same-ish mean, much noisier
    r = stats.paired_sharpe_diff_ci(a, b, days, n=1000, seed=0)
    assert r["delta_sr"] > 0, r


def test_bh_threshold_tightens_with_looks():
    assert stats.bh_fdr_threshold(1) == 0.10
    assert stats.bh_fdr_threshold(2) == 0.05
    assert abs(stats.bh_fdr_threshold(12) - 0.00833) < 1e-4
    # a fresh ledger must not be treated as zero looks
    assert stats.bh_fdr_threshold(0) == 0.10


def test_benjamini_hochberg():
    r = stats.benjamini_hochberg([0.001, 0.20, 0.60, 0.90], q=0.10)
    assert r["n_survive"] == 1 and r["survive_mask"][0] is True, r
    r2 = stats.benjamini_hochberg([0.4, 0.5, 0.6], q=0.10)
    assert r2["n_survive"] == 0, r2


def test_fold_stability_flags_instability():
    rng = np.random.default_rng(2)
    days = np.repeat(np.arange(20), 10)
    good = stats.fold_stability_cents(rng.normal(8.0, 2.0, 200), days)
    assert good["fold_robust"] is True, good
    bad = stats.fold_stability_cents(rng.normal(0.0, 40.0, 200), days)
    assert bad["fold_robust"] is False, bad


def test_two_leg_nominal_edge_is_the_oracle_risk_premium():
    """The headline structural fact of this project, locked in so it cannot be re-forgotten.

    Measured live on the 2026-07-24 20:45Z BTC window: Kalshi YES ask 21c + PM DOWN ask 70c.
    A naive "riskless arb" calculation reports +5.53c. The two venues settle OPPOSITELY 5.70%
    of the time (n=2,859 matched windows), so the pair is worth 94.30c, not 100c, and the true
    EV is -0.17c. The apparent free money is almost exactly the oracle risk premium.
    """
    r = venue_costs.two_leg_ev_cents(21.0, 70.0, asset="btc")
    assert abs(r["nominal_edge_cents"] - 5.53) < 0.01, r     # the illusion
    assert abs(r["ev_cents"] - (-0.17)) < 0.01, r            # the truth
    assert r["nominal_edge_cents"] > 0 > r["ev_cents"], r    # they have OPPOSITE signs
    assert r["oracle_risk_modelled"] is True

    # the bar any entry must clear is exactly 100 * p_disagree
    assert abs(venue_costs.required_edge_cents("btc") - 5.701) < 1e-3


def test_two_leg_ev_is_monotone_and_clears_when_divergence_is_wide():
    """A wide enough divergence does produce real EV; cheaper entries are always better."""
    wide = venue_costs.two_leg_ev_cents(10.0, 70.0, asset="btc")
    tight = venue_costs.two_leg_ev_cents(30.0, 70.0, asset="btc")
    assert wide["ev_cents"] > 10.0 > tight["ev_cents"], (wide, tight)
    assert wide["ev_cents"] > tight["ev_cents"]
    # breakeven_p_disagree = how much oracle risk this entry can absorb
    assert wide["breakeven_p_disagree"] > venue_costs.P_DISAGREE["btc"]
    assert tight["breakeven_p_disagree"] < venue_costs.P_DISAGREE["btc"]


def test_unmeasured_asset_falls_back_to_the_worst_rate_not_zero():
    """A missing measurement must be conservative, never optimistic."""
    r = venue_costs.two_leg_ev_cents(21.0, 70.0, asset="hype")
    assert r["p_disagree"] == venue_costs.P_DISAGREE_DEFAULT
    assert r["p_disagree"] == max(venue_costs.P_DISAGREE.values())
    assert r["ev_cents"] < venue_costs.two_leg_ev_cents(21.0, 70.0, asset="btc")["ev_cents"]


def test_flat_share_vs_flat_dollar_divergence():
    """The sizing trap, asserted so it stays visible.

    Kilos states the spread as "12.5x at ask 0.08". That figure is the FEE-FREE ratio: a fixed
    $4 buys 4/0.08 = 50 shares at 8c but only 4 at 100c. Including the taker fee the ratio
    compresses to ~11.6x, because the fee is proportionally heavier on the cheap side. Both are
    asserted here so neither number can be quoted as the other.
    """
    stake = 4.0
    # fee-free: the clean 12.5x
    assert abs((stake / 0.08) / (stake / 1.00) - 12.5) < 1e-9

    # fee-inclusive: still an order of magnitude, slightly compressed
    cheap = venue_costs.pm_shares_for_spend(stake, 0.08)
    rich = venue_costs.pm_shares_for_spend(stake, 0.99)
    ratio = cheap / rich
    assert 11.0 < ratio < 12.5, ratio

    # the point of the trap: settlement notional per $1 staked varies hugely, so any
    # dollar-denominated risk stat computed at flat SHARE does not describe a flat-DOLLAR arm
    assert cheap * 1.00 / stake > 11.0, cheap


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except Exception as e:                                    # noqa: BLE001
            failed += 1
            print(f"  FAIL  {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
