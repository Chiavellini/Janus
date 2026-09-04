#!/usr/bin/env python3
"""L38: the lane's event-loop lag per hour, from socket_health.loop_lag_s."""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from kernel.paths import DB, LOGS  # noqa: E402

HERE = Path(__file__).resolve().parent
BOUND_S = 5.0
START = datetime(2026, 9, 4, 1, 0, tzinfo=timezone.utc).timestamp()      # the A1 restart


def q(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(p * len(s)))], 3)


def slate_minutes(log: Path) -> set[int]:
    """Minutes (epoch // 60) holding a [slate] line, read from the tick line before it."""
    out, tick = set(), None
    if not log.exists():
        return out
    for line in log.read_text(errors="replace").splitlines():
        m = re.match(r"\[(\d\d):(\d\d):(\d\d)Z\]", line)
        if m:
            tick = tuple(int(x) for x in m.groups())
        elif line.startswith("[slate]") and tick:
            # date is not on the line; the lane log is today's, and the row is a coincidence count
            now = datetime.now(timezone.utc)
            t = now.replace(hour=tick[0], minute=tick[1], second=tick[2], microsecond=0).timestamp()
            out.add(int(t // 60))
    return out


def main() -> int:
    run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    since = float(sys.argv[1]) if len(sys.argv) > 1 else START
    until = min(since + 86400.0, datetime.now(timezone.utc).timestamp())
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute("SELECT seen_ts, loop_lag_s FROM socket_health WHERE venue='kalshi' AND loop_lag_s IS NOT NULL "
                       "AND seen_ts >= ? AND seen_ts < ? ORDER BY seen_ts", (since, until)).fetchall()
    con.close()
    slates = slate_minutes(LOGS / "live_stream.stdout.log")
    by_hour = defaultdict(list)
    for ts, lag in rows:
        by_hour[int(ts // 3600)].append((ts, float(lag)))
    hours = {}
    for h, xs in sorted(by_hour.items()):
        lags = [l for _, l in xs]
        stalled = [(t, l) for t, l in xs if l > BOUND_S]
        coin = sum(1 for t, _ in stalled if int(t // 60) in slates or int(t // 60) - 1 in slates)
        hours[datetime.fromtimestamp(h * 3600, timezone.utc).strftime("%Y-%m-%dT%H")] = {
            "ticks": len(lags), "p50": q(lags, 0.5), "p90": q(lags, 0.9), "p99": q(lags, 0.99), "max": round(max(lags), 3),
            "stalled": len(stalled), "share_stalled": round(len(stalled) / len(lags), 4),
            "stalled_at_discovery": coin}
    all_lags = [l for _, l in rows]
    res = {"run": run, "since": since, "until": until, "bound_s": BOUND_S, "ticks": len(all_lags),
           "share_stalled": round(sum(1 for l in all_lags if l > BOUND_S) / len(all_lags), 4) if all_lags else None,
           "p50": q(all_lags, 0.5), "p99": q(all_lags, 0.99), "max": round(max(all_lags), 3) if all_lags else None, "hours": hours}
    (HERE / f"results_{run}.json").write_text(json.dumps(res, indent=2) + "\n")
    lines = [f"\n## Run {run} — {datetime.fromtimestamp(since, timezone.utc):%Y-%m-%d %H:%M}Z to {datetime.fromtimestamp(until, timezone.utc):%H:%M}Z", "",
             f"{res['ticks']} ticks; share past {BOUND_S:.0f} s = {res['share_stalled']}; p50 {res['p50']} s, p99 {res['p99']} s, max {res['max']} s.", "",
             "| hour | ticks | p50 | p90 | p99 | max | stalled | share | at discovery |", "|---|---|---|---|---|---|---|---|---|"]
    for h, x in hours.items():
        lines.append(f"| {h} | {x['ticks']} | {x['p50']} | {x['p90']} | {x['p99']} | {x['max']} | {x['stalled']} | {x['share_stalled']} | {x['stalled_at_discovery']} |")
    v = HERE / "verdict.md"
    if not v.exists():
        v.write_text("# L38 — the lane's event-loop lag on the Mac (descriptive, re-runnable)\n\nFrom `socket_health.loop_lag_s`: the worst overshoot of a 250 ms sleep per report tick. Definitions in `spec.yaml`.\n")
    with v.open("a") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
