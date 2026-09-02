#!/usr/bin/env python3
"""Janus Phase-1 GO/NO-GO: the cross-venue settlement basis.

Answers one question: is the Kalshi<->Polymarket price difference a real arbitrage, or is it
compensation for the two venues settling differently?

  Part 1  agreement      -- how often do the two venues settle the same way? (acceptance test)
  Part 2  mechanism      -- reconstruct BOTH reference levels and test H1: disagreement happens
                            when the close lands between them
  Part 3  ev_surface     -- conditional EV after both fees and measured oracle risk

Read-only against Kilos. Spends no snooping look (descriptive; see spec.yaml).

    python3 engine.py --out-dir .
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from lib import kilos_data as kd            # noqa: E402
from lib import stats, venue_costs          # noqa: E402

ORACLE_ASSETS = {"btc": "btc/usd", "eth": "eth/usd", "sol": "sol/usd"}


# ══════════════════════════════════════════════════════════════════════════
# Part 1 — agreement
# ══════════════════════════════════════════════════════════════════════════

def part1_agreement(rows: list[dict]) -> dict:
    by_asset = defaultdict(lambda: {"n": 0, "disagree": 0, "xtab": Counter()})
    for r in rows:
        a = by_asset[r["asset"]]
        a["n"] += 1
        a["disagree"] += (not r["agree"])
        a["xtab"][(r["pm_resolution"], r["kalshi_result"])] += 1

    out = {}
    for asset, a in sorted(by_asset.items()):
        n, d = a["n"], a["disagree"]
        p = d / n if n else float("nan")
        # day-block CI on the disagreement rate
        days = np.array([r["open_date"] for r in rows if r["asset"] == asset])
        vals = np.array([0.0 if r["agree"] else 1.0 for r in rows if r["asset"] == asset])
        ci = stats.block_bootstrap_ci(vals, days, n=2000, seed=0)
        out[asset] = {
            "n_matched": n, "n_disagree": d, "p_disagree": round(p, 5),
            "p_disagree_ci": [round(ci["ci_lo"], 5), round(ci["ci_hi"], 5)],
            "n_days": ci["n_days"],
            "hedge_value_cents": round(100 * (1 - p), 3),
            "required_nominal_edge_cents": round(100 * p, 3),
            "xtab": {f"pm={k[0]},kalshi={k[1]}": v for k, v in sorted(a["xtab"].items())},
        }
    return out


# ══════════════════════════════════════════════════════════════════════════
# Part 2 — mechanism: reconstruct both reference levels
# ══════════════════════════════════════════════════════════════════════════

def load_oracle(asset: str) -> tuple[np.ndarray, np.ndarray]:
    """Chainlink series (PM's settlement feed) as sorted (ts, price) arrays."""
    sym = ORACLE_ASSETS.get(asset)
    if sym is None:
        return np.array([]), np.array([])
    ts, px = [], []
    for db in (kd.PM_DB, kd.PM_XA_DB):
        if not db.exists():
            continue
        con = kd.connect_ro(db)
        try:
            q = ("SELECT timestamp, price FROM pm_oracle_prices "
                 "WHERE source='chainlink' AND symbol=? ORDER BY timestamp")
            for t, p in con.execute(q, (sym,)):
                ts.append(t); px.append(p)
        finally:
            con.close()
    if not ts:
        return np.array([]), np.array([])
    o = np.argsort(ts)
    return np.asarray(ts, float)[o], np.asarray(px, float)[o]


def asof(ts: np.ndarray, px: np.ndarray, t: float, max_stale: float = 120.0):
    """Last oracle print at or before t, or None if the feed is staler than max_stale."""
    if ts.size == 0:
        return None
    i = np.searchsorted(ts, t, side="right") - 1
    if i < 0 or (t - ts[i]) > max_stale:
        return None
    return float(px[i])


def part2_mechanism(rows: list[dict]) -> tuple[dict, list[dict]]:
    """H1: the venues disagree when the close lands BETWEEN their two reference levels."""
    recs = []
    for asset in sorted({r["asset"] for r in rows}):
        ts, px = load_oracle(asset)
        if ts.size == 0:
            continue
        for r in (x for x in rows if x["asset"] == asset):
            pm_ref = asof(ts, px, r["window_start"])      # PM's reference = window open
            close = asof(ts, px, r["close_ts"])           # the settling print
            k_ref = r["floor_strike"]                     # Kalshi's reference
            if pm_ref is None or close is None or not k_ref:
                continue
            wedge = k_ref - pm_ref                        # signed, in price units
            move = close - pm_ref                         # realized move over the window
            # Does the close land strictly between the two references?
            lo, hi = (min(pm_ref, k_ref), max(pm_ref, k_ref))
            between = lo <= close < hi
            # Kalshi's OWN settlement print (its BRTI reading) when available -- lets us measure
            # the index difference directly instead of inferring it from the reference wedge.
            k_settle = r.get("kalshi_settle_value")
            idx_diff_bps = (1e4 * (k_settle - close) / close) if k_settle else None
            recs.append({
                "asset": asset, "open_date": r["open_date"], "close_ts": r["close_ts"],
                "pm_ref": pm_ref, "kalshi_ref": k_ref, "close": close,
                "kalshi_settle": k_settle, "index_diff_bps": idx_diff_bps,
                "wedge_abs": abs(wedge), "wedge_bps": 1e4 * wedge / pm_ref,
                "move_abs": abs(move), "move_bps": 1e4 * move / pm_ref,
                "close_between_refs": between,
                "agree": r["agree"],
                "move_lt_wedge": abs(move) < abs(wedge),
                "floor_strike_source": r.get("floor_strike_source"),
            })

    summ = {}
    for asset in sorted({x["asset"] for x in recs}):
        rs = [x for x in recs if x["asset"] == asset]
        dis = [x for x in rs if not x["agree"]]
        agr = [x for x in rs if x["agree"]]
        wedges = np.array([x["wedge_abs"] for x in rs])
        wedge_bps = np.array([abs(x["wedge_bps"]) for x in rs])
        idx = np.array([x["index_diff_bps"] for x in rs if x["index_diff_bps"] is not None])
        summ[asset] = {
            "n": len(rs), "n_disagree": len(dis),
            # BRTI vs Chainlink, measured directly from Kalshi's own settlement print
            "index_diff_bps_n": int(idx.size),
            "index_diff_bps_median": round(float(np.median(idx)), 3) if idx.size else None,
            "index_diff_bps_abs_median": round(float(np.median(np.abs(idx))), 3) if idx.size else None,
            "index_diff_bps_abs_p90": round(float(np.percentile(np.abs(idx), 90)), 3) if idx.size else None,
            "wedge_abs_median": round(float(np.median(wedges)), 4),
            "wedge_bps_median": round(float(np.median(wedge_bps)), 3),
            "wedge_bps_p90": round(float(np.percentile(wedge_bps, 90)), 3),
            "median_abs_move_bps_all": round(
                float(np.median([abs(x["move_bps"]) for x in rs])), 3),
            "median_abs_move_bps_disagree": round(
                float(np.median([abs(x["move_bps"]) for x in dis])), 3) if dis else None,
            "median_abs_move_bps_agree": round(
                float(np.median([abs(x["move_bps"]) for x in agr])), 3) if agr else None,
            # H1 tests
            "pct_disagree_with_close_between_refs": round(
                100 * np.mean([x["close_between_refs"] for x in dis]), 2) if dis else None,
            "pct_agree_with_close_between_refs": round(
                100 * np.mean([x["close_between_refs"] for x in agr]), 2) if agr else None,
            "p_disagree_given_close_between": _cond(rs, lambda x: x["close_between_refs"]),
            "p_disagree_given_close_outside": _cond(rs, lambda x: not x["close_between_refs"]),
            "p_disagree_given_move_lt_wedge": _cond(rs, lambda x: x["move_lt_wedge"]),
            "p_disagree_given_move_gt_wedge": _cond(rs, lambda x: not x["move_lt_wedge"]),
        }
    return summ, recs


def _cond(rs, pred):
    sel = [x for x in rs if pred(x)]
    if not sel:
        return {"n": 0, "p_disagree": None}
    return {"n": len(sel),
            "p_disagree": round(float(np.mean([not x["agree"] for x in sel])), 5)}


# ══════════════════════════════════════════════════════════════════════════
# Part 3 — the EV surface
# ══════════════════════════════════════════════════════════════════════════

def part3_ev_surface(recs: list[dict]) -> list[dict]:
    """Conditional oracle risk by an ENTRY-OBSERVABLE gate, and the EV it implies.

    The gate is |move so far| / |wedge| -- how decisively the price has cleared the ambiguous
    band between the two reference levels. Both inputs are observable live: Kalshi publishes
    floor_strike, and the Chainlink stream is the PM reference. Here it is evaluated at the
    CLOSE (i.e. with hindsight) to establish the ceiling on what such a gate can deliver; the
    entry-time version is the follow-up study and will be strictly worse.
    """
    out = []
    bands = [(0.0, 1.0), (1.0, 2.0), (2.0, 5.0), (5.0, 10.0), (10.0, 1e9)]
    for asset in sorted({x["asset"] for x in recs}):
        rs = [x for x in recs if x["asset"] == asset and x["wedge_abs"] > 0]
        for lo, hi in bands:
            sel = [x for x in rs if lo <= x["move_abs"] / x["wedge_abs"] < hi]
            if len(sel) < 20:
                continue
            p_dis = float(np.mean([not x["agree"] for x in sel]))
            days = np.array([x["open_date"] for x in sel])
            vals = np.array([0.0 if x["agree"] else 1.0 for x in sel])
            ci = stats.block_bootstrap_ci(vals, days, n=2000, seed=0)
            hedge = 100 * (1 - p_dis)
            out.append({
                "asset": asset,
                "band_move_over_wedge": f"{lo:g}-{hi:g}" if hi < 1e9 else f"{lo:g}+",
                "n": len(sel),
                "pct_of_windows": round(100 * len(sel) / len(rs), 2),
                "p_disagree": round(p_dis, 5),
                "p_disagree_ci_lo": round(ci["ci_lo"], 5),
                "p_disagree_ci_hi": round(ci["ci_hi"], 5),
                "hedge_value_cents": round(hedge, 3),
                "required_nominal_edge_cents": round(100 * p_dis, 3),
            })
    return out


# ══════════════════════════════════════════════════════════════════════════

def part4_entry_gate(rows: list[dict], offsets=(0, 300, 480, 660, 780, 840)) -> list[dict]:
    """THE deliverable: the gate computed at ENTRY time, with no hindsight.

    Part 3's gate used the closing price, so it is an upper bound nobody can trade. Here the same
    ratio is rebuilt from information available at `offset` seconds into the window:

        gate = |price_so_far - pm_ref| / |kalshi_ref - pm_ref|

    Both inputs are live-observable -- Kalshi publishes floor_strike when the market opens, and
    the Chainlink stream is PM's own settlement feed. So this is OBSERVING how decisively the
    price has cleared the ambiguous band between the two venues' reference levels, not predicting
    anything. The question is how much of Part 3's separation survives the loss of hindsight.
    """
    out = []
    bands = [(0.0, 1.0), (1.0, 2.0), (2.0, 5.0), (5.0, 10.0), (10.0, 1e9)]
    for asset in sorted({r["asset"] for r in rows}):
        ts, px = load_oracle(asset)
        if ts.size == 0:
            continue
        base = []
        for r in (x for x in rows if x["asset"] == asset):
            pm_ref = asof(ts, px, r["window_start"])
            k_ref = r["floor_strike"]
            if pm_ref is None or not k_ref:
                continue
            wedge = abs(k_ref - pm_ref)
            if wedge <= 0:
                continue
            base.append((r, pm_ref, wedge))
        for off in offsets:
            rec = []
            for r, pm_ref, wedge in base:
                p = asof(ts, px, r["window_start"] + off)
                if p is None:
                    continue
                rec.append({"gate": abs(p - pm_ref) / wedge, "agree": r["agree"],
                            "open_date": r["open_date"]})
            if not rec:
                continue
            for lo, hi in bands:
                sel = [x for x in rec if lo <= x["gate"] < hi]
                if len(sel) < 30:
                    continue
                p_dis = float(np.mean([not x["agree"] for x in sel]))
                ci = stats.block_bootstrap_ci(
                    np.array([0.0 if x["agree"] else 1.0 for x in sel]),
                    np.array([x["open_date"] for x in sel]), n=2000, seed=0)
                out.append({
                    "asset": asset, "offset_s": off,
                    "band_move_over_wedge": f"{lo:g}-{hi:g}" if hi < 1e9 else f"{lo:g}+",
                    "n": len(sel), "pct_of_windows": round(100 * len(sel) / len(rec), 2),
                    "p_disagree": round(p_dis, 5),
                    "p_disagree_ci_lo": round(ci["ci_lo"], 5),
                    "p_disagree_ci_hi": round(ci["ci_hi"], 5),
                    "hedge_value_cents": round(100 * (1 - p_dis), 3),
                    "required_nominal_edge_cents": round(100 * p_dis, 3),
                })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=".")
    a = ap.parse_args()
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)

    print("loading matched settlements (read-only from Kilos)...")
    rows = kd.matched_settlements()
    print(f"  matched windows: {len(rows)}")

    print("part 1 -- agreement")
    agree = part1_agreement(rows)
    for k, v in agree.items():
        print(f"  {k:4s} n={v['n_matched']:5d} disagree={v['n_disagree']:4d} "
              f"({100*v['p_disagree']:.2f}%)  hedge worth {v['hedge_value_cents']:.2f}c")

    print("part 2 -- mechanism (reconstructing both reference levels)")
    mech, recs = part2_mechanism(rows)
    print(f"  windows with both references + a settling print: {len(recs)}")
    for k, v in mech.items():
        print(f"  {k:4s} n={v['n']:5d} wedge median {v['wedge_bps_median']:.2f} bps  |  "
              f"|move| median: agree {v['median_abs_move_bps_agree']} vs "
              f"disagree {v['median_abs_move_bps_disagree']} bps")
        print(f"       P(disagree | close BETWEEN refs) = {v['p_disagree_given_close_between']}")
        print(f"       P(disagree | close OUTSIDE refs) = {v['p_disagree_given_close_outside']}")

    print("part 3 -- EV surface (hindsight gate; an upper bound, not tradeable)")
    surf = part3_ev_surface(recs)
    for s in surf:
        print(f"   {s['asset']} move/wedge {s['band_move_over_wedge']:>5s}  n={s['n']:4d} "
              f"({s['pct_of_windows']:5.2f}%)  p_dis={100*s['p_disagree']:6.2f}%  "
              f"hedge {s['hedge_value_cents']:6.2f}c")

    print("\npart 4 -- ENTRY-TIME gate (no hindsight; this is the tradeable version)")
    gate = part4_entry_gate(rows)
    cur = None
    for g in gate:
        if (g["asset"], g["offset_s"]) != cur:
            cur = (g["asset"], g["offset_s"])
            print(f"  {g['asset']} @ open+{g['offset_s']}s "
                  f"({900 - g['offset_s']}s left in window)")
        print(f"     move/wedge {g['band_move_over_wedge']:>5s}  n={g['n']:4d} "
              f"({g['pct_of_windows']:5.2f}%)  p_dis={100*g['p_disagree']:6.2f}% "
              f"[{100*g['p_disagree_ci_lo']:.2f},{100*g['p_disagree_ci_hi']:.2f}]  "
              f"hedge {g['hedge_value_cents']:6.2f}c  needs >{g['required_nominal_edge_cents']:.2f}c")
    stats.write_csv(gate, out / "entry_gate.csv")

    stats.write_csv([{"asset": k, **{kk: vv for kk, vv in v.items() if kk != "xtab"}}
                     for k, v in agree.items()], out / "agreement_by_asset.csv")
    stats.write_csv(recs, out / "mechanism.csv")
    stats.write_csv(surf, out / "ev_surface.csv")

    res = {
        "schema_version": 1,
        "run_ts_utc": dt.datetime.now(dt.UTC).isoformat(),
        "script": "research/basis/2026-07-24_settlement-agreement/engine.py",
        "spec_ref": "research/basis/2026-07-24_settlement-agreement/spec.yaml",
        "holdout_touched": False,
        "snooping_look_spent": False,
        "n_matched_windows": len(rows),
        "part1_agreement": agree,
        "part2_mechanism": mech,
        "part3_ev_surface_hindsight": surf,
        "part4_entry_gate": gate,
        "cost_pins": {
            "kalshi_taker_coeff": venue_costs.KALSHI_TAKER_COEFF,
            "pm_taker_rate": venue_costs.PM_TAKER_RATE,
        },
    }
    (out / "results.json").write_text(json.dumps(stats.json_ready(res), indent=1))
    print(f"\nwrote {out}/results.json + 3 csv")

    # acceptance tests from spec.yaml
    print("\nacceptance tests (must reproduce the 2026-07-24 ad-hoc measurement):")
    exp = {"btc": (2859, 163), "eth": (1063, 65), "sol": (1064, 79)}
    ok = True
    for asset, (n, d) in exp.items():
        got = agree.get(asset)
        good = got and got["n_matched"] == n and got["n_disagree"] == d
        ok &= bool(good)
        print(f"  {'PASS' if good else 'FAIL'}  {asset}: expected n={n} disagree={d}, "
              f"got n={got['n_matched'] if got else '-'} disagree={got['n_disagree'] if got else '-'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
