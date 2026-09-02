#!/usr/bin/env python3
"""Stage 3 collector: fetch real books for Stage-2 pairs and compute fee-net cover cost.

Registered spec: research/sports/2026-08-17_stage3-divergence/spec.yaml (ledger L12).
Reads prices. Places nothing. `arming_allowed: false`.

VENUE BOOK SHAPES — each is wrong in its own way and none is the shape you expect
────────────────────────────────────────────────────────────────────────────────
Kalshi      `orderbook_fp` carries `yes_dollars` and `no_dollars`, and BOTH ARE BID LADDERS.
            There are no asks in the payload. A YES ask at p exists only as a NO bid at 1-p, so
            asks are synthesised with `fold_complement_bids`. Read naively you see half the market
            and compute a spread that does not exist.

Polymarket  genuinely two-sided, but BOTH LADDERS PUT THE BEST PRICE LAST. `bids[0]` is the worst
            bid and `asks[0]` is the worst ask. Indexing [0] for "best" silently prices every
            trade at the far end of the book.

SX Bet      not a ladder at all — a list of resting maker orders. `percentageOdds` is the MAKER's
            implied probability scaled by 1e20, and a taker buying outcome ONE lifts orders whose
            maker took outcome TWO. So the taker's price is 1 - makerOdds, and
            `isMakerBettingOutcomeOne` selects which side an order offers. Getting this backwards
            inverts every price and produces beautiful nonsense.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nodes.entities.resolve import Resolver
from kernel.fetch import Client
from kernel.schema import Book, Quote
from nodes.schedule_espn import espn
from nodes.match_sports.sports_match import kalshi_markets, pm_markets
from nodes.cover.cover import Leg, best_cover
from nodes.venue_kalshi.books import KALSHI_BASE, fetch_kalshi_books, kalshi_book
from nodes.venue_polymarket.books import PM_CLOB, PM_GAMMA, fetch_pm_books, pm_book, pm_token_map
from nodes.venue_sxbet.books import SX_BASE, fetch_sx_mlb, sx_book


#: All Janus data goes here. NEVER the root disk (11 GB free, 95% full).
DATA_ROOT = Path("data/sports")

LIQUIDITY_SOURCE = {"kalshi": "kalshi_clob", "polymarket": "polymarket_clob",
                    "sxbet": "sxbet_clob"}


# ── book parsers (pure) ──────────────────────────────────────────────────────







# ── fetchers ─────────────────────────────────────────────────────────────────









# ── one poll ─────────────────────────────────────────────────────────────────

def poll(league: str, days: int, quantities, out_dir: Path, *, recheck_s: int = 60,
         max_leg_age_s: float = 30.0) -> dict:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days)
    window = (int(start.timestamp()), int(end.timestamp()))

    games = espn.fetch_range(league, start, end, use_cache=False)
    by_pair = espn.index_by_participants(games)
    r = Resolver.load()

    from collections import Counter
    stats = Counter(); stats["k_reason"] = Counter(); stats["p_reason"] = Counter()
    nm: list[dict] = []
    kms = kalshi_markets(league, r, by_pair, window, stats, nm)
    pms = pm_markets(league, r, by_pair, window, stats, nm)

    kc, pc, sc = Client("kalshi", 4, 8), Client("polymarket", 3, 6), Client("sxbet", 3, 6)

    # ── PRE-RESOLVE STATIC METADATA FIRST ────────────────────────────────
    # Gamma token lookups are static per market and slow. Doing them inside the timing-sensitive
    # loop is what made the first version of this collector reject 93 of 192 observations as
    # stale: it fetched ALL Kalshi books, then ALL PM books, then priced — by which point the
    # earliest legs were minutes old. Books are now fetched PER GAME, back to back, so a cover's
    # legs are seconds apart rather than minutes.
    tokmap = pm_token_map(sorted({m.venue_id for m in pms}), pc)
    pm_tokens: dict[str, str] = {}
    for m in pms:
        entry = tokmap.get(m.venue_id)
        if not entry:
            continue
        names, _ = entry
        for nm_, tok in names.items():
            if r.resolve(league, text=nm_).entity_id == m.entity_id:
                pm_tokens[m.outcome_id] = tok

    k_by_game: dict[str, list] = defaultdict(list)
    p_by_game: dict[str, list] = defaultdict(list)
    for m in kms:
        k_by_game[m.game_id].append(m)
    for m in pms:
        if m.outcome_id in pm_tokens:
            p_by_game[m.game_id].append(m)

    def legs_for(game_id: str) -> dict[str, list[Leg]]:
        """Fetch every leg of ONE game back to back. Leg age stays within a few seconds."""
        per: dict[str, list[Leg]] = defaultdict(list)
        for m in k_by_game.get(game_id, []):
            try:
                t0 = time.time()
                d = kc.get_json(f"{KALSHI_BASE}/markets/{m.outcome_id}/orderbook",
                                params={"depth": 20}, use_cache=False)
                b = kalshi_book(d, "yes", t0)
            except Exception:  # noqa: BLE001
                continue
            if b.asks:
                per[m.entity_id].append(
                    Leg("kalshi", LIQUIDITY_SOURCE["kalshi"], m.outcome_id, m.venue_id, b))
        for m in p_by_game.get(game_id, []):
            try:
                t0 = time.time()
                d = pc.get_json(f"{PM_CLOB}/book", params={"token_id": pm_tokens[m.outcome_id]},
                                use_cache=False)
                b = pm_book(d, t0)
            except Exception:  # noqa: BLE001
                continue
            if b.asks:
                per[m.entity_id].append(
                    Leg("polymarket", LIQUIDITY_SOURCE["polymarket"], m.outcome_id, m.venue_id,
                        b, {"fee_rate": 0.05}))   # PM sports rate, per-market override (L7)
        return per

    all_games = sorted(set(k_by_game) | set(p_by_game))
    kbooks = {"n": sum(len(v) for v in k_by_game.values())}
    pbooks = {"n": len(pm_tokens)}

    obs, cands = [], []
    n_both = 0
    # PRICE EACH GAME THE INSTANT ITS BOOKS LAND. Taking one clock reading after fetching all 48
    # games made every early game look stale — the same fetch-all-then-price mistake as before,
    # one level up. A cover is priced against the clock at the moment its own legs were fetched.
    for game_id in all_games:
        per_entity = legs_for(game_id)
        if len(per_entity) != 2:
            continue
        n_both += 1
        tnow = time.time()
        venues = {l.venue for legs in per_entity.values() for l in legs}
        for q in quantities:
            cov = best_cover(per_entity, q, now_utc=tnow, max_leg_age_s=max_leg_age_s,
                             exhaustive=True)     # MLB moneyline: no draw, exhaustive by sport
            row = {"utc": tnow, "game_id": game_id, "contracts": q,
                   "venues": "|".join(sorted(venues)),
                   "ok": cov.ok, "reject": cov.reject_reason or "",
                   "cost": cov.cost_per_contract, "gross": cov.gross_per_contract,
                   "fee": cov.fee_per_contract, "edge": cov.edge_per_contract,
                   "max_leg_age_s": cov.max_leg_age_s,
                   "single_venue": cov.single_venue,
                   "legs": "|".join(f"{l.venue}:{l.vwap:.4f}" for l in cov.legs)}
            obs.append(row)
            if cov.ok and cov.cost_per_contract is not None and cov.cost_per_contract < 0.995:
                cands.append(dict(row))

    # ── persistence recheck: a candidate that evaporates is not a trade ──────
    if cands:
        print(f"  {len(cands)} candidate(s) < 0.995 — re-fetching in {recheck_s}s")
        time.sleep(recheck_s)
        for c in cands:
            per = legs_for(c["game_id"])
            t2 = time.time()
            c2 = (best_cover(per, c["contracts"], now_utc=t2, max_leg_age_s=max_leg_age_s,
                             exhaustive=True) if len(per) == 2 else None)
            c["recheck_cost"] = c2.cost_per_contract if (c2 and c2.ok) else None
            c["persisted"] = bool(c2 and c2.ok and c2.cost_per_contract is not None
                                  and c2.cost_per_contract < 0.995)

    priced = [o for o in obs if o["ok"]]
    below = [o for o in priced if o["cost"] is not None and o["cost"] < 0.995]
    summary = {
        "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "league": league,
        "games_with_both_sides": n_both,
        "kalshi_markets": kbooks["n"], "pm_markets": pbooks["n"],
        "observations": len(obs), "priced_ok": len(priced),
        "rejects": dict(__import__("collections").Counter(
            o["reject"] for o in obs if not o["ok"])),
        "below_0995": len(below),
        "rate_below_0995": round(len(below) / len(priced), 5) if priced else None,
        "persisted": sum(1 for c in cands if c.get("persisted")),
        "min_cost": min((o["cost"] for o in priced if o["cost"] is not None), default=None),
        "median_cost_by_q": {},
    }
    for q in quantities:
        v = sorted(o["cost"] for o in priced if o["contracts"] == q and o["cost"] is not None)
        if v:
            summary["median_cost_by_q"][str(q)] = round(v[len(v) // 2], 5)

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    _write_csv(out_dir / f"observations_{stamp}.csv", obs)
    if cands:
        _write_csv(out_dir / f"candidates_{stamp}.csv", cands)
    (out_dir / f"summary_{stamp}.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    return summary


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    cols = sorted({k for r in rows for k in r})
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="mlb")
    ap.add_argument("--days", type=int, default=4)
    ap.add_argument("--q", default="50,100,200,500")
    ap.add_argument("--out", type=Path, default=DATA_ROOT / "stage3")
    ap.add_argument("--recheck", type=int, default=60)
    a = ap.parse_args()
    poll(a.league, a.days, [float(x) for x in a.q.split(",")], a.out, recheck_s=a.recheck)
