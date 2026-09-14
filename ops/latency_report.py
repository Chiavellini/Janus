#!/usr/bin/env python3
"""Where the time goes between a priced cover and its hedge: p50 / p95 per stage from the
`executions.stages_json` the coordinator writes (2026-09-07), read-only.

    python3 ops/latency_report.py [--db PATH] [--last N] [--mode LIMITED_LIVE]

Stages are ms from the machine's entry: the grid's pre-machine stages (frame_to_eval_ms,
eval_to_exec_ms, worker_hop_ms, balances_ms, clear_ms, pre_machine_ms), then a_submit/a_ack/a_settled,
b_submit/b_ack/b_settled, done_ms, with db_ms (store writes) and a_polls/b_polls/b_attempts.

Two of those are disjoint intervals as of L97 (2026-09-13) and were not before: `eval_to_exec_ms`
was measured from the FRAME, so it contained `frame_to_eval_ms` in full and summing the two
double-counted it. `worker_hop_ms` is the executor queue hop -- the largest interval on the path
that previously had no stage at all.
Beside them, `orders.submitted_utc -> order_events.seen_ts` gives submit->ack per order as the
cross-check. L34 gives the venues' bare round trips from each host."""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kernel.paths import DB  # noqa: E402

#: Display order. The `*_ms` keys are CUMULATIVE from the machine's `_t0`, so a segment is the
#: difference between two of them ON THE SAME ROW -- never the difference of two medians, which is
#: how L107 came to overstate one segment by 50 % (L108). `hedge_book_ms` and `b_sleep_ms` are
#: accumulators, not stamps: they repeat inside one execution and a stamp can only hold the last.
ORDER = ["frame_to_eval_ms", "eval_to_exec_ms", "worker_hop_ms", "balances_ms", "clear_ms",
         "pre_machine_ms", "confirm_budget_ms", "a_submit_ms",
         "a_ack_ms", "a_settled_ms", "a_overfill_ms", "a_recorded_ms", "a_post_confirm_ms",
         "protect_entry_ms", "b_first_attempt_ms", "b_submit_ms", "b_ack_ms",
         "b_last_submit_ms", "b_last_ack_ms", "b_settled_ms", "done_ms", "db_ms",
         "hedge_book_ms", "b_sleep_ms",
         "a_polls", "b_polls", "b_attempts", "hedge_book_reads", "guard_rerun", "hedge_slippage_c"]


#: (label, from, to) over the CUMULATIVE stamps -- differenced PER ROW, then summarised. `None`
#: means "from the machine's t0". This is the table to read; the raw stage list above it is
#: cumulative and invites exactly the subtraction that produced L107's wrong numbers.
SEGMENTS = [
    ("pre-machine", None, "pre_machine_ms"),
    ("A submit->ack", "a_submit_ms", "a_ack_ms"),
    ("A ack->settled", "a_ack_ms", "a_settled_ms"),
    ("A settled->overfilled", "a_settled_ms", "a_overfill_ms"),
    ("A overfill->recorded", "a_overfill_ms", "a_recorded_ms"),
    ("A recorded->protect", "a_recorded_ms", "protect_entry_ms"),
    ("protect->1st attempt", "protect_entry_ms", "b_first_attempt_ms"),
    ("1st attempt->1st send", "b_first_attempt_ms", "b_submit_ms"),
    ("B submit->ack", "b_submit_ms", "b_ack_ms"),
    ("B chase (ack->last send)", "b_ack_ms", "b_last_submit_ms"),
    ("B last send->last ack", "b_last_submit_ms", "b_last_ack_ms"),
    ("B last ack->settled", "b_last_ack_ms", "b_settled_ms"),
    ("decision->hedge ack", None, "b_ack_ms"),
]


def q(xs: list[float]) -> dict:
    if not xs:
        return {}
    xs = sorted(xs)
    qs = statistics.quantiles(xs, n=100) if len(xs) >= 2 else [xs[0]] * 99
    return {"n": len(xs), "p50": round(qs[49], 1), "p95": round(qs[94], 1), "max": round(xs[-1], 1)}


def report(db: Path, *, last: int = 200, mode: str | None = None, since: float | None = None,
           include_reruns: bool = False) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cols = {r[1] for r in con.execute("PRAGMA table_info(executions)")}
    if "stages_json" not in cols:
        return {"executions": 0, "note": "no stages_json column yet (lane older than 2026-09-07)"}
    sql = "SELECT mode, state, stages_json FROM executions WHERE stages_json IS NOT NULL"
    args: list = []
    if mode:
        sql += " AND mode=?"
        args.append(mode)
    if since is not None:
        # Without this, `--last N` reaches back across deploys and a key added yesterday reports
        # n=4 against 200 rows. Every stage comparison needs the window pinned to one code tree.
        sql += " AND started_utc >= ?"
        args.append(float(since))
    rows = con.execute(sql + " ORDER BY started_utc DESC LIMIT ?", (*args, last)).fetchall()
    by_key: dict[str, list[float]] = {}
    states: dict[str, int] = {}
    segs: dict[str, list[float]] = {}
    reruns = 0
    for m, st, sj in rows:
        try:
            d = json.loads(sj)
        except ValueError:
            continue
        # `protect_existing` resets the machine's `_t0`, so on a guard re-run the b_* stamps are
        # re-based to the re-run's start while the a_* stamps keep the original run's. Differencing
        # across such a row subtracts two different clocks; L100 recorded 2,840 re-runs on one
        # execution, so this is not a rare contaminant.
        if d.get("guard_rerun") and not include_reruns:
            reruns += 1
            continue
        states[st] = states.get(st, 0) + 1
        for k, v in d.items():
            if isinstance(v, (int, float)):
                by_key.setdefault(k, []).append(float(v))
        for name, a, b in SEGMENTS:
            if b in d and (a is None or a in d):
                delta = float(d[b]) - (0.0 if a is None else float(d[a]))
                segs.setdefault(name, []).append(delta)
    keys = [k for k in ORDER if k in by_key] + sorted(k for k in by_key if k not in ORDER)
    # submit -> ack per order, the cross-check
    acks: dict[str, list[float]] = {}
    try:
        for venue, sub, seen in con.execute(
                "SELECT o.venue, o.submitted_utc, e.seen_ts FROM orders o JOIN order_events e ON e.client_order_id=o.client_order_id "
                "WHERE e.kind IN ('ack','unconfirmed','reject') ORDER BY o.submitted_utc DESC LIMIT ?", (last,)):
            if sub and seen:
                acks.setdefault(venue, []).append((seen - sub) * 1000.0)
    except sqlite3.OperationalError:
        pass
    return {"executions": len(rows), "states": states, "stages": {k: q(by_key[k]) for k in keys},
            "segments": {n: q(v) for n, _a, _b in SEGMENTS if (v := segs.get(n))},
            "guard_reruns_excluded": reruns,
            "submit_to_ack_ms": {v: q(xs) for v, xs in acks.items()}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--last", type=int, default=200)
    ap.add_argument("--mode", default=None)
    ap.add_argument("--since", type=float, default=None,
                    help="unix ts: pin the window to ONE code tree, or a new stamp reports n=4 against 200 rows")
    ap.add_argument("--hours", type=float, default=None, help="convenience for --since")
    ap.add_argument("--include-reruns", action="store_true",
                    help="keep guard re-run rows, whose b_* stamps are re-based to the re-run's start")
    a = ap.parse_args()
    since = a.since if a.since is not None else (time.time() - a.hours * 3600 if a.hours else None)
    r = report(a.db, last=a.last, mode=a.mode, since=since, include_reruns=a.include_reruns)
    print(f"executions: {r['executions']}  states: {r.get('states', {})}")
    if r.get("note"):
        print(r["note"])
    print(f"{'stage':<18}{'n':>6}{'p50':>10}{'p95':>10}{'max':>10}")
    for k, s in r.get("stages", {}).items():
        print(f"{k:<18}{s['n']:>6}{s['p50']:>10}{s['p95']:>10}{s['max']:>10}")
    if r.get("segments"):
        print(f"\nper-row SEGMENTS (differenced on each row, then summarised -- read this one)")
        print(f"{'segment':<26}{'n':>6}{'p50':>10}{'p95':>10}{'max':>10}")
        for k, sg in r["segments"].items():
            print(f"{k:<26}{sg['n']:>6}{sg['p50']:>10}{sg['p95']:>10}{sg['max']:>10}")
    if r.get("guard_reruns_excluded"):
        print(f"\n({r['guard_reruns_excluded']} guard re-run rows excluded: their b_* stamps use a different t0)")
    for v, s in r.get("submit_to_ack_ms", {}).items():
        print(f"submit->ack {v:<12}{s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
