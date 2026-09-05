#!/usr/bin/env python3
"""The daily football-data.org snapshot (ledger F6): fetch every free-tier competition, record it
with first-seen kickoffs immutable, and report per-league postponement and cancellation counts with
the row's registered estimator. Appends a dated section to verdict.md; results_<run>.json beside it.
Refuses to run without FD_TOKEN. Reads no price, claims no edge."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from kernel.fetch import Client  # noqa: E402
from kernel.paths import DB  # noqa: E402
from nodes.store_tuples.store import TupleStore  # noqa: E402
from nodes.watch_fd.snapshot import COMPETITIONS, fetch_matches, rates, record  # noqa: E402
from nodes.watch_settle.settle import upper_bound_95  # noqa: E402

HERE = Path(__file__).resolve().parent
MIN_REGISTER, POINT_AT = 100, 300


def main() -> int:
    token = os.environ.get("FD_TOKEN", "")
    if not token:
        print("FD_TOKEN is not set: nothing fetched, nothing written. The operator's token goes in the credentials env.", file=sys.stderr)
        return 3
    now = datetime.now(timezone.utc)
    run = now.strftime("%Y%m%dT%H%M%SZ")
    store = TupleStore(DB)
    cl = Client("football-data", rate=1, burst=2, cache_dir=None)      # the free tier allows 10 calls a minute
    fetched = {}
    for code in COMPETITIONS:
        try:
            ms = fetch_matches(code, cl, token=token)
            fetched[code] = record(store, code, ms, now=now.timestamp())
        except Exception as exc:  # noqa: BLE001 -- one competition failing must not lose the others
            fetched[code] = f"FAILED {type(exc).__name__}"
    store.commit()
    r = rates(store)
    store.close()
    table = {}
    for league, x in r.items():
        n = x["terminal"]
        est = {}
        for key, k in (("postponed_gt48h_rate", x["moved_gt48h"]), ("cancelled_rate", x["cancelled"])):
            est[key] = None if n < MIN_REGISTER else round((k / n) if n >= POINT_AT else upper_bound_95(k, n), 6)
        table[league] = {**x, "registered": est}
    res = {"run": run, "fetched": fetched, "leagues": table}
    (HERE / f"results_{run}.json").write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    lines = [f"\n## Run {run}", "", f"Fetched: {fetched}.", "",
             "| league | matches | terminal | moved > 48 h | cancelled | registered postponed (bound < 300) | registered cancelled |",
             "|---|---|---|---|---|---|---|"]
    for league, x in table.items():
        lines.append(f"| {league} | {x['matches']} | {x['terminal']} | {x['moved_gt48h']} | {x['cancelled']} | "
                     f"{x['registered']['postponed_gt48h_rate']} | {x['registered']['cancelled_rate']} |")
    lines += ["", "Caveats: the clock runs from the FIRST-SEEN kickoff; a match first seen terminal is excluded. Reads no price, claims no edge."]
    v = HERE / "verdict.md"
    if not v.exists():
        v.write_text("# Soccer postponement and cancellation, forward (nodes/watch_fd; ledger F6)\n")
    with v.open("a") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
