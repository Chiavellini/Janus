#!/usr/bin/env python3
"""Settlement results from each venue, as that venue states them. Fetch is thin; parse is pure.

Kalshi: GET /markets/{ticker} carries `result` ("yes" | "no" | "" while open) and `status`
("settled" when final). Polymarket: the Gamma market carries `closed`, `umaResolutionStatuses`
and `outcomePrices` (["1","0"] once resolved) beside `outcomes`. Each venue's own result is what
its leg pays on -- which is exactly why `reconcile.settle` takes them per venue.
"""

from __future__ import annotations

import json
import math

from kernel.fetch import Client

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
PM_GAMMA = "https://gamma-api.polymarket.com"


def _unit(value) -> float | None:
    """Return a finite contract payout, rejecting malformed venue data."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) and 0.0 <= out <= 1.0 else None


def kalshi_payouts(market: dict) -> dict[str, float] | None:
    """The authoritative YES/NO payout for one finalized Kalshi ticker.

    Binary markets expose ``result``.  Cancelled/scalar markets expose the exact payout in
    ``settlement_value_dollars``; that value is the YES contract payout and the complementary NO
    payout is one minus it.  A final response without either representation is a BLOCK.
    """
    m = market.get("market", market)
    if str(m.get("status", "")).lower() not in ("settled", "finalized", "determined"):
        return None
    result = str(m.get("result", "")).lower()
    if result in ("yes", "no"):
        return {"yes": 1.0 if result == "yes" else 0.0,
                "no": 0.0 if result == "yes" else 1.0}
    if result != "scalar":
        return None
    yes = _unit(m.get("settlement_value_dollars"))
    return None if yes is None else {"yes": yes, "no": 1.0 - yes}


def kalshi_result(market: dict) -> str | None:
    """The winning outcome_id in this project's terms for a Kalshi game market, or None while open.
    A market's `result` is yes/no on ITS OWN ticker; the winner of the game is the ticker whose
    result is yes. The caller maps ticker -> outcome_id; this returns 'yes' | 'no' | None."""
    m = market.get("market", market)
    if kalshi_payouts(market) is None:
        return None
    r = str(m.get("result", "")).lower()
    return r if r in ("yes", "no") else None


def polymarket_payouts(market: dict) -> dict[str, float] | None:
    """Return a complete label -> payout map only after Gamma says the market is final."""
    if not market.get("closed"):
        return None
    for key in ("umaResolutionStatus", "resolutionStatus"):
        if key in market and str(market.get(key, "")).lower() not in ("resolved", "finalized"):
            return None
    statuses = market.get("umaResolutionStatuses")
    # Some Gamma responses retain the historical plural proposal statuses alongside the
    # authoritative singular resolved status.  The singular terminal field wins when present.
    if statuses is not None and "umaResolutionStatus" not in market:
        if isinstance(statuses, str):
            try:
                statuses = json.loads(statuses)
            except (TypeError, ValueError):
                return None
        if not isinstance(statuses, list) or not statuses or any(str(s).lower() not in ("resolved", "finalized") for s in statuses):
            return None
    outs, prices = market.get("outcomes"), market.get("outcomePrices")
    if isinstance(outs, str):
        try: outs = json.loads(outs)
        except (TypeError, ValueError): return None
    if isinstance(prices, str):
        try: prices = json.loads(prices)
        except (TypeError, ValueError): return None
    if not isinstance(outs, list) or not isinstance(prices, list) or not outs or len(outs) != len(prices):
        return None
    if len(set(map(str, outs))) != len(outs):
        return None
    result = {}
    for outcome, price in zip(outs, prices):
        payout = _unit(price)
        if payout is None:
            return None
        result[str(outcome)] = payout
    # Gamma's resolved probabilities are a complete payout vector, not an arbitrary collection of
    # independent quotes.  Requiring the unit sum prevents partial/ambiguous cancellation payloads.
    return result if abs(sum(result.values()) - 1.0) <= 1e-6 else None


def polymarket_result(market: dict) -> str | None:
    """The winning outcome label of a Gamma market once resolved, else None."""
    payouts = polymarket_payouts(market)
    if payouts is None:
        return None
    winners = [o for o, p in payouts.items() if p >= 0.999]
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
    settled = [t for t, m in kalshi_markets.items() if kalshi_payouts(m) is not None]
    if len(yes) == 1 and len(settled) == len(kalshi_markets):
        out["kalshi"] = kalshi_outcomes[yes[0]]
    if pm_market is not None:
        w = polymarket_result(pm_market)
        if w is not None and w in pm_outcomes:
            out["polymarket"] = pm_outcomes[w]
    return out
