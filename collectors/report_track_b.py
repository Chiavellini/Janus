#!/usr/bin/env python3
"""Registered Track B Phase A/B characterization reports.

The reporter reads only Janus-owned episode data. It never reads Kilos' BTC episode set, never
models a realized fill, and labels the Phase-B capacity output as displayed capacity.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collectors.track_b_core import REQUIRED_OFFSETS_S, alarm_decision  # noqa: E402

PHASE_A_DIR = Path("research/exec/2026-08-17_track-b-phase-a")
PHASE_B_DIR = Path("research/exec/2026-08-17_open-collapse")


def _median(values):
    vals = [float(x) for x in values if x is not None]
    return statistics.median(vals) if vals else None


def _quantile_edges(values: list[float]) -> list[float]:
    vals = sorted(values)
    if len(vals) < 4:
        return []
    return [vals[math.ceil((len(vals) - 1) * q)] for q in (.25, .50, .75)]


def _bucket(value: float, edges: list[float]) -> str:
    return f"Q{1 + sum(value > edge for edge in edges)}"


def phase_a(db: Path, out_dir: Path = PHASE_A_DIR) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    bounds = con.execute("""SELECT MIN(open_ts), MAX(open_ts)+60 FROM expectations
      WHERE target_offset_s<=60 AND status!='pending'""").fetchone()
    duration_h = ((bounds[1] - bounds[0]) / 3600.0) if bounds and bounds[0] else 0.0
    rows = con.execute("""SELECT x.venue,x.market_id,COALESCE(m.ticker,x.market_id,'') ticker,
        x.series,m.asset,x.open_ts,x.target_offset_s,x.status,x.reason,
        e.reference_source,e.reference_value
      FROM expectations x LEFT JOIN markets m
        ON m.venue=x.venue AND m.market_id=x.market_id
      LEFT JOIN episodes e ON e.venue=x.venue AND e.market_id=x.market_id
        AND e.target_offset_s=x.target_offset_s
      WHERE x.open_ts <= COALESCE((SELECT MAX(updated_ts)-60 FROM expectations),0)
      ORDER BY x.venue,x.series,x.open_ts,x.target_offset_s""").fetchall()
    grouped: dict[tuple, dict] = {}
    for row in rows:
        key = (row["venue"], row["series"], row["open_ts"])
        item = grouped.setdefault(key, {"venue": row["venue"], "market_id": row["market_id"],
            "ticker": row["ticker"],
            "series": row["series"], "asset": row["asset"], "open_ts": row["open_ts"],
            "offsets": {}})
        if row["target_offset_s"] in REQUIRED_OFFSETS_S:
            item["offsets"][float(row["target_offset_s"])] = row["status"]

    per_series = defaultdict(lambda: {"windows": 0, "complete_windows": 0,
                                     "captured_samples": 0, "expected_samples": 0})
    for item in grouped.values():
        stat = per_series[(item["venue"], item["series"])]
        stat["windows"] += 1
        statuses = [item["offsets"].get(float(off)) for off in REQUIRED_OFFSETS_S]
        stat["expected_samples"] += len(REQUIRED_OFFSETS_S)
        stat["captured_samples"] += sum(x == "captured" for x in statuses)
        stat["complete_windows"] += int(all(x == "captured" for x in statuses))

    series_rows = []
    for (venue, series), stat in sorted(per_series.items()):
        stat = dict(stat)
        stat.update({"venue": venue, "series": series,
                     "sample_capture_rate": (stat["captured_samples"] / stat["expected_samples"]
                                             if stat["expected_samples"] else 0.0),
                     "window_capture_rate": (stat["complete_windows"] / stat["windows"]
                                             if stat["windows"] else 0.0)})
        series_rows.append(stat)

    # Missingness vs realized volatility uses the predeclared reference attached to episode rows.
    # It does not compare venue prices. Unsupported references remain UNKNOWN and are counted.
    moves = []
    for item in grouped.values():
        ticks = con.execute("""SELECT target_offset_s,reference_value FROM episodes
          WHERE venue=? AND market_id=? AND target_offset_s IN (0,60)
            AND reference_value IS NOT NULL ORDER BY target_offset_s""",
            (item["venue"], item["market_id"])).fetchall()
        if len(ticks) != 2:
            continue
        first, last = ticks
        if first[1] and last[1]:
            item["realized_move_bps"] = abs(float(last[1]) / float(first[1]) - 1) * 10_000
            moves.append(item["realized_move_bps"])
    edges = _quantile_edges(moves)
    vol = defaultdict(lambda: {"windows": 0, "complete": 0})
    unknown = 0
    for item in grouped.values():
        if "realized_move_bps" not in item or not edges:
            unknown += 1
            continue
        key = _bucket(item["realized_move_bps"], edges)
        statuses = [item["offsets"].get(float(off)) for off in REQUIRED_OFFSETS_S]
        vol[key]["windows"] += 1
        vol[key]["complete"] += int(all(x == "captured" for x in statuses))
    vol_rows = [{"bucket": key, **value,
                 "window_capture_rate": value["complete"] / value["windows"]}
                for key, value in sorted(vol.items())]

    passing_series = sum(r["venue"] == "kalshi" and r["window_capture_rate"] >= .98
                         for r in series_rows)
    disk_mb_day = ((db.stat().st_size / 1024 ** 2) / (duration_h / 24)) if duration_h >= 1 else None
    fake_alarm_pass = alarm_decision(free_bytes=1, disk_floor_bytes=2,
        last_message_age_s=91, max_message_age_s=90, capture_rate=.97,
        min_capture_rate=.98) == ["disk_floor", "liveness", "capture_gap"]
    if duration_h < 72:
        verdict = "PENDING_INSUFFICIENT_DURATION"
    elif passing_series >= 12 and disk_mb_day is not None and disk_mb_day < 100 and fake_alarm_pass:
        verdict = "PASS"
    else:
        verdict = "FAIL_STOP"
    result = {
        "evidence_tier": "M1",
        "verdict": verdict,
        "duration_h": duration_h,
        "required_duration_h": 72,
        "kalshi_series_passing_98pct_window_capture": passing_series,
        "required_series_passing": 12,
        "disk_mb_per_day": disk_mb_day,
        "disk_gate_mb_per_day": 100,
        "fake_target_alarm_selftest": fake_alarm_pass,
        "volatility_bucket_edges_bps": edges,
        "volatility_unknown_windows": unknown,
        "per_series": series_rows,
        "volatility_capture": vol_rows,
        "notes": [
            "Window capture requires every registered offset through +60s; sample capture is also reported.",
            "Volatility uses predeclared within-Chainlink or within-Pyth 60s moves; unsupported references are UNKNOWN.",
            "No settlement PnL, modeled fill, or Kilos BTC episode row was read.",
        ],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (out_dir / "verdict.md").write_text(
        f"# Track B Phase A capture\n\n**{verdict}** after {duration_h:.2f} h. "
        f"{passing_series} series meet the 98% complete-window bar.\n\n"
        "This is collection characterization (M1), not a strategy result. No test look spent.\n")
    with (out_dir / "volatility_capture.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["bucket", "windows", "complete", "window_capture_rate"])
        writer.writeheader(); writer.writerows(vol_rows)
    con.close()
    return result


def phase_b(db: Path, phase_a_result: dict, out_dir: Path = PHASE_B_DIR) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    if phase_a_result.get("verdict") != "PASS":
        result = {"evidence_tier": "M1", "verdict": "BLOCKED_PHASE_A",
                  "phase_a_verdict": phase_a_result.get("verdict"),
                  "test_looks_spent": 0}
        (out_dir / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        (out_dir / "verdict.md").write_text(
            "# Track B Phase B open collapse\n\n**BLOCKED_PHASE_A.** The 72-hour capture gate has not passed.\n")
        return result
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute("""SELECT series,market_id,target_offset_s,spread,
        yes_ask,no_ask,yes_ask_size,no_ask_size,yes_ask_depth_1c,no_ask_depth_1c
      FROM episodes WHERE venue='kalshi' AND series!='KXBTC15M'
        AND status='captured' AND target_offset_s IN (0,5)""").fetchall()
    by_series: dict[str, dict[str, dict[float, sqlite3.Row]]] = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        by_series[row["series"]][row["market_id"]][float(row["target_offset_s"])] = row
    output = []
    for series, markets in sorted(by_series.items()):
        paired = [v for v in markets.values() if 0.0 in v and 5.0 in v]
        spread0 = _median([v[0.0]["spread"] for v in paired])
        spread5 = _median([v[5.0]["spread"] for v in paired])
        collapse = spread0 - spread5 if spread0 is not None and spread5 is not None else None
        touch = [sum(x for x in (v[0.0]["yes_ask_size"], v[0.0]["no_ask_size"]) if x is not None)
                 for v in paired]
        notional = [sum((v[0.0][price] or 0) * (v[0.0][size] or 0)
                        for price, size in (("yes_ask", "yes_ask_size"),
                                            ("no_ask", "no_ask_size")))
                    for v in paired]
        within1 = [sum(x for x in (v[0.0]["yes_ask_depth_1c"], v[0.0]["no_ask_depth_1c"])
                       if x is not None) for v in paired]
        output.append({"series": series, "n_windows": len(paired), "median_spread_t0": spread0,
            "median_spread_t5": spread5, "collapse": collapse,
            "passes": len(paired) >= 200 and collapse is not None and collapse >= .10,
            "median_displayed_touch_contracts_both_sides": _median(touch),
            "median_displayed_touch_notional_usd_per_window": _median(notional),
            "displayed_touch_notional_usd_per_day_96_windows": (
                _median(notional) * 96 if _median(notional) is not None else None),
            "median_displayed_within_1c_contracts_both_sides": _median(within1)})
    passing = sum(x["passes"] for x in output)
    verdict = "PASS" if passing >= 3 else "FAIL_STOP"
    result = {"evidence_tier": "M1", "verdict": verdict,
              "non_btc_series_passing": passing, "required_series_passing": 3,
              "min_windows_per_series": 200, "collapse_threshold": .10,
              "series": output, "test_looks_spent": 0,
              "capacity_label": "displayed capacity, not realized fills",
              "out_of_scope_unknowns": ["queue position", "realized fill rate", "own impact",
                                        "quote-induced incumbent fading", "realized maker fee"]}
    (out_dir / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (out_dir / "verdict.md").write_text(
        f"# Track B Phase B open collapse\n\n**{verdict}.** {passing} non-BTC series pass the "
        "registered >=10-cent median t0-to-t5 collapse with >=200 windows.\n\n"
        "Capacity is displayed depth only; no fill model is reported as measurement.\n")
    fields = list(output[0]) if output else ["series", "n_windows", "median_spread_t0",
        "median_spread_t5", "collapse", "passes",
        "median_displayed_touch_contracts_both_sides",
        "median_displayed_within_1c_contracts_both_sides"]
    with (out_dir / "series.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields); writer.writeheader(); writer.writerows(output)
    vol_rows = phase_a_result.get("volatility_capture", [])
    with (out_dir / "volatility_capture.csv").open("w", newline="") as fh:
        fields_vol = ["bucket", "windows", "complete", "window_capture_rate"]
        writer = csv.DictWriter(fh, fieldnames=fields_vol); writer.writeheader(); writer.writerows(vol_rows)
    con.close()
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/track_b/episodes.sqlite")
    ap.add_argument("--phase", choices=("a", "b", "all"), default="all")
    args = ap.parse_args()
    db = Path(args.db)
    if not db.exists():
        raise SystemExit(f"database not found: {db}")
    a = phase_a(db) if args.phase in ("a", "all") else json.loads(
        (PHASE_A_DIR / "results.json").read_text())
    print(json.dumps(a, indent=2, sort_keys=True))
    if args.phase in ("b", "all"):
        print(json.dumps(phase_b(db, a), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
