#!/usr/bin/env python3
"""Polymarket book fetch and parse, plus the Gamma token map.

THE PAYLOAD SHAPE IS A TRAP. The book is genuinely two-sided, but BOTH LADDERS PUT THE BEST PRICE
LAST: `bids[0]` is the WORST bid and `asks[0]` the WORST ask. Indexing [0] for "best" silently
prices every trade at the far end of the book.

Polymarket's rate limiter also QUEUES rather than rejecting, so a throttled response is a stale
quote wearing a fresh wall-clock timestamp (kernel/schema.py, `Book`).

Node kind: `source` (fetch) + `pure` (parse)."""

from __future__ import annotations

from kernel.fetch import Client
from kernel.schema import Book, Quote

PM_CLOB = "https://clob.polymarket.com"
PM_GAMMA = "https://gamma-api.polymarket.com"


def pm_book(payload: dict, fetched_utc: float) -> Book:
    """Polymarket CLOB book. Best price is LAST in both arrays — sort, never index."""
    bids = tuple(sorted((Quote(float(b["price"]), float(b["size"]))
                         for b in payload.get("bids") or []), key=lambda q: -q.price))
    asks = tuple(sorted((Quote(float(a["price"]), float(a["size"]))
                         for a in payload.get("asks") or []), key=lambda q: q.price))
    return Book(bids=bids, asks=asks, fetched_utc=fetched_utc)


def fetch_pm_books(token_map: dict[str, str], cl: Client) -> dict[str, Book]:
    out = {}
    for outcome_id, token in token_map.items():
        try:
            now = time.time()
            d = cl.get_json(f"{PM_CLOB}/book", params={"token_id": token}, use_cache=False)
            out[outcome_id] = pm_book(d, now)
        except Exception:  # noqa: BLE001
            continue
    return out


def pm_token_map(slugs, cl: Client) -> dict[str, tuple[str, str]]:
    """slug -> (token_outcome0, token_outcome1) for the FULL-GAME moneyline market only."""
    out = {}
    for slug in slugs:
        try:
            ev = cl.get_json(f"{PM_GAMMA}/events", params={"slug": slug}, use_cache=False)
            ev = ev[0] if isinstance(ev, list) else ev
            for m in ev.get("markets") or []:
                if m.get("slug") != slug:
                    continue                       # the parent market carries the slug exactly
                toks = m.get("clobTokenIds")
                if isinstance(toks, str):
                    toks = json.loads(toks)
                outs = m.get("outcomes")
                if isinstance(outs, str):
                    outs = json.loads(outs)
                if toks and len(toks) == 2 and outs and len(outs) == 2:
                    out[slug] = (dict(zip(outs, toks)), ev)
                break
        except Exception:  # noqa: BLE001
            continue
    return out
