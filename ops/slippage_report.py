#!/usr/bin/env python3
"""What the hedge actually paid against what the cover was priced at, per league, read-only.

    python3 ops/slippage_report.py [--db PATH] [--hours 168] [--min-samples 20]

L86 (2026-09-12). Entry prices a cover at the hedge's CURRENT vwap and charges nothing for that
price moving: `Plan.holding_reserve_per_contract` is fee + settlement buffer only, and
`nodes/cover/capacity.slippage_for` is read by `frontier()` for reporting and by nothing that
gates an order (`44045ff` says so in its own message). The first 48 h of real covers put the cost
of that omission at a 5c median against the ~0.5c of margin a 0.5 % hurdle provides, every one of
seven adverse, five of seven covers losing money.

This is the measurement that has to exist before a reserve can be set honestly. It reports, per
league, the realised hedge slippage and what it did to the cover's return; it refuses to suggest a
per-league reserve until a league has `--min-samples`, because that module's rule is that an
unmeasured league is LABELLED unmodelled, never assumed zero.

Nothing here gates anything. Wiring a measured number into SLIPPAGE_BY_LEAGUE and charging it at
entry is a dated GATE_TO_LIVE row, not a report.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import time
from pathlib import Path

#: Importable when piped to the box's interpreter on stdin (`bash ops/box/run.sh < wrapper.sh`),
#: where there is no `__file__`; the release tree is already on the path there.
if "__file__" in globals():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kernel.paths import DB  # noqa: E402
from kernel.schema import Mode  # noqa: E402

#: A cover's own cushion: what the plan left between its all-in cost and the payout, in cents.
#: Slippage above this turns a planned profit into a realised loss.
REAL_MODES = frozenset(m.value for m in Mode if m.sends_real_orders)


def summarize(xs: list[float]) -> dict:
    if not xs:
        return {}
    s = sorted(xs)
    out = {"n": len(s), "min": round(s[0], 2), "p50": round(statistics.median(s), 2),
           "max": round(s[-1], 2), "mean": round(statistics.fmean(s), 2),
           "adverse": sum(1 for x in s if x > 0)}
    if len(s) >= 10:
        out["p90"] = round(statistics.quantiles(s, n=10)[8], 2)
    return out


def covers(con, *, since_ts: float):
    """Every real cover that reached a hedge fill, with its planned and realised economics."""
    sql = ("SELECT execution_id, league, mode, last_utc, state, quantity, plan_json, "
           "first_avg_price, hedge_avg_price FROM executions "
           "WHERE hedge_avg_price IS NOT NULL AND first_avg_price IS NOT NULL "
           "AND plan_json IS NOT NULL AND last_utc > ? ORDER BY last_utc")
    for eid, league, mode, t, state, qty, pj, first, hedge in con.execute(sql, (since_ts,)):
        if mode not in REAL_MODES:
            continue
        try:
            p = json.loads(pj)
            planned_hedge = float(p["hedge"]["vwap"])
            planned_first = float(p["first"]["vwap"])
            hold = float(p["fee"]) + float(p["settlement_buffer"])
            max_cost = float(p["max_cost"])
        except (ValueError, KeyError, TypeError):
            continue
        planned_all = planned_first + planned_hedge + hold
        actual_all = float(first) + float(hedge) + hold
        yield {
            "execution_id": eid, "league": league or "?", "state": state, "utc": float(t),
            "quantity": float(qty or 0.0),
            # The cover's own cushion at entry, in cents: what it could afford to lose and still clear.
            "margin_c": round((max_cost - planned_all) * 100.0, 2),
            "slippage_c": round((float(hedge) - planned_hedge) * 100.0, 2),
            "planned_return": round((1.0 - planned_all) / planned_all, 6) if planned_all > 0 else None,
            "actual_return": round((1.0 - actual_all) / actual_all, 6) if actual_all > 0 else None,
            "pnl_usd": round((1.0 - actual_all) * float(qty or 0.0), 4),
        }


def report(db: Path, *, hours: float = 168.0, min_samples: int = 20) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = list(covers(con, since_ts=time.time() - hours * 3600.0))
    by_league: dict[str, list[dict]] = {}
    for r in rows:
        by_league.setdefault(r["league"], []).append(r)
    leagues = {}
    for lg, rs in sorted(by_league.items()):
        slips = [r["slippage_c"] for r in rs]
        leagues[lg] = {
            **summarize(slips),
            "pnl_usd": round(sum(r["pnl_usd"] for r in rs), 4),
            "lost_money": sum(1 for r in rs if r["pnl_usd"] < 0),
            "margin_c_p50": round(statistics.median([r["margin_c"] for r in rs]), 2),
            # A reserve is only proposed once the league has enough covers to mean anything.
            "reserve_c": (round(statistics.median(slips), 2) if len(rs) >= min_samples else None),
            "measured": len(rs) >= min_samples,
        }
    all_slips = [r["slippage_c"] for r in rows]
    return {
        "covers": len(rows), "hours": hours, "min_samples": min_samples,
        "pooled": {**summarize(all_slips),
                   "pnl_usd": round(sum(r["pnl_usd"] for r in rows), 4),
                   "lost_money": sum(1 for r in rows if r["pnl_usd"] < 0)},
        "by_league": leagues, "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--hours", type=float, default=168.0)
    ap.add_argument("--min-samples", type=int, default=20,
                    help="covers a league needs before this report will propose a reserve for it")
    ap.add_argument("--rows", action="store_true", help="print every cover, not just the summaries")
    a = ap.parse_args()
    r = report(a.db, hours=a.hours, min_samples=a.min_samples)
    print(f"real covers with a hedge fill in the last {a.hours:g} h: {r['covers']}")
    if not r["covers"]:
        print("nothing to measure yet")
        return 0
    p = r["pooled"]
    print(f"pooled hedge slippage (cents): n={p['n']} min={p['min']} p50={p['p50']} "
          f"max={p['max']} mean={p['mean']}  adverse={p['adverse']}/{p['n']}")
    print(f"pooled P&L: {p['pnl_usd']:+.2f} USD across {p['n']} covers; {p['lost_money']} lost money")
    print()
    print(f"{'league':<8}{'n':>4}{'slip p50':>10}{'slip max':>10}{'adverse':>9}"
          f"{'margin p50':>12}{'P&L':>10}{'reserve':>13}")
    for lg, s in r["by_league"].items():
        reserve = f"{s['reserve_c']:.2f}c" if s["measured"] else "unmodelled"
        print(f"{lg:<8}{s['n']:>4}{s['p50']:>10}{s['max']:>10}"
              f"{str(s['adverse']) + '/' + str(s['n']):>9}{s['margin_c_p50']:>12}"
              f"{s['pnl_usd']:>10.2f}{reserve:>13}")
    thin = [lg for lg, s in r["by_league"].items() if not s["measured"]]
    if thin:
        print()
        print(f"UNMEASURED (fewer than {a.min_samples} covers): {', '.join(thin)} — these leagues have "
              f"no defensible reserve yet. Labelled unmodelled; not assumed zero.")
    if a.rows:
        print()
        print(f"{'exec':<10}{'lg':<6}{'slip_c':>8}{'margin_c':>10}{'planned':>10}{'actual':>10}{'pnl':>9}")
        for row in r["rows"]:
            pr = f"{row['planned_return'] * 100:.2f}%" if row["planned_return"] is not None else "-"
            ar = f"{row['actual_return'] * 100:.2f}%" if row["actual_return"] is not None else "-"
            print(f"{row['execution_id'][:8]:<10}{row['league']:<6}{row['slippage_c']:>8}"
                  f"{row['margin_c']:>10}{pr:>10}{ar:>10}{row['pnl_usd']:>9.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
