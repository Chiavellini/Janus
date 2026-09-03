#!/usr/bin/env python3
"""Settlement results from each venue, as that venue states them. Fetch is thin; parse is pure.

Kalshi: GET /markets/{ticker} carries `result` ("yes" | "no" | "" while open) and `status`
("settled" when final). Polymarket: the Gamma market carries `closed`, `umaResolutionStatuses`
and `outcomePrices` (["1","0"] once resolved) beside `outcomes`. Each venue's own result is what
its leg pays on -- which is exactly why `reconcile.settle` takes them per venue.
"""

from __future__ import annotations

import json

from kernel.fetch import Client

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
PM_GAMMA = "https://gamma-api.polymarket.com"


def kalshi_result(market: dict) -> str | None:
    """The winning outcome_id in this project's terms for a Kalshi game market, or None while open.
    A market's `result` is yes/no on ITS OWN ticker; the winner of the game is the ticker whose
    result is yes. The caller maps ticker -> outcome_id; this returns 'yes' | 'no' | None."""
    m = market.get("market", market)
    if str(m.get("status", "")).lower() not in ("settled", "finalized", "determined"):
        return None
    r = str(m.get("result", "")).lower()
    return r if r in ("yes", "no") else None


def polymarket_result(market: dict) -> str | None:
    """The winning outcome label of a Gamma market once resolved, else None."""
    if not market.get("closed"):
        return None
    outs, prices = market.get("outcomes"), market.get("outcomePrices")
    if isinstance(outs, str):
        outs = json.loads(outs)
    if isinstance(prices, str):
        prices = json.loads(prices)
    if not outs or not prices or len(outs) != len(prices):
        return None
    winners = [o for o, p in zip(outs, prices) if float(p) >= 0.999]
    return winners[0] if len(winners) == 1 else None


def fetch_kalshi_market(ticker: str, cl: Client) -> dict:
    return cl.get_json(f"{KALSHI_BASE}/markets/{ticker}", use_cache=False)


def fetch_pm_market(slug: str, cl: Client) -> dict | None:
    ev = cl.get_json(f"{PM_GAMMA}/events", params={"slug": slug}, use_cache=False)
    ev = ev[0] if isinstance(ev, list) and ev else None
    if not ev:
        return None
    return next((m for m in ev.get("markets") or [] if m.get("slug") == slug), None)


def winners_for_pair(*, kalshi_markets: dict[str, dict], pm_market: dict | None,
                     kalshi_outcomes: dict[str, str], pm_outcomes: dict[str, str]) -> dict[str, str]:
    """venue -> winning outcome_id, only for venues that have settled.
    `kalshi_markets`: ticker -> market dict; `kalshi_outcomes`: ticker -> outcome_id;
    `pm_outcomes`: Gamma outcome label -> outcome_id (token id)."""
    out: dict[str, str] = {}
    yes = [t for t, m in kalshi_markets.items() if kalshi_result(m) == "yes"]
    settled = [t for t, m in kalshi_markets.items() if kalshi_result(m) is not None]
    if len(yes) == 1 and len(settled) == len(kalshi_markets):
        out["kalshi"] = kalshi_outcomes[yes[0]]
    if pm_market is not None:
        w = polymarket_result(pm_market)
        if w is not None and w in pm_outcomes:
            out["polymarket"] = pm_outcomes[w]
    return out
