#!/usr/bin/env python3
"""L26: MLB settlement-wedge rates from the MLB Stats API. Descriptive; run once."""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from kernel.fetch import Client  # noqa: E402

HERE = Path(__file__).resolve().parent
START, END = "2026-03-25", "2026-09-02"
PRE = {"Scheduled", "Pre-Game", "Warmup", "Delayed Start", "In Progress", "Delayed", "Manager challenge"}


def main() -> int:
    cl = Client("mlbstats", rate=3, burst=6, cache_dir="/Volumes/Kilos/janus/catalog/mlb_stats_cache")
    games: dict[int, dict] = {}
    a = datetime.fromisoformat(START)
    end = datetime.fromisoformat(END)
    while a <= end:
        b = min(a + timedelta(days=30), end)
        d = cl.get_json("https://statsapi.mlb.com/api/v1/schedule",
                        params={"sportId": 1, "gameType": "R", "startDate": a.strftime("%Y-%m-%d"),
                                "endDate": b.strftime("%Y-%m-%d")}, use_cache=True)
        for day in d.get("dates", []):
            for g in day.get("games", []):
                games.setdefault(g["gamePk"], g)          # a makeup is its own gamePk; keep first sighting
        a = b + timedelta(days=1)

    states = Counter(); reasons = Counter()
    n = postponed = postponed_gt2d = gt2d_null = cancelled = suspended = completed_early = 0
    for g in games.values():
        st = g["status"].get("detailedState", "?")
        if st in PRE:
            continue
        n += 1
        states[st] += 1
        if g["status"].get("reason"):
            reasons[(st, g["status"]["reason"])] += 1
        if st == "Postponed":
            postponed += 1
            orig = datetime.fromisoformat(g["gameDate"].replace("Z", "+00:00"))
            rs = g.get("rescheduleDate")
            if rs is None:
                postponed_gt2d += 1; gt2d_null += 1
            elif datetime.fromisoformat(rs.replace("Z", "+00:00")) - orig > timedelta(days=2):
                postponed_gt2d += 1
        if st in ("Cancelled", "Canceled"):
            cancelled += 1
        if g.get("resumeDate") or st == "Suspended":
            suspended += 1
        if st == "Completed Early":
            completed_early += 1

    res = {"spec": "research/sports/2026-09-02_mlb-settlement-wedge-rates/spec.yaml",
           "source": "https://statsapi.mlb.com/api/v1/schedule?sportId=1&gameType=R",
           "window": [START, END], "retrieved_at": datetime.now(timezone.utc).isoformat(),
           "games_seen": len(games), "denominator": n, "states": dict(states),
           "reasons": {f"{k[0]} | {k[1]}": v for k, v in reasons.items()},
           "counts": {"postponed": postponed, "postponed_gt2d": postponed_gt2d,
                      "postponed_gt2d_with_null_reschedule": gt2d_null, "cancelled": cancelled,
                      "suspended": suspended, "completed_early": completed_early},
           "rates": {"mlb.postponed_rate": postponed / n, "mlb.postponed_gt2d_rate": postponed_gt2d / n,
                     "mlb.cancelled_rate": cancelled / n, "mlb.suspended_rate": suspended / n},
           "postponed_gt2d_is_upper_bound": gt2d_null > 0,
           "sufficient": n >= 1500}
    (HERE / "results.json").write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    r = res["rates"]
    lines = ["# L26 — MLB settlement-wedge rates (descriptive)", "",
             f"Window {START} → {END}, MLB Stats API regular-season schedule, retrieved {res['retrieved_at']}.",
             f"Games seen {len(games)}; denominator (not pre-game) **{n}** — "
             + ("sufficient (≥1,500)." if res["sufficient"] else "**INSUFFICIENT**; evidence NOT registered."), "",
             "| state | n |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(states.items())] + ["",
             "| rate | value | count |", "|---|---|---|",
             f"| mlb.postponed_rate | {r['mlb.postponed_rate']:.5f} | {postponed} |",
             f"| mlb.postponed_gt2d_rate | {r['mlb.postponed_gt2d_rate']:.5f} | {postponed_gt2d} "
             + (f"(**upper bound**: {gt2d_null} with no reschedule date)" if gt2d_null else "(exact)") + " |",
             f"| mlb.cancelled_rate | {r['mlb.cancelled_rate']:.5f} | {cancelled} |",
             f"| mlb.suspended_rate | {r['mlb.suspended_rate']:.5f} | {suspended} |", "",
             f"Completed-early (rain-shortened, official on both venues): {completed_early}.", "",
             "Registered in `nodes/settle_wedge/evidence.py` as `mlb.postponed_gt2d_rate` and `mlb.cancelled_rate`"
             " verbatim. This row claims nothing about edge; it prices a reserve. NFL/NHL need their own rows."]
    (HERE / "verdict.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(res, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
