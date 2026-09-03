#!/usr/bin/env python3
"""L29: NFL settlement-wedge rates from nflverse (denominator) and events.csv (numerator)."""
from __future__ import annotations

import csv
import io
import json
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent
URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
CACHE = Path("/Volumes/Kilos/janus/catalog/nflverse/games.csv")
SEASONS = {2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025}
HOLIDAY = {(12, 24), (12, 25), (12, 26)}


def games() -> list[dict]:
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(URL, headers={"User-Agent": "janus-research/1.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            CACHE.write_bytes(r.read())
    return list(csv.DictReader(io.StringIO(CACHE.read_text())))


def is_black_friday(d: datetime) -> bool:
    # the Friday after the fourth Thursday of November
    return d.month == 11 and d.weekday() == 4 and 23 <= d.day <= 29


def main() -> int:
    rows = [g for g in games() if g["game_type"] == "REG" and int(g["season"]) in SEASONS]
    events = list(csv.DictReader((HERE / "events.csv").open()))
    by_key = {(int(g["season"]), g["away_team"], g["home_team"]): g for g in rows}
    problems: list[str] = []
    n_post, n_canc = 0, 0
    per_season: dict[int, Counter] = {s: Counter() for s in sorted(SEASONS)}
    extra_denominator = 0
    for e in events:
        key = (int(e["season"]), e["away"], e["home"])
        cancelled = e["actual_kickoff_local_or_CANCELLED"].strip().upper() == "CANCELLED"
        if cancelled:
            n_canc += 1
            per_season[key[0]]["cancelled"] += 1
            if key not in by_key:
                extra_denominator += 1          # nflverse omits the cancelled game
            continue
        if key not in by_key:
            problems.append(f"events.csv row {key} matches no nflverse REG game")
            continue
        if float(e["hours_moved"]) > 48.0:
            n_post += 1
            per_season[key[0]]["postponed_gt48h"] += 1
        else:
            per_season[key[0]]["moved_le48h"] += 1
    # completeness gate: odd weekdays must be explained
    explained = {(int(e["season"]), e["away"], e["home"]) for e in events}
    unexplained = []
    for g in rows:
        d = datetime.strptime(g["gameday"], "%Y-%m-%d")
        odd = d.weekday() in (1, 2) or (d.weekday() == 4 and not is_black_friday(d))
        if odd and (d.month, d.day) not in HOLIDAY and (int(g["season"]), g["away_team"], g["home_team"]) not in explained:
            unexplained.append(f"{g['season']} wk{g['week']} {g['away_team']}@{g['home_team']} {g['gameday']} ({g['weekday']})")
    denominator = len(rows) + extra_denominator
    complete = not problems and not unexplained
    sufficient = denominator >= 2000
    res = {"spec": "research/sports/2026-09-03_nfl-settlement-wedge-rates/spec.yaml", "source": URL,
           "retrieved_at": datetime.now(timezone.utc).isoformat(), "seasons": sorted(SEASONS),
           "nflverse_reg_rows": len(rows), "cancelled_absent_from_nflverse": extra_denominator, "denominator": denominator,
           "counts": {"postponed_gt48h": n_post, "cancelled": n_canc, "events_rows": len(events)},
           "rates": {"postponed_gt48h_rate": round(n_post / denominator, 6), "cancelled_rate": round(n_canc / denominator, 6)},
           "per_season": {str(s): dict(c) for s, c in per_season.items()},
           "reg_rows_per_season": {str(s): sum(1 for g in rows if int(g["season"]) == s) for s in sorted(SEASONS)},
           "completeness": {"problems": problems, "unexplained_odd_weekday_games": unexplained, "complete": complete},
           "sufficient": sufficient, "verdict": "REGISTERED" if (complete and sufficient) else ("INCOMPLETE" if not complete else "INSUFFICIENT")}
    (HERE / "results.json").write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    lines = ["# L29 — NFL settlement-wedge rates (descriptive)", "",
             f"nflverse `games.csv` REG rows for seasons {sorted(SEASONS)} (2020 excluded by decision), retrieved {res['retrieved_at']}.",
             f"Denominator **{denominator}** = {len(rows)} nflverse rows + {extra_denominator} cancelled game(s) nflverse omits "
             f"({'sufficient' if sufficient else 'INSUFFICIENT'}).", "",
             "| rate | value | count |", "|---|---|---|",
             f"| postponed_gt48h_rate | {res['rates']['postponed_gt48h_rate']:.6f} | {n_post} |",
             f"| cancelled_rate | {res['rates']['cancelled_rate']:.6f} | {n_canc} |", "",
             "| season | REG rows | >48 h | ≤48 h moves | cancelled |", "|---|---|---|---|---|"]
    for s in sorted(SEASONS):
        c = per_season[s]
        lines.append(f"| {s} | {res['reg_rows_per_season'][str(s)]} | {c.get('postponed_gt48h', 0)} | {c.get('moved_le48h', 0)} | {c.get('cancelled', 0)} |")
    lines += ["", f"Completeness gate: {'PASSED' if complete else 'FAILED'} — {len(unexplained)} unexplained Tue/Wed/Fri game(s), "
              f"{len(problems)} table row(s) without a schedule game." + (f" {unexplained + problems}" if not complete else ""),
              "", f"Verdict: **{res['verdict']}**." + (" Both rates registered in `nodes/settle_wedge/evidence.py` with this row as `research_ref`. "
                                                       "Claims nothing about edge." if res["verdict"] == "REGISTERED" else " Nothing registered.")]
    (HERE / "verdict.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if res["verdict"] == "REGISTERED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
