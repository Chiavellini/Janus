#!/usr/bin/env python3
"""L40: how many profitable prints survive a SUSPECT rule that can be false. Appends a dated section
to verdict.md; results_<run>.json beside it. Reads no outcome, claims no edge."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from kernel.paths import DB  # noqa: E402
from nodes.cover_cost.distribution import load_flap_windows  # noqa: E402
from nodes.cover_cost.suspect import label, load  # noqa: E402

HERE = Path(__file__).resolve().parent
SEAL = datetime(2026, 9, 4, 0, 25, tzinfo=timezone.utc).timestamp()      # the first clean data (CHECKLIST B)


def main() -> int:
    now = datetime.now(timezone.utc)
    run = now.strftime("%Y%m%dT%H%M%SZ")
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else DB
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    data = load(con, since=SEAL, until=now.timestamp())
    flaps = load_flap_windows(con)
    con.close()
    res = label(data, flaps)
    res.update({"run": run, "since": SEAL, "until": now.timestamp(), "flap_windows": len(flaps)})
    (HERE / f"results_{run}.json").write_text(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=2, sort_keys=True, default=str) + "\n")
    lines = [f"\n## Run {run} — since the seal 2026-09-04 00:25Z", "",
             f"{res['prints']} profitable prints; **{res['clean']} clean, {res['suspect']} suspect** under SUSPECT_V2. Clauses fired: "
             f"flapping {res['why']['flapping']}, end {res['why']['end']}, stale_before_60s {res['why']['stale_before_60s']}, "
             f"no mapped replica {res['why']['no_mapped_replica']}. {len(flaps)} flap windows.", "",
             "| cell | prints | clean | clean median return | clean sigma |", "|---|---|---|---|---|"]
    for k, c in res["cells"].items():
        lines.append(f"| {k} | {c['prints']} | {c['clean']} | {c['clean_median_return']} | {c['clean_sigma_return']} |")
    lines += ["", f"### Clean prints ({res['clean']})", "", "| seen | game | league | q | phase | cost | locked return | replicas |", "|---|---|---|---|---|---|---|---|"]
    for p in res["clean_rows"]:
        lines.append(f"| {datetime.fromtimestamp(p['seen_ts'], timezone.utc):%m-%d %H:%M:%S}Z | {p['game_id']} | {p['league']} | {p['quantity']:g} | "
                     f"{p['phase']} | {p['cost']:.4f} | {p['return_locked']:+.4f} | {p['replicas']} |")
    lines += ["", "Descriptive. A clean print is a priced book no recorded fault contradicts: not a fill, not a return. Claims no edge."]
    v = HERE / "verdict.md"
    if not v.exists():
        v.write_text("# L40 — a SUSPECT rule that can be false (descriptive, re-runnable)\n\nDefinitions in `spec.yaml`, immutable after the first run.\n")
    with v.open("a") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
