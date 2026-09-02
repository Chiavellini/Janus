#!/usr/bin/env python3
"""Enumerate the real Kalshi catalog: events, markets, rules text, and per-series fees.

    python3 catalog/enumerate_kalshi.py --out-dir data/catalog

WHY NOT /markets — measured 2026-07-24: `GET /markets?status=open` returned 40,000 rows that were
**99.8% parlay combinations** (`KXMVE*` multivariate baskets). Only 79 were real markets and none
had volume. The parlays swamp cursor pagination, so that endpoint cannot enumerate the tradeable
book at all. `GET /events?status=open&with_nested_markets=true` returns 8,478 events / 76,622
markets with **zero** parlays. Always enumerate by event.

FEES ARE NOT UNIFORM. Each series carries `fee_type` and `fee_multiplier`. Crypto is the 0.07
premium tier but S&P/NASDAQ series are 0.035, so a hardcoded 0.07 overstates cost by 2x on index
markets. This crawler pins the real per-series multiplier and Janus' cost model consumes it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.fetch import Client  # noqa: E402

BASE = "https://api.elections.kalshi.com/trade-api/v2"

#: Parlay/multivariate baskets. Not tradeable as a cross-venue pair — one leg would be a basket.
PARLAY_PREFIX = "KXMVE"


def f(v):
    """Kalshi's REST API now returns `*_dollars` STRING fields (it used to return integer cents).
    Kilos' code still expects cents; anything reading this API must convert explicitly."""
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_series(c: Client) -> dict:
    """{series_ticker: {category, fee_type, fee_multiplier, frequency, title, settlement_sources}}"""
    d = c.get_json(f"{BASE}/series", params={"limit": 1000})
    out = {}
    for s in d.get("series", []):
        out[s["ticker"]] = {
            "category": s.get("category"),
            "title": s.get("title"),
            "frequency": s.get("frequency"),
            "fee_type": s.get("fee_type"),
            "fee_multiplier": s.get("fee_multiplier"),
            "settlement_sources": [x.get("name") for x in (s.get("settlement_sources") or [])],
            "tags": s.get("tags"),
        }
    return out


def fetch_events(c: Client, status: str = "open", max_pages: int = 200) -> list[dict]:
    evs = []
    for page in c.paginate_cursor(
            f"{BASE}/events",
            {"status": status, "limit": 200, "with_nested_markets": "true"},
            key="events", max_pages=max_pages):
        evs.extend(page)
    return evs


def flatten(events: list[dict], series: dict, now: float) -> list[dict]:
    """One row per tradeable market, carrying event context, quotes, rules text and fee pins."""
    rows = []
    for e in events:
        st = e.get("series_ticker") or ""
        if st.startswith(PARLAY_PREFIX):
            continue
        s = series.get(st, {})
        for m in (e.get("markets") or []):
            close = m.get("close_time")
            try:
                close_ts = dt.datetime.fromisoformat(close.replace("Z", "+00:00")).timestamp()
            except (AttributeError, ValueError):
                close_ts = None
            yb, ya = f(m.get("yes_bid_dollars")), f(m.get("yes_ask_dollars"))
            rows.append({
                "venue": "kalshi",
                "series": st,
                "event_ticker": e.get("event_ticker"),
                "ticker": m.get("ticker"),
                "category": e.get("category") or s.get("category"),
                "title": m.get("title"),
                "yes_sub_title": m.get("yes_sub_title"),
                # `custom_strike` carries the STRUCTURED strike, e.g. {"Word": "UFC"} on mention
                # markets. yes_sub_title is null on whole families (all the earnings-call mention
                # series), so relying on it alone silently loses the term and any cross-venue
                # match on it returns zero pairs.
                "custom_strike": m.get("custom_strike"),
                "term": ((m.get("custom_strike") or {}).get("Word")
                         or m.get("yes_sub_title") or None),
                "event_title": e.get("title"),
                "sub_title": e.get("sub_title"),
                "mutually_exclusive": e.get("mutually_exclusive"),
                # rules text — the input to the equivalence verifier
                "rules_primary": m.get("rules_primary"),
                "rules_secondary": m.get("rules_secondary"),
                "settlement_sources": s.get("settlement_sources"),
                # structure
                "market_type": m.get("market_type"),
                "strike_type": m.get("strike_type"),
                "floor_strike": m.get("floor_strike"),
                "cap_strike": m.get("cap_strike"),
                # timing
                "open_time": m.get("open_time"),
                "close_time": close,
                "close_ts": close_ts,
                "days_to_close": ((close_ts - now) / 86400.0) if close_ts else None,
                # pricing
                "yes_bid": yb, "yes_ask": ya,
                "no_bid": f(m.get("no_bid_dollars")), "no_ask": f(m.get("no_ask_dollars")),
                "yes_bid_size": f(m.get("yes_bid_size_fp")),
                "yes_ask_size": f(m.get("yes_ask_size_fp")),
                "spread": (ya - yb) if (ya is not None and yb is not None) else None,
                "two_sided": bool(yb and ya and yb > 0 and ya < 1.0),
                "volume": f(m.get("volume_fp")),
                "open_interest": f(m.get("open_interest_fp")),
                "liquidity": f(m.get("liquidity_dollars")),
                # fee pins (NOT uniform across series)
                "fee_type": s.get("fee_type"),
                "fee_multiplier": s.get("fee_multiplier"),
                "series_frequency": s.get("frequency"),
            })
    return rows


def summarize(rows: list[dict], horizon_days: float) -> dict:
    short = [r for r in rows if r["days_to_close"] is not None and 0 <= r["days_to_close"] <= horizon_days]
    tradeable = [r for r in short if r["two_sided"]]
    return {
        "n_markets": len(rows),
        "n_short_dated": len(short),
        "n_short_dated_two_sided": len(tradeable),
        "horizon_days": horizon_days,
        "by_category_all": dict(Counter(r["category"] for r in rows).most_common()),
        "by_category_short_dated": dict(Counter(r["category"] for r in short).most_common()),
        "by_category_short_tradeable": dict(Counter(r["category"] for r in tradeable).most_common()),
        "fee_multipliers_seen": dict(Counter(
            f"{r['fee_type']}:{r['fee_multiplier']}" for r in rows).most_common()),
        "parlays_excluded": True,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="data/catalog")
    ap.add_argument("--horizon-days", type=float, default=30.0)
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    c = Client("kalshi", rate=6.0, burst=10.0,
               cache_dir=None if a.no_cache else out / "_cache_kalshi")
    now = dt.datetime.now(dt.UTC).timestamp()

    print("fetching series metadata (fee pins)...")
    series = fetch_series(c)
    print(f"  series: {len(series)}")

    print("fetching open events (nested markets)...")
    events = fetch_events(c)
    parlay = sum(1 for e in events if (e.get("series_ticker") or "").startswith(PARLAY_PREFIX))
    print(f"  events: {len(events)}  (parlay events: {parlay})")

    rows = flatten(events, series, now)
    print(f"  tradeable markets: {len(rows)}")

    summ = summarize(rows, a.horizon_days)
    (out / "kalshi_markets.json").write_text(json.dumps(rows))
    (out / "kalshi_series.json").write_text(json.dumps(series, indent=1))
    (out / "kalshi_summary.json").write_text(json.dumps(summ, indent=1))

    print(f"\nshort-dated (<={a.horizon_days:g}d): {summ['n_short_dated']}  "
          f"of which two-sided quoted: {summ['n_short_dated_two_sided']}")
    print("\nshort-dated tradeable by category:")
    for k, v in summ["by_category_short_tradeable"].items():
        print(f"  {v:6d}  {k}")
    print(f"\nfee tiers seen: {summ['fee_multipliers_seen']}")
    print(f"\nhttp stats: {c.stats}")
    print(f"wrote {out}/kalshi_markets.json (+series, +summary)")

    # invariant: the parlay endpoint problem must never silently return
    assert not any(r["series"].startswith(PARLAY_PREFIX) for r in rows), "parlay leaked into catalog"
    return 0


if __name__ == "__main__":
    sys.exit(main())
