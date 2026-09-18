#!/usr/bin/env python3
"""L153: does L152's STRONG_LEAD survive checking each trade against the book it was matched to?

    python3 robustness.py            # offline: reads L152's cached trades and track.sqlite

A Kalshi trade prints AT a touch -- a YES-taker lifts the ask, a NO-taker hits the bid -- so a trade is
CONSISTENT with its matched sample when its yes_price is within one tick of that sample's k_ask (YES
taker) or k_bid (NO taker). An inconsistent trade shows the book had already moved, so the sample's wide
spread cannot be credited to it. Everything else is L152's arithmetic, imported, not re-derived.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("l152_measure", HERE / "measure.py")
m = importlib.util.module_from_spec(_spec)
sys.modules["l152_measure"] = m
_spec.loader.exec_module(m)

TIGHT_WINDOW_S = 10.0
CACHE = Path("/private/tmp/claude-501/-Users-bernardodelrio-Code-Janus/"
             "76d06160-ea8a-4767-935a-b9776800a018/scratchpad/l152_trades")


def consistent(trade: dict, k_bid: float, k_ask: float) -> bool:
    """The trade printed at the touch the sample showed, within one tick."""
    side = trade.get("taker_side")
    if side == "yes":
        return abs(trade["yes_price"] - k_ask) <= m.TICK + 1e-9
    if side == "no":
        return abs(trade["yes_price"] - k_bid) <= m.TICK + 1e-9
    return False


def run(samples: dict, trades: dict) -> dict:
    all_ts = [r[0] for rows in samples.values() for r in rows]
    t0, t1 = min(all_ts), max(all_ts)
    days = (t1 - t0) / 86400.0
    agg = {th: defaultdict(float) for th in m.THRESHOLDS}
    for ticker, rows in samples.items():
        times = [r[0] for r in rows]
        start = m.game_start_utc(ticker)
        for tr in trades.get(ticker, []):
            if not (t0 <= tr["ts"] <= t1):
                continue
            i = m.latest_before(times, tr["ts"])
            if i is None:
                continue
            ts, kb, ka, pb, pa, age = rows[i]
            if m.bucket(age) is None:
                continue
            in_play = start is not None and tr["ts"] >= start
            for th in m.THRESHOLDS:
                e = m.quote_edge(kb, ka, pb, pa, th)
                if e is None:
                    continue
                c = tr["count"]
                a = agg[th]
                a["all_contracts"] += c
                a["all_usd"] += e * c
                if consistent(tr, kb, ka):
                    a["consistent_contracts"] += c
                    a["consistent_usd"] += e * c
                    if tr["ts"] - ts <= TIGHT_WINDOW_S:
                        a["tight_contracts"] += c
                        a["tight_usd"] += e * c
                    if not in_play:
                        a["pregame_consistent_usd"] += e * c
                if not in_play:
                    a["pregame_usd"] += e * c

    out = {"schema": "janus.l153.l152_robustness.v1", "days": round(days, 3), "by_threshold": {}}
    best_consistent_25 = 0.0
    for th in m.THRESHOLDS:
        a = agg[th]
        per_day = lambda usd, share: round(usd * share / days, 4)
        consistent_25 = per_day(a["consistent_usd"], 0.25)
        best_consistent_25 = max(best_consistent_25, consistent_25)
        out["by_threshold"][f"{int(th * 100)}c"] = {
            "capturable_contracts_L152": round(a["all_contracts"], 2),
            "consistent_contracts": round(a["consistent_contracts"], 2),
            "consistent_share": round(a["consistent_contracts"] / a["all_contracts"], 4) if a["all_contracts"] else None,
            "CEILING_usd_per_day_L152_at_25pct": per_day(a["all_usd"], 0.25),
            "CEILING_usd_per_day_consistent": {f"{int(s * 100)}%": per_day(a["consistent_usd"], s) for s in m.CAPTURE_SHARES},
            "CEILING_usd_per_day_consistent_within_10s": {f"{int(s * 100)}%": per_day(a["tight_usd"], s) for s in m.CAPTURE_SHARES},
            "CEILING_usd_per_day_pregame_only_at_100pct": per_day(a["pregame_usd"], 1.0),
            "CEILING_usd_per_day_pregame_consistent_at_100pct": per_day(a["pregame_consistent_usd"], 1.0),
        }
    if best_consistent_25 >= 50.0:
        name = "SURVIVES"
    elif best_consistent_25 >= 15.0:
        name = "WEAKENED"
    else:
        name = "ARTIFACT"
    out["verdict"] = name
    out["verdict_reason"] = (f"best consistent CEILING at 25 % capture is {best_consistent_25:.2f} USD/day "
                             "(registered bars: >= 50 SURVIVES, 15-50 WEAKENED, < 15 ARTIFACT)")
    return out


def main() -> int:
    samples = m.load_samples()
    trades = {t: m.fetch_trades(t, CACHE, offline=True) for t in samples}
    result = run(samples, trades)
    text = json.dumps(result, indent=2, sort_keys=True)
    (HERE / "results_L153_20260918.json").write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
