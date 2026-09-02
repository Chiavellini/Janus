#!/usr/bin/env python3
"""Significance / false-positive controls for Janus.

PROVENANCE — COPIED, NOT IMPORTED.
  Source A: ~/Code/Kilos/Phase1/validate.py               (copied 2026-07-24, verbatim bodies)
  Source B: ~/Code/Kilos/Equity/kernel/stats.py              (copied 2026-07-24, verbatim bodies)
  Source B is itself a copy of Kilos PM/phase2/run_phase2.py + favorite_study.py.

Janus is a READ-ONLY CONSUMER of Kilos data and imports NO Kilos code. Per the doctrine in
~/Code/Kilos/DaC/AGENTS.md rule 1, shared lineage is carried by copying with a
provenance header, never by a cross-project import. If you fix a bug here that also exists
upstream, say so in the commit message — the two copies drift on purpose, not by accident.

Pure functions only. No data access, no label access, no holdout access lives in this file.

Two naming notes, because the same idea appears twice with different signatures:
  * `block_bootstrap_ci` (Source A) returns a dict; `day_block_ci` (Source B) returns a
    (lo, hi) tuple. Both are kept — call sites upstream expect different shapes.
  * "dSR" in this program means the PAIRED SHARPE DIFFERENCE from `paired_sharpe_diff_ci`.
    It is NOT Lopez de Prado's deflated Sharpe ratio, which is not implemented anywhere in
    either project. Do not conflate them in a writeup.
"""

from __future__ import annotations

import csv
import math

import numpy as np
import pandas as pd

# ══════════════════════════════════════════════════════════════════════════
# Settlement PnL
# ══════════════════════════════════════════════════════════════════════════


def settlement_net_pnl(side_is_yes, entry_cents, resolved_yes,
                       fee_round_cents: float = 2.0) -> np.ndarray:
    """Per-trade net PnL (cents) for a hold-to-settlement binary bet.

    NOTE: this is cents per SHARE (flat settlement notional). If the deployed arm sizes flat
    DOLLAR cost (shares = stake/ask), every dollar-denominated risk statistic derived from
    this — worst day, max drawdown, day-Sharpe, concentration — is wrong for that arm. They
    differ 12.5x at ask 0.08. See research/portfolio/2026-07-24_basis-concentration-sizing/
    in Kilos. `ev_c` per $1 of settlement notional is scale-free and does carry over.
    """
    side_is_yes = np.asarray(side_is_yes, dtype=bool)
    entry_cents = np.asarray(entry_cents, dtype=float)
    resolved_yes = np.asarray(resolved_yes, dtype=int)
    win = side_is_yes == (resolved_yes == 1)
    return np.where(win, 100.0, 0.0) - entry_cents - fee_round_cents


# ══════════════════════════════════════════════════════════════════════════
# Permutation tests (Gate 3)
# ══════════════════════════════════════════════════════════════════════════


def permutation_pvalue(side_is_yes, entry_cents, resolved_yes, *, n: int = 10_000, seed: int = 0,
                       fee_round_cents: float = 2.0) -> dict:
    """Label-permutation test. Null: the chosen side is unrelated to the outcome.

    Shuffles `resolved_yes` across the selected trades (preserving the yes/no outcome mix)
    and recomputes total net PnL. One-sided p = P(perm total >= observed).
    """
    side_is_yes = np.asarray(side_is_yes, dtype=bool)
    entry_cents = np.asarray(entry_cents, dtype=float)
    resolved_yes = np.asarray(resolved_yes, dtype=int)
    obs = settlement_net_pnl(side_is_yes, entry_cents, resolved_yes, fee_round_cents).sum()
    rng = np.random.default_rng(seed)
    perm = np.empty(n)
    for i in range(n):
        perm[i] = settlement_net_pnl(
            side_is_yes, entry_cents, rng.permutation(resolved_yes), fee_round_cents).sum()
    p = (np.sum(perm >= obs) + 1) / (n + 1)
    return {"observed_net_cents": float(obs), "perm_mean": float(perm.mean()),
            "perm_std": float(perm.std()), "p_value": float(p), "n_perm": n}


def day_block_perm_p(trades: pd.DataFrame, *, n: int = 10_000, seed: int = 0) -> float:
    """Day-block permutation p: shuffle whole-day outcome blocks, recompute total pnl.

    Preferred over `permutation_pvalue` whenever trades within a day are correlated (they are
    here — concurrent windows on the same asset were 99.6% same-side in Kilos' measurement).
    Requires columns: open_date, side_up, outcome_up, pnl_win, pnl_loss.
    """
    order = np.argsort(trades["open_date"].values, kind="stable")
    su = trades["side_up"].values.astype(bool)[order]
    ou = trades["outcome_up"].values.astype(bool)[order]
    pw = trades["pnl_win"].values.astype(float)[order]
    pl = trades["pnl_loss"].values.astype(float)[order]
    ds = trades["open_date"].values[order]
    obs = np.where(su == ou, pw, pl).sum()
    blocks = [ou[ds == d] for d in pd.unique(ds)]
    rng = np.random.default_rng(seed)
    perms = np.empty(n)
    idx = np.arange(len(blocks))
    for i in range(n):
        rng.shuffle(idx)
        sh = np.concatenate([blocks[j] for j in idx])
        perms[i] = np.where(su == sh, pw, pl).sum()
    return float((np.sum(perms >= obs) + 1) / (n + 1))


def paired_signflip_pvalue(diffs, groups, *, n: int = 20_000, seed: int = 0) -> dict:
    """Day-block sign-flip test on a PAIRED per-trade difference series (e.g. overlay - base).

    Null: the overlay has no effect (diffs symmetric about 0, whole days exchangeable in sign).
    Valid for path-dependent exit PnL, where the label-permutation test's settlement-payoff
    assumption is not.
    """
    diffs = np.asarray(diffs, dtype=float)
    groups = np.asarray(groups)
    uniq = np.unique(groups)
    sums = np.array([diffs[groups == g].sum() for g in uniq])
    m = len(diffs)
    obs = diffs.mean()
    rng = np.random.default_rng(seed)
    flips = rng.choice([-1.0, 1.0], size=(n, len(uniq)))
    perm_means = (flips @ sums) / m
    p = (np.sum(perm_means >= obs) + 1) / (n + 1)
    return {"observed_mean_diff_cents": float(obs), "n_days": int(len(uniq)),
            "p_value": float(p), "n_perm": n}


# ══════════════════════════════════════════════════════════════════════════
# Confidence intervals (Gate 4)
# ══════════════════════════════════════════════════════════════════════════


def block_bootstrap_ci(values, groups, *, n: int = 10_000, seed: int = 0,
                       alpha: float = 0.05) -> dict:
    """CI on mean per-trade net PnL by resampling whole groups (trading days) with replacement.

    Respects within-day correlation that a naive per-trade bootstrap would ignore. Returns a
    dict; see `day_block_ci` for the (lo, hi) tuple form.
    """
    values = np.asarray(values, dtype=float)
    groups = np.asarray(groups)
    uniq = np.unique(groups)
    idx_by = {g: np.where(groups == g)[0] for g in uniq}
    rng = np.random.default_rng(seed)
    means = np.empty(n)
    for i in range(n):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        sel = np.concatenate([idx_by[g] for g in pick])
        means[i] = values[sel].mean() if sel.size else np.nan
    lo, hi = np.nanquantile(means, [alpha / 2, 1 - alpha / 2])
    return {"mean": float(values.mean()), "ci_lo": float(lo), "ci_hi": float(hi),
            "alpha": alpha, "n_days": int(len(uniq))}


def day_block_ci(pnl, dates, *, n: int = 10_000, seed: int = 0, alpha: float = 0.05):
    """(lo, hi) tuple form of `block_bootstrap_ci`. Kept for call-site compatibility."""
    r = block_bootstrap_ci(pnl, dates, n=n, seed=seed, alpha=alpha)
    return r["ci_lo"], r["ci_hi"]


def paired_sharpe_diff_ci(a, b, groups, *, n: int = 10_000, seed: int = 0,
                          alpha: float = 0.05) -> dict:
    """Paired day-block bootstrap CI on the per-trade Sharpe DIFFERENCE SR(a) - SR(b).

    Both series must be measured on the SAME trades. Resamples whole groups (days) with
    replacement and recomputes both arms' SR on the pooled resampled trades.

    This is the program's "dSR". With few day blocks the CI is indicative, not a precise test.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    groups = np.asarray(groups)
    uniq = np.unique(groups)
    idx_by = {g: np.where(groups == g)[0] for g in uniq}

    def sr(x):
        s = x.std()
        return x.mean() / s if s > 0 else np.nan

    obs = sr(a) - sr(b)
    rng = np.random.default_rng(seed)
    diffs = np.empty(n)
    for i in range(n):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        sel = np.concatenate([idx_by[g] for g in pick])
        diffs[i] = sr(a[sel]) - sr(b[sel])
    lo, hi = np.nanquantile(diffs, [alpha / 2, 1 - alpha / 2])
    return {"sr_a": float(sr(a)), "sr_b": float(sr(b)), "delta_sr": float(obs),
            "ci_lo": float(lo), "ci_hi": float(hi), "alpha": alpha, "n_days": int(len(uniq))}


# ══════════════════════════════════════════════════════════════════════════
# Multiple-testing control (the snooping budget)
# ══════════════════════════════════════════════════════════════════════════


def bh_fdr_threshold(ledger_rows: int, q: float = 0.10) -> float:
    """BH-FDR per-look threshold used across the program: q / (total ledger row count).

    `ledger_rows` = the number of rows in THIS project's snooping_ledger.md at the time of the
    look, including the row being spent. Janus starts a FRESH budget at 0 spent looks — it does
    NOT inherit Kilos' row counts.
    """
    return q / max(1, ledger_rows)


def benjamini_hochberg(pvalues: list[float], q: float = 0.10) -> dict:
    """BH step-up across all configs tried. Returns which hypotheses survive FDR control at q
    and the largest passing p (the threshold)."""
    p = np.asarray(pvalues, dtype=float)
    m = len(p)
    order = np.argsort(p)
    thresh = q * (np.arange(1, m + 1)) / m
    passed = p[order] <= thresh
    kmax = np.max(np.where(passed)[0]) + 1 if passed.any() else 0
    crit = float(p[order][kmax - 1]) if kmax > 0 else 0.0
    survive = (p <= crit) if kmax > 0 else np.zeros(m, dtype=bool)
    return {"m_tests": m, "q": q, "crit_p": crit, "n_survive": int(survive.sum()),
            "survive_mask": survive.tolist()}


# ══════════════════════════════════════════════════════════════════════════
# Fold stability
# ══════════════════════════════════════════════════════════════════════════

FOLD_ROBUST_MIN_FOLDS = 10
FOLD_ROBUST_MIN_PCT_POSITIVE = 60.0
FOLD_ROBUST_MIN_WORST_CENTS = -20.0


def fold_stability_cents(pnl, open_date) -> dict:
    """Per-day fold stability. `fold_robust` requires >=10 folds, >=60% positive, worst > -20c."""
    pnl = np.asarray(pnl, dtype=float)
    if len(pnl) == 0:
        return {"n_folds": 0, "pct_positive_folds": None,
                "min_fold_mean_cents": None, "fold_robust": False}
    df = pd.DataFrame({"pnl": pnl, "open_date": np.asarray(open_date)})
    means = df.groupby("open_date")["pnl"].mean().values
    pct_pos = round(float((means > 0).mean() * 100.0), 2)
    worst = round(float(means.min()), 4)
    return {
        "n_folds": int(len(means)),
        "pct_positive_folds": pct_pos,
        "min_fold_mean_cents": worst,
        "fold_robust": bool(
            len(means) >= FOLD_ROBUST_MIN_FOLDS
            and pct_pos >= FOLD_ROBUST_MIN_PCT_POSITIVE
            and worst > FOLD_ROBUST_MIN_WORST_CENTS
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# IO helpers
# ══════════════════════════════════════════════════════════════════════════


def json_ready(v):
    """Recursively convert numpy scalars/containers to JSON-serialisable Python types."""
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (np.floating, np.integer)):
        return v.item()
    if isinstance(v, (list, tuple)):
        return [json_ready(x) for x in v]
    if isinstance(v, dict):
        return {str(k): json_ready(vv) for k, vv in v.items()}
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def write_csv(rows: list[dict], path) -> None:
    """Write a list of dicts to CSV using the first row's keys as the header."""
    from pathlib import Path
    path = Path(path)
    if not rows:
        path.write_text("")
        return
    keys = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in keys})
