#!/usr/bin/env python3
"""Polymarket book fetch and parse, plus the Gamma token map.

THE PAYLOAD SHAPE IS A TRAP. The book is genuinely two-sided, but BOTH LADDERS PUT THE BEST PRICE
LAST: `bids[0]` is the WORST bid and `asks[0]` the WORST ask. Indexing [0] for "best" silently
prices every trade at the far end of the book.

Polymarket's rate limiter also QUEUES rather than rejecting, so a throttled response is a stale
quote wearing a fresh wall-clock timestamp (kernel/schema.py, `Book`).

Node kind: `source` (fetch) + `pure` (parse)."""

from __future__ import annotations

import json
import time

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
    return Book(bids=bids, asks=asks, fetched_utc=fetched_utc, source="rest")


def fetch_pm_books(token_map: dict[str, str], cl: Client) -> dict[str, Book]:
    """outcome_id -> Book. Failures land under `__errors__`, keyed by outcome_id."""
    out: dict = {}
    errors: dict[str, str] = {}
    for outcome_id, token in token_map.items():
        try:
            now = time.time()
            d = cl.get_json(f"{PM_CLOB}/book", params={"token_id": token}, use_cache=False)
            out[outcome_id] = pm_book(d, now)
        # NARROW, deliberately. A bare `except Exception` here swallowed a NameError for the
        # missing `json` import and turned a hard bug into "no tokens resolved" on every game --
        # 14 of 14 blocked with PM_TOKEN_RESOLUTION and nothing saying why. Network and parse
        # failures are expected and recorded; programming errors must stay loud.
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            errors[outcome_id] = f"{type(exc).__name__}: {exc}"
    if errors:
        out["__errors__"] = errors  # type: ignore[assignment]
    return out


def pm_market_for_slug(event: dict, slug: str) -> dict | None:
    """The market inside a Gamma event whose slug matches exactly (the full-game moneyline)."""
    for m in (event or {}).get("markets") or []:
        if m.get("slug") == slug:
            return m
    return None


def pm_fee_params(market: dict) -> dict | None:
    """Per-market fee schedule from Gamma; None if the market carries none.

    Verified live 2026-09-02 on an MLB market: `feeType: sports_fees_v2`,
    `feeSchedule: {exponent: 1, rate: 0.03, takerOnly: true, rebateRate: 0.25}`. The rate is NOT
    the 0.05 the lane hardcoded, and the registry's measured distribution (0.04/0.05/0.07/none)
    says it varies by market. A None here must BLOCK the leg, never default.
    """
    fs = (market or {}).get("feeSchedule")
    if not isinstance(fs, dict) or fs.get("rate") is None:
        return None
    out = {"fee_rate": float(fs["rate"])}
    if fs.get("exponent") is not None:
        out["fee_exponent"] = float(fs["exponent"])
    if fs.get("takerOnly") is not None:
        out["taker_only"] = bool(fs["takerOnly"])
    if fs.get("rebateRate") is not None:
        out["rebate_rate"] = float(fs["rebateRate"])
    return out


def pm_order_limits(market: dict) -> dict:
    """`orderMinSize` and `orderPriceMinTickSize` as the schema names them. Missing -> absent."""
    out: dict = {}
    if (market or {}).get("orderMinSize") is not None:
        out["min_order_contracts"] = float(market["orderMinSize"])
    if (market or {}).get("orderPriceMinTickSize") is not None:
        out["tick"] = float(market["orderPriceMinTickSize"])
    return out


def pm_token_map(slugs, cl: Client) -> dict[str, tuple[str, str]]:
    """slug -> ({outcome_label: token}, event) for the FULL-GAME moneyline market only.

    Failures are recorded under the `__errors__` key rather than silently dropped, so a caller
    that gets fewer tokens than it expected can say WHY instead of reporting a bare
    PM_TOKEN_RESOLUTION block.
    """
    out: dict = {}
    errors: dict[str, str] = {}
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
        # NARROW, deliberately. A bare `except Exception` here swallowed a NameError for the
        # missing `json` import and turned a hard bug into "no tokens resolved" on every game --
        # 14 of 14 blocked with PM_TOKEN_RESOLUTION and nothing saying why. Network and parse
        # failures are expected and recorded; programming errors must stay loud.
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            errors[slug] = f"{type(exc).__name__}: {exc}"
    if errors:
        out["__errors__"] = errors  # type: ignore[assignment]
    return out
