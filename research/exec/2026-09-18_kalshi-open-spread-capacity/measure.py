#!/usr/bin/env python3
"""L152: the MOST a maker quoting inside Kalshi's sports spreads could earn. READ-ONLY, free.

    python3 measure.py                 # uses the cached Kalshi trades, fetching any that are missing
    python3 measure.py --offline       # refuses to touch the network

Inputs, all read-only:
  * /Volumes/Kilos/janus/convergence/track.sqlite  -- paired Kalshi/Polymarket snapshots, timed from
    Kalshi's open (`age_s`), ~69 s apart. MLB only, 2026-08-21..27.
  * /Volumes/Kilos/janus/shadow/kalshi_open.sqlite -- the snapshot AT Kalshi's open.
  * Kalshi's PUBLIC trade history (GET /trade-api/v2/markets/trades, no account), cached as gzipped
    JSON lines under the scratch cache so the run reproduces offline.

Every dollar figure this produces is a CEILING: zero adverse selection, no queue competition, both
sides filling, the Polymarket mid taken as fair value, Kalshi's per-order fee rounding ignored, and a
side quoted only where it would clear its own maker fee. The spec (spec.yaml) fixes all of it.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import statistics
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
from nodes.fees.models import KalshiQuadratic  # noqa: E402 -- the project's own pin, not a re-derivation

TRACK ="/Volumes/Kilos/janus/convergence/track.sqlite"
OPEN_DB = "/Volumes/Kilos/janus/shadow/kalshi_open.sqlite"
API = "https://api.elections.kalshi.com/trade-api/v2/markets/trades"
SCHEMA = "janus.l152.kalshi_open_spread_capacity.v1"

THRESHOLDS = (0.06, 0.10)                 # spec: quotable at a Kalshi spread of >= 6c and >= 10c
CAPTURE_SHARES = (0.10, 0.25, 0.50)
MATCH_WINDOW_S = 120.0                    # spec: a trade matches the latest sample within 120 s before it
TICK = 0.01
TARGET_USD_PER_DAY = 50.0
BUCKETS = ((0, 300, "0-5 min"), (300, 1800, "5-30 min"), (1800, 7200, "30 min-2 h"),
           (7200, 21600, "2-6 h"), (21600, 86400, "6-24 h"), (86400, float("inf"), ">24 h"))
MONTHS = {m: i + 1 for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                                          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"))}


# ── pure pieces (tested) ─────────────────────────────────────────────────────────────────────────
def kalshi_maker_fee(p: float) -> float:
    """Kalshi's maker fee per contract: `KalshiQuadratic.maker_coeff * p * (1 - p)`. For KXMLBGAME
    (`quadratic_with_maker_fees`) the repo pins the maker side at the UNSCALED 0.0175 because no maker
    fill has been observed (nodes/fees/models.py:137-146) -- the conservative choice, kept here."""
    return KalshiQuadratic.maker_coeff * p * (1.0 - p)


def quote_edge(k_bid: float, k_ask: float, pm_bid: float, pm_ask: float, threshold: float) -> float | None:
    """Edge per filled contract for a two-sided quote around the Polymarket mid, one tick inside
    Kalshi's nearer touch, net of the maker fee -- or None when the sample is not quotable.

    Quotable (spec): Kalshi spread >= threshold AND the Polymarket mid strictly inside Kalshi's bid-ask.
    A side that would not clear its own maker fee is not quoted, so the edge is floored at zero -- the
    optimistic direction, as a ceiling must be."""
    if None in (k_bid, k_ask, pm_bid, pm_ask) or k_ask <= k_bid:
        return None
    mid = (pm_bid + pm_ask) / 2.0
    if (k_ask - k_bid) + 1e-9 < threshold or not (k_bid < mid < k_ask):
        return None
    h = max(0.0, min(mid - k_bid, k_ask - mid) - TICK)
    return max(0.0, h - kalshi_maker_fee(mid))


def bucket(age_s: float | None) -> str | None:
    if age_s is None:
        return None
    for lo, hi, name in BUCKETS:
        if lo <= age_s < hi:
            return name
    return None


def game_start_utc(ticker: str) -> float | None:
    """KXMLBGAME-26AUG231910ATLMIL-MIL -> 2026-08-23 19:10 US/Eastern. August is EDT (UTC-4)."""
    try:
        code = ticker.split("-")[1]
        yy, mon, dd, hh, mm = int(code[0:2]), MONTHS[code[2:5]], int(code[5:7]), int(code[7:9]), int(code[9:11])
    except (IndexError, KeyError, ValueError):
        return None
    local = datetime(2000 + yy, mon, dd, hh, mm, tzinfo=timezone(timedelta(hours=-4)))
    return local.timestamp()


def latest_before(times: list[float], t: float) -> int | None:
    """Index of the last sample time <= t within MATCH_WINDOW_S, by binary search."""
    lo, hi = 0, len(times)
    while lo < hi:
        m = (lo + hi) // 2
        if times[m] <= t:
            lo = m + 1
        else:
            hi = m
    i = lo - 1
    if i < 0 or t - times[i] > MATCH_WINDOW_S:
        return None
    return i


def verdict(ceiling: dict, contracts_per_day: float) -> tuple[str, str]:
    """The registered rule. `ceiling[(threshold, share)]` is USD/day.

    STRONG if either threshold reaches $50/day at 25 %; DEAD if neither reaches $15/day even at 50 %,
    or fewer than 100 contracts a day trade while quotable; WEAK otherwise (between the two)."""
    best25 = max(ceiling[(t, 0.25)] for t in THRESHOLDS)
    best50 = max(ceiling[(t, 0.50)] for t in THRESHOLDS)
    if contracts_per_day < 100.0:
        return "DEAD", f"only {contracts_per_day:.0f} contracts/day trade while quotable (< 100)"
    if best25 >= TARGET_USD_PER_DAY:
        return "STRONG_LEAD", f"CEILING {best25:.2f} USD/day at 25 % capture reaches $50"
    if best50 < 15.0:
        return "DEAD", f"CEILING {best50:.2f} USD/day even at 50 % capture is under $15"
    return "WEAK_LEAD", f"CEILING {best25:.2f} USD/day at 25 % capture: between $15 and $50"


# ── data ─────────────────────────────────────────────────────────────────────────────────────────
def load_samples(db: str = TRACK) -> dict[str, list[tuple]]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT kalshi_ticker, sample_ts, k_bid, k_ask, pm_bid, pm_ask, age_s "
                           "FROM samples WHERE kalshi_ticker IS NOT NULL ORDER BY kalshi_ticker, sample_ts")
        out: dict[str, list[tuple]] = defaultdict(list)
        for r in rows:
            out[r[0]].append(r[1:])
        return out
    finally:
        con.close()


def load_open_snapshots(db: str = OPEN_DB) -> list[dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cols = ("kalshi_ticker", "lag_s", "k_bid", "k_ask", "pm_bid", "pm_ask")
        return [dict(zip(cols, r)) for r in con.execute(
            "SELECT kalshi_ticker, lag_s, k_bid, k_ask, pm_bid, pm_ask FROM decisions")]
    finally:
        con.close()


def fetch_trades(ticker: str, cache: Path, *, offline: bool) -> list[dict]:
    """Every public trade for one ticker, cached. Kalshi's public market data needs no account."""
    path = cache / f"{ticker}.jsonl.gz"
    if path.exists():
        with gzip.open(path, "rt") as fh:
            return [json.loads(line) for line in fh]
    if offline:
        raise SystemExit(f"--offline and no cached trades for {ticker}")
    trades, cursor = [], ""
    while True:
        url = f"{API}?ticker={ticker}&limit=1000" + (f"&cursor={cursor}" if cursor else "")
        with urllib.request.urlopen(url, timeout=30) as resp:
            page = json.loads(resp.read())
        for t in page.get("trades") or []:
            trades.append({"ts": datetime.fromisoformat(t["created_time"].replace("Z", "+00:00")).timestamp(),
                           "count": float(t.get("count_fp") or t.get("count") or 0.0),
                           "yes_price": float(t.get("yes_price_dollars") or 0.0),
                           "taker_side": t.get("taker_side")})
        cursor = page.get("cursor") or ""
        time.sleep(0.25)                                  # gentle on a public endpoint
        if not cursor:
            break
    cache.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt") as fh:
        for t in trades:
            fh.write(json.dumps(t) + "\n")
    tmp.replace(path)
    return trades


# ── the measurement ──────────────────────────────────────────────────────────────────────────────
def summarise(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    s = sorted(xs)
    q = lambda p: s[min(len(s) - 1, int(p * (len(s) - 1)))]
    return {"n": len(s), "median": round(statistics.median(s), 4), "p25": round(q(0.25), 4),
            "p75": round(q(0.75), 4)}


def measure(samples: dict[str, list[tuple]], trades: dict[str, list[dict]], opens: list[dict]) -> dict:
    all_ts = [row[0] for rows in samples.values() for row in rows]
    t0, t1 = min(all_ts), max(all_ts)
    days = (t1 - t0) / 86400.0

    spreads = defaultdict(list)
    errors = defaultdict(list)
    quotable_samples = defaultdict(lambda: defaultdict(int))
    samples_per_bucket = defaultdict(int)
    for rows in samples.values():
        for ts, kb, ka, pb, pa, age in rows:
            b = bucket(age)
            if b is None or None in (kb, ka, pb, pa):
                continue
            samples_per_bucket[b] += 1
            spreads[b].append(ka - kb)
            errors[b].append(((kb + ka) / 2.0) - ((pb + pa) / 2.0))
            for th in THRESHOLDS:
                if quote_edge(kb, ka, pb, pa, th) is not None:
                    quotable_samples[b][th] += 1

    # trades while quotable
    cap_contracts = {th: defaultdict(float) for th in THRESHOLDS}
    cap_edge_usd = {th: defaultdict(float) for th in THRESHOLDS}
    phase_edge_usd = {th: {"pre-game": 0.0, "in-play": 0.0} for th in THRESHOLDS}
    phase_contracts = {th: {"pre-game": 0.0, "in-play": 0.0} for th in THRESHOLDS}
    edges_used = {th: [] for th in THRESHOLDS}
    trades_total = trades_in_window = 0
    contracts_total = 0.0
    for ticker, rows in samples.items():
        times = [r[0] for r in rows]
        start = game_start_utc(ticker)
        for tr in trades.get(ticker, []):
            if not (t0 <= tr["ts"] <= t1):
                continue
            trades_total += 1
            contracts_total += tr["count"]
            i = latest_before(times, tr["ts"])
            if i is None:
                continue
            trades_in_window += 1
            ts, kb, ka, pb, pa, age = rows[i]
            b = bucket(age)
            if b is None:
                continue
            phase = "in-play" if (start is not None and tr["ts"] >= start) else "pre-game"
            for th in THRESHOLDS:
                e = quote_edge(kb, ka, pb, pa, th)
                if e is None:
                    continue
                cap_contracts[th][b] += tr["count"]
                cap_edge_usd[th][b] += e * tr["count"]
                phase_contracts[th][phase] += tr["count"]
                phase_edge_usd[th][phase] += e * tr["count"]
                edges_used[th].append(e)

    ceiling = {}
    for th in THRESHOLDS:
        total = sum(cap_edge_usd[th].values())
        for share in CAPTURE_SHARES:
            ceiling[(th, share)] = round(total * share / days, 4)

    contracts_per_day = {th: round(sum(cap_contracts[th].values()) / days, 2) for th in THRESHOLDS}
    required = {}
    for th in THRESHOLDS:
        e = [x for x in edges_used[th] if x > 0]
        required[th] = round(TARGET_USD_PER_DAY / statistics.mean(e), 0) if e else None

    name, why = verdict(ceiling, max(contracts_per_day.values()))
    bucket_names = [n for _, _, n in BUCKETS]
    return {
        "schema": SCHEMA,
        "coverage": {"first_utc": datetime.fromtimestamp(t0, timezone.utc).isoformat(),
                     "last_utc": datetime.fromtimestamp(t1, timezone.utc).isoformat(),
                     "days": round(days, 3), "kalshi_markets": len(samples),
                     "league": "MLB (KXMLBGAME) only", "sample_cadence_s": "~69 (cycles)",
                     "kalshi_trades_in_period": trades_total,
                     "kalshi_contracts_in_period": round(contracts_total, 2),
                     "trades_matched_to_a_sample_within_120s": trades_in_window},
        "at_open": {"n": len(opens),
                    "kalshi_spread": summarise([o["k_ask"] - o["k_bid"] for o in opens
                                                if o["k_ask"] is not None and o["k_bid"] is not None]),
                    "polymarket_spread": summarise([o["pm_ask"] - o["pm_bid"] for o in opens
                                                    if o["pm_ask"] is not None and o["pm_bid"] is not None]),
                    "lag_s": summarise([o["lag_s"] for o in opens if o["lag_s"] is not None])},
        "by_age_since_open": {
            b: {"samples": samples_per_bucket[b],
                "kalshi_spread": summarise(spreads[b]),
                "share_spread_ge_6c": round(sum(1 for x in spreads[b] if x >= 0.06 - 1e-9) / len(spreads[b]), 4) if spreads[b] else None,
                "share_spread_ge_10c": round(sum(1 for x in spreads[b] if x >= 0.10 - 1e-9) / len(spreads[b]), 4) if spreads[b] else None,
                "kalshi_mid_minus_pm_mid": summarise(errors[b]),
                "share_quotable": {f"{int(th*100)}c": round(quotable_samples[b][th] / samples_per_bucket[b], 4)
                                   if samples_per_bucket[b] else None for th in THRESHOLDS},
                "contracts_traded_while_quotable": {f"{int(th*100)}c": round(cap_contracts[th][b], 2)
                                                    for th in THRESHOLDS},
                "ceiling_edge_usd_at_100pct": {f"{int(th*100)}c": round(cap_edge_usd[th][b], 4)
                                               for th in THRESHOLDS}}
            for b in bucket_names},
        "contracts_per_day_traded_while_quotable": {f"{int(th*100)}c": v for th, v in contracts_per_day.items()},
        "CEILING_usd_per_day": {f"{int(th*100)}c@{int(s*100)}%": v for (th, s), v in ceiling.items()},
        "supplementary_by_phase": {
            f"{int(th*100)}c": {ph: {"contracts": round(phase_contracts[th][ph], 2),
                                     "CEILING_usd_per_day_at_100pct": round(phase_edge_usd[th][ph] / days, 4)}
                                for ph in ("pre-game", "in-play")}
            for th in THRESHOLDS},
        "required_filled_contracts_per_day_for_50usd": {f"{int(th*100)}c": v for th, v in required.items()},
        "verdict": name,
        "verdict_reason": why,
        "caveats": [
            "EVERY dollar figure is a CEILING: zero adverse selection, no queue competition, both sides "
            "filling, the Polymarket mid as fair value, fee rounding ignored.",
            "Capturable volume is Kalshi flow that traded while a quote WOULD have improved the touch; "
            "it does not show anyone would have traded against OUR quote.",
            "MLB only, 2026-08-21..27; nothing here generalises to other leagues or seasons.",
            "Samples begin ~4 minutes after Kalshi's open; the very first minutes are seen only through "
            "kalshi_open.sqlite's open snapshots.",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--cache", type=Path,
                    default=Path("/private/tmp/claude-501/-Users-bernardodelrio-Code-Janus/"
                                 "76d06160-ea8a-4767-935a-b9776800a018/scratchpad/l152_trades"))
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    samples = load_samples()
    trades = {}
    for n, ticker in enumerate(sorted(samples), 1):
        trades[ticker] = fetch_trades(ticker, a.cache, offline=a.offline)
        if n % 25 == 0:
            print(f"  trades fetched for {n}/{len(samples)} markets", file=sys.stderr)
    result = measure(samples, trades, load_open_snapshots())
    text = json.dumps(result, indent=2, sort_keys=True)
    if a.out:
        a.out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
