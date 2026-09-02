#!/usr/bin/env python3
"""The box scheduler's input: what the next few days look like, and what they cost.

    python3 -m nodes.slate.monitor --days 3
    python3 -m nodes.slate.monitor --days 3 --now          # is the box needed right now?

Answers three questions a scheduler needs and a person wants: when to wake, when to drain, and
what the schedule costs against leaving the instance on.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone

from nodes.schedule_espn import espn
from nodes.slate.slate import (Window, cost_estimate, next_transition, uptime_hours, windows_for)

#: c7g.medium on-demand, us-east-1. Non-burstable on purpose: t-class CPU credit throttling adds
#: exactly the jitter a latency-sensitive capture lane is trying to remove.
DEFAULT_USD_PER_HOUR = 0.0361


def slate(leagues: list[str], days: int, *, use_cache: bool = False) -> tuple[list, dict]:
    """Every scheduled game across `leagues` for the next `days`, plus per-league failures."""
    now = datetime.now(timezone.utc)
    games, failures = [], {}
    for lg in leagues:
        try:
            games += list(espn.fetch_range(lg, now, now + timedelta(days=days), use_cache=use_cache))
        except Exception as exc:  # noqa: BLE001 -- one league must not blank the schedule
            failures[lg] = f"{type(exc).__name__}: {exc}"
    return games, failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", default="mlb,nfl,nba,wnba,nhl,epl")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--lead-min", type=int, default=30)
    ap.add_argument("--settle-min", type=int, default=45)
    ap.add_argument("--usd-per-hour", type=float, default=DEFAULT_USD_PER_HOUR)
    ap.add_argument("--now", action="store_true", help="print WAKE or DRAIN for this instant and exit")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    leagues = [x.strip() for x in a.leagues.split(",") if x.strip()]
    games, failures = slate(leagues, a.days)
    wins = windows_for(games, lead_s=a.lead_min * 60, settle_s=a.settle_min * 60)
    now = time.time()

    if a.now:
        # The scheduler's whole contract: should the box be up at this instant?
        live = next((w for w in wins if w.covers(now)), None)
        state = "WAKE" if live else "DRAIN"
        nxt = next_transition(wins, now)
        if a.json:
            print(json.dumps({"state": state, "reason_games": len(live.game_ids) if live else 0,
                              "next": nxt[0] if nxt else None,
                              "next_utc": nxt[1] if nxt else None}, sort_keys=True))
        else:
            detail = f"{len(live.game_ids)} games in window until " \
                     f"{datetime.fromtimestamp(live.end_utc, timezone.utc):%H:%M}Z" if live \
                     else "no game window open"
            print(f"{state}  ({detail})")
            if nxt:
                mins = (nxt[1] - now) / 60.0
                print(f"  next: {nxt[0]} in {mins:.0f} min "
                      f"({datetime.fromtimestamp(nxt[1], timezone.utc):%a %H:%M}Z)")
        return 0

    cost = cost_estimate(wins, a.usd_per_hour)
    if a.json:
        print(json.dumps({"windows": [{"start_utc": w.start_utc, "end_utc": w.end_utc,
                                       "hours": round(w.hours, 2), "games": len(w.game_ids),
                                       "leagues": list(w.leagues)} for w in wins],
                          "cost": cost, "failures": failures}, indent=2, sort_keys=True))
        return 0

    print(f"{len(games)} games across {len(leagues)} leagues in the next {a.days}d "
          f"-> {len(wins)} box windows")
    if failures:
        print(f"  schedule failures: {failures}")
    print()
    for w in wins:
        print(f"  {w}")
    print(f"\n  uptime {cost['hours']}h over {a.days}d "
          f"= ${cost['usd']} at ${a.usd_per_hour}/h")
    print(f"  always-on would be ${cost['always_on_usd']} -> {cost['saving_pct']}% saved by scheduling")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
