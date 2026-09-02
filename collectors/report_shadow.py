#!/usr/bin/env python3
"""F1 checkpoint report — reads the shadow DB, reports the PRE-REGISTERED statistic.

    python3 collectors/report_shadow.py

Spec: research/exec/2026-08-21_shadow-kalshi-open/spec.yaml · Ledger F1.

THE PRIMARY GATE IS GAP EXISTENCE, NOT PnL. That is what the spec pins, and it is the only thing a
handful of events can answer: it is observable at t0 and needs no settlement. PnL is printed because
it is recorded, and is labelled UNDERPOWERED because binary settlement has ~50c standard deviation
-- at n=10 the standard error on mean PnL is ~16c against a hoped-for ~4c edge, so "the shadow
trades made money" is not evidence of anything and must not be reported as though it were.

n COUNTS GAMES, NOT ROWS. The two outcomes of a game are the same bet mirrored; counting them
separately would double apparent n and halve every p-value.

STALE_OPEN / COLD_START rows are excluded from the numerator AND the denominator, and reported
separately -- a market first seen long after it opened is not an at-open observation. That
distinction is why the first run's 94 decisions were discarded.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

DB = Path("/Volumes/Kilos/janus/shadow/kalshi_open.sqlite")


def game_of(ticker: str) -> str:
    """KXMLBGAME-26AUG201835NYYBAL-BAL -> KXMLBGAME-26AUG201835NYYBAL (drop the outcome)."""
    return ticker.rsplit("-", 1)[0] if ticker else ticker


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)

    rows = [dict(zip([c[0] for c in cur.description], r)) for cur in
            [con.execute("SELECT * FROM decisions")] for r in cur.fetchall()]
    if not rows:
        print("no decisions yet -- the collector decides only on markets it watched OPEN")
        return 0

    stale = [r for r in rows if r["reason"] in ("STALE_OPEN", "COLD_START_SEED")]
    valid = [r for r in rows if r["reason"] not in ("STALE_OPEN", "COLD_START_SEED")]

    games = {}
    for r in valid:
        g = game_of(r["kalshi_ticker"])
        # a game counts as having a gap if EITHER of its two outcome rows found one
        cur = games.get(g)
        if cur is None or (r["action"] == "TRADE" and cur["action"] != "TRADE"):
            games[g] = r

    n_games = len(games)
    traded = [g for g in games.values() if g["action"] == "TRADE"]
    lags = sorted(r["lag_s"] for r in valid if r["lag_s"] is not None)

    out = {
        "n_at_open_rows": len(valid),
        "n_games": n_games,
        "excluded_stale_or_seed": len(stale),
        "PRIMARY_gap_existence": {
            "games_with_executable_fee_surviving_gap": len(traded),
            "of_games": n_games,
            "rate": round(len(traded) / n_games, 3) if n_games else None,
        },
        "no_trade_reasons": dict(Counter(r["reason"] for r in valid if r["reason"])),
        "entry_venue_split": dict(Counter(r["entry_venue"] for r in traded if r["entry_venue"])),
        "net_edge_cents_on_trades": {
            "min": round(min((r["net_edge_cents"] for r in traded), default=0), 3),
            "median": round(sorted(r["net_edge_cents"] for r in traded)[len(traded) // 2], 3)
            if traded else None,
            "max": round(max((r["net_edge_cents"] for r in traded), default=0), 3),
        },
        "detection_lag_s": {"p50": lags[len(lags) // 2] if lags else None,
                            "max": lags[-1] if lags else None},
        "checkpoint_reached": n_games >= 10,
    }

    settled = con.execute("SELECT count(*), COALESCE(sum(pnl_cents),0) FROM settlements").fetchone()
    out["pnl"] = {"settled_positions": settled[0], "total_cents": settled[1],
                  "STATUS": "UNDERPOWERED -- ~50c settlement SD means ~16c standard error at n=10; "
                            "no PnL claim may be made at the checkpoint"}

    if a.json:
        print(json.dumps(out, indent=1))
        return 0

    p = out["PRIMARY_gap_existence"]
    print(f"F1 shadow — {out['n_games']} games at open "
          f"({out['n_at_open_rows']} rows; {out['excluded_stale_or_seed']} stale/seed excluded)")
    print(f"\nPRIMARY GATE — executable, fee-surviving gap at t0:")
    print(f"  {p['games_with_executable_fee_surviving_gap']} / {p['of_games']} games"
          + (f"  ({p['rate']:.0%})" if p["rate"] is not None else ""))
    if out["entry_venue_split"]:
        print(f"  entry venue: {out['entry_venue_split']}   "
              f"(both arms pinned; the inherited mirror failed at -2.375c)")
    if traded:
        e = out["net_edge_cents_on_trades"]
        print(f"  net edge on those: min {e['min']}c  median {e['median']}c  max {e['max']}c")
    print(f"\nno-trade reasons: {out['no_trade_reasons']}")
    print(f"detection lag: p50 {out['detection_lag_s']['p50']}s  max {out['detection_lag_s']['max']}s")
    print(f"\ncheckpoint (10 games): {'REACHED' if out['checkpoint_reached'] else 'not yet'}")
    print(f"PnL: {out['pnl']['settled_positions']} settled — {out['pnl']['STATUS']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
