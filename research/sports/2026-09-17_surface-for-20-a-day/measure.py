#!/usr/bin/env python3
"""L147: summarise L28 census runs to ask whether the surface could carry $20 or $50 a day.

Read-only.  Takes a directory of `results_*.json` files written by L28's census and prints one small
JSON object.  Small on purpose: it must fit a single SSM response when run on the box.

Counts come from the census's own fields; nothing is re-joined.
"""
from __future__ import annotations

import glob
import json
import os
import statistics
import sys

SCHEMA = "janus.l147.surface_for_20_a_day.v1"

# Registered in spec.yaml.
BEST_CASE_PROFIT_PER_COVER = 0.28
TARGETS_USD = {"20": 20.0, "50": 50.0}
OBSERVED_COVERS_PER_DAY = 4.7
OBSERVED_COVERS_PER_ENGAGED_EVENT = 0.08
EVENTS_PER_DAY_THRESHOLD = 72
CAPITAL_PER_COVER_USD = 21.0
DAILY_NOTIONAL_CAP_USD = 500.0


def window_hours(run: dict) -> float:
    lo, hi = run.get("window_h") or (3.0, 48.0)
    return float(lo) + float(hi)


def per_day(count: float, run: dict) -> float:
    return count * 24.0 / window_hours(run)


def summarise_run(run: dict, name: str) -> dict:
    comps = run.get("competitions") or []
    co = sum(int(c.get("co_listed_48h") or 0) for c in comps)
    two = sum(int(c.get("two_sided_both") or 0) for c in comps)
    touch_k = [c["kalshi_touch_usd_median"] for c in comps if c.get("kalshi_touch_usd_median") is not None]
    touch_p = [c["pm_touch_usd_median"] for c in comps if c.get("pm_touch_usd_median") is not None]
    sampled_k = sum(int(c.get("kalshi_touch_n") or 0) for c in comps)
    sampled_p = sum(int(c.get("pm_touch_n") or 0) for c in comps)
    books = (run.get("polymarket") or {}).get("books_sampled")
    return {
        "run": run.get("run") or name, "partial": bool(run.get("partial")),
        "window_h": window_hours(run),
        "co_listed_window": co, "co_listed_per_day": round(per_day(co, run), 2),
        "two_sided_both_window": two, "two_sided_both_per_day": round(per_day(two, run), 2),
        "competitions": len(comps),
        "pm_books_sampled": books, "kalshi_touch_sampled": sampled_k, "pm_touch_sampled": sampled_p,
        "median_competition_touch_usd": {
            "kalshi": round(statistics.median(touch_k), 2) if touch_k else None,
            "polymarket": round(statistics.median(touch_p), 2) if touch_p else None},
        "top_competitions": [
            {"kalshi_series": c.get("kalshi_series"), "pm_sport": c.get("pm_sport"),
             "co_listed": c.get("co_listed_48h"), "two_sided_both": c.get("two_sided_both"),
             "kalshi_touch_usd": c.get("kalshi_touch_usd_median"),
             "pm_touch_usd": c.get("pm_touch_usd_median")}
            for c in sorted(comps, key=lambda z: -(z.get("co_listed_48h") or 0))[:8]],
    }


def verdict(runs: list[dict]) -> tuple[str, str]:
    usable = [r for r in runs if not r["partial"]]
    if len(usable) < 3:
        return "INCONCLUSIVE", f"only {len(usable)} usable census runs (registered minimum 3)"
    med_two = statistics.median(r["two_sided_both_per_day"] for r in usable)
    if med_two < EVENTS_PER_DAY_THRESHOLD:
        return "SURFACE_INSUFFICIENT_FOR_20", (
            f"median two-sided co-listed events {med_two:.1f}/day < {EVENTS_PER_DAY_THRESHOLD}")
    return "SURFACE_ALLOWS_20_IN_PRINCIPLE", (
        f"median two-sided co-listed events {med_two:.1f}/day >= {EVENTS_PER_DAY_THRESHOLD}")


def run(directory: str) -> dict:
    files = sorted(glob.glob(os.path.join(directory, "results_*.json")))
    runs, unreadable = [], []
    for path in files:
        try:
            with open(path) as fh:
                runs.append(summarise_run(json.load(fh), os.path.basename(path)))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            unreadable.append(f"{os.path.basename(path)}: {type(exc).__name__}")
    usable = [r for r in runs if not r["partial"]]
    v, reason = verdict(runs)

    def med(key):
        return round(statistics.median(r[key] for r in usable), 2) if usable else None

    covers_needed = {k: round(t / BEST_CASE_PROFIT_PER_COVER, 1) for k, t in TARGETS_USD.items()}
    cap_covers = DAILY_NOTIONAL_CAP_USD / CAPITAL_PER_COVER_USD
    return {
        "schema": SCHEMA, "directory": directory,
        "runs_found": len(files), "runs_usable": len(usable),
        "runs_partial": [r["run"] for r in runs if r["partial"]], "unreadable": unreadable,
        "median_co_listed_per_day": med("co_listed_per_day"),
        "median_two_sided_both_per_day": med("two_sided_both_per_day"),
        "covers_per_day_needed_best_case": covers_needed,
        "covers_per_event_needed_if_every_co_listed_event_used": {
            k: (round(n / med("co_listed_per_day"), 3) if usable and med("co_listed_per_day") else None)
            for k, n in covers_needed.items()},
        "observed": {"covers_per_day": OBSERVED_COVERS_PER_DAY,
                     "covers_per_engaged_event": OBSERVED_COVERS_PER_ENGAGED_EVENT},
        "notional_cap": {"daily_usd": DAILY_NOTIONAL_CAP_USD, "capital_per_cover_usd": CAPITAL_PER_COVER_USD,
                         "max_covers_per_day": round(cap_covers, 1),
                         "max_usd_per_day_best_case": round(cap_covers * BEST_CASE_PROFIT_PER_COVER, 2)},
        "verdict": v, "verdict_reason": reason,
        "runs": runs,
    }


if __name__ == "__main__":
    print(json.dumps(run(sys.argv[1] if len(sys.argv) > 1 else "."), sort_keys=True, separators=(",", ":")))
