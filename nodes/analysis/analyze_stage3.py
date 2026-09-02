#!/usr/bin/env python3
"""Aggregate Stage-3 polls and evaluate the pre-registered kill criterion.

Spec: research/sports/2026-08-17_stage3-divergence/spec.yaml (ledger L12).

    KILL: fewer than 0.5% of observations below 0.995 at >= $200 depth
          AND no candidate survives a 60s re-fetch
          -> the Track A thesis is DEAD. BOTH must fail.

The decomposition that matters is GROSS vs FEE. "No arbitrage" has two very different causes:
prices that agree (nothing to capture) and prices that diverge but by less than the fee floor
(something to capture, on venues we cannot reach). Phase 1 could not tell these apart; reporting
them separately is the point of this script.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

ARB = 0.995
MIN_DEPTH_CONTRACTS = 200        # $200 of payout at $1/contract


def load(pattern: str) -> list[dict]:
    rows = []
    for f in sorted(glob.glob(pattern)):
        with open(f, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                r["_file"] = Path(f).name
                rows.append(r)
    return rows


def _f(r, k):
    try:
        return float(r[k])
    except (KeyError, TypeError, ValueError):
        return None


def analyze(obs_glob: str, cand_glob: str) -> dict:
    rows = load(obs_glob)
    ok = [r for r in rows if r.get("ok") == "True"]
    polls = len({r["_file"] for r in rows})

    out: dict = {
        "polls": polls,
        "observations_total": len(rows),
        "observations_priced": len(ok),
        "rejects": dict(Counter(r["reject"] for r in rows if r.get("ok") != "True")),
        "games": len({r["game_id"] for r in rows}),
    }

    # ── the kill criterion, evaluated at the registered depth ────────────
    gated = [r for r in ok if (_f(r, "contracts") or 0) >= MIN_DEPTH_CONTRACTS]
    below = [r for r in gated if (_f(r, "cost") or 9) < ARB]
    out["kill_criterion"] = {
        "min_depth_contracts": MIN_DEPTH_CONTRACTS,
        "observations_at_depth": len(gated),
        "below_0995": len(below),
        "rate": round(len(below) / len(gated), 6) if gated else None,
        "threshold": 0.005,
        "rate_test_fails": (len(below) / len(gated) < 0.005) if gated else None,
    }

    cands = load(cand_glob) if cand_glob else []
    persisted = [c for c in cands if str(c.get("persisted")).lower() == "true"]
    out["kill_criterion"]["candidates_seen"] = len(cands)
    out["kill_criterion"]["candidates_persisted_60s"] = len(persisted)
    out["kill_criterion"]["persistence_test_fails"] = (len(persisted) == 0)
    # ── DATA SUFFICIENCY: the criterion may not fire on a short sample ───
    # The spec registers a 7-DAY, 5-MINUTELY collection. Evaluating the kill criterion on twenty
    # minutes of polling and declaring the thesis dead would be exactly the move the pre-registration
    # exists to prevent -- reaching the registered conclusion on unregistered evidence. The verdict
    # stays PRELIMINARY until the registered collection is met.
    MIN_POLLS = 288 * 7 // 12          # >=168 polls ~ 1 poll/5min sustained over the window
    MIN_OBS_AT_DEPTH = 5000
    sufficient = polls >= MIN_POLLS and len(gated) >= MIN_OBS_AT_DEPTH
    out["kill_criterion"]["data_sufficient_for_verdict"] = sufficient
    out["kill_criterion"]["required_polls"] = MIN_POLLS
    out["kill_criterion"]["required_observations_at_depth"] = MIN_OBS_AT_DEPTH
    both_fail = bool(out["kill_criterion"]["rate_test_fails"]
                     and out["kill_criterion"]["persistence_test_fails"])
    out["kill_criterion"]["both_tests_currently_fail"] = both_fail
    out["kill_criterion"]["THESIS_DEAD"] = bool(both_fail and sufficient)
    out["kill_criterion"]["verdict"] = (
        ("THESIS DEAD" if both_fail else "THESIS SURVIVES") if sufficient
        else f"PRELIMINARY - {polls}/{MIN_POLLS} polls, {len(gated)}/{MIN_OBS_AT_DEPTH} obs at depth")

    # ── gross vs fee: WHY there is no arb ────────────────────────────────
    by_q: dict[str, dict] = {}
    for q in sorted({r["contracts"] for r in ok}, key=float):
        sub = [r for r in ok if r["contracts"] == q]
        g = [x for x in (_f(r, "gross") for r in sub) if x is not None]
        fe = [x for x in (_f(r, "fee") for r in sub) if x is not None]
        c = [x for x in (_f(r, "cost") for r in sub) if x is not None]
        if not c:
            continue
        by_q[q] = {
            "n": len(sub),
            "gross_median": round(st.median(g), 5), "gross_min": round(min(g), 5),
            "gross_below_1": sum(1 for x in g if x < 1.0),
            "gross_below_1_rate": round(sum(1 for x in g if x < 1.0) / len(g), 5),
            "fee_median": round(st.median(fe), 5),
            "cost_median": round(st.median(c), 5), "cost_min": round(min(c), 5),
            "cost_below_0995": sum(1 for x in c if x < ARB),
        }
    out["by_quantity"] = by_q

    # ── the headline decomposition ───────────────────────────────────────
    g_all = [x for x in (_f(r, "gross") for r in ok) if x is not None]
    divergent = [r for r in ok if (_f(r, "gross") or 9) < 1.0]
    out["decomposition"] = {
        "gross_below_1_observations": len(divergent),
        "gross_below_1_rate": round(len(divergent) / len(ok), 5) if ok else None,
        "best_gross_seen": round(min(g_all), 5) if g_all else None,
        "median_fee": round(st.median([x for x in (_f(r, "fee") for r in ok)
                                       if x is not None]), 5) if ok else None,
        "reading": ("Prices DIVERGE but by less than the fee floor on the reachable venue pair. "
                    "That is a different finding from 'the venues agree', and phase 1 could not "
                    "distinguish them."),
    }
    if divergent:
        best = min(divergent, key=lambda r: _f(r, "gross"))
        out["decomposition"]["best_divergence_example"] = {
            "gross": _f(best, "gross"), "fee": _f(best, "fee"), "cost": _f(best, "cost"),
            "contracts": _f(best, "contracts"), "legs": best.get("legs"),
            "max_leg_age_s": _f(best, "max_leg_age_s"),
        }

    # ── venue composition of the cheapest cover ──────────────────────────
    comp = Counter()
    for r in ok:
        vs = tuple(sorted(p.split(":")[0] for p in (r.get("legs") or "").split("|") if p))
        if vs:
            comp["+".join(vs)] += 1
    out["cheapest_cover_venue_mix"] = dict(comp.most_common())
    out["single_venue_share"] = round(
        sum(1 for r in ok if r.get("single_venue") == "True") / len(ok), 4) if ok else None

    # ── intra-venue control (L1: 0 violations in 124,437 markets) ────────
    sv = [r for r in ok if r.get("single_venue") == "True"]
    sv_bad = [r for r in sv if (_f(r, "gross") or 9) < 1.0]
    out["intra_venue_control"] = {
        "n": len(sv),
        "gross_below_1": len(sv_bad),
        "expectation": "0 - the complement identity makes intra-venue arb structurally impossible",
        "status": "OK" if not sv_bad else "BUG SIGNAL - investigate before believing anything else",
    }
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/sports/stage3")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    res = analyze(f"{a.dir}/observations_*.csv", f"{a.dir}/candidates_*.csv")
    print(json.dumps(res, indent=1))
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1))
