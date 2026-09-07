#!/usr/bin/env python3
"""Print the execution-proof commands with REAL tickers and slugs filled in, from the lane's own
events table, so the operator never runs a placeholder (2026-09-07: `<ticker>` reached zsh as a
redirect and neither proof ran).

    python3 ops/proof_target.py              # the next co-listed MLB game (pre-game or in play)
    python3 ops/proof_target.py --league epl

Read-only. It chooses nothing about size or side beyond the proofs' defaults (2 Kalshi contracts,
Polymarket's minimum order); the operator still decides whether to run them.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kernel.paths import DB  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--league", default="mlb")
    ap.add_argument("--db", type=Path, default=DB)
    a = ap.parse_args()
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    now = time.time()
    rows = con.execute(
        "SELECT short_name, phase, start_utc, pm_slug, spec_json FROM events WHERE league=? AND pm_slug IS NOT NULL "
        "AND spec_json IS NOT NULL AND start_utc > ? ORDER BY start_utc LIMIT 3", (a.league, now - 3 * 3600)).fetchall()
    if not rows:
        print(f"no co-listed {a.league} game in the events table within the last 3 h or ahead; run again when the slate has one")
        return 1
    for name, phase, start, slug, sj in rows:
        spec = json.loads(sj)
        when = time.strftime("%Y-%m-%d %H:%MZ", time.gmtime(start))
        print(f"\n== {name} ({phase}, starts {when}); Polymarket slug {slug}")
        for key, v in spec["outcomes"].items():
            print(f"   outcome {key:<16} Kalshi {v.get('kalshi')}   Polymarket YES token {str(v.get('polymarket'))[:14]}…")
        first = next(iter(spec["outcomes"].values()))
        label = next(iter(spec["outcomes"])).split(":")[-1].replace("_", " ")
        print("\n   Kalshi proof (dry run, then armed, then settle after the game):")
        print(f"   python3 ops/kalshi_live_proof.py --ticker {first['kalshi']} --contracts 2")
        print(f"   python3 ops/kalshi_live_proof.py --ticker {first['kalshi']} --contracts 2 --arm")
        print("   python3 ops/kalshi_live_proof.py --settle /Volumes/Kilos/janus/proofs/<the kalshi_*.json the armed run printed>")
        print("\n   Polymarket proof (dry, armed, settle); --outcome is the team's label on Polymarket, --token the YES token id:")
        print(f"   python3 ops/polymarket_live_proof.py --slug {slug} --token {first['polymarket']}")
        print(f"   python3 ops/polymarket_live_proof.py --slug {slug} --token {first['polymarket']} --arm")
        print("   python3 ops/polymarket_live_proof.py --settle /Volumes/Kilos/janus/proofs/<the polymarket_*.json the armed run printed>")
        break
    print("\nThe one thing to paste by hand is the proof file name each armed run prints; everything else above is literal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
