#!/usr/bin/env python3
"""L37: the Kalshi socket's inter-frame gaps, per window, from the raw capture."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from kernel.paths import FRAMES_ROOT  # noqa: E402
from nodes.capture.capture import iter_capture  # noqa: E402

HERE = Path(__file__).resolve().parent
BOUND_S = 15.0
WINDOWS = {"clean_2026-09-03T2330Z": (datetime(2026, 9, 3, 23, 30, tzinfo=timezone.utc), datetime(2026, 9, 4, 0, 30, tzinfo=timezone.utc)),
           "flapping_2026-09-03T1700Z": (datetime(2026, 9, 3, 17, 0, tzinfo=timezone.utc), datetime(2026, 9, 3, 18, 0, tzinfo=timezone.utc))}


def q(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(p * len(s)))], 3)


def measure(start: float, end: float) -> dict:
    ts, kinds, hb = [], {}, []
    last_hb = None
    for f in iter_capture(FRAMES_ROOT, "kalshi", start, end):
        ts.append(f.received_utc)
        try:
            k = json.loads(f.raw).get("type", "?") if isinstance(f.raw, str) else (f.raw or {}).get("type", "?")
        except Exception:  # noqa: BLE001
            k = "unparsed"
        kinds[k] = kinds.get(k, 0) + 1
        if k == "heartbeat":
            if last_hb is not None:
                hb.append(f.received_utc - last_hb)
            last_hb = f.received_utc
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    over = sum(g - BOUND_S for g in gaps if g > BOUND_S)
    return {"frames": len(ts), "by_kind": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
            "gap_p50": q(gaps, 0.5), "gap_p90": q(gaps, 0.9), "gap_p99": q(gaps, 0.99), "gap_max": round(max(gaps), 3) if gaps else None,
            "gaps_over_bound": sum(1 for g in gaps if g > BOUND_S), "share_over_bound": round(over / (end - start), 4),
            "heartbeat_n": len(hb), "heartbeat_p50": q(hb, 0.5), "heartbeat_p99": q(hb, 0.99), "heartbeat_max": round(max(hb), 3) if hb else None,
            "first_frame": datetime.fromtimestamp(ts[0], timezone.utc).isoformat() if ts else None,
            "last_frame": datetime.fromtimestamp(ts[-1], timezone.utc).isoformat() if ts else None}


def main() -> int:
    """No arguments: the two registered windows. `measure.py <name> <start-iso> <end-iso>`: one more
    window (a re-run on a clean hour), appended to the verdict, results in results_<name>.json."""
    windows = dict(WINDOWS)
    if len(sys.argv) == 4:
        windows = {sys.argv[1]: (datetime.fromisoformat(sys.argv[2]), datetime.fromisoformat(sys.argv[3]))}
    res = {"bound_s": BOUND_S, "run": datetime.now(timezone.utc).isoformat(), "windows": {}}
    for name, (a, b) in windows.items():
        res["windows"][name] = measure(a.timestamp(), b.timestamp())
    out = HERE / ("results.json" if len(sys.argv) != 4 else f"results_{sys.argv[1]}.json")
    out.write_text(json.dumps(res, indent=2) + "\n")
    lines = [] if len(sys.argv) == 4 else ["# L37 — Kalshi socket cadence (descriptive)", ""]
    lines += [f"\n## Run {res['run']}" if len(sys.argv) == 4 else f"Bound under test: {BOUND_S:.0f} s without any frame = HEARTBEAT_LOST. Run {res['run']}.", "",
             "| window | frames | by kind | gap p50 / p90 / p99 / max (s) | gaps > bound | share of hour past bound | heartbeat n / p50 / p99 / max (s) |",
             "|---|---|---|---|---|---|---|"]
    for name, w in res["windows"].items():
        lines.append(f"| {name} | {w['frames']} | {json.dumps(w['by_kind'])} | {w['gap_p50']} / {w['gap_p90']} / {w['gap_p99']} / {w['gap_max']} | "
                     f"{w['gaps_over_bound']} | {w['share_over_bound']} | {w['heartbeat_n']} / {w['heartbeat_p50']} / {w['heartbeat_p99']} / {w['heartbeat_max']} |")
    v = HERE / "verdict.md"
    if len(sys.argv) == 4 and v.exists():
        with v.open("a") as fh:
            fh.write("\n".join(lines) + "\n")
    else:
        v.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
