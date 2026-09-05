#!/usr/bin/env python3
"""The daily resolver for nodes/watch_settle (ledger F4 once registered): asks Gamma about every
capture-only event whose start is at least an hour old, then reports the delay table for tennis.
Appends a dated section to verdict.md; results_<run>.json beside it."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from kernel.fetch import Client  # noqa: E402
from kernel.paths import DB  # noqa: E402
from nodes.store_tuples.store import TupleStore  # noqa: E402
from nodes.watch_settle.settle import delay_rows, resolve_pending, upper_bound_95  # noqa: E402

HERE = Path(__file__).resolve().parent
GT7D = 7 * 86400.0


def main() -> int:
    now = datetime.now(timezone.utc)
    run = now.strftime("%Y%m%dT%H%M%SZ")
    store = TupleStore(DB)
    out = resolve_pending(store, Client("gamma-settle", rate=3, burst=6, cache_dir=None), now=now.timestamp())
    store.commit()
    rows = delay_rows(store)
    n = len(rows)
    late = [r for r in rows if r[4] - r[2] > GT7D]
    half = [r for r in rows if r[5] == "HALF"]
    moved = [r for r in rows if r[3] is not None and r[2] is not None and abs(r[3] - r[2]) > 3600]
    res = {"run": run, "resolve": out, "resolved_tennis_rows": n, "delayed_gt7d": len(late), "half": len(half),
           "start_moved_gt1h": len(moved),
           "delayed_gt7d_rate": round(len(late) / n, 6) if n else None, "half_rate": round(len(half) / n, 6) if n else None,
           # F4's REGISTERED value while n < 300 (spec): the one-sided 95% upper bound, never the point estimate
           "registered_upper_bound_95": round(upper_bound_95(len(late), n), 6) if n else None,
           "late_rows": [r[0] for r in late][:50], "half_rows": [r[0] for r in half][:50]}
    (HERE / f"results_{run}.json").write_text(json.dumps(res, indent=2) + "\n")
    store.close()
    lines = [f"\n## Run {run}", "",
             f"Resolver: {out}. Resolved tennis rows so far: {n}; completed more than 7 days after the first-seen start: {len(late)} "
             f"(rate {res['delayed_gt7d_rate']}; registered upper bound {res['registered_upper_bound_95']}); closed at 0.5/0.5: {len(half)} (rate {res['half_rate']}); start moved by more than an hour after first sight: {len(moved)}.",
             "", "Caveats: the delay clock runs from the FIRST-SEEN gameStartTime; resolution time is the poll time (a ±24 h box). Reads no price, claims no edge."]
    v = HERE / "verdict.md"
    if not v.exists():
        v.write_text("# Tennis settlement timing, forward (nodes/watch_settle; ledger F4 once registered)\n")
    with v.open("a") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
