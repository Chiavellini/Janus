#!/usr/bin/env python3
"""F24 progress and verdict report. Read-only.

    python3 report.py <start_utc> [end_utc] [--include EXEC_ID ...] [--exclude EXEC_ID ...]

Reads `executions` and `execution_settlements` for executions started in [start, end], and prints one
compact JSON object: the funnel, realised net per settled cover and per day, the registered
event-clustered interval, the loss-making covers, and the verdict F24's spec defines.

Run it with an L141-window start/end first: it must reproduce L141's known totals before its F24
numbers are trusted.
"""
from __future__ import annotations

import json
import math
import random
import sqlite3
import statistics
import sys
import time
from collections import Counter, defaultdict

DB = "/srv/janus/tuples/tuples.sqlite"
SCHEMA = "janus.f24.taker_profitability_report.v1"

# Registered in spec.yaml.
END_COVERS = 30
END_DAYS = 7
CUMULATIVE_LOSS_STOP_USD = 50.0
MIN_COVERS_FOR_VERDICT = 10
RESAMPLES = 10000
SEED = 170924


def clustered_interval(covers: list[dict]) -> dict | None:
    """Event-clustered percentile bootstrap of mean net per settled cover."""
    by_event: dict[str, list[float]] = defaultdict(list)
    for c in covers:
        by_event[c["event_id"]].append(c["realized_usd"])
    keys = sorted(by_event)
    if len(keys) < 2:
        return None
    rng = random.Random(SEED)
    means = []
    for _ in range(RESAMPLES):
        vals = [v for k in (rng.choice(keys) for _ in keys) for v in by_event[k]]
        means.append(statistics.fmean(vals))
    means.sort()

    def pct(p: float) -> float:
        return means[max(0, min(len(means) - 1, math.ceil(p * len(means)) - 1))]

    return {"events": len(keys), "resamples": RESAMPLES, "seed": SEED,
            "lower_95": round(pct(0.025), 6), "upper_95": round(pct(0.975), 6)}


def verdict(total: float, n: int, ci: dict | None, stopped: str | None) -> tuple[str, str]:
    if stopped:
        return "STOP", stopped
    if n < MIN_COVERS_FOR_VERDICT:
        return "INSUFFICIENT", f"{n} settled covers < {MIN_COVERS_FOR_VERDICT}"
    if total < 0:
        return "LOSES_MONEY", f"total realised net {total:+.5f} < 0"
    if total > 0 and ci is not None and ci["lower_95"] > 0:
        return "MAKES_MONEY_PROVEN", f"total {total:+.5f} and 95% interval lower bound {ci['lower_95']:+.5f} > 0"
    if total > 0:
        return "MAKES_MONEY_NOT_PROVEN", f"total {total:+.5f} > 0 but the 95% interval includes zero"
    return "LOSES_MONEY", f"total realised net {total:+.5f} is not above zero"


def run(db: str, start: float, end: float | None, include=(), exclude=()) -> dict:
    stop_at = end if end is not None else time.time()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT execution_id, event_id, league, state, started_utc FROM executions "
        "WHERE started_utc >= ? AND started_utc <= ?", (start, stop_at))]
    rows = [r for r in rows if r["execution_id"] not in set(exclude)]
    have = {r["execution_id"] for r in rows}
    for eid in include:
        if eid not in have:
            r = con.execute("SELECT execution_id, event_id, league, state, started_utc FROM executions "
                            "WHERE execution_id=?", (eid,)).fetchone()
            if r:
                rows.append(dict(r))
    settle = {}
    ids = [r["execution_id"] for r in rows]
    if ids:
        marks = ",".join("?" * len(ids))
        for s in con.execute(
                "SELECT execution_id, realized_usd, released, kind, settled_ts FROM execution_settlements "
                f"WHERE execution_id IN ({marks})", ids):
            settle[s["execution_id"]] = dict(s)

    covers, unsettled_fills = [], []
    for r in rows:
        s = settle.get(r["execution_id"])
        if s is not None and s["released"] and s["realized_usd"] is not None:
            covers.append({"execution_id": r["execution_id"], "event_id": r["event_id"],
                           "league": r["league"], "kind": s["kind"],
                           "realized_usd": float(s["realized_usd"]), "settled_ts": s["settled_ts"]})
        elif r["state"] in ("HEDGED", "SETTLED", "RECONCILED"):
            unsettled_fills.append(r["execution_id"])

    total = round(sum(c["realized_usd"] for c in covers), 6)
    by_day: dict[str, float] = defaultdict(float)
    for c in covers:
        by_day[time.strftime("%Y-%m-%d", time.gmtime(c["settled_ts"]))] += c["realized_usd"]
    ci = clustered_interval(covers)

    elapsed_days = (stop_at - start) / 86400.0
    stopped = None
    if total <= -CUMULATIVE_LOSS_STOP_USD:
        stopped = f"cumulative realised loss {total:+.2f} reached the ${CUMULATIVE_LOSS_STOP_USD:.0f} stop"
    ended = (len(covers) >= END_COVERS or elapsed_days >= END_DAYS or stopped is not None)
    v, reason = verdict(total, len(covers), ci, stopped)

    return {
        "schema": SCHEMA,
        "window": {"start_utc": start, "end_utc": stop_at, "elapsed_days": round(elapsed_days, 3)},
        "ended": ended,
        "end_rule": {"covers": END_COVERS, "days": END_DAYS, "cumulative_loss_stop_usd": CUMULATIVE_LOSS_STOP_USD},
        "funnel": {"executions": len(rows),
                   "by_state": dict(sorted(Counter(r["state"] for r in rows).items())),
                   "settled_covers": len(covers),
                   "filled_not_yet_settled": len(unsettled_fills)},
        "net": {"total_usd": total,
                "per_settled_cover_usd": (round(total / len(covers), 6) if covers else None),
                "by_settle_day_usd": {k: round(v, 6) for k, v in sorted(by_day.items())},
                "per_elapsed_day_usd": (round(total / elapsed_days, 4) if elapsed_days > 0 else None)},
        "interval_net_per_cover": ci,
        "loss_making_covers": sorted(
            [c for c in covers if c["realized_usd"] < 0], key=lambda c: c["realized_usd"]),
        "verdict": v if ended else f"IN_PROGRESS (would be {v})",
        "verdict_reason": reason,
        "note": "Only a verdict with ended=true is F24's result. An unsettled fill is not scored.",
    }


if __name__ == "__main__":
    args = sys.argv[1:]
    inc, exc, pos = [], [], []
    i = 0
    while i < len(args):
        if args[i] == "--include":
            inc.append(args[i + 1]); i += 2
        elif args[i] == "--exclude":
            exc.append(args[i + 1]); i += 2
        else:
            pos.append(args[i]); i += 1
    start = float(pos[0])
    end = float(pos[1]) if len(pos) > 1 else None
    print(json.dumps(run(DB, start, end, inc, exc), sort_keys=True, separators=(",", ":")))
