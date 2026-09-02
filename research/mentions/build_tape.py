#!/usr/bin/env python3
"""Crawl Kalshi trade tapes for settled mention markets -> a price->outcome dataset.

    python3 research/mentions/build_tape.py --limit 20000

WHY THIS IS NEEDED. Kalshi's settled-market API gives the OUTCOME but no usable entry price:
`last_price_dollars` is the final print *after* the result was known (a YES market last trades at
0.99), and `previous_*` fields come back 0.0000. Without a pre-resolution price nothing about
calibration or EV is testable. The trade tape (`/markets/trades?ticker=`) carries real timestamped
prints and is cursor-paginated, so entry prices can be reconstructed at any point before close.

TWO LEAKS THIS FILE IS BUILT TO AVOID — mention markets close EARLY the moment the word is said
(`early_close_condition`), so:

  1. `close_time` LEAKS THE OUTCOME. A market whose close_time is well before its
     `expected_expiration_time` resolved YES, by construction. close_time must never be a feature,
     and any "time to close" computed from it is contaminated.
  2. LATE PRINTS LEAK. Trades near close are made by people who already heard the word. Features
     are therefore taken at a fixed offset from market OPEN, never relative to close, and every
     record carries how much of the tape preceded it so contamination is auditable.

Resumable: markets already present in the output are skipped, so this can be killed and restarted.
Characterization era only — the holdout guard in lib/mentions_data.py is respected by construction
because that is the only era loaded here.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib.fetch import Client  # noqa: E402
from lib import mentions_data as md  # noqa: E402

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
OUT = md.DATA / "kalshi_tape.jsonl"

#: Seconds after market OPEN at which to sample the tape. Anchored to open, never to close,
#: because close is contaminated (see module docstring).
OFFSETS = [0, 300, 900, 1800, 3600, 7200, 21600]


def iso_ts(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


#: How far past OPEN to pull the tape. Must exceed max(OFFSETS) so every sample point is covered.
WINDOW_S = 24 * 3600


def fetch_tape(c: Client, ticker: str, open_ts: float | None, max_pages: int = 4) -> list[dict]:
    """Pull the tape near market OPEN using the endpoint's `min_ts`/`max_ts` filters.

    The naive version paged the whole tape, because trades come back NEWEST-FIRST and the first
    print is therefore last. On mention markets that is 4,000-6,000 trades / 6+ requests each, and
    measured at ~16 markets/min it would have taken ~16h for the corpus. A bounded window returns
    the early trades directly in ~1 request.

    THE TRAP THIS AVOIDS: a full 1000-row page inside the window means the response was TRUNCATED
    from the newest end, so the true first trade is missing and `first_trade_price` would silently
    be wrong. When that happens we halve the window and retry, which walks back toward open until
    the page is not full. Falling back to "just use what we got" would corrupt the entry price on
    exactly the busiest markets.
    """
    if open_ts is None:
        return []
    lo = int(open_ts)
    span = WINDOW_S
    for _ in range(6):
        trades, cur, pages, truncated = [], None, 0, False
        while pages < max_pages:
            p = {"ticker": ticker, "limit": 1000, "min_ts": lo, "max_ts": lo + span}
            if cur:
                p["cursor"] = cur
            d = c.get_json(f"{KALSHI}/markets/trades", params=p)
            page = d.get("trades") or []
            trades.extend(page)
            pages += 1
            cur = d.get("cursor") or None
            if not cur or not page:
                break
            if pages >= max_pages and cur:
                truncated = True
        if not truncated:
            return trades
        span = max(300, span // 2)   # window still too busy -- walk back toward open
    return trades


def summarize_market(m: dict, trades: list[dict]) -> dict | None:
    open_ts = iso_ts(m.get("open_time"))
    close_ts = m.get("close_ts")
    if open_ts is None or not trades:
        return None
    pts = []
    for t in trades:
        ts = iso_ts(t.get("created_time"))
        try:
            px = float(t.get("yes_price_dollars"))
        except (TypeError, ValueError):
            continue
        if ts is not None:
            pts.append((ts, px))
    if not pts:
        return None
    pts.sort()
    t0 = pts[0][0]

    rec = {
        "ticker": m["ticker"], "series": m["series"], "term": m.get("term"),
        "outcome": m["outcome"],
        "open_time": m.get("open_time"), "close_time": m.get("close_time"),
        "open_ts": open_ts, "close_ts": close_ts,
        # duration is DERIVED FROM CLOSE and therefore leaky -- kept for auditing, never a feature
        "leaky_duration_s": (close_ts - open_ts) if close_ts else None,
        "closed_early": (bool(close_ts and iso_ts(m.get("expected_expiration_time"))
                              and close_ts < iso_ts(m.get("expected_expiration_time")) - 60)
                         if m.get("expected_expiration_time") else None),
        "n_trades": len(pts),
        "first_trade_price": pts[0][1],
        "first_trade_lag_s": round(t0 - open_ts, 1),
        "volume": m.get("volume"),
    }
    # price at fixed offsets from OPEN (last print at or before the offset)
    for off in OFFSETS:
        target = open_ts + off
        px = None
        n_before = 0
        for ts, p in pts:
            if ts <= target:
                px = p
                n_before += 1
            else:
                break
        rec[f"px_{off}s"] = px
        rec[f"ntrades_by_{off}s"] = n_before
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20000)
    ap.add_argument("--min-volume", type=float, default=1.0)
    a = ap.parse_args()

    rows = md.load("kalshi")  # characterization era ONLY
    rows = [r for r in rows if r.get("outcome") is not None
            and (r.get("volume") or 0) >= a.min_volume]
    rows.sort(key=lambda r: -(r.get("volume") or 0))
    rows = rows[:a.limit]

    done = set()
    if OUT.exists():
        with OUT.open() as f:
            for line in f:
                try:
                    done.add(json.loads(line)["ticker"])
                except (ValueError, KeyError):
                    pass
    todo = [r for r in rows if r["ticker"] not in done]
    print(f"settled mention markets: {len(rows)}  already taped: {len(done)}  todo: {len(todo)}")

    c = Client("kalshi-tape", rate=8.0, burst=12.0, cache_dir=None)
    n_ok = n_empty = 0
    with OUT.open("a") as f:
        for i, m in enumerate(todo, 1):
            try:
                tr = fetch_tape(c, m["ticker"], iso_ts(m.get("open_time")))
                rec = summarize_market(m, tr)
                if rec:
                    f.write(json.dumps(rec) + "\n")
                    n_ok += 1
                else:
                    n_empty += 1
            except Exception as e:  # noqa: BLE001
                print(f"  ! {m['ticker']}: {type(e).__name__}: {str(e)[:60]}")
            if i % 250 == 0:
                f.flush()
                print(f"  {i}/{len(todo)}  ok={n_ok} empty={n_empty}  {c.stats}")
    print(f"done: ok={n_ok} empty={n_empty}  wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
