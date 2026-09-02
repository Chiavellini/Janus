#!/usr/bin/env python3
"""Economic screen: of the blocked candidates, which actually show a tradeable price gap?

    python3 match/screen.py --match-dir data/match --catalog data/catalog

WHY THIS RUNS BEFORE THE LLM VERIFIER. Blocking emits ~112k candidates. Verifying all of them by
reading two rules texts each is expensive and, more importantly, POINTLESS: if the two venues quote
the same price there is nothing to trade whether or not they are the same market. So the pipeline is

    block  ->  ECONOMIC SCREEN  ->  LLM equivalence verify  ->  trade

which cuts verification to the handful of pairs where money is actually on the table.

THE TRADE. Both legs are hold-to-resolution buys of OPPOSITE outcomes, one per venue:

    A:  buy Kalshi YES  @ kalshi_yes_ask   +   buy Polymarket NO  @ (1 - pm_best_bid)
    B:  buy Kalshi NO   @ (1 - kalshi_yes_bid) +  buy Polymarket YES @ pm_best_ask

Exactly one leg pays $1, so the pair returns 100c *whenever the venues resolve the same way*.
`nominal_edge = 100 - both entry prices - both fees`.

This screen reports the NOMINAL edge only. It is NOT profit:
  * the pair must first be verified to be the same market (rules mismatch is this project's
    equivalent of the oracle wedge that made the BTC trade worth 94.30c instead of 100c);
  * P(venues resolve differently) must then be subtracted -- that is Phase C's job.
A large nominal edge on an unverified pair is a red flag, not an opportunity: it usually means the
two markets are NOT the same question.

PM quote convention (verified against a live book 2026-07-24): gamma's `bestBid`/`bestAsk` describe
the FIRST outcome's book, and the complement's book is its exact mirror (mint/merge enforces
ask_a + ask_b = 1 + spread). So pm_no_ask = 1 - pm_best_bid.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import venue_costs as vc  # noqa: E402


def kalshi_fee_c(price_c: float, fee_multiplier, fee_type: str | None) -> float:
    """Per-contract Kalshi fee in cents, honouring the SERIES fee tier.

    Kalshi fees are not uniform: the catalog crawl found `quadratic:1` (69,976 markets),
    `quadratic_with_maker_fees:1` (2,317) and `quadratic:0` (58). A hardcoded 0.07 is wrong for the
    zero-multiplier series. Interpretation used: effective coeff = 0.07 * fee_multiplier for the
    quadratic family. FLAGGED: confirm against a real fill before this is used for sizing.
    """
    mult = 1.0 if fee_multiplier is None else float(fee_multiplier)
    if not (fee_type or "").startswith("quadratic"):
        mult = 1.0
    coeff = vc.KALSHI_TAKER_COEFF * mult
    if coeff <= 0:
        return 0.0
    p = min(max(price_c / 100.0, 0.0), 1.0)
    return math.ceil(round(coeff * 100.0 * p * (1.0 - p), 9))


def pm_fee_c(price_c: float, fee_schedule: dict | None = None) -> float:
    """Per-contract Polymarket fee in cents, honouring the PER-MARKET rate.

    Polymarket's rate is per-market and `lib/fees/registry.py` labels the pinned 0.07 "the MINORITY
    case ... kept only as a conservative fallback". This function previously applied the constant
    unconditionally, which overstates PM's cost and therefore biases the screen toward "no edge" --
    the more dangerous direction, since a missed edge is invisible while a false one gets caught
    downstream. Measured on the 2026-08-20 non-sports scope: rate 0.07 -> 2,426 markets,
    0.04 -> 1,577, 0.05 -> 1,481, absent -> 255. At the money the 0.04 markets were being charged
    0.75c/leg too much against a two-leg floor of ~3.75c.
    """
    p = min(max(price_c / 100.0, 0.0), 1.0)
    rate = vc.PM_TAKER_RATE
    if isinstance(fee_schedule, dict) and fee_schedule.get("rate") is not None:
        try:
            rate = float(fee_schedule["rate"])
        except (TypeError, ValueError):
            rate = vc.PM_TAKER_RATE
    return rate * 100.0 * p * (1.0 - p)


def pm_fee_rate(fee_schedule: dict | None) -> tuple[float, str]:
    """The rate actually applied, and whether it came from the market or the fallback pin."""
    if isinstance(fee_schedule, dict) and fee_schedule.get("rate") is not None:
        try:
            return float(fee_schedule["rate"]), "per_market"
        except (TypeError, ValueError):
            pass
    return vc.PM_TAKER_RATE, "pinned_fallback"


def screen_pair(cand: dict, kmeta: dict, pmeta: dict | None = None) -> dict | None:
    kb, ka = cand.get("kalshi_yes_bid"), cand.get("kalshi_yes_ask")
    pb, pa = cand.get("pm_best_bid"), cand.get("pm_best_ask")
    if None in (kb, ka, pb, pa):
        return None
    kb, ka, pb, pa = 100 * kb, 100 * ka, 100 * pb, 100 * pa
    if not (0 < kb < ka < 100 and 0 < pb < pa < 100):
        return None

    ft = kmeta.get("fee_type")
    fm = kmeta.get("fee_multiplier")
    fs = (pmeta or {}).get("fee_schedule")
    pm_rate, pm_rate_src = pm_fee_rate(fs)

    # A: Kalshi YES + PM NO
    a_k, a_p = ka, 100 - pb
    a_cost = a_k + a_p + kalshi_fee_c(a_k, fm, ft) + pm_fee_c(a_p, fs)
    # B: Kalshi NO + PM YES
    b_k, b_p = 100 - kb, pa
    b_cost = b_k + b_p + kalshi_fee_c(b_k, fm, ft) + pm_fee_c(b_p, fs)

    side = "A_kalshiYES_pmNO" if a_cost <= b_cost else "B_kalshiNO_pmYES"
    cost = min(a_cost, b_cost)
    edge = 100.0 - cost
    days = max(cand.get("kalshi_days_to_close") or 0, cand.get("pm_days_to_close") or 0, 1e-6)
    # annualised simple return on the capital actually locked up
    ann = ((edge / cost) * (365.0 / days) * 100.0) if cost > 0 else None

    out = dict(cand)
    out.update({
        "side": side,
        "cost_cents": round(cost, 3),
        "nominal_edge_cents": round(edge, 3),
        "days_locked": round(days, 2),
        "annualised_pct": round(ann, 1) if ann is not None else None,
        "kalshi_mid": round((kb + ka) / 2, 2),
        "pm_mid": round((pb + pa) / 2, 2),
        "price_gap_pp": round(abs((kb + ka) / 2 - (pb + pa) / 2), 2),
        "fee_type": ft, "fee_multiplier": fm,
        "pm_fee_rate": pm_rate, "pm_fee_rate_source": pm_rate_src,
    })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-dir", default="data/match")
    ap.add_argument("--catalog", default="data/catalog")
    ap.add_argument("--min-edge", type=float, default=2.0,
                    help="nominal cents; ~2-3c is the floor because Kalshi's ceil() fee alone "
                         "costs ~1c/contract regardless of price")
    # `action="store_true", default=True` could never be turned off from the CLI. The archetype flag
    # is also now redundant with match/verify.py, which rejects a mismatch only when BOTH sides were
    # positively classified -- "other" is a no-match sentinel, not evidence of difference.
    ap.add_argument("--require-archetype-match", dest="require_archetype_match",
                    action="store_true", default=False)
    ap.add_argument("--no-require-archetype-match", dest="require_archetype_match",
                    action="store_false")
    ap.add_argument("--candidates", default=None,
                    help="pair file to price; defaults to <match-dir>/candidates.json. Point this at "
                         "verify.py's survivors to price only pairs that passed equivalence.")
    a = ap.parse_args()
    md, cat = Path(a.match_dir), Path(a.catalog)

    cands = json.loads(Path(a.candidates or (md / "candidates.json")).read_text())
    kmeta = {r["ticker"]: r for r in json.loads((cat / "kalshi_markets.json").read_text())}
    pmeta = {r["condition_id"]: r for r in json.loads((cat / "pm_markets.json").read_text())}
    print(f"candidates: {len(cands)}")

    scored, skipped = [], 0
    for c in cands:
        if a.require_archetype_match and not c.get("archetype_match"):
            continue
        s = screen_pair(c, kmeta.get(c["kalshi_ticker"], {}), pmeta.get(c.get("pm_condition_id")))
        if s is None:
            skipped += 1
            continue
        scored.append(s)
    print(f"priced: {len(scored)}  (skipped for missing/degenerate quotes: {skipped})")

    hits = [s for s in scored if s["nominal_edge_cents"] >= a.min_edge]
    hits.sort(key=lambda x: -x["nominal_edge_cents"])
    (md / "screened.json").write_text(json.dumps(scored))
    (md / "arb_candidates.json").write_text(json.dumps(hits, indent=1))

    print(f"\nnominal edge >= {a.min_edge}c: {len(hits)}  "
          f"({100 * len(hits) / max(1, len(scored)):.1f}% of priced pairs)")
    if scored:
        e = sorted(s["nominal_edge_cents"] for s in scored)
        q = lambda p: e[min(len(e) - 1, int(p * len(e)))]  # noqa: E731
        print(f"edge distribution (cents): p10 {q(.10):+.1f}  p50 {q(.50):+.1f}  "
              f"p90 {q(.90):+.1f}  p99 {q(.99):+.1f}  max {e[-1]:+.1f}")
    print("\nby kalshi category:", Counter(h["kalshi_category"] for h in hits).most_common(10))

    print(f"\n--- top 20 nominal arbs (UNVERIFIED - treat a big number as a red flag) ---")
    for h in hits[:20]:
        print(f"  {h['nominal_edge_cents']:+6.2f}c  cost {h['cost_cents']:6.2f}  "
              f"{h['days_locked']:5.1f}d  ann {str(h['annualised_pct']):>9s}%  "
              f"gap {h['price_gap_pp']:5.1f}pp  jac {h['jaccard']:.2f}")
        print(f"      K: {h['kalshi_text'][:76]}")
        print(f"      P: {h['pm_text'][:76]}")
    print(f"\nwrote {md}/arb_candidates.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
