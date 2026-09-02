#!/usr/bin/env python3
"""Enumerate the real Polymarket catalog: events, markets, rules text, quotes.

    python3 catalog/enumerate_pm.py --out-dir data/catalog

WHY THIS IS NOT A SIMPLE OFFSET WALK — measured 2026-07-24. Gamma's `/events` endpoint returns
**HTTP 422 past offset ~2100**, and ordering by id biases toward newly-created markets. A naive
`closed=false&order=id&ascending=false` crawl returned 2,078 events and made Polymarket look like a
table-tennis venue with **15 political events**. Tag-based enumeration on the same day showed the
truth:

    elections   100+ events   $206M liquidity
    politics    100+ events   $202M liquidity
    sports      100+ events   $50M
    geopolitics 100+ events   $13M

The first crawl was not "incomplete", it was **actively misleading** — it would have killed the
project on a false corpus reading. So this crawler enumerates through THREE independent channels
and unions them:

  1. per-TAG pagination (the Kilos `collect_equity.py` pattern) — reaches the deep liquid book
  2. global offset pagination until OffsetCap — catches untagged/new markets
  3. date-window slicing on close date — the Kilos `build_gap_windows.py` workaround, which resets
     the offset counter per window and so reaches past the cap

Union-by-id, then report per-channel contribution so a channel silently dying is visible rather
than quietly shrinking the catalog.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.fetch import Client, OffsetCap  # noqa: E402

GAMMA = "https://gamma-api.polymarket.com"

#: Tags worth crawling, widest-first. Discovered from /tags plus the categories Kalshi is deep in.
TAGS = [
    "politics", "elections", "economics", "fed", "geopolitics", "sports", "crypto",
    "world", "us-politics", "trump", "business", "tech", "science", "pop-culture",
    "middle-east", "russia-ukraine", "china", "inflation", "courts", "congress",
    "nba", "nfl", "mlb", "soccer", "tennis", "epl", "champions-league",
]


def parse_json_field(v):
    """gamma returns `outcomes` / `clobTokenIds` as JSON-encoded STRINGS, not arrays."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return None
    return v


def iso_ts(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def crawl_tags(c: Client, tags=TAGS) -> tuple[dict, dict]:
    seen, per_tag = {}, {}
    for tag in tags:
        n0 = len(seen)
        try:
            for page in c.paginate_offset(f"{GAMMA}/events",
                                          {"closed": "false", "tag_slug": tag}, limit=100):
                for e in page:
                    seen[e["id"]] = e
        except OffsetCap:
            pass
        per_tag[tag] = len(seen) - n0
    return seen, per_tag


#: Global orderings to sweep. Each walks to gamma's ~2100 offset cap, so they overlap heavily and
#: cost ~21 requests apiece. Two complementary orderings (newest-created, soonest-resolving) reach
#: the distinct ends of the book; adding startDate/ascending variants measured as almost pure
#: duplication for ~4x the crawl time. The tag and date-window channels cover the middle.
GLOBAL_ORDERS = [("id", "false"), ("endDate", "true")]


def crawl_global(c: Client) -> dict:
    seen = {}
    for order, asc in GLOBAL_ORDERS:
        try:
            for page in c.paginate_offset(
                    f"{GAMMA}/events",
                    {"closed": "false", "order": order, "ascending": asc}, limit=100):
                for e in page:
                    seen[e["id"]] = e
        except OffsetCap:
            continue
    return seen


def crawl_date_windows(c: Client, days_ahead: int = 60, step_days: int = 3) -> dict:
    """Slice by close date so each window's offset counter starts fresh (beats the cap)."""
    seen = {}
    today = dt.datetime.now(dt.UTC).date()
    d = today
    while d < today + dt.timedelta(days=days_ahead):
        lo, hi = d, d + dt.timedelta(days=step_days)
        try:
            for page in c.paginate_offset(
                    f"{GAMMA}/events",
                    {"closed": "false", "end_date_min": lo.isoformat(),
                     "end_date_max": hi.isoformat()}, limit=100):
                for e in page:
                    seen[e["id"]] = e
        except OffsetCap:
            pass
        d = hi
    return seen


def flatten(events: dict, now: float) -> list[dict]:
    rows = []
    for e in events.values():
        tags = [t.get("slug") for t in (e.get("tags") or []) if isinstance(t, dict)]
        for m in (e.get("markets") or []):
            end_ts = iso_ts(m.get("endDateIso") or m.get("endDate"))
            outs = parse_json_field(m.get("outcomes"))
            toks = parse_json_field(m.get("clobTokenIds"))
            prices = parse_json_field(m.get("outcomePrices"))
            bb, ba = m.get("bestBid"), m.get("bestAsk")
            rows.append({
                "venue": "polymarket",
                "event_slug": e.get("slug"),
                "event_title": e.get("title"),
                "condition_id": m.get("conditionId"),
                "gamma_id": m.get("id"),
                "slug": m.get("slug"),
                "question": m.get("question"),
                # rules text — the input to the equivalence verifier
                "description": m.get("description"),
                "resolution_source": m.get("resolutionSource"),
                "tags": tags,
                # structure
                "outcomes": outs,
                "clob_token_ids": toks,
                "outcome_prices": prices,
                "neg_risk": m.get("negRisk"),
                "tick_size": m.get("orderPriceMinTickSize"),
                "min_order_size": m.get("orderMinSize"),
                "fee_schedule": m.get("feeSchedule"),
                "accepting_orders": m.get("acceptingOrders"),
                "enable_order_book": m.get("enableOrderBook"),
                # timing
                "end_date": m.get("endDateIso") or m.get("endDate"),
                "end_ts": end_ts,
                "days_to_close": ((end_ts - now) / 86400.0) if end_ts else None,
                # pricing
                "best_bid": bb, "best_ask": ba,
                "spread": (ba - bb) if (bb is not None and ba is not None) else None,
                "two_sided": bool(bb and ba and 0 < bb < ba < 1.0),
                "liquidity": m.get("liquidityNum"),
                "volume": m.get("volumeNum"),
            })
    return rows


def summarize(rows, horizon_days: float) -> dict:
    short = [r for r in rows if r["days_to_close"] is not None and 0 <= r["days_to_close"] <= horizon_days]
    trad = [r for r in short if r["two_sided"] and r.get("accepting_orders")]
    def liq(rs):
        return round(sum((r["liquidity"] or 0) for r in rs))
    tagc = Counter()
    for r in short:
        for t in (r["tags"] or []):
            tagc[t] += 1
    return {
        "n_markets": len(rows),
        "n_short_dated": len(short),
        "n_short_dated_tradeable": len(trad),
        "horizon_days": horizon_days,
        "liquidity_all": liq(rows),
        "liquidity_short_dated": liq(short),
        "liquidity_short_tradeable": liq(trad),
        "top_tags_short_dated": dict(tagc.most_common(30)),
        "fee_schedules_seen": dict(Counter(
            json.dumps(r["fee_schedule"], sort_keys=True) for r in rows).most_common(5)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="data/catalog")
    ap.add_argument("--horizon-days", type=float, default=30.0)
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    c = Client("polymarket", rate=5.0, burst=8.0,
               cache_dir=None if a.no_cache else out / "_cache_pm")
    now = dt.datetime.now(dt.UTC).timestamp()

    print("channel 1/3: per-tag pagination...")
    ev, per_tag = crawl_tags(c)
    print(f"  {len(ev)} events; top tags: "
          f"{sorted(per_tag.items(), key=lambda x: -x[1])[:6]}")

    print("channel 2/3: global offset pagination (to the cap)...")
    g = crawl_global(c)
    new_g = len(set(g) - set(ev))
    ev.update(g)
    print(f"  +{new_g} new  (total {len(ev)})")

    print("channel 3/3: date-window slicing...")
    d = crawl_date_windows(c)
    new_d = len(set(d) - set(ev))
    ev.update(d)
    print(f"  +{new_d} new  (total {len(ev)})")

    rows = flatten(ev, now)
    summ = summarize(rows, a.horizon_days)
    summ["channel_contribution"] = {"tags": per_tag, "global_new": new_g, "date_windows_new": new_d}

    (out / "pm_markets.json").write_text(json.dumps(rows))
    (out / "pm_summary.json").write_text(json.dumps(summ, indent=1))

    print(f"\nevents {len(ev)}  markets {len(rows)}")
    print(f"short-dated (<={a.horizon_days:g}d): {summ['n_short_dated']}  "
          f"tradeable: {summ['n_short_dated_tradeable']}  "
          f"liquidity ${summ['liquidity_short_tradeable']:,}")
    print("\ntop tags among short-dated:")
    for k, v in list(summ["top_tags_short_dated"].items())[:15]:
        print(f"  {v:5d}  {k}")
    print(f"\nhttp stats: {c.stats}")
    print(f"wrote {out}/pm_markets.json (+summary)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
