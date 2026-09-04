#!/usr/bin/env python3
"""L36: the recorded cover-cost distribution. Appends results_<run>.json and a section to verdict.md."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from kernel.paths import DB  # noqa: E402
from nodes.cover_cost.distribution import distribute, load_flap_windows, load_games, load_rows  # noqa: E402

HERE = Path(__file__).resolve().parent
SEAL = datetime(2026, 9, 2, tzinfo=timezone.utc).timestamp()
#: The IllegalTransition reconnect loop, before the reconnect counter existed (CHANGELOG 2026-09-03 night).
DECLARED_FLAPS = [(datetime(2026, 9, 3, 16, 54, tzinfo=timezone.utc).timestamp(), datetime(2026, 9, 3, 18, 50, tzinfo=timezone.utc).timestamp()),
                  (datetime(2026, 9, 3, 22, 50, tzinfo=timezone.utc).timestamp(), datetime(2026, 9, 3, 23, 26, tzinfo=timezone.utc).timestamp())]
THIN_S = 60.0
#: Kalshi taker fees on sports were pinned at half the venue's charge until the 2026-09-04 re-pin
#: (CHANGELOG 2026-09-04); rows priced before it are reported apart, never mixed.
ERAS = [("fee-half", SEAL), ("fee-repinned", datetime(2026, 9, 4, 0, 45, tzinfo=timezone.utc).timestamp())]


def main() -> int:
    now = datetime.now(timezone.utc)
    run = now.strftime("%Y%m%dT%H%M%SZ")
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else DB
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows, excluded = load_rows(con, since=SEAL, until=now.timestamp())
    games = load_games(con)
    flaps = load_flap_windows(con, declared=DECLARED_FLAPS)
    con.close()
    res = distribute(rows, games, flaps, eras=ERAS)
    res.update({"run": run, "db": str(db), "since": SEAL, "until": now.timestamp(), "rows": len(rows),
                "excluded_old_vocabulary": excluded, "games": len({r.game_id for r in rows}),
                "flap_windows": len(flaps), "flap_seconds": round(sum(b - a for a, b in flaps), 1)})
    (HERE / f"results_{run}.json").write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")

    lines = [f"\n## Run {run}", "",
             f"{len(rows)} rows in the lane's vocabulary since the seal over {res['games']} games; {excluded} rows of the "
             f"old vocabulary excluded; {len(flaps)} flap windows ({res['flap_seconds']:.0f} s).", "",
             "| cell (league, q, phase, flap, fee era) | rows | dwell s | priced | near 1¢ | profitable | cost p50 | p90 | min | statuses (dwell share) | blocked reasons (dwell share) |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    fmt = lambda v: "—" if v is None else f"{v:.4f}"
    for key, c in res["cells"].items():
        thin = " THIN" if c["dwell_s"] < THIN_S else ""
        st = ", ".join(f"{k} {v:.2f}" for k, v in c["status_share"].items())
        br = ", ".join(f"{k} {v:.2f}" for k, v in c["blocked_reason_share"].items()) or "—"
        lines.append(f"| {key}{thin} | {c['rows']} | {c['dwell_s']:.0f} | {c['priced_share']:.2f} | {c['near_actionable_share']:.3f} | "
                     f"{c['profitable_share']:.3f} | {fmt(c['cost_p50'])} | {fmt(c['cost_p90'])} | {fmt(c['cost_min'])} | {st} | {br} |")
    lines += ["", f"### Profitable rows ({len(res['profitable'])})", "",
              "| seen | game | q | phase | flapping | stale within 60 s | cost | locked return | label |", "|---|---|---|---|---|---|---|---|---|"]
    for p in res["profitable"]:
        suspect = p["flapping"] or p["phase"] == "end" or p["stale_within_60s"]
        lines.append(f"| {datetime.fromtimestamp(p['seen_ts'], timezone.utc):%m-%d %H:%M:%S}Z | {p['game_id']} | {p['quantity']:g} | {p['phase']} | "
                     f"{p['flapping']} | {p['stale_within_60s']} | {p['cost']:.4f} | {p['return_locked']:+.4f} | {'SUSPECT' if suspect else 'clean'} |")
    n = res["n_for_paper"]
    lines += ["", f"**n for the forward paper row: {n['n']}** (basis: {n['basis']}; {n['in_play_clean_actionable_rows']} in-play, clean "
              f"actionable rows" + (f"; sigma {n['sigma_locked_return']}, median locked return {n['median_locked_return']}" if n["basis"] == "power" else f"; {n['note']}") + ").",
              "", "Descriptive. Reads no outcome, claims no edge."]
    v = HERE / "verdict.md"
    if not v.exists():
        v.write_text("# L36 — the recorded cover-cost distribution (descriptive, re-runnable)\n\nDwell-weighted over the material-change "
                     "series in `stream_evaluations` since the 2026-09-02 seal; cells are (league | quantity | phase | flap or clean). "
                     "Definitions are in `spec.yaml` and are immutable.\n")
    with v.open("a") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
