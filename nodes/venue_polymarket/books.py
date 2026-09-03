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


def pm_primary_market(event: dict, slug: str) -> dict | None:
    """The market whose fee schedule, order limits and rules text stand for the event: the one
    carrying the event slug (two-outcome games), else the first per-side moneyline market of a
    three-way game (`{slug}-{abbrev}`; the draw market differs only in its cancellation clause)."""
    m = pm_market_for_slug(event, slug)
    if m is not None:
        return m
    for x in (event or {}).get("markets") or []:
        if str(x.get("slug", "")).startswith(slug + "-") and x.get("sportsMarketType") == "moneyline" \
                and not str(x.get("slug", "")).endswith("-draw"):
            return x
    return None


def pm_outcome_tokens(event: dict, slug: str) -> dict[str, str]:
    """outcome label -> YES token for the full-game moneyline. Two shapes, both verified live:
    a two-outcome game is ONE market carrying the event slug with outcomes [away, home] and two
    tokens; a three-way soccer game is THREE Yes/No markets `{slug}-{abbrev}`, `{slug}-draw`,
    `{slug}-{abbrev}`, each with its own YES token. Labels are the team names from `teams` and
    "Draw"; an event matching neither shape yields {}."""
    markets = (event or {}).get("markets") or []
    for m in markets:
        if m.get("slug") != slug:
            continue
        toks = m.get("clobTokenIds")
        if isinstance(toks, str):
            toks = json.loads(toks)
        outs = m.get("outcomes")
        if isinstance(outs, str):
            outs = json.loads(outs)
        if toks and len(toks) == 2 and outs and len(outs) == 2:
            return dict(zip(outs, toks))
        return {}
    by_abbrev = {str(t.get("abbreviation", "")).lower(): t.get("name") for t in (event or {}).get("teams") or []}
    out: dict[str, str] = {}
    for m in markets:
        ms = str(m.get("slug", ""))
        if not ms.startswith(slug + "-") or m.get("sportsMarketType") != "moneyline":
            continue
        toks = m.get("clobTokenIds")
        if isinstance(toks, str):
            toks = json.loads(toks)
        if not toks:
            continue
        suffix = ms[len(slug) + 1:]
        if suffix == "draw":
            out["Draw"] = str(toks[0])
        elif suffix in by_abbrev and by_abbrev[suffix]:
            out[str(by_abbrev[suffix])] = str(toks[0])
    return out if len(out) == 3 else {}


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
            names = pm_outcome_tokens(ev, slug)
            if names:
                out[slug] = (names, ev)
        # NARROW, deliberately. A bare `except Exception` here swallowed a NameError for the
        # missing `json` import and turned a hard bug into "no tokens resolved" on every game --
        # 14 of 14 blocked with PM_TOKEN_RESOLUTION and nothing saying why. Network and parse
        # failures are expected and recorded; programming errors must stay loud.
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            errors[slug] = f"{type(exc).__name__}: {exc}"
    if errors:
        out["__errors__"] = errors  # type: ignore[assignment]
    return out
