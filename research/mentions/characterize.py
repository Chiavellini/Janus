#!/usr/bin/env python3
"""Characterize the mentions tape: calibration, EV at real entry prices, and a hypothesis queue.

    python3 research/mentions/characterize.py --out-dir research/mentions/current

CHARACTERIZATION ERA ONLY. Nothing here is a verdict. Every number is descriptive and belongs in
an `L#` ledger row; the sealed forward holdout (research/mentions/HOLDOUT.md) is what can actually
confirm a hypothesis. The output is a RANKED HYPOTHESIS QUEUE, not a promotion.

The central question is calibration: at an entry price of p, does the event happen p of the time?
A systematic gap is the only thing that can pay for two spreads and a fee. Prediction markets in
this program have shown favourite-longshot bias before (Kilos' Equity weekly ladder: far-OTM
"above" strikes implied 0.239 vs 0.138 realized), so that is the prior worth testing here.

LEAK DISCIPLINE (mention markets close early the moment the word is said):
  * prices are sampled at fixed offsets from OPEN, never relative to close;
  * `leaky_duration_s` and `closed_early` exist ONLY to audit contamination and are never features;
  * a market whose first trade arrives long after open has no early price -- those are reported
    separately rather than silently dropped, because dropping them would select on liquidity.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib import mentions_data as md, stats, venue_costs as vc  # noqa: E402

OFFSETS = [0, 300, 900, 1800, 3600, 7200, 21600]
BUCKETS = [(0.00, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 0.35),
           (0.35, 0.50), (0.50, 0.65), (0.65, 0.80), (0.80, 0.90),
           (0.90, 0.95), (0.95, 1.01)]


def load_tape() -> list[dict]:
    p = md.DATA / "kalshi_tape.jsonl"
    if not p.exists():
        raise FileNotFoundError(f"{p} — run research/mentions/build_tape.py first")
    out = []
    with p.open() as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def buy_yes_ev_cents(price: float, outcome: int, fee_mult=1.0) -> float:
    """Net cents from buying YES at `price` and holding to settlement, with the real Kalshi fee."""
    c = price * 100.0
    fee = float(vc.kalshi_fee_cents(c, coeff=vc.KALSHI_TAKER_COEFF * fee_mult))
    return (100.0 - c - fee) if outcome == 1 else -(c + fee)


def calibration(rows, key: str) -> list[dict]:
    out = []
    for lo, hi in BUCKETS:
        sel = [r for r in rows if r.get(key) is not None and lo <= r[key] < hi]
        if len(sel) < 25:
            continue
        px = np.array([r[key] for r in sel])
        oc = np.array([r["outcome"] for r in sel], dtype=float)
        ev_yes = np.array([buy_yes_ev_cents(r[key], r["outcome"]) for r in sel])
        ev_no = np.array([buy_yes_ev_cents(1 - r[key], 1 - r["outcome"]) for r in sel])
        days = np.array([r["ticker"].split("-")[1][:7] if "-" in r["ticker"] else "x"
                         for r in sel])
        ci_y = stats.block_bootstrap_ci(ev_yes, days, n=1500, seed=0)
        ci_n = stats.block_bootstrap_ci(ev_no, days, n=1500, seed=0)
        out.append({
            "bucket": f"{lo:.2f}-{hi:.2f}", "n": len(sel),
            "mean_price": round(float(px.mean()), 4),
            "realized": round(float(oc.mean()), 4),
            "gap_pp": round(100 * float(oc.mean() - px.mean()), 2),
            "ev_buy_yes_c": round(float(ev_yes.mean()), 3),
            "ev_yes_ci": [round(ci_y["ci_lo"], 2), round(ci_y["ci_hi"], 2)],
            "ev_buy_no_c": round(float(ev_no.mean()), 3),
            "ev_no_ci": [round(ci_n["ci_lo"], 2), round(ci_n["ci_hi"], 2)],
        })
    return out


def by_series(rows, key: str, min_n: int = 60) -> list[dict]:
    g = defaultdict(list)
    for r in rows:
        if r.get(key) is not None:
            g[r["series"]].append(r)
    out = []
    for s, rs in g.items():
        if len(rs) < min_n:
            continue
        px = np.array([r[key] for r in rs])
        oc = np.array([r["outcome"] for r in rs], dtype=float)
        out.append({"series": s, "n": len(rs),
                    "mean_price": round(float(px.mean()), 4),
                    "realized": round(float(oc.mean()), 4),
                    "gap_pp": round(100 * float(oc.mean() - px.mean()), 2)})
    out.sort(key=lambda x: x["gap_pp"])
    return out


def coverage(rows) -> dict:
    cov = {"n": len(rows)}
    for off in OFFSETS:
        k = f"px_{off}s"
        cov[k] = sum(1 for r in rows if r.get(k) is not None)
    lags = sorted(r["first_trade_lag_s"] for r in rows if r.get("first_trade_lag_s") is not None)
    if lags:
        cov["first_trade_lag_s_median"] = round(lags[len(lags) // 2], 1)
        cov["first_trade_lag_s_p90"] = round(lags[int(0.9 * len(lags))], 1)
        cov["pct_first_trade_within_5min"] = round(
            100 * sum(1 for x in lags if x <= 300) / len(lags), 1)
    return cov


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="research/mentions/current")
    # first_trade_price is the DEFAULT anchor, not px_900s. Measured on the first 60 tapes: the
    # median first trade lands 9,122s (2.5h) after open and only 3.3% of markets trade within 5
    # minutes, so open-anchored offsets have almost no coverage (px_0s: 0/60, px_900s: 6/60).
    # The first print has 100% coverage, is observable live, and is not close-contaminated.
    ap.add_argument("--key", default="first_trade_price")
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    rows = load_tape()
    rows = [r for r in rows if r.get("outcome") is not None]
    print(f"taped settled mention markets: {len(rows)}")
    cov = coverage(rows)
    print(f"coverage: {json.dumps(cov)}")

    res = {"n_taped": len(rows), "coverage": cov, "calibration": {}, "by_series": {}}
    # the requested key FIRST -- it is the primary anchor and was previously omitted from the
    # calibration dict entirely (only px_* keys were computed), so the headline table never printed
    for k in [a.key] + [f"px_{off}s" for off in OFFSETS]:
        cal = calibration(rows, k)
        if cal:
            res["calibration"][k] = cal
    res["by_series"] = by_series(rows, a.key)

    key = a.key
    if key in res["calibration"]:
        print(f"\n=== CALIBRATION at {key} (entry price vs realized) ===")
        print(f"{'bucket':12s} {'n':>6s} {'price':>7s} {'realized':>9s} {'gap pp':>7s} "
              f"{'EV buy YES':>11s} {'EV buy NO':>11s}")
        for c in res["calibration"][key]:
            print(f"{c['bucket']:12s} {c['n']:6d} {c['mean_price']:7.3f} {c['realized']:9.3f} "
                  f"{c['gap_pp']:+7.2f} {c['ev_buy_yes_c']:+8.2f}c   {c['ev_buy_no_c']:+8.2f}c")
    if res["by_series"]:
        print(f"\n=== most MIS-priced series at {key} (gap = realized - price) ===")
        for s in (res["by_series"][:5] + res["by_series"][-5:]):
            print(f"  {s['series']:26s} n={s['n']:5d} price {s['mean_price']:.3f} "
                  f"realized {s['realized']:.3f}  gap {s['gap_pp']:+6.2f}pp")

    (out / "characterization.json").write_text(json.dumps(stats.json_ready(res), indent=1))
    print(f"\nwrote {out}/characterization.json")
    print("\nNOTE: descriptive only. No hypothesis is confirmed by this file; the sealed forward "
          "holdout is the only thing that can do that (research/mentions/HOLDOUT.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
