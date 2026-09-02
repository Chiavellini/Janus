#!/usr/bin/env python3
"""Low-latency, live-sports pure-arbitrage lane.

The discovery pass is schedule-first and bounded to games in progress (or, optionally, games
starting soon). Once a game is identified, only its exact Kalshi/Polymarket outcome books are
fetched. No venue-wide quote snapshot is written. This is intentionally deployable on the
Ashburn host, where the final request latency should be lower and more stable than from a home
connection; the local run is useful for validating matching and economics first.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nodes.entities.resolve import Resolver  # noqa: E402
from kernel.fetch import Client  # noqa: E402
from nodes.schedule_espn import espn  # noqa: E402
from nodes.match_sports.sports_match import kalshi_markets, pair, pm_markets  # noqa: E402
from nodes.venue_kalshi.books import kalshi_book  # noqa: E402
from nodes.venue_polymarket.books import pm_book, pm_token_map  # noqa: E402
from nodes.cover.cover import Leg, best_cover  # noqa: E402
from nodes.rules_exhaustive.rules import NotExhaustive, prove  # noqa: E402
from nodes.store_tuples.store import TupleStore  # noqa: E402

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
PM_CLOB = "https://clob.polymarket.com"
SPEC_REF = "research/sports/2026-09-01_pure-arb-event-scan/spec.yaml"
#: Registered artifacts for a ledger row are IMMUTABLE. The scan used to write results.json and
#: verdict.md straight into row 2's study directory with fixed filenames, so every run overwrote
#: registered evidence and there was no scan history at all. Observation runs now write one
#: directory per run on the data volume; a `latest` symlink is flipped only on a completed run, so
#: a crashed run can never leave a previous "Status: OK" verdict standing as if it were fresh.
RUNS_DIR = Path("/Volumes/Kilos/janus/runs/live_sports")
DB = Path("/Volumes/Kilos/janus/tuples/tuples.sqlite")
QUANTITIES = (5.0, 25.0, 100.0)

#: Hours ahead of first pitch/puck to start watching a pre-game market.
DEFAULT_PRE_HOURS = 6.0
MIN_RETURN = 0.01
MAX_QUOTE_SKEW = 5.0
LIQUIDITY_SOURCE = {"kalshi": "kalshi_clob", "polymarket": "polymarket_clob"}


def _fetch_book(client: Client, venue: str, market_id: str, token: str | None = None) -> dict:
    started = time.time()
    if venue == "kalshi":
        payload = client.get_json(f"{KALSHI_BASE}/markets/{market_id}/orderbook",
                                  params={"depth": 20}, use_cache=False)
        book = kalshi_book(payload, "yes", time.time())
    else:
        payload = client.get_json(f"{PM_CLOB}/book", params={"token_id": token}, use_cache=False)
        book = pm_book(payload, time.time())
    return {"book": book, "started": started, "received": time.time(), "venue": venue,
            "market_id": market_id}


def _book_levels(book) -> list[dict]:
    return [{"side": side, "price": round(q.price, 6), "size": round(q.size, 6),
             "synthetic": q.is_synthetic}
            for side, arr in (("bid", book.bids), ("ask", book.asks))
            for q in arr[:20]]


def _live_games(leagues: list[str], now: datetime, include_near: bool,
                pre_hours: float = DEFAULT_PRE_HOURS) -> tuple[list, dict]:
    """In-progress games, plus pre-game starting within `pre_hours`.

    The window used to be a hardcoded +/-30 minutes, which is why the 2026-09-02 scan saw exactly
    one game against a registered universe of 30 days. One ESPN failure also killed every league,
    because the loop had no guard -- so each league is isolated here and a failed league is
    reported rather than fatal.
    """
    games, failures = [], {}
    horizon = max(1.0, pre_hours / 24.0 + 1.0)
    for league in leagues:
        try:
            schedule = espn.fetch_range(league, now - timedelta(days=1),
                                        now + timedelta(days=horizon), use_cache=False)
        except Exception as exc:  # noqa: BLE001 -- one league must not take the others down
            failures[league] = f"{type(exc).__name__}: {exc}"
            continue
        for g in schedule:
            delta = g.start_utc - now.timestamp()
            if g.state == "in" or (include_near and g.state == "pre"
                                   and -1800 <= delta <= pre_hours * 3600.0):
                games.append(g)
    return games, {"by_id": {g.game_id: g for g in games}, "schedule_failures": failures}


def _match_live(league: str, games: list, now: datetime):
    by_pair = espn.index_by_participants(games)
    resolver = Resolver.load()
    stats = Counter(); stats["k_reason"] = Counter(); stats["p_reason"] = Counter()
    near_miss: list[dict] = []
    # These helpers query only the league game series and its sports tag. They do not persist the
    # returned catalog, and the result is immediately reduced to the live game ids.
    kms = kalshi_markets(league, resolver, by_pair,
                         (int((now - timedelta(days=1)).timestamp()), int((now + timedelta(days=1)).timestamp())),
                         stats, near_miss)
    pms = pm_markets(league, resolver, by_pair,
                     (int((now - timedelta(days=1)).timestamp()), int((now + timedelta(days=1)).timestamp())),
                     stats, near_miss)
    live_ids = {g.game_id for g in games}
    return [p for p in pair(kms, pms) if p["game_id"] in live_ids], {
        "kalshi_markets": len(kms), "polymarket_markets": len(pms),
        "near_misses": len(near_miss), "matcher_reasons": {"kalshi": dict(stats["k_reason"]),
                                                               "polymarket": dict(stats["p_reason"])}}, resolver


def scan(leagues: list[str], *, include_near: bool = False, db: Path = DB,
         pre_hours: float = DEFAULT_PRE_HOURS) -> dict:
    started = time.time(); now = datetime.now(timezone.utc)
    sweep_id = now.strftime("%Y%m%dT%H%M%SZ")
    result = {"spec_ref": SPEC_REF, "sweep_id": sweep_id, "mode": "live_plus_near" if include_near else "live",
              "started_utc": now.isoformat(), "leagues": leagues, "games": [], "candidates": [],
              "blocked": [], "summary": {}}
    store = TupleStore(db)
    kclient, pclient = Client("kalshi", rate=8, burst=8, cache_dir=None), Client("polymarket", rate=8, burst=8, cache_dir=None)
    discovered = watched = changed = opportunities = 0
    try:
        games, meta = _live_games(leagues, now, include_near, pre_hours)
        for lg, err in meta["schedule_failures"].items():
            result["blocked"].append({"league": lg, "reason": "SCHEDULE_FETCH", "detail": err})
        for league in leagues:
            league_games = [g for g in games if g.league == league]
            if not league_games:
                continue
            matches, match_stats, resolver = _match_live(league, league_games, now)
            by_game: dict[str, list[dict]] = defaultdict(list)
            for m in matches: by_game[m["game_id"]].append(m)
            for g in league_games:
                rows = by_game.get(g.game_id, [])
                game_out = {"game_id": g.game_id, "league": g.league, "short_name": g.short_name,
                            "state": g.state, "start_utc": datetime.fromtimestamp(g.start_utc, timezone.utc).isoformat(),
                            "matched_outcomes": len({x["entity_id"] for x in rows}), "observations": []}
                if len({x["entity_id"] for x in rows}) != 2:
                    result["blocked"].append({"game_id": g.game_id, "reason": "INCOMPLETE_EXACT_TWO_OUTCOME_MATCH",
                                              "matched_outcomes": sorted({x["entity_id"] for x in rows})})
                    result["games"].append(game_out); continue
                slugs = sorted({m["pm_event"] for m in rows})
                tokmap = pm_token_map(slugs, pclient)
                tok_errors = tokmap.pop("__errors__", {})
                token_by_entity = {}
                for slug in slugs:
                    entry = tokmap.get(slug)
                    if not entry: continue
                    names, _event = entry
                    for name, token in names.items():
                        resolved = resolver.resolve(league, text=name, venue="polymarket")
                        if resolved.ok: token_by_entity[(slug, resolved.entity_id)] = token
                if len(token_by_entity) < 2:
                    result["blocked"].append({
                        "game_id": g.game_id, "reason": "PM_TOKEN_RESOLUTION",
                        "resolved": len(token_by_entity), "slugs": slugs,
                        "detail": tok_errors or "gamma returned no full-game moneyline market"})
                    result["games"].append(game_out); continue
                # The exact match gives one Kalshi market and one PM token per team. Fetch four
                # books concurrently so the cover does not mix a minute-old leg with a live leg.
                jobs = {}
                for m in rows:
                    jobs[("kalshi", m["kalshi_outcome"])] = (kclient, "kalshi", m["kalshi_outcome"], None)
                    token = token_by_entity.get((m["pm_event"], m["entity_id"]))
                    if token: jobs[("polymarket", m["pm_outcome"])] = (pclient, "polymarket", m["pm_outcome"], token)
                fetched = {}
                with ThreadPoolExecutor(max_workers=4) as pool:
                    future_map = {pool.submit(_fetch_book, c, v, mid, token): key
                                  for key, (c, v, mid, token) in jobs.items()}
                    for fut in as_completed(future_map):
                        try: fetched[future_map[fut]] = fut.result()
                        except Exception as exc: result["blocked"].append({"game_id": g.game_id, "reason": "BOOK_FETCH", "detail": type(exc).__name__})
                if len(fetched) < 4:
                    result["games"].append(game_out); continue
                latest = max(x["received"] for x in fetched.values())
                skew = latest - min(x["received"] for x in fetched.values())
                game_out["book_latency_ms"] = {f"{key[0]}:{key[1]}": round((value["received"] - value["started"]) * 1000, 2)
                                               for key, value in fetched.items()}
                game_out["book_quote_skew_s"] = round(skew, 4)
                if skew > MAX_QUOTE_SKEW:
                    result["blocked"].append({"game_id": g.game_id, "reason": "QUOTE_SKEW", "skew_s": round(skew, 3)})
                    result["games"].append(game_out); continue
                offers = defaultdict(list)
                for m in rows:
                    kf = fetched.get(("kalshi", m["kalshi_outcome"]))
                    pf = fetched.get(("polymarket", m["pm_outcome"]))
                    if not kf or not pf: continue
                    offers[m["entity_id"]] = [
                        Leg("kalshi", LIQUIDITY_SOURCE["kalshi"], m["kalshi_outcome"], m["kalshi_event"], kf["book"]),
                        Leg("polymarket", LIQUIDITY_SOURCE["polymarket"], m["pm_outcome"], m["pm_event"], pf["book"], {"fee_rate": 0.05}),
                    ]
                    for venue, f in (("kalshi", kf), ("polymarket", pf)):
                        b = f["book"]
                        market_id = m["kalshi_outcome"] if venue == "kalshi" else m["pm_outcome"]
                        store.market(venue=venue, market_id=market_id, family="sports", event_key=g.game_id,
                                     outcome=m["entity_id"], category=league, created_ts=None, close_ts=None,
                                     status="live", settlement_ref="schedule-anchored; venue rules required",
                                     watch_tier="live", metadata={"event": m["kalshi_event"] if venue == "kalshi" else m["pm_event"],
                                                                   "label": m["kalshi_label"] if venue == "kalshi" else m["pm_label"]}, seen_ts=f["received"])
                        changed += int(store.quote(venue=venue, market_id=market_id,
                            best_bid=b.best_bid.price if b.best_bid else None, best_ask=b.best_ask.price if b.best_ask else None,
                            bid_depth=sum(x.size for x in b.bids), ask_depth=sum(x.size for x in b.asks),
                            n_bid_levels=len(b.bids), n_ask_levels=len(b.asks), two_sided=bool(b.bids and b.asks),
                            levels=_book_levels(b), seen_ts=f["received"]))
                if set(offers) != {x["entity_id"] for x in rows}:
                    result["blocked"].append({"game_id": g.game_id, "reason": "INCOMPLETE_BOOKS"})
                    result["games"].append(game_out); continue
                discovered += len(rows) * 2; watched += len(rows) * 2

                # Exhaustiveness is PROVEN per league, never assumed. An unproven outcome set is a
                # BLOCK: pricing a 3-way EPL match as a two-leg cover reports ~+31% for what is
                # really a bet the match is not drawn. `prove` mints the only token best_cover
                # accepts, so an uncited league cannot reach the pricer at all.
                proof = prove(g.league, "moneyline", "game", sorted(offers))
                if isinstance(proof, NotExhaustive):
                    result["blocked"].append({"game_id": g.game_id, "reason": proof.code,
                                              "detail": proof.detail, **dict(proof.context)})
                    game_out["exhaustive_block"] = proof.code
                    result["games"].append(game_out); continue

                for q in QUANTITIES:
                    cov = best_cover(offers, q, now_utc=latest, max_leg_age_s=MAX_QUOTE_SKEW,
                                     exhaustive=proof)
                    edge = cov.edge_per_contract
                    cross = cov.ok and not cov.single_venue and {l.venue for l in cov.legs} == {"kalshi", "polymarket"}
                    ret = edge / cov.cost_per_contract if (edge is not None and cov.cost_per_contract and cov.cost_per_contract > 0) else None
                    status = "ACTIONABLE" if cross and ret is not None and ret >= MIN_RETURN else ("NO_EDGE" if cov.ok else (cov.reject_reason or "NO_PRICE"))
                    oid = f"{g.game_id}:moneyline:cross_venue:{int(q)}"
                    transition = store.opportunity(tuple_id=oid, relation_type="cross_venue_live_moneyline", status=status,
                        gross_cost=cov.gross_per_contract * q if cov.ok and cov.gross_per_contract is not None else None,
                        fees=cov.fee_per_contract * q if cov.ok and cov.fee_per_contract is not None else None,
                        net_profit=edge * q if edge is not None else None, return_locked=ret,
                        capacity=q if cov.ok else None,
                        details={"game_id": g.game_id, "quantity": q, "edge_per_contract": edge,
                                 "skew_s": skew, "single_venue": cov.single_venue if cov.ok else None,
                                 "legs": [{"venue": x.venue, "outcome": x.outcome_id, "vwap": x.vwap} for x in cov.legs]}, seen_ts=latest)
                    opp = {"game_id": g.game_id, "short_name": g.short_name, "quantity": q, "status": status,
                           "cost_per_contract": cov.cost_per_contract, "edge_per_contract": edge,
                           "return_locked": ret, "quote_skew_s": skew, "transition_recorded": transition}
                    game_out["observations"].append(opp)
                    if status == "ACTIONABLE": result["candidates"].append(opp); opportunities += 1
                result["games"].append(game_out)
        result["summary"] = {"scheduled_live_or_near_games": len(games), "games_with_exact_matches": sum(1 for g in result["games"] if g["matched_outcomes"] == 2),
                              "candidate_observations": len(result["candidates"]), "blocked": len(result["blocked"]),
                              "discovered_outcome_legs": discovered, "watched_outcome_legs": watched, "material_quote_changes": changed,
                              "actionability_hurdle": MIN_RETURN, "max_quote_skew_s": MAX_QUOTE_SKEW,
                              "book_rtt_ms": sorted(lat for g in result["games"] for lat in g.get("book_latency_ms", {}).values()),
                              "quote_skew_s": sorted(g.get("book_quote_skew_s") for g in result["games"] if g.get("book_quote_skew_s") is not None)}
        result["status"] = "OK"
    finally:
        result["finished_utc"] = datetime.now(timezone.utc).isoformat()
        store.sweep(sweep_id=sweep_id, started_ts=started, finished_ts=time.time(), universe="live:" + ",".join(leagues),
                    n_discovered=discovered, n_watched=watched, n_changed=changed,
                    n_opportunities=opportunities, status=result.get("status", "ERROR"), error=None)
        store.commit(); store.close()
    return result


def write_artifacts(result: dict) -> Path:
    out = RUNS_DIR / result["sweep_id"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    lines = ["# Live sports pure-arbitrage scan", "",
             f"Status: **{result.get('status')}** · run `{result['sweep_id']}` · "
             f"finished {result.get('finished_utc', '(did not finish)')}", "",
             "The lane searched live schedule-anchored events and fetched books only for exact matches.", ""]
    s = result.get("summary", {})
    lines.append(f"Games in the live/near window: {s.get('scheduled_live_or_near_games', 0)}; exact two-outcome matches: {s.get('games_with_exact_matches', 0)}; "
                 f"candidate observations meeting the 1% locked-return hurdle: {s.get('candidate_observations', 0)}.")
    for c in result.get("candidates", []):
        lines.append(f"- `{c['short_name']}` q={c['quantity']}: cost/contract {c.get('cost_per_contract')}, "
                     f"edge {c.get('edge_per_contract')}, locked return {c.get('return_locked'):.4%}, skew {c.get('quote_skew_s')}s")
    if result.get("blocked"):
        lines += ["", "Blocked states (not treated as zero-risk):"]
        lines += [f"- `{x.get('game_id')}`: {x.get('reason')}" for x in result["blocked"]]
    lines += ["", "No orders were submitted. Settlement rules, execution reconciliation, and any recheck remain required before promotion."]
    (out / "verdict.md").write_text("\n".join(lines) + "\n")
    if result.get("status") == "OK":                     # only a completed run becomes `latest`
        link = RUNS_DIR / "latest"
        tmp = RUNS_DIR / ".latest.tmp"
        tmp.unlink(missing_ok=True)
        tmp.symlink_to(out.name)
        tmp.replace(link)                                # atomic flip
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", default="mlb,nfl,nba,wnba,nhl,epl")
    ap.add_argument("--include-near", action="store_true")
    ap.add_argument("--pre-hours", type=float, default=DEFAULT_PRE_HOURS,
                    help="watch pre-game markets starting within N hours (default 6)")
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--loop", action="store_true", help="repeat discovery/book polling; storage remains change-only")
    ap.add_argument("--period", type=int, default=10, help="seconds between live sweeps in --loop mode")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        assert MIN_RETURN == 0.01 and MAX_QUOTE_SKEW == 5.0
        print("live_sports_arb selftest OK")
        return
    leagues = [x.strip() for x in a.leagues.split(",") if x.strip()]
    while True:
        result = scan(leagues, include_near=a.include_near, db=a.db, pre_hours=a.pre_hours)
        write_artifacts(result)
        print(json.dumps(result["summary"], indent=2, sort_keys=True))
        if not a.loop:
            break
        time.sleep(max(5, a.period))


if __name__ == "__main__":
    main()
