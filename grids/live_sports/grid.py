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
import os
import signal
import sys
import traceback
import csv
import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
from nodes.fees.targeting import hurdle_for  # noqa: E402
from nodes.store_tuples.store import TupleStore  # noqa: E402
from ops import run_index  # noqa: E402

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
        # BOTH sides from the SAME payload, at no extra request. A Kalshi event carries one market
        # per participant, and buying NO on the other participant's market is the same exposure as
        # buying YES on this one -- a different order book with its own depth and its own price.
        # Reading only the YES ladder of each market ignored roughly half the available liquidity
        # on every pair, which understated every capacity number the frontier reports.
        now_ts = time.time()
        book = kalshi_book(payload, "yes", now_ts)
        no_book = kalshi_book(payload, "no", now_ts)
        return {"book": book, "no_book": no_book, "started": started, "received": time.time(),
                "venue": venue, "market_id": market_id}
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


@dataclass
class Discovery:
    """The slate: which markets to watch, on which venue, for which canonical outcome.

    Discovery is SLOW (ESPN per league, a paginated Kalshi pull, a paginated PM Gamma pull, then
    one Gamma call per slug) and changes on the order of minutes -- games start, games end, new
    markets list. Book polling is FAST and is the only thing that needs to run every few seconds.
    Recomputing the slate on every sweep hammered three APIs to re-derive a nearly identical
    answer; this splits the two clocks.
    """
    made_utc: float
    games: list
    schedule_failures: dict[str, str]
    per_league: dict            # league -> (matches, match_stats, resolver)
    tokens: dict                # slug -> ({outcome_label: token}, event)
    token_errors: dict[str, str]

    def age_s(self, now: float | None = None) -> float:
        return (now or time.time()) - self.made_utc


def discover(leagues: list[str], now: datetime, include_near: bool, pre_hours: float,
             pclient: Client) -> Discovery:
    """Build the watch set. Every failure is recorded, none is fatal."""
    games, meta = _live_games(leagues, now, include_near, pre_hours)
    per_league, slugs = {}, set()
    for league in leagues:
        lg_games = [g for g in games if g.league == league]
        if not lg_games:
            continue
        try:
            matches, stats, resolver = _match_live(league, lg_games, now)
        except Exception as exc:  # noqa: BLE001 -- one league must not take the slate down
            meta["schedule_failures"][league] = f"match: {type(exc).__name__}: {exc}"
            continue
        per_league[league] = (matches, stats, resolver)
        slugs |= {m["pm_event"] for m in matches}
    tokens = pm_token_map(sorted(slugs), pclient) if slugs else {}
    token_errors = tokens.pop("__errors__", {})
    return Discovery(time.time(), games, meta["schedule_failures"], per_league, tokens, token_errors)


def scan(leagues: list[str], *, include_near: bool = False, db: Path = DB,
         pre_hours: float = DEFAULT_PRE_HOURS,
         discovery: Discovery | None = None) -> dict:
    started = time.time(); now = datetime.now(timezone.utc)
    sweep_id = now.strftime("%Y%m%dT%H%M%SZ")
    result = {"spec_ref": SPEC_REF, "sweep_id": sweep_id, "mode": "live_plus_near" if include_near else "live",
              "started_utc": now.isoformat(), "leagues": leagues, "games": [], "candidates": [],
              "blocked": [], "summary": {}}
    store = TupleStore(db)
    kclient, pclient = Client("kalshi", rate=8, burst=8, cache_dir=None), Client("polymarket", rate=8, burst=8, cache_dir=None)
    discovered = watched = changed = opportunities = 0
    try:
        d = discovery or discover(leagues, now, include_near, pre_hours, pclient)
        result["discovery_age_s"] = round(d.age_s(), 1)
        games = d.games
        for lg, err in d.schedule_failures.items():
            result["blocked"].append({"league": lg, "reason": "SCHEDULE_FETCH", "detail": err})
        for league in leagues:
            league_games = [g for g in games if g.league == league]
            if not league_games or league not in d.per_league:
                continue
            matches, match_stats, resolver = d.per_league[league]
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
                tokmap, tok_errors = d.tokens, d.token_errors
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
                by_entity = {m["entity_id"]: m for m in rows}
                for m in rows:
                    kf = fetched.get(("kalshi", m["kalshi_outcome"]))
                    pf = fetched.get(("polymarket", m["pm_outcome"]))
                    if not kf or not pf: continue
                    legs = [
                        Leg("kalshi", LIQUIDITY_SOURCE["kalshi"], m["kalshi_outcome"], m["kalshi_event"], kf["book"]),
                        Leg("polymarket", LIQUIDITY_SOURCE["polymarket"], m["pm_outcome"], m["pm_event"], pf["book"], {"fee_rate": 0.05}),
                    ]
                    # The complementary market's NO ladder is the same exposure from a different
                    # book. Its outcome_id is that market's ticker, so the liquidity_source guard
                    # still catches a genuine double-count of one book.
                    other = next((x for e, x in by_entity.items() if e != m["entity_id"]), None)
                    if other is not None:
                        okf = fetched.get(("kalshi", other["kalshi_outcome"]))
                        if okf and okf.get("no_book") and okf["no_book"].asks:
                            legs.append(Leg("kalshi", LIQUIDITY_SOURCE["kalshi"],
                                            f"{other['kalshi_outcome']}:NO", other["kalshi_event"],
                                            okf["no_book"]))
                    offers[m["entity_id"]] = legs
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
                    # HOW FAR AWAY was this, and how far away COULD it be? The lane used to
                    # record only ACTIONABLE/NO_EDGE, which collapses "the venues disagree but
                    # fees ate it" and "the venues agree" into one uninformative null. The fee
                    # hurdle is computable in advance from the price, so record the distance to
                    # actionable in cents -- that is the near-miss channel, empty since August.
                    fav = max((l.vwap for l in cov.legs), default=None) if cov.ok else None
                    hd = hurdle_for(fav, hurdle=MIN_RETURN) if fav is not None else None
                    gross = cov.gross_per_contract if cov.ok else None
                    opp = {"game_id": g.game_id, "short_name": g.short_name, "quantity": q, "status": status,
                           "cost_per_contract": cov.cost_per_contract, "edge_per_contract": edge,
                           "return_locked": ret, "quote_skew_s": skew, "transition_recorded": transition,
                           "gross_per_contract": gross,
                           "fee_per_contract": cov.fee_per_contract if cov.ok else None,
                           "required_ask_sum": hd.required_ask_sum if hd else None,
                           "fee_hurdle_cents": round(hd.gap_needed_cents, 3) if hd else None,
                           "cents_from_actionable": (round((gross - hd.required_ask_sum) * 100.0, 3)
                                                     if (hd and gross is not None) else None)}
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


#: How often the slate is rebuilt. Games start and end on the order of minutes; markets do not
#: appear every ten seconds. Book polling runs on its own, much faster clock.
DEFAULT_DISCOVERY_PERIOD = 300

_STOP = False


def _on_signal(signum, _frame):
    """SIGTERM/SIGINT set a flag; the loop finishes its sweep and records an outcome.

    Dying mid-sweep is what leaves a start row with no finish row, which the watchdog then has to
    report as CRASHED. A clean stop should look clean.
    """
    global _STOP
    _STOP = True
    print(f"\n[signal {signum}] finishing the current sweep, then stopping", flush=True)


def _interesting(result: dict) -> bool:
    """Does this sweep deserve a durable artifact directory?

    At a 10 s period an unconditional write is 8,640 directories a day, almost all identical. The
    SQLite store already keeps change-gated history, so the run directory is for sweeps a human
    would want to open: a candidate, a block, or a failure.
    """
    return bool(result.get("candidates") or result.get("blocked")
                or result.get("status") != "OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", default="mlb,nfl,nba,wnba,nhl,epl")
    ap.add_argument("--include-near", action="store_true")
    ap.add_argument("--pre-hours", type=float, default=DEFAULT_PRE_HOURS,
                    help="watch pre-game markets starting within N hours (default 6)")
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--loop", action="store_true", help="repeat book polling; storage stays change-only")
    ap.add_argument("--period", type=int, default=10, help="seconds between book sweeps in --loop mode")
    ap.add_argument("--discovery-period", type=int, default=DEFAULT_DISCOVERY_PERIOD,
                    help="seconds between slate rebuilds (default 300)")
    ap.add_argument("--heartbeat", type=int, default=900,
                    help="write an artifact at least this often even when nothing is interesting")
    ap.add_argument("--max-sweeps", type=int, default=0, help="stop after N sweeps (0 = unbounded)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()

    if a.self_test:
        from nodes.rules_exhaustive.rules import NotExhaustive, prove
        assert isinstance(prove("epl", "moneyline", "game", ["a", "b"]), NotExhaustive), \
            "3-way EPL must not prove exhaustive"
        assert isinstance(prove("nfl", "moneyline", "game", ["a", "b"]), NotExhaustive), \
            "NFL can tie; it must not prove exhaustive"
        assert prove("mlb", "moneyline", "game", ["a", "b"]).rule_id == "mlb_no_draw"
        d = discover(["mlb"], datetime.now(timezone.utc), True, 6.0,
                     Client("polymarket", rate=3, burst=6, cache_dir=None))
        assert d.games, "no MLB games discovered; the slate is empty"
        print(f"live_sports selftest OK — {len(d.games)} games, "
              f"{sum(len(v[0]) for v in d.per_league.values())} matched legs, "
              f"{len(d.tokens)} PM token maps")
        return

    leagues = [x.strip() for x in a.leagues.split(",") if x.strip()]
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    # A start row BEFORE any work, so a crash during discovery still leaves a trace. ops/watchdog.py
    # reads this; a job that starts and never finishes is exactly the shape convergence had for
    # thirteen undetected days.
    # ops/run_node.sh already opened a run and exported its id. Writing a second pair of rows
    # would give the watchdog two run_ids for one process; defer to the wrapper when it is there.
    ambient = os.environ.get("JANUS_RUN_ID")
    run_id = ambient or run_index.start("live_sports", argv=sys.argv[1:])
    owns_row = ambient is None
    exit_code, final_status = 0, "OK"

    pclient = Client("polymarket", rate=8, burst=8, cache_dir=None)
    d: Discovery | None = None
    sweeps = consecutive_errors = 0
    last_artifact = 0.0

    while not _STOP:
        try:
            if d is None or d.age_s() > a.discovery_period:
                d = discover(leagues, datetime.now(timezone.utc), a.include_near, a.pre_hours, pclient)
                print(f"[slate] {len(d.games)} games, {len(d.tokens)} token maps"
                      f"{', failures: ' + str(d.schedule_failures) if d.schedule_failures else ''}",
                      flush=True)
            result = scan(leagues, include_near=a.include_near, db=a.db,
                          pre_hours=a.pre_hours, discovery=d)
            consecutive_errors = 0
        except Exception as exc:  # noqa: BLE001 -- a sweep must never take the loop down
            consecutive_errors += 1
            print(f"[sweep FAILED {consecutive_errors}] {type(exc).__name__}: {exc}", flush=True)
            traceback.print_exc()
            d = None                                   # rebuild the slate; it may be the cause
            if consecutive_errors >= 10:
                print("[fatal] 10 consecutive sweep failures; stopping rather than spinning",
                      flush=True)
                if owns_row:
                    run_index.finish("live_sports", run_id, exit_code=1, status="FAILED",
                                     sweeps=sweeps, error=f"{type(exc).__name__}: {exc}")
                raise
            time.sleep(min(60, 2 ** consecutive_errors))
            continue

        sweeps += 1
        s = result["summary"]
        due = (time.time() - last_artifact) > a.heartbeat
        if _interesting(result) or due:
            out = write_artifacts(result)
            last_artifact = time.time()
        else:
            out = None
        print(f"[{result['sweep_id']}] games={s['scheduled_live_or_near_games']} "
              f"matched={s['games_with_exact_matches']} legs={s['watched_outcome_legs']} "
              f"blocked={s['blocked']} candidates={s['candidate_observations']} "
              f"changed={s['material_quote_changes']}"
              f"{'  -> ' + out.name if out else ''}", flush=True)
        for c in result.get("candidates", []):
            print(f"  *** CANDIDATE {c['short_name']} q={c['quantity']} "
                  f"cost={c['cost_per_contract']:.4f} return={c['return_locked']:+.3%}", flush=True)

        if not a.loop or (a.max_sweeps and sweeps >= a.max_sweeps):
            break
        for _ in range(max(1, a.period)):              # responsive to a signal
            if _STOP:
                break
            time.sleep(1)

    if owns_row:
        run_index.finish("live_sports", run_id, exit_code=exit_code, status=final_status,
                         sweeps=sweeps, leagues=",".join(leagues))
    print(f"[stopped] {sweeps} sweeps, recorded as {final_status} (run {run_id})", flush=True)


if __name__ == "__main__":
    main()
