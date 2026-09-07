#!/usr/bin/env python3
"""Both venues list it; did the lane pair it? The census's independent join (nodes/discovery/census,
daily) gives every event both venues list in the next 48 h; the lane's events table gives what it
paired and, since 2026-09-07, why not (`UNPAIRED:kalshi=…,polymarket=…`, `SPAWN:…`). The difference,
per event with the lane's reason, is this report and the watchdog's COVERAGE_GAP.

    python3 ops/coverage_report.py [--db PATH] [--census PATH] [--all-leagues]

Read-only. The census results file is the newest `results_*.json` under the L28 row unless given.
Enabled leagues only by default (a disabled league is a registry decision, not a gap)."""
from __future__ import annotations

import argparse
import glob
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kernel.paths import DB  # noqa: E402
from nodes.entities.leagues import default_leagues, league_for_series  # noqa: E402

CENSUS_DIR = ROOT / "research" / "sports" / "2026-09-03_co-listing-census"


def newest_census(directory: Path = CENSUS_DIR) -> Path | None:
    files = sorted(glob.glob(str(directory / "results_*.json")))
    return Path(files[-1]) if files else None


def report(db: Path, census: Path | None, *, now: float | None = None, enabled_only: bool = True) -> dict:
    t = now or time.time()
    if census is None or not Path(census).exists():
        return {"census": None, "rows": [], "note": "no census results file"}
    res = json.loads(Path(census).read_text())
    pairs = res.get("co_listed_pairs_48h") or []
    if not pairs:
        return {"census": str(census), "rows": [], "note": "census results carry no pair list (run older than 2026-09-07)"}
    enabled = set(default_leagues()) if enabled_only else None
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cols = {r[1] for r in con.execute("PRAGMA table_info(events)")}
    if not cols:
        con.close()
        return {"census": str(census), "rows": [], "note": "no events table"}
    covered = {r[0] for r in con.execute("SELECT kalshi_event FROM events WHERE phase LIKE '%:co_listed' AND kalshi_event IS NOT NULL")}
    rows = []
    for pr in pairs:
        league = league_for_series(pr.get("kalshi_series") or "")
        if league is None:
            continue
        if enabled is not None and league not in enabled:
            continue
        kev = pr.get("kalshi_event")
        row = {"league": league, "kalshi_event": kev, "pm_event": pr.get("pm_event"), "date": pr.get("date"),
               "start_utc": pr.get("start_utc"), "participants": pr.get("participants") or [], "lane": "covered" if kev in covered else "gap",
               "lane_reason": None, "lane_event": None}
        if row["lane"] == "gap":
            # the lane's own nearest record: same league, the same day (±1), any reason it wrote
            day = pr.get("date")
            cands = con.execute("SELECT event_id, short_name, block_reason, phase, start_utc FROM events WHERE league=? "
                                "AND ABS(start_utc - ?) <= 129600 ORDER BY ABS(start_utc - ?) LIMIT 40",
                                (league, pr.get("start_utc") or 0, pr.get("start_utc") or 0)).fetchall() if pr.get("start_utc") else []
            names = " ".join(str(x).lower() for x in pr.get("participants") or [])
            best = None
            for eid, short, reason, phase, st in cands:
                toks = [w for w in str(short).lower().replace("@", " ").replace(" v ", " ").split() if len(w) > 2]
                if any(w in names for w in toks):
                    best = (eid, short, reason, phase)
                    break
            if best:
                row["lane_event"], row["lane_short"], row["lane_reason"], row["lane_phase"] = best
            else:
                row["lane_reason"] = "NOT_IN_LANE_SCHEDULE"
            _ = day
        rows.append(row)
    con.close()
    by_league: dict[str, dict] = {}
    for r in rows:
        b = by_league.setdefault(r["league"], {"covered": 0, "gap": 0})
        b[r["lane"]] += 1
    return {"census": str(census), "run": res.get("run"), "now": t, "rows": rows, "by_league": by_league}


def coverage_alerts(db: Path, census: Path | None, *, now: float | None = None, back_s: float = 3 * 3600,
                    ahead_s: float = 6 * 3600) -> list[str]:
    """Watchdog-shaped: a co-listed event in an enabled league whose start is inside the lane's
    window and which the lane did not pair."""
    t = now or time.time()
    r = report(db, census, now=t)
    out = []
    for row in r.get("rows", []):
        st = row.get("start_utc")
        if row["lane"] != "gap" or st is None or not (t - back_s <= st <= t + ahead_s):
            continue
        out.append(f"coverage: COVERAGE_GAP — {row['league']} {row['kalshi_event']} <> {row['pm_event']} "
                   f"(lane: {row.get('lane_reason')})")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--census", type=Path, default=None)
    ap.add_argument("--all-leagues", action="store_true")
    a = ap.parse_args()
    r = report(a.db, a.census or newest_census(), enabled_only=not a.all_leagues)
    if r.get("note"):
        print(r["note"])
    print(f"census {r.get('census')} run {r.get('run')}")
    for lg, b in sorted((r.get("by_league") or {}).items()):
        print(f"  {lg:<5} covered {b['covered']:>3}  gap {b['gap']:>3}")
    for row in r.get("rows", []):
        if row["lane"] == "gap":
            when = datetime.fromtimestamp(row["start_utc"], timezone.utc).strftime("%m-%d %H:%MZ") if row.get("start_utc") else row.get("date")
            print(f"  GAP {row['league']} {when} {row['kalshi_event']} <> {row['pm_event']} :: {row.get('lane_reason')}"
                  + (f" [{row.get('lane_short')}]" if row.get("lane_short") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
