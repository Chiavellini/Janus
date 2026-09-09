#!/usr/bin/env python3
"""Compare the census's candidate venue joins with the lane's exact registered-league matches.

The census join (nodes/discovery/census, daily) is deliberately loose and may collide across
sports or competitions.  For a registered series the lane's canonical schedule join supplies the
authoritative decision and reason (`UNPAIRED:kalshi=…,polymarket=…`, `SPAWN:…`).  Unregistered
census rows have no such verification: this report retains them as research-only
`UNVERIFIED_COVERAGE_CANDIDATE` rows and never emits an operational alert for them.

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
    covered = {r[0] for r in con.execute(
        "SELECT kalshi_event FROM events WHERE phase LIKE '%:co_listed' AND kalshi_event IS NOT NULL"
    )}
    # Discovery keeps following a game through its final state. Once Kalshi removes settled
    # markets, the current row becomes `post`/UNPAIRED even though the lane did pair and poll the
    # game for hours. Coverage is historical evidence (did the lane ever pair it), so retain any
    # event whose append-only transition history contains a co-listed phase.
    covered.update(r[0] for r in con.execute(
        "SELECT DISTINCT e.kalshi_event FROM events e JOIN event_transitions t ON t.event_id=e.event_id "
        "WHERE t.phase LIKE '%:co_listed' AND e.kalshi_event IS NOT NULL"
    ))
    rows = []
    unregistered = []
    unregistered_seen: set[tuple[str, str, str, str]] = set()
    discarded_unregistered = 0
    for pr in pairs:
        league = league_for_series(pr.get("kalshi_series") or "")
        if league is None:
            # This is not a canonical pair. Retain only complete, exactly de-duplicated raw
            # candidate identities so research counts cannot inflate on repeated census rows.
            ident = tuple(str(pr.get(key) or "") for key in
                          ("kalshi_series", "pm_sport", "kalshi_event", "pm_event"))
            if not all(ident) or ident in unregistered_seen:
                discarded_unregistered += 1
                continue
            unregistered_seen.add(ident)
            unregistered.append({
                "league": None,
                "kalshi_series": pr.get("kalshi_series"),
                "pm_sport": pr.get("pm_sport"),
                "kalshi_event": pr.get("kalshi_event"),
                "pm_event": pr.get("pm_event"),
                "date": pr.get("date"),
                "start_utc": pr.get("start_utc"),
                "participants": pr.get("participants") or [],
                "status": "UNVERIFIED_COVERAGE_CANDIDATE",
                "operational": False,
                "basis": "LOOSE_PARTICIPANT_DATE_JOIN",
            })
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
    candidate_counts: dict[tuple[str, str], int] = {}
    for candidate in unregistered:
        key = (candidate["kalshi_series"], candidate["pm_sport"])
        candidate_counts[key] = candidate_counts.get(key, 0) + 1
    return {"census": str(census), "run": res.get("run") or res.get("run_utc"), "now": t,
            "rows": rows, "by_league": by_league,
            "unverified_coverage_candidates_48h": unregistered,
            "unverified_candidate_summary": {
                "candidate_rows": len(unregistered),
                "discarded_malformed_or_duplicate_rows": discarded_unregistered,
                "mapping_candidates": [
                    {"kalshi_series": series, "pm_sport": sport, "candidate_rows": count}
                    for (series, sport), count in sorted(candidate_counts.items())
                ],
            }}


def coverage_alerts(db: Path, census: Path | None, *, now: float | None = None, back_s: float = 3 * 3600,
                    ahead_s: float = 6 * 3600) -> list[str]:
    """Registered-league candidate gaps only; unverified/unregistered rows are research-only."""
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
    unregistered = r.get("unverified_coverage_candidates_48h") or []
    if unregistered:
        print(f"  UNVERIFIED research candidates {len(unregistered)} "
              "(loose participant/date joins; not co-listed or tradeable assertions)")
        by_mapping: dict[tuple[str, str], int] = {}
        for row in unregistered:
            key = (row.get("kalshi_series") or "?", row.get("pm_sport") or "?")
            by_mapping[key] = by_mapping.get(key, 0) + 1
        for (series, sport), count in sorted(by_mapping.items(), key=lambda item: (-item[1], item[0])):
            print(f"    {series} <> {sport}: {count} candidate rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
