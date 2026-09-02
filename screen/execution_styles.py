#!/usr/bin/env python3
"""What a cover costs under each EXECUTION STYLE, not just the expensive one.

Spec: research/sports/2026-08-17_stage3-divergence/spec.yaml (ledger L12), extended.

WHY THIS EXISTS
───────────────
Stage 3 measured cover cost assuming you CROSS the spread on both legs (taker/taker) and found
~2c of dislocation against a ~3c fee floor: no trade. That measured the most expensive way to do
it. Polymarket charges makers NOTHING and Kalshi charges them a quarter of the taker rate, so the
two-leg floor at the money falls from 3.00c to 0.44c — nearly 7x — on venues already readable.

    Kalshi taker + PM taker    3.00c    <- what Stage 3 measured
    Kalshi taker + PM maker    1.75c
    Kalshi maker + PM taker    1.69c
    Kalshi maker + PM maker    0.44c

THE THING THIS SCRIPT MUST NOT BE ALLOWED TO PRETEND
────────────────────────────────────────────────────
**A maker cover is not arbitrage.** Arbitrage is riskless because both legs execute at once. A
resting order may not fill, so a "maker cover" is a HOPE about two independent queues, and the two
failure modes are not symmetric:

  * BOTH legs fill      -> you are covered, and you earned both spreads.
  * ONE leg fills       -> you are NAKED DIRECTIONAL on a $1 binary. Not hedged. Not arbitrage.
  * NEITHER fills       -> nothing happened.

Worse, fills are ADVERSELY SELECTED — you get filled precisely when someone informed wanted to
trade against you. Phase 1 measured this directly on Polymarket: maker-filled windows settled
**-22c** while unfilled windows carried **+9.4c**, a 31c gap. That was a directional book, so it
does not transfer unchanged to a covered one; but "does not transfer unchanged" is not "does not
apply", and the covered case is UNMEASURED.

So every number this script emits is **MODELLED (tier MOD)**, not measured. It answers exactly one
question — *is the maker-achievable cover cheap enough, often enough, to be worth measuring fill
behaviour at all?* — and nothing more. A NO here kills the idea for free. A YES buys the right to
do the expensive work, not the right to trade.

WHAT "MAKER PRICE" MEANS HERE — AND A MODEL THAT WAS WRONG
──────────────────────────────────────────────────────────
The first version of this script priced a maker leg at the BEST BID. On tight books that is
roughly fair. On wide books it is nonsense, and it produced "covers" at **0.53** — 47c of apparent
edge — from Polymarket books bidding 0.30 and 0.23 against a true value near 0.50. Resting a bid
27c below fair value is not a strategy; it is an order that never fills, except in the one state
where the game has already moved against you. That is the phase-1 "+97.94c golfer vs cyclist"
failure wearing different clothes: a number that is enormous *because* it is meaningless.

So the maker leg is now priced three ways, and the DEFENSIBLE one is the headline:

  AT_MID   quote at the book's midpoint. To be filled you must offer a price someone will hit, and
           in a wide book that is near fair value, not near the stale bid. This captures half the
           spread versus crossing. THIS IS THE HEADLINE NUMBER.
  AT_BID   quote at the current best bid. An UPPER BOUND on how good maker execution can get, and
           only meaningful where the spread is already tight. Reported, never headlined.
  IMPROVE  one tick inside the best bid. Between the two.

None of the three models queue depth ahead of you, cancellation, partial fills, or the fact that
your own quote moves the market. All of those need resting orders to measure and are out of scope
under `arming_allowed: false`.

THE DISLOCATION MEASURE, WHICH IS EXECUTION-INDEPENDENT
──────────────────────────────────────────────────────
`cover_at_mid` — the sum of both legs' midpoints — is the honest measure of whether the VENUES
DISAGREE, separate from how you execute. If cover_at_mid >= 1.00 there is no cross-venue
dislocation and any apparent maker "edge" is purely spread capture, i.e. market making, with all
the adverse selection that implies. Reporting it alongside is what stops the two being confused.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics as st
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib.entities.resolve import Resolver
from lib.fees.models import Fill
from lib.fees.registry import model_for, params_for
from lib.fetch import Client
from lib.schedule import espn
from match.sports_match import kalshi_markets, pm_markets

TICK = 0.01
ARB = 0.995

#: (style name, kalshi liquidity, pm liquidity). "taker" crosses; "maker" rests.
STYLES = [
    ("taker_taker", "taker", "taker"),      # Stage 3's measurement — the only MEASURED row
    ("maker_taker", "maker", "taker"),
    ("taker_maker", "taker", "maker"),
    ("maker_maker", "maker", "maker"),
]

PM_OVERRIDES = {"fee_rate": 0.05}          # PM sports rate, per-market (L7)


def mid(book) -> float | None:
    if not (book.best_bid and book.best_ask):
        return None
    return (book.best_bid.price + book.best_ask.price) / 2.0


def spread(book) -> float | None:
    if not (book.best_bid and book.best_ask):
        return None
    return book.best_ask.price - book.best_bid.price


def leg_price(book, liquidity: str, mode: str) -> float | None:
    """Price for one contract under this execution style.

    taker    -> lift the best ask. A REAL, executable price.
    at_mid   -> quote at the midpoint. A hope, but a PLAUSIBLE one: to be filled you must offer a
                price someone will hit.
    at_bid   -> quote at the best bid. An upper bound; meaningless in a wide book.
    improve  -> one tick inside the best bid.
    """
    if liquidity == "taker":
        return book.best_ask.price if book.best_ask else None
    if not book.best_bid:
        return None
    if mode == "at_mid":
        return mid(book)
    p = book.best_bid.price + (TICK if mode == "improve" else 0.0)
    return p if 0.0 < p < 1.0 else None


def fee_for(venue: str, price: float, contracts: float, liquidity: str,
            overrides: dict) -> float:
    ov = dict(overrides); ov["liquidity"] = liquidity
    params = params_for(venue, ov)
    f = Fill(venue=venue, market_id="m", outcome_id="o", side="yes",
             price=price, contracts=contracts, liquidity=liquidity)
    return model_for(venue).entry_cost([f], params)


def dislocation(books_by_game: dict) -> list[dict]:
    """cover_at_mid per game: do the VENUES disagree, independent of how you execute?"""
    out = []
    for game_id, per_entity in books_by_game.items():
        if len(per_entity) != 2:
            continue
        tot, ok, sp = 0.0, True, []
        for _, venues in per_entity.items():
            best = None
            for _, book in venues.items():
                m = mid(book)
                if m is None:
                    continue
                if best is None or m < best:
                    best = m
                sp.append(spread(book))
            if best is None:
                ok = False
                break
            tot += best
        if ok:
            out.append({"game_id": game_id, "cover_at_mid": round(tot, 6),
                        "max_spread": round(max(x for x in sp if x is not None), 4)})
    return out


def evaluate(books_by_game: dict, contracts: float, mode: str) -> list[dict]:
    rows = []
    for game_id, per_entity in books_by_game.items():
        if len(per_entity) != 2:
            continue
        for style, k_liq, p_liq in STYLES:
            total, ok, legs = 0.0, True, []
            for entity, venues in per_entity.items():
                # cheapest venue for THIS leg under THIS style
                best = None
                for venue, book in venues.items():
                    liq = k_liq if venue == "kalshi" else p_liq
                    px = leg_price(book, liq, mode)
                    if px is None:
                        continue
                    ov = PM_OVERRIDES if venue == "polymarket" else {}
                    c = px + fee_for(venue, px, contracts, liq, ov) / contracts
                    if best is None or c < best[0]:
                        best = (c, venue, px, liq)
                if best is None:
                    ok = False
                    break
                total += best[0]
                legs.append(f"{best[1]}/{best[3]}:{best[2]:.4f}")
            if ok:
                rows.append({"game_id": game_id, "style": style, "mode": mode,
                             "contracts": contracts, "cover": round(total, 6),
                             "edge": round(1.0 - total, 6), "legs": "|".join(legs),
                             "measured": style == "taker_taker"})
    return rows


def collect(league: str, days: int) -> dict:
    from collectors.sports_books import (KALSHI_BASE, PM_CLOB, kalshi_book, pm_book,
                                         pm_token_map)
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days)
    games = espn.fetch_range(league, start, end, use_cache=False)
    by_pair = espn.index_by_participants(games)
    r = Resolver.load()

    stats = Counter(); stats["k_reason"] = Counter(); stats["p_reason"] = Counter()
    kms = kalshi_markets(league, r, by_pair,
                         (int(start.timestamp()), int(end.timestamp())), stats, [])
    pms = pm_markets(league, r, by_pair,
                     (int(start.timestamp()), int(end.timestamp())), stats, [])

    kc, pc = Client("kalshi", 4, 8), Client("polymarket", 3, 6)
    tokmap = pm_token_map(sorted({m.venue_id for m in pms}), pc)
    pm_tokens = {}
    for m in pms:
        e = tokmap.get(m.venue_id)
        if not e:
            continue
        for nm_, tok in e[0].items():
            if r.resolve(league, text=nm_).entity_id == m.entity_id:
                pm_tokens[m.outcome_id] = tok

    k_by_game, p_by_game = defaultdict(list), defaultdict(list)
    for m in kms:
        k_by_game[m.game_id].append(m)
    for m in pms:
        if m.outcome_id in pm_tokens:
            p_by_game[m.game_id].append(m)

    out = {}
    for gid in sorted(set(k_by_game) | set(p_by_game)):
        per = defaultdict(dict)
        for m in k_by_game.get(gid, []):
            try:
                d = kc.get_json(f"{KALSHI_BASE}/markets/{m.outcome_id}/orderbook",
                                params={"depth": 20}, use_cache=False)
                b = kalshi_book(d, "yes", time.time())
                if b.asks and b.bids:
                    per[m.entity_id]["kalshi"] = b
            except Exception:  # noqa: BLE001
                pass
        for m in p_by_game.get(gid, []):
            try:
                d = pc.get_json(f"{PM_CLOB}/book", params={"token_id": pm_tokens[m.outcome_id]},
                                use_cache=False)
                b = pm_book(d, time.time())
                if b.asks and b.bids:
                    per[m.entity_id]["polymarket"] = b
            except Exception:  # noqa: BLE001
                pass
        if len(per) == 2:
            out[gid] = dict(per)
    return out


def summarize(rows: list[dict]) -> dict:
    res = {}
    for style, _, _ in STYLES:
        for mode in ("at_mid", "improve", "at_bid"):
            sub = [r for r in rows if r["style"] == style and r["mode"] == mode]
            if not sub:
                continue
            cov = [r["cover"] for r in sub]
            clear = [r for r in sub if r["cover"] < ARB]
            res[f"{style}__{mode}"] = {
                "n": len(sub),
                "median_cover": round(st.median(cov), 5),
                "min_cover": round(min(cov), 5),
                "clears_0995": len(clear),
                "clears_rate": round(len(clear) / len(sub), 4),
                "median_edge_cents": round((1 - st.median(cov)) * 100, 3),
                "evidence": "MEASURED (executable asks)" if style == "taker_taker"
                            else "MODELLED - resting price, NO FILL ASSUMED",
            }
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="mlb")
    ap.add_argument("--days", type=int, default=4)
    ap.add_argument("--contracts", type=float, default=200.0)
    ap.add_argument("--out", type=Path,
                    default=Path("research/sports/2026-08-17_stage3-divergence"))
    a = ap.parse_args()

    books = collect(a.league, a.days)
    print(f"games with both sides on both venues: {len(books)}")

    dis = dislocation(books)
    dm = [d["cover_at_mid"] for d in dis]
    print("\n=== DISLOCATION (execution-independent): sum of midpoints ===")
    if dm:
        print(f"  median cover_at_mid {st.median(dm):.5f} | min {min(dm):.5f} | "
              f"below 1.00: {sum(1 for x in dm if x < 1.0)}/{len(dm)}")
        sps = [d["max_spread"] for d in dis]
        print(f"  widest leg spread: median {st.median(sps):.3f} | max {max(sps):.3f}")
        print("  >= 1.00 means the venues AGREE and any maker 'edge' is spread capture, "
              "not dislocation.\n")
    rows = []
    for mode in ("at_mid", "improve", "at_bid"):
        rows += evaluate(books, a.contracts, mode)
    summary = summarize(rows)
    print(json.dumps(summary, indent=1))

    a.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with (a.out / f"execution_styles_{stamp}.csv").open("w", newline="") as fh:
        if rows:
            w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    (a.out / f"execution_styles_{stamp}.json").write_text(json.dumps(
        {"contracts": a.contracts, "games": len(books), "summary": summary,
         "dislocation": {"median_cover_at_mid": round(st.median(dm), 5) if dm else None,
                         "min_cover_at_mid": round(min(dm), 5) if dm else None,
                         "below_1_of_n": f"{sum(1 for x in dm if x < 1.0)}/{len(dm)}" if dm else None}},
        indent=1))
