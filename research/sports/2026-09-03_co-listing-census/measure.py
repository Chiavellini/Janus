#!/usr/bin/env python3
"""L28: one daily co-listing census. Appends results_<run>.json and a section to verdict.md."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from kernel.fetch import Client  # noqa: E402
from nodes.discovery.census import run_census  # noqa: E402

HERE = Path(__file__).resolve().parent


def main() -> int:
    run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    res = run_census(Client("kalshi-census", rate=4, burst=8, cache_dir=None),
                     Client("polymarket-census", rate=4, burst=8, cache_dir=None))
    res["run"] = run
    partial = any(k.startswith(("kalshi:", "polymarket:")) for k in res["errors"]) or not res["kalshi"]["events_total"] \
        or not res["polymarket"]["game_events_total"]
    res["partial"] = partial
    (HERE / f"results_{run}.json").write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    rows = res["competitions"]
    lines = [f"\n## Run {run}" + (" — PARTIAL (does not count)" if partial else ""), "",
             f"Kalshi: {res['kalshi']['sports_series']} sports series, {res['kalshi']['game_class_series']} game-class, "
             f"{len(res['kalshi']['series'])} with open markets, {res['kalshi']['events_total']} events. "
             f"Polymarket: {res['polymarket']['leagues']} leagues in /sports, {len(res['polymarket']['sports'])} with game events, "
             f"{res['polymarket']['game_events_total']} game events, {res['polymarket']['books_sampled']} books sampled. "
             f"Joined: {res['pairs_total']} co-listed events (all dates).", "",
             "| rank | Kalshi series | PM sport | co-listed 48h | two-sided both | Kalshi touch $ (n) | PM touch $ (n) | life h | capacity $ | score | join |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        uk = res["unmatched_kalshi_48h"].get(r["kalshi_series"], 0)
        up = res["unmatched_pm_48h"].get(r["pm_sport"], 0)
        weak = "JOIN_WEAK" if max(uk, up) > r["co_listed_48h"] else "ok"
        f = lambda v: "—" if v is None else f"{v:.0f}"
        lines.append(f"| {i} | {r['kalshi_series']} | {r['pm_sport']} | {r['co_listed_48h']} | {r['two_sided_both']} | "
                     f"{f(r['kalshi_touch_usd_median'])} ({r['kalshi_touch_n']}) | {f(r['pm_touch_usd_median'])} ({r['pm_touch_n']}) | "
                     f"{f(r['life_h_median'])} | {f(r['capacity_usd'])} | {'—' if r['score'] is None else f'{r['score']:.2f}'} | {weak} (K {uk} / PM {up} unmatched) |")
    unk = {k: v for k, v in res["kalshi_events_48h"].items() if k not in {r["kalshi_series"] for r in rows}}
    unp = {k: v for k, v in res["pm_events_48h"].items() if k not in {r["pm_sport"] for r in rows}}
    lines += ["", f"Kalshi series with events in the window but no co-listing: {json.dumps(unk, sort_keys=True)}",
              "", f"Polymarket sports with game events in the window but no co-listing: {json.dumps(unp, sort_keys=True)}",
              "", f"Errors: {len(res['errors'])}" + (f" — {json.dumps(res['errors'])[:600]}" if res["errors"] else "")]
    v = HERE / "verdict.md"
    if not v.exists():
        v.write_text("# L28 — co-listing census (descriptive, daily for seven days)\n\nScore = co-listed capacity at the touch / "
                     "median contract life. Rank is read from the seven-day median; fewer than four runs orders nothing.\n")
    with v.open("a") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
