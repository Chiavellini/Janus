#!/usr/bin/env python3
"""Where the surface goes: co-listed events -> actionable prints -> refusals -> orders -> money.

    python3 ops/funnel_report.py [--db PATH] [--hours 24]

L113 (2026-09-14). Nothing joined these stages. `ops/box/launchpad_extract.py` computes two halves
-- `profitable_prints` from `stream_evaluations` and `attempts` from `executions` -- and never joins
them; `ops/coverage_report.py` stops at "did the lane pair it"; `ops/slippage_report.py` starts at
covers that already completed. So "1,893 actionable prints and 4 executions" was answerable only by
running three tools and doing arithmetic by hand, and the middle of the funnel -- the refusals --
was not answerable at all, because both channels ended at `print()`.

Read the caveats with the numbers:

  * `stream_evaluations` is MATERIAL-CHANGE gated (a 0.1c cost move, a status change, or a 15 s
    heartbeat), so a count is distinct actionable EPISODES, not evaluations. It also carries one row
    per size rung, so every count here filters on a single quantity.
  * Refusal counts begin at the first report tick after L113 deploys. An empty section means the
    lane has not ticked since, not that nothing was refused.
  * `stream_evaluations`, `sizing_decisions` and `refusal_counts` age out at 7 days; `events`,
    `orders`, `executions` and `execution_settlements` never do. Do not compute a ratio across a
    longer window than 7 days.
  * A halted lane prices nothing at all (L111), and those epochs appear as BLOCKED_STALE with
    `blocked_by='supervisor:halt:...'`. They are counted separately below, because the denominator
    they represent -- how many would have been actionable -- is unknowable.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

if "__file__" in globals():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kernel.paths import DB  # noqa: E402

REAL = ("LIMITED_LIVE", "LIVE")


def _one(con, sql, args=()):
    r = con.execute(sql, args).fetchone()
    return r[0] if r and r[0] is not None else 0


def report(db: Path, *, hours: float = 24.0, quantity: float | None = None) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    since = time.time() - hours * 3600
    q = quantity
    if q is None:
        q = con.execute("SELECT quantity FROM stream_evaluations WHERE seen_ts>? "
                        "GROUP BY quantity ORDER BY COUNT(*) DESC LIMIT 1", (since,)).fetchone()
        q = q[0] if q else 10.0
    marks = ",".join("?" * len(REAL))

    out: dict = {"hours": hours, "quantity": q, "stages": {}, "detail": {}}
    st = out["stages"]
    st["events_seen"] = _one(con, "SELECT COUNT(*) FROM events WHERE last_seen_ts>?", (since,))
    st["co_listed"] = _one(con, "SELECT COUNT(*) FROM events WHERE last_seen_ts>? AND phase LIKE '%:co_listed'", (since,))
    st["unpaired"] = _one(con, "SELECT COUNT(*) FROM events WHERE last_seen_ts>? AND block_reason LIKE 'UNPAIRED:%'", (since,))
    st["spawn_blocked"] = _one(con, "SELECT COUNT(*) FROM events WHERE last_seen_ts>? AND block_reason LIKE 'SPAWN:%'", (since,))
    st["games_priced"] = _one(con, "SELECT COUNT(DISTINCT game_id) FROM stream_evaluations WHERE seen_ts>?", (since,))
    st["actionable_prints"] = _one(con, "SELECT COUNT(*) FROM stream_evaluations WHERE seen_ts>? AND quantity=? "
                                       "AND status='PROFITABLE_UNEXECUTED'", (since, q))
    st["halted_prints"] = _one(con, "SELECT COUNT(*) FROM stream_evaluations WHERE seen_ts>? AND quantity=? "
                                    "AND blocked_by LIKE 'supervisor:halt:%'", (since, q))
    st["executions"] = _one(con, f"SELECT COUNT(*) FROM executions WHERE started_utc>? AND mode IN ({marks})", (since, *REAL))
    st["orders"] = _one(con, f"SELECT COUNT(*) FROM orders WHERE submitted_utc>? AND mode IN ({marks})", (since, *REAL))
    st["orders_filled"] = _one(con, f"SELECT COUNT(*) FROM orders WHERE submitted_utc>? AND mode IN ({marks}) "
                                    "AND filled_contracts>0", (since, *REAL))
    st["covers"] = _one(con, f"SELECT COUNT(*) FROM execution_settlements WHERE settled_ts>? AND mode IN ({marks}) "
                             "AND kind='COVER' AND hedged_contracts>0", (since, *REAL))

    out["detail"]["evaluation_status"] = dict(con.execute(
        "SELECT status, COUNT(*) FROM stream_evaluations WHERE seen_ts>? AND quantity=? GROUP BY 1 ORDER BY 2 DESC",
        (since, q)).fetchall())
    out["detail"]["unpaired_reason"] = dict(con.execute(
        "SELECT substr(block_reason,1,44), COUNT(*) FROM events WHERE last_seen_ts>? AND block_reason IS NOT NULL "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 8", (since,)).fetchall())
    try:
        out["detail"]["refusals"] = [
            {"channel": ch, "code": code, "n": n} for ch, code, n in con.execute(
                "SELECT channel, code, SUM(n) FROM refusal_counts WHERE seen_ts>? GROUP BY 1,2 ORDER BY 3 DESC LIMIT 16",
                (since,))]
    except sqlite3.OperationalError:
        out["detail"]["refusals"] = []          # lane has not ticked since L113 deployed
    money = con.execute(
        f"SELECT ROUND(SUM(cover_usd),4), ROUND(SUM(directional_usd),4), ROUND(SUM(realized_usd),4) "
        f"FROM execution_settlements WHERE settled_ts>? AND mode IN ({marks})", (since, *REAL)).fetchone()
    out["money"] = {"cover_usd": money[0] or 0.0, "directional_usd": money[1] or 0.0,
                    "realized_usd": money[2] or 0.0}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--quantity", type=float, default=None, help="size rung; default is the busiest")
    a = ap.parse_args()
    r = report(a.db, hours=a.hours, quantity=a.quantity)
    print(f"=== funnel, last {r['hours']:g} h, size rung q={r['quantity']:g} ===")
    prev = None
    for k, v in r["stages"].items():
        pct = "" if prev in (None, 0) or k in ("unpaired", "spawn_blocked", "halted_prints") else f"  ({v / prev * 100:5.1f}% of previous)"
        print(f"  {k:22} {v:>10,}{pct}")
        if k not in ("unpaired", "spawn_blocked", "halted_prints"):
            prev = v
    print("\n  evaluation status:")
    for k, v in r["detail"]["evaluation_status"].items():
        print(f"    {k:30} {v:>10,}")
    if r["detail"]["unpaired_reason"]:
        print("\n  why events did not pair:")
        for k, v in r["detail"]["unpaired_reason"].items():
            print(f"    {k:46} {v:>6,}")
    print("\n  refusals by channel and code:")
    if not r["detail"]["refusals"]:
        print("    (none recorded - the lane has not reported a tick since L113 deployed)")
    for row in r["detail"]["refusals"]:
        print(f"    [{row['channel']:4}] {row['code']:28} {row['n']:>10,}")
    m = r["money"]
    print(f"\n  money: cover {m['cover_usd']:+.4f}   directional {m['directional_usd']:+.4f}   "
          f"realized {m['realized_usd']:+.4f} USD")
    print("  (cover_usd is the arbitrage business; directional_usd is an unhedged bet that happened to land)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
