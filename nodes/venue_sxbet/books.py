#!/usr/bin/env python3
"""SX Bet book fetch and parse.

NOT A LADDER. The payload is a list of resting maker orders. `percentageOdds` is the MAKER's
implied probability scaled by 1e20, and a taker buying outcome ONE lifts orders whose maker took
outcome TWO — so the taker pays 1 - makerOdds, and `isMakerBettingOutcomeOne` selects which side
an order offers. Getting this backwards inverts every price and produces beautiful nonsense.

WHY THIS NODE MATTERS. SX Bet is a zero-rake CLOB: 0% commission on singles, the cheapest
screening coefficient of any two-sided venue in nodes/fees/registry.py. Unlike a sportsbook it has
two-sided depth, a real NO side, and no counterparty discretion to reject a winning bet.

Node kind: `source` (fetch) + `pure` (parse)."""

from __future__ import annotations

import time
from collections import defaultdict

from kernel.fetch import Client
from kernel.schema import Book, Quote

SX_BASE = "https://api.sx.bet"


def sx_book(orders: list[dict], want_outcome_one: bool, fetched_utc: float) -> Book:
    """SX Bet resting orders -> a Book for the taker of one outcome.

    A maker who backed outcome TWO is offering outcome ONE to a taker. `percentageOdds` is the
    MAKER's implied probability × 1e20, so the taker pays 1 − that. `totalBetSize` is the maker's
    stake in base-token units; the taker's available contracts are stake/(1−makerOdds) … but the
    exact size convention is UNVERIFIED against a real fill, so sizes here are treated as an
    upper bound and the venue is excluded from any depth claim until reconciled.
    """
    asks = []
    for o in orders:
        maker_one = bool(o.get("isMakerBettingOutcomeOne"))
        if maker_one == want_outcome_one:
            continue                       # this maker is on the same side as us; not our liquidity
        try:
            maker_odds = float(o["percentageOdds"]) / 1e20
            stake = float(o.get("totalBetSize", 0)) / 1e18
        except (KeyError, TypeError, ValueError):
            continue
        taker_price = 1.0 - maker_odds
        if not (0.0 < taker_price < 1.0) or stake <= 0:
            continue
        contracts = stake / taker_price if taker_price > 0 else 0.0
        asks.append(Quote(round(taker_price, 6), contracts))
    return Book(asks=tuple(sorted(asks, key=lambda q: q.price)), fetched_utc=fetched_utc,
                one_sided=True)


def fetch_sx_mlb(cl: Client) -> dict:
    """{(entity_pair, gameTime): {outcome_name: Book}} for MLB moneyline (type 226)."""
    try:
        mk = cl.get_json(f"{SX_BASE}/markets/active", params={"leagueId": 171},
                         use_cache=False)["data"]["markets"]
    except Exception:  # noqa: BLE001
        return {}
    ml = [m for m in mk if m.get("type") == 226]
    if not ml:
        return {}
    hashes = [m["marketHash"] for m in ml]
    orders = defaultdict(list)
    for i in range(0, len(hashes), 20):
        try:
            d = cl.get_json(f"{SX_BASE}/orders",
                            params={"marketHashes": ",".join(hashes[i:i + 20])},
                            use_cache=False)["data"]
        except Exception:  # noqa: BLE001
            continue
        for o in d:
            orders[o["marketHash"]].append(o)
    now = time.time()
    out = {}
    for m in ml:
        od = orders.get(m["marketHash"], [])
        if not od:
            continue
        out[m["marketHash"]] = {
            "teamOne": m.get("teamOneName"), "teamTwo": m.get("teamTwoName"),
            "gameTime": m.get("gameTime"),
            "books": {m.get("outcomeOneName"): sx_book(od, True, now),
                      m.get("outcomeTwoName"): sx_book(od, False, now)},
        }
    return out
