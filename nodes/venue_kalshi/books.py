#!/usr/bin/env python3
"""Kalshi book fetch and parse.

THE PAYLOAD SHAPE IS A TRAP. `orderbook_fp` carries `yes_dollars` and `no_dollars`, and BOTH ARE
BID LADDERS. There are no asks in the payload at all. A YES ask at p exists only as a NO bid at
1-p, so asks are synthesised via `fold_complement_bids`. Read naively you see half the market and
compute a spread that does not exist.

Node kind: `source` (fetch) + `pure` (parse). The parse half must stay importable without network.
Grid position: feeds `nodes/cover` via a grid; see grids/live_sports/README.md."""

from __future__ import annotations

import time

from kernel.fetch import Client
from kernel.schema import Book, Quote, fold_complement_bids

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"


def kalshi_book(payload: dict, side: str, fetched_utc: float) -> Book:
    """Kalshi orderbook -> Book for one side. BOTH arrays are bids; asks are folded."""
    ob = payload.get("orderbook_fp") or payload.get("orderbook") or {}
    own = ob.get(f"{side}_dollars") or ob.get(side) or []
    other = ob.get(f"{'no' if side == 'yes' else 'yes'}_dollars") or []
    bids = tuple(sorted((Quote(float(p), float(s)) for p, s in own),
                        key=lambda q: -q.price))
    comp = tuple(Quote(float(p), float(s)) for p, s in other)
    return Book(bids=bids, asks=fold_complement_bids(comp), fetched_utc=fetched_utc)


def fetch_kalshi_books(tickers, cl: Client) -> dict[str, Book]:
    out = {}
    for t in tickers:
        try:
            now = time.time()
            d = cl.get_json(f"{KALSHI_BASE}/markets/{t}/orderbook",
                            params={"depth": 20}, use_cache=False)
            out[t] = kalshi_book(d, "yes", now)
        except Exception:  # noqa: BLE001
            continue
    return out
