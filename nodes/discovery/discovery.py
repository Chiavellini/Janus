#!/usr/bin/env python3
"""The event registry: which games exist, which are co-listed, and what each venue charges.

Discovery is SLOW (ESPN per league, a paginated Kalshi pull, a paginated Gamma pull, one Gamma
call per slug, one series call per league) and changes on the order of minutes -- games start,
games end, markets list. Everything downstream is fast and runs on its own clock. Recomputing the
slate on every sweep hammered three APIs to re-derive a nearly identical answer, so this node
builds it once per discovery period and hands out a frozen `Discovery`.

This used to live inside `grids/live_sports`, and `grids/live_stream` imported it from there --
a grid importing a grid, which the layering rule forbids because it makes a failure attributable
to two places. It is a node now. Grids compose it; nothing here imports a grid.

WHAT A SLATE ENTRY CARRIES. Besides the four market ids, each co-listed game carries the fee
params each venue REPORTED for it: Kalshi's `fee_type`/`fee_multiplier` from the league's game
series and Polymarket's `feeSchedule` from the Gamma market. Measured on 2026-09-02: KXMLBGAME is
`quadratic_with_maker_fees` at 0.5x, and an MLB Gamma market carried rate 0.03 -- against the 1.0x
and 0.05 the lane had been charging. A venue whose schedule could not be fetched is simply absent
from `fee_params`, and `nodes/game_poller` then blocks that leg with FEE_SCHEDULE_MISSING rather
than pricing it on a constant.

Persistence: the `events` table is this node's own (see `EVENTS_DDL`), keyed by the ESPN game id.
It is the stable `event_id` that per-event risk limits, kill-by-event and event-focused storage
will key on.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Mapping

from kernel.fetch import Client
from kernel.redact import brief_error
from nodes.entities.resolve import Resolver, normalize
from nodes.discovery.venue_schedule import fetch_schedule
from nodes.entities.leagues import LEAGUES, venue_structured
from nodes.entities.seed import KALSHI_GAME_SERIES, NON_TEAM_OUTCOMES
from nodes.match_sports.sports_match import DRAW_ENTITY, kalshi_markets, pair, pm_markets, seed_live_players, pull_pm, _client
from nodes.schedule_espn import espn
from nodes.settle_wedge.pair import certify_from_spec, records_from_spec, summary
from nodes.settle_wedge.records import record_equivalence, record_rules
from nodes.venue_kalshi.books import fetch_kalshi_series, kalshi_fee_params
from nodes.venue_polymarket.books import pm_outcome_no_tokens, pm_fee_params, pm_order_limits, pm_primary_market, pm_token_map

#: Hours ahead of first pitch/puck to start watching a pre-game market.
DEFAULT_PRE_HOURS = 6.0
#: The rolling event universe (spec §3). Kalshi lists a game ~72 h out, Polymarket ~82 h; 48 h is
#: what both venues reliably cover, and it bounds the registry.
UNIVERSE_HOURS = 48.0
#: Priority tiers, in the order the spec ranks them. `tier_of` assigns exactly one per game.
TIERS = ("live", "starting_soon", "newborn", "recently_listed", "closing_soon", "long_term")
SOON_S = 2 * 3600            # starts within two hours
NEWBORN_S = 6 * 3600         # listed within the last six hours
RECENT_S = 24 * 3600         # listed within the last day
#: A market is thinnest and most dislocated right at the open; keep watching a game that started
#: up to this long ago even if ESPN still says "pre" (its state lags).
DEFAULT_LEAD_S = 1800


# ── the schedule half ────────────────────────────────────────────────────────
def select_live(schedule: list, now_ts: float, include_near: bool, pre_hours: float,
                *, lead_s: int = DEFAULT_LEAD_S) -> list:
    """PURE. In-progress games, plus (optionally) pre-game ones starting within `pre_hours`."""
    out = []
    for g in schedule:
        delta = g.start_utc - now_ts
        if g.state == "in" or (include_near and g.state == "pre"
                               and -lead_s <= delta <= pre_hours * 3600.0):
            out.append(g)
    return out


def tier_of(g, now_ts: float, *, first_seen_ts: float | None = None) -> str:
    """PURE. One tier per game, by the spec's priority order. `first_seen_ts` is when the registry
    first saw the game co-listed (the events table's first_seen), which is what "newborn" and
    "recently listed" mean; without it those two tiers cannot be claimed."""
    delta = g.start_utc - now_ts
    if g.state == "in":
        return "live"
    if g.state == "pre" and -DEFAULT_LEAD_S <= delta <= SOON_S:
        return "starting_soon"
    if first_seen_ts is not None:
        age = now_ts - first_seen_ts
        if age <= NEWBORN_S:
            return "newborn"
        if age <= RECENT_S:
            return "recently_listed"
    if delta <= UNIVERSE_HOURS * 3600:
        return "closing_soon"
    return "long_term"


def universe(schedule: list, now_ts: float, *, hours: float = UNIVERSE_HOURS) -> list:
    """PURE. Every game not yet over that starts inside the rolling horizon."""
    return [g for g in schedule if g.state != "post" and -DEFAULT_LEAD_S <= g.start_utc - now_ts <= hours * 3600]


def live_games(leagues: list[str], now: datetime, include_near: bool,
               pre_hours: float = DEFAULT_PRE_HOURS) -> tuple[list, dict]:
    """The schedule side. One league's ESPN failure is recorded, never fatal for the others."""
    games, universe, failures = [], [], {}
    horizon = max(UNIVERSE_HOURS / 24.0, pre_hours / 24.0 + 1.0)
    t = now.timestamp()
    for league in leagues:
        try:
            if league in venue_structured():
                # No ESPN anchor: the schedule is Polymarket's own game events (nodes/discovery/venue_schedule).
                schedule = fetch_schedule(league, now)
            else:
                schedule = espn.fetch_range(league, now - timedelta(days=1),
                                            now + timedelta(days=horizon), use_cache=False)
        except Exception as exc:  # noqa: BLE001 -- one league must not take the others down
            failures[league] = brief_error(exc)
            continue
        games.extend(select_live(schedule, t, include_near, pre_hours))
        # The rolling universe (UNIVERSE_HOURS): what the matchers pair against, so a venue's
        # ticker for a game 6-48 h out is a pair waiting, not "outside_window" (2026-09-07).
        universe.extend(g for g in schedule if -86400 <= g.start_utc - t <= UNIVERSE_HOURS * 3600)
    return games, {"by_id": {g.game_id: g for g in games}, "schedule_failures": failures, "universe": universe}


def match_live(league: str, games: list, now: datetime, universe: list | None = None):
    """Both venues resolved onto the schedule independently, then an exact join. `games` is the
    live set (what may spawn); `universe` (default: `games`) is what the venues' markets pair
    against, up to UNIVERSE_HOURS out."""
    by_pair = espn.index_by_participants(universe if universe else games)
    resolver = Resolver.load()
    stats = Counter(); stats["k_reason"] = Counter(); stats["p_reason"] = Counter()
    near_miss: list[dict] = []
    window = (int((now - timedelta(days=1)).timestamp()), int((now + timedelta(hours=UNIVERSE_HOURS)).timestamp()))
    pm_events = None
    if league in venue_structured():
        # Tennis: the players are whoever Polymarket lists today. Seeded into the resolver
        # BEFORE the Kalshi pass, so a Kalshi market's full-name label resolves to the same
        # entity (2026-09-07: Swiatek v Zheng, in play on both venues, had no entity row).
        pm_events = pull_pm(league, _client("polymarket"))
        stats["players_seeded"] = seed_live_players(league, resolver, pm_events)
    kms = kalshi_markets(league, resolver, by_pair, window, stats, near_miss)
    pms = pm_markets(league, resolver, by_pair, window, stats, near_miss, events=pm_events)
    live_ids = {g.game_id for g in games}
    return [p for p in pair(kms, pms) if p["game_id"] in live_ids], {
        "kalshi_markets": len(kms), "polymarket_markets": len(pms),
        "near_misses": len(near_miss),
        # The named reason for every venue market that did not pair, and the games each venue
        # DID match. Both were computed and thrown away until 2026-09-07 (GATE step 1 promised
        # "every unmatched game in a named reason bucket; zero silent drops").
        "near_miss": near_miss,
        "kalshi_games": sorted(stats.get("k_games") or ()),
        "polymarket_games": sorted(stats.get("p_games") or ()),
        "matcher_reasons": {"kalshi": dict(stats["k_reason"]), "polymarket": dict(stats["p_reason"])},
    }, resolver


# ── the fee half ─────────────────────────────────────────────────────────────
def kalshi_league_fees(leagues: list[str], kclient: Client,
                       series_out: dict | None = None) -> tuple[dict[str, dict], dict[str, str]]:
    """league -> {fee_type, fee_multiplier} from the league's game series. Failures are named.
    The raw series record lands in `series_out` (settlement_sources ride with the rules)."""
    out, errors = {}, {}
    for league in leagues:
        ticker = KALSHI_GAME_SERIES.get(league)
        if not ticker:
            errors[league] = "no game series registered for league"
            continue
        try:
            raw = fetch_kalshi_series(ticker, kclient)
            if series_out is not None:
                series_out[league] = raw
            fp = kalshi_fee_params(raw)
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            errors[league] = brief_error(exc)
            continue
        if fp is None:
            errors[league] = f"{ticker} carries no fee_type/fee_multiplier"
            continue
        out[league] = fp
    return out, errors


# ── the slate ────────────────────────────────────────────────────────────────
@dataclass
class Discovery:
    """The frozen answer to 'what should be watched right now, and on what terms'."""
    made_utc: float
    games: list
    schedule_failures: dict[str, str]
    per_league: dict            # league -> (matches, match_stats, resolver)
    tokens: dict                # slug -> ({outcome_label: token}, event)
    token_errors: dict[str, str]
    #: venue -> key -> params. Kalshi is keyed by LEAGUE (one series per league); Polymarket by
    #: SLUG (one schedule per market). Absent = never fetched = the poller blocks that leg.
    fee_params: dict[str, dict[str, dict]] = field(default_factory=lambda: {"kalshi": {}, "polymarket": {}})
    fee_errors: dict[str, dict[str, str]] = field(default_factory=dict)
    series: dict[str, dict] = field(default_factory=dict)    # league -> raw Kalshi series record

    def age_s(self, now: float | None = None) -> float:
        return (now or time.time()) - self.made_utc


def discover(leagues: list[str], now: datetime, include_near: bool, pre_hours: float,
             pclient: Client, kclient: Client | None = None) -> Discovery:
    """Build the watch set. Every failure is recorded, none is fatal."""
    games, meta = live_games(leagues, now, include_near, pre_hours)
    per_league, slugs = {}, set()
    for league in leagues:
        lg_games = [g for g in games if g.league == league]
        if not lg_games:
            continue
        lg_universe = [g for g in meta.get("universe") or () if g.league == league]
        try:
            matches, stats, resolver = match_live(league, lg_games, now, universe=lg_universe)
        except Exception as exc:  # noqa: BLE001 -- one league must not take the slate down
            meta["schedule_failures"][league] = f"match: {brief_error(exc)}"
            continue
        per_league[league] = (matches, stats, resolver)
        slugs |= {m["pm_event"] for m in matches}
    tokens = pm_token_map(sorted(slugs), pclient) if slugs else {}
    token_errors = tokens.pop("__errors__", {})

    pm_fees: dict[str, dict] = {}
    pm_fee_errors: dict[str, str] = {}
    for slug, (_names, ev) in tokens.items():
        fp = pm_fee_params(pm_primary_market(ev, slug) or {})
        if fp is None:
            pm_fee_errors[slug] = "gamma market carries no feeSchedule"
        else:
            pm_fees[slug] = fp
    series: dict[str, dict] = {}
    k_fees, k_errors = ({}, {}) if not per_league else kalshi_league_fees(
        sorted(per_league), kclient or Client("kalshi", rate=4, burst=8, cache_dir=None), series)
    return Discovery(time.time(), games, meta["schedule_failures"], per_league, tokens, token_errors,
                     fee_params={"kalshi": k_fees, "polymarket": pm_fees},
                     fee_errors={"kalshi": k_errors, "polymarket": pm_fee_errors}, series=series)


def co_listed(d: Discovery, *, first_seen: Mapping[str, float] | None = None,
              now: float | None = None) -> tuple[dict[str, dict], dict[str, str]]:
    """PURE over a Discovery. game_id -> slate spec for every game live on BOTH venues, plus a
    game_id -> reason map for everything that was not. This is what the supervisor spawns from.

    A spec carries: league, short_name, state, start_utc, outcomes (entity -> {venue: market_id}),
    fee_params (venue -> params, only for venues whose schedule was fetched), pm_slug,
    kalshi_event, and the PM order limits when Gamma reported them.
    """
    slate: dict[str, dict] = {}
    blocked: dict[str, str] = {}
    for lg, err in d.schedule_failures.items():
        blocked[lg] = f"SCHEDULE_FETCH: {err}"
    games_by_id = {g.game_id: g for g in d.games}
    for league, (matches, _stats, resolver) in d.per_league.items():
        n_out = LEAGUES[league].outcomes if league in LEAGUES else 2
        tok_by: dict[tuple, str] = {}
        for slug, (names, _ev) in d.tokens.items():
            for name, token in names.items():
                if name == "Draw":
                    tok_by[(slug, DRAW_ENTITY)] = token
                    continue
                res = resolver.resolve(league, text=name, venue="polymarket")
                if res.ok:
                    tok_by[(slug, res.entity_id)] = token
        by_game: dict[str, dict] = {}
        for m in matches:
            by_game.setdefault(m["game_id"], {})[m["entity_id"]] = m
            # A tennis market labels its outcomes by surname ("Siegemund") while the event names the
            # player in full; when the label resolves to nothing, the participant whose full name
            # ends with the label owns the token. Exact suffix on normalised text, never a score.
            slug, label = m["pm_event"], m.get("pm_label") or ""
            if slug in d.tokens and (slug, m["entity_id"]) not in tok_by:
                full = normalize(label)
                for name, token in d.tokens[slug][0].items():
                    n = normalize(name)
                    if n and (full == n or full.endswith(" " + n)):
                        tok_by[(slug, m["entity_id"])] = token
                        break
        for gid, rows in by_game.items():
            g = games_by_id.get(gid)
            if g is None or len(rows) != n_out:
                blocked[gid] = "INCOMPLETE_EXACT_TWO_OUTCOME_MATCH" if n_out == 2 else "INCOMPLETE_EXACT_THREE_OUTCOME_MATCH"
                continue
            outcomes: dict[str, dict] = {}
            slug = next(iter(rows.values()))["pm_event"]
            # Three-way: the NO token of each TEAM market pays on the other two outcomes, which
            # is how a soccer cover is executed as two legs (nodes/game_poller, nodes/cover).
            no_by_label = pm_outcome_no_tokens(d.tokens.get(slug, (None, {}))[1] or {}, slug) if n_out == 3 else {}
            no_by_ent: dict[str, str] = {}
            for name, tok_no in no_by_label.items():
                res = resolver.resolve(league, text=name, venue="polymarket")
                if res.ok:
                    no_by_ent[res.entity_id] = tok_no
            for ent, m in rows.items():
                tok = tok_by.get((m["pm_event"], ent))
                if not tok:
                    break
                outcomes[ent] = {"kalshi": m["kalshi_outcome"], "polymarket": tok}
                if ent in no_by_ent:
                    outcomes[ent]["polymarket_no"] = no_by_ent[ent]
            if len(outcomes) != n_out:
                detail = d.token_errors.get(slug)
                blocked[gid] = "PM_TOKEN_RESOLUTION" + (f": {detail}" if detail else "")
                continue
            fees: dict[str, dict] = {}
            if league in d.fee_params.get("kalshi", {}):
                fees["kalshi"] = dict(d.fee_params["kalshi"][league])
            if slug in d.fee_params.get("polymarket", {}):
                fees["polymarket"] = dict(d.fee_params["polymarket"][slug])
            ev = d.tokens.get(slug, (None, {}))[1]
            # The venues' settlement text rides with the spec, so the supervisor and the replay
            # certify from the same words discovery read, and the store keeps them.
            # The rules text of a TEAM market. The draw's own text differs ("If Tie is the result",
            # Polymarket's draw cancellation clause) and is not the template the policy is keyed on.
            first = next((m for ent, m in rows.items() if ent != DRAW_ENTITY), next(iter(rows.values())))
            # Participants for the template normaliser: team names only. The draw's labels ("Tie",
            # "Draw") are rule words in the venues' own texts; stripping them would change the hash.
            names = sorted({x for m in rows.values() for x in (m.get("kalshi_label"), m.get("pm_label"))
                            if x and normalize(x) not in NON_TEAM_OUTCOMES} | {g.home_name, g.away_name})
            k_rules = dict(first.get("kalshi_rules") or {})
            p_rules = dict(first.get("pm_rules") or {})
            spec = {"league": league, "short_name": g.short_name, "state": g.state,
                    "tier": tier_of(g, now or d.made_utc, first_seen_ts=(first_seen or {}).get(gid)),
                    "start_utc": g.start_utc, "outcomes": outcomes, "fee_params": fees,
                    "pm_slug": slug, "kalshi_event": first["kalshi_event"],
                    "pm_limits": pm_order_limits(pm_primary_market(ev, slug) or {}),
                    "rules": {"kalshi": {"market": k_rules, "participants": names,
                                         "series": d.series.get(league)},
                              "polymarket": {"market": p_rules, "participants": names},
                              "retrieved_at": d.made_utc}}
            spec["settlement"] = summary(certify_from_spec(spec, league))
            slate[gid] = spec
    # Every game in the window that is on neither the slate nor an explicit block says which venue
    # side was missing. The events table carries it (record_events), the supervisor prints it
    # once, and ops/coverage_report.py reads it beside the census.
    for league, (_matches, stats, _r) in d.per_league.items():
        k_games = set(stats.get("kalshi_games") or ())
        p_games = set(stats.get("polymarket_games") or ())
        for g in d.games:
            if g.league != league or g.game_id in slate or g.game_id in blocked:
                continue
            blocked[g.game_id] = (f"UNPAIRED:kalshi={'found' if g.game_id in k_games else 'missing'},"
                                  f"polymarket={'found' if g.game_id in p_games else 'missing'}")
    return slate, blocked


# ── the registry on disk ─────────────────────────────────────────────────────
EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS events(
  event_id TEXT PRIMARY KEY, league TEXT NOT NULL, start_utc INTEGER, participants TEXT,
  short_name TEXT, phase TEXT NOT NULL, kalshi_event TEXT, pm_slug TEXT, fee_params_json TEXT,
  spec_json TEXT, first_seen_ts REAL NOT NULL, last_seen_ts REAL NOT NULL, block_reason TEXT, tier TEXT);
CREATE TABLE IF NOT EXISTS event_transitions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, seen_ts REAL NOT NULL, event_id TEXT NOT NULL,
  phase TEXT NOT NULL, block_reason TEXT);
CREATE INDEX IF NOT EXISTS event_transitions_event ON event_transitions(event_id, seen_ts);
"""


def record_spawn_block(store, event_id: str, reason: str, *, now: float | None = None) -> None:
    """A co-listed game the lane refused to spawn a poller for (unproven outcome set or settlement
    basis) gets its reason on the event's row and a transition, so the record explains an
    evening without a poller. `record_events` carries the reason forward while the game stays on
    the slate (the supervisor passes it back in `blocked`)."""
    t = now or time.time()
    store.ensure_ddl(EVENTS_DDL)
    row = store.con.execute("SELECT phase, block_reason FROM events WHERE event_id=?", (event_id,)).fetchone()
    if row is None:
        return
    if row[1] != reason:
        store.con.execute("UPDATE events SET block_reason=?, last_seen_ts=? WHERE event_id=?", (reason, t, event_id))
        store.con.execute("INSERT INTO event_transitions(seen_ts, event_id, phase, block_reason) VALUES(?,?,?,?)",
                          (t, event_id, row[0], reason))
        store.con.commit()


def record_events(store, d: Discovery, slate: Mapping[str, dict], blocked: Mapping[str, str],
                  *, now: float | None = None) -> int:
    """Upsert every discovered game; append a transition only when phase or block changes.

    Returns the number of transitions written. `store` is a `nodes/store_tuples.TupleStore`
    (anything with `.ensure_ddl` and `.con` works). Phase is ESPN's state (`pre|in|post`) with
    `co_listed` recorded alongside so the registry says which games actually had four books.
    """
    t = now or time.time()
    store.ensure_ddl(EVENTS_DDL)
    con = store.con
    written = 0
    for g in d.games:
        spec = slate.get(g.game_id)
        phase = f"{g.state}:co_listed" if spec else g.state
        tier = spec.get("tier") if spec else None
        reason = blocked.get(g.game_id)
        row = con.execute("SELECT phase, block_reason FROM events WHERE event_id=?",
                          (g.game_id,)).fetchone()
        con.execute(
            "INSERT INTO events(event_id, league, start_utc, participants, short_name, phase, "
            "kalshi_event, pm_slug, fee_params_json, spec_json, first_seen_ts, last_seen_ts, block_reason, tier) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET "
            "phase=excluded.phase, kalshi_event=COALESCE(excluded.kalshi_event, events.kalshi_event), "
            "pm_slug=COALESCE(excluded.pm_slug, events.pm_slug), "
            "fee_params_json=COALESCE(excluded.fee_params_json, events.fee_params_json), "
            "spec_json=COALESCE(excluded.spec_json, events.spec_json), "
            "last_seen_ts=excluded.last_seen_ts, block_reason=excluded.block_reason, tier=excluded.tier",
            (g.game_id, g.league, g.start_utc, json.dumps(list(g.participants_espn)), g.short_name,
             phase, spec["kalshi_event"] if spec else None, spec["pm_slug"] if spec else None,
             json.dumps(spec["fee_params"], sort_keys=True) if spec else None,
             json.dumps(spec, sort_keys=True) if spec else None, t, t, reason, tier))
        if row is None or (row[0], row[1]) != (phase, reason):
            con.execute("INSERT INTO event_transitions(seen_ts, event_id, phase, block_reason) "
                        "VALUES(?,?,?,?)", (t, g.game_id, phase, reason))
            written += 1
        if spec:
            recs = records_from_spec(spec)
            if recs is not None:
                record_rules(store, recs[0]); record_rules(store, recs[1])
                record_equivalence(store, event_id=g.game_id, league=g.league, rec_a=recs[0],
                                   rec_b=recs[1], result=certify_from_spec(spec, g.league), now=t)
    return written


def load_specs(store, *, game_ids: list[str] | None = None) -> dict[str, dict]:
    """The slate specs the supervisor spawned from, straight from the events table. What
    `nodes/replay` rebuilds its pollers from."""
    store.ensure_ddl(EVENTS_DDL)
    rows = store.con.execute("SELECT event_id, spec_json FROM events WHERE spec_json IS NOT NULL").fetchall()
    out = {gid: json.loads(spec) for gid, spec in rows}
    if game_ids is not None:
        out = {g: s for g, s in out.items() if g in game_ids}
    return out


def first_seen(store) -> dict[str, float]:
    """event_id -> first_seen_ts from the registry, for the newborn / recently-listed tiers."""
    store.ensure_ddl(EVENTS_DDL)
    return {r[0]: r[1] for r in store.con.execute("SELECT event_id, first_seen_ts FROM events").fetchall()}


def registry_health(store, *, now: float | None = None, in_season: bool = True,
                    max_silence_s: float = 24 * 3600) -> list[str]:
    """Watchdog-shaped alerts about the registry itself: in season, no co-listed game for a day
    means discovery is broken, not that nothing is on."""
    t = now or time.time()
    store.ensure_ddl(EVENTS_DDL)
    if not in_season:
        return []
    last = store.con.execute("SELECT MAX(last_seen_ts) FROM events WHERE phase LIKE '%:co_listed'").fetchone()[0]
    if last is not None:
        return ([f"registry: NO_CO_LISTED_GAMES — none seen for {int(t - last)}s (limit {int(max_silence_s)}s)"]
                if t - last > max_silence_s else [])
    # Nothing co-listed EVER: only a fault once discovery has been writing for a whole limit
    # without one. A fresh registry (first boot) is silent, not alarmed.
    oldest = store.con.execute("SELECT MIN(first_seen_ts) FROM events").fetchone()[0]
    if oldest is not None and t - oldest > max_silence_s:
        return [f"registry: NO_CO_LISTED_GAMES — discovery has written for {int(t - oldest)}s without one co-listed game"]
    return []
