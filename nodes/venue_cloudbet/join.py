#!/usr/bin/env python3
"""Cloudbet sports discovery and exact schedule join.

Cloudbet is queried by explicit competition key, then its structured event participants and
``startTime`` are joined to the existing ESPN schedule spine. Titles and Cloudbet event keys are
kept for audit only. An event without an exact schedule match, a known outcome map, or a tradeable
status is blocked rather than coerced into a candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from nodes.entities.resolve import Resolver
from nodes.schedule_espn.espn import DEFAULT_START_TOLERANCE_S, ScheduledGame, index_by_participants, nearest_game
from nodes.venue_cloudbet.feed import (
    EVENT_TRADEABLE_STATUSES,
    CloudbetEventMarket,
    CloudbetFeedClient,
    CloudbetSelection,
    cloudbet_leg,
    event_start_utc,
    event_status,
    event_team_name,
    iter_event_markets,
)
from nodes.cover.cover import Leg


@dataclass(frozen=True)
class CloudbetScheduleMatch:
    game: ScheduledGame
    event: Mapping[str, object]
    market: CloudbetEventMarket
    competition_key: str


@dataclass(frozen=True)
class CloudbetDiscovery:
    matches: tuple[CloudbetScheduleMatch, ...]
    blocked: tuple[dict[str, str], ...]


def _event_id(event: Mapping[str, object]) -> str:
    return str(event.get("id", event.get("eventId", event.get("key", ""))))


def _event_items(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    events = payload.get("events")
    if isinstance(events, Mapping):
        return [v for v in events.values() if isinstance(v, Mapping)]
    if isinstance(events, (list, tuple)):
        return [v for v in events if isinstance(v, Mapping)]
    if isinstance(payload.get("event"), Mapping):
        return [payload["event"]]  # type: ignore[list-item]
    if payload.get("id") or payload.get("eventId"):
        return [payload]
    return []


def _schedule_game(event: Mapping[str, object], games: Sequence[ScheduledGame], *, league: str,
                   resolver: Resolver, tolerance_s: int) -> tuple[ScheduledGame | None, str | None]:
    names = {side: event_team_name(event, side) for side in ("home", "away")}
    if not names["home"] or not names["away"]:
        return None, "MISSING_STRUCTURED_PARTICIPANTS"
    resolved = {
        side: resolver.resolve(league, text=name, venue="cloudbet")
        for side, name in names.items()
    }
    if any(not r.ok for r in resolved.values()):
        return None, "UNRESOLVED_STRUCTURED_PARTICIPANT"
    entities = [r.entity_id for r in resolved.values()]
    if len(set(entities)) != 2:
        return None, "DUPLICATE_STRUCTURED_PARTICIPANT"
    espn_ids = tuple(sorted(resolver.teams[e].espn_id for e in entities if e in resolver.teams))
    if len(espn_ids) != 2:
        return None, "PARTICIPANT_WITHOUT_ESPN_XREF"
    start = event_start_utc(event)
    if start is None:
        return None, "MISSING_STRUCTURED_START_TIME"
    game = nearest_game(index_by_participants(games).get(espn_ids, []), start, tolerance_s)
    return (game, None) if game is not None else (None, "NO_EXACT_SCHEDULE_MATCH")


def discover_joined(
    payloads: Iterable[tuple[str, Mapping[str, object]]],
    games: Sequence[ScheduledGame],
    *,
    league: str,
    resolver: Resolver,
    market_keys: Sequence[str] = (),
    tolerance_s: int = DEFAULT_START_TOLERANCE_S,
) -> CloudbetDiscovery:
    """Join competition payloads to the schedule, preserving blocked reasons.

    ``payloads`` is deliberately injectable so frozen fixtures exercise the exact same code as
    the authenticated feed client. The caller chooses explicit market keys; a missing key is a
    coverage miss, never a fuzzy fallback.
    """
    wanted = set(market_keys)
    matches: list[CloudbetScheduleMatch] = []
    blocked: list[dict[str, str]] = []
    for competition_key, payload in payloads:
        for event in _event_items(payload):
            eid = _event_id(event)
            if event_status(event) not in EVENT_TRADEABLE_STATUSES:
                blocked.append({"event_id": eid, "reason": "EVENT_NOT_TRADEABLE_STATUS",
                                "status": event_status(event)})
                continue
            game, reason = _schedule_game(event, games, league=league, resolver=resolver,
                                          tolerance_s=tolerance_s)
            if game is None:
                blocked.append({"event_id": eid, "reason": reason or "NO_SCHEDULE_MATCH"})
                continue
            found = False
            for item in iter_event_markets(event, fetched_utc=0.0):
                if wanted and item.market_key not in wanted:
                    continue
                found = True
                matches.append(CloudbetScheduleMatch(game, event, item, competition_key))
            if not found:
                blocked.append({"event_id": eid, "reason": "NO_CONFIGURED_MARKET"})
    matches.sort(key=lambda x: (x.game.start_utc, _event_id(x.event),
                               x.market.market_key, x.market.submarket_key))
    return CloudbetDiscovery(tuple(matches), tuple(blocked))


def discover_from_feed(
    feed: CloudbetFeedClient,
    competition_keys: Sequence[str],
    games: Sequence[ScheduledGame],
    *,
    league: str,
    resolver: Resolver,
    market_keys: Sequence[str] = (),
    tolerance_s: int = DEFAULT_START_TOLERANCE_S,
) -> CloudbetDiscovery:
    """Network boundary for discovery; the join itself remains pure/testable."""
    payloads = ((key, feed.competition(key, markets=market_keys)) for key in competition_keys)
    return discover_joined(payloads, games, league=league, resolver=resolver,
                           market_keys=market_keys, tolerance_s=tolerance_s)


def _selection_label(item: CloudbetEventMarket, selection: CloudbetSelection) -> str:
    if selection.outcome in {"home", "away"}:
        return event_team_name(item.event, selection.outcome)
    return selection.outcome


def add_cloudbet_legs(
    offers: Mapping[str, Sequence[Leg]], item: CloudbetEventMarket, *,
    resolver: Resolver, league: str,
) -> "CloudbetJoin":
    """Append Cloudbet BACK legs to an exact schedule-anchored outcome map.

    Feed selections are included with ``executable=False`` until the Trading API accepts the exact
    requested stake. The raw ``home``/``away`` labels are resolved through the event's structured
    team names; Cloudbet's generic labels are not treated as canonical entity IDs.
    """
    resolved: dict[str, list[CloudbetSelection]] = {}
    for selection in item.selections:
        label = _selection_label(item, selection)
        result = resolver.resolve(league, text=label, venue="cloudbet")
        if not result.ok:
            return CloudbetJoin({}, tuple(sorted(resolved)),
                               f"UNRESOLVED_CLOUDBET_OUTCOME:{label}")
        assert result.entity_id is not None
        resolved.setdefault(result.entity_id, []).append(selection)

    expected = set(offers)
    actual = set(resolved)
    if actual != expected:
        return CloudbetJoin({}, tuple(sorted(actual)),
                            f"CLOUDBET_OUTCOME_SET_MISMATCH:expected={sorted(expected)}:actual={sorted(actual)}")
    if any(len(selections) != 1 for selections in resolved.values()):
        return CloudbetJoin({}, tuple(sorted(actual)), "DUPLICATE_CLOUDBET_SELECTION")

    merged = {entity: tuple(legs) for entity, legs in offers.items()}
    for entity, selections in resolved.items():
        merged[entity] = merged[entity] + (
            cloudbet_leg(selections[0], market_id=selections[0].event_id, outcome_id=entity),
        )
    return CloudbetJoin(merged, tuple(sorted(actual)))


def add_accepted_cloudbet_legs(
    offers: Mapping[str, Sequence[Leg]], item: CloudbetEventMarket, *,
    resolver: Resolver, league: str, acceptances: Mapping[str, object],
) -> "CloudbetJoin":
    """Append only provider-confirmed Cloudbet legs to the cover input.

    ``acceptances`` is keyed by the stable selection ID. Every selection in the exact outcome set
    must be ACCEPTED or REDUCED; a pending, timeout, rejected, or missing acceptance blocks the
    whole join. The accepted odds/stake replace feed economics before ``best_cover`` runs.
    """
    from nodes.venue_cloudbet.trading import TERMINAL_STATES

    resolved: dict[str, list[tuple[CloudbetSelection, object]]] = {}
    for selection in item.selections:
        acceptance = acceptances.get(selection.selection_id)
        if acceptance is None or acceptance.state not in TERMINAL_STATES:
            return CloudbetJoin({}, (), f"CLOUDBET_ACCEPTANCE_NOT_LOCKED:{selection.selection_id}")
        label = _selection_label(item, selection)
        result = resolver.resolve(league, text=label, venue="cloudbet")
        if not result.ok:
            return CloudbetJoin({}, tuple(sorted(resolved)), f"UNRESOLVED_CLOUDBET_OUTCOME:{label}")
        assert result.entity_id is not None
        resolved.setdefault(result.entity_id, []).append((selection, acceptance))

    expected = set(offers)
    actual = set(resolved)
    if actual != expected:
        return CloudbetJoin({}, tuple(sorted(actual)),
                            f"CLOUDBET_OUTCOME_SET_MISMATCH:expected={sorted(expected)}:actual={sorted(actual)}")
    if any(len(values) != 1 for values in resolved.values()):
        return CloudbetJoin({}, tuple(sorted(actual)), "DUPLICATE_CLOUDBET_SELECTION")

    merged = {entity: tuple(legs) for entity, legs in offers.items()}
    for entity, values in resolved.items():
        selection, acceptance = values[0]
        if not acceptance.executable:
            return CloudbetJoin({}, (), f"CLOUDBET_ACCEPTANCE_ECONOMICS_MISSING:{selection.selection_id}")
        locked = selection.accepted_offer(acceptance.accepted_stake, odds=acceptance.accepted_price)
        merged[entity] = merged[entity] + (
            cloudbet_leg(locked, market_id=selection.event_id, outcome_id=entity),
        )
    return CloudbetJoin(merged, tuple(sorted(actual)))


def record_accepted_cloudbet_leg(store, selection: CloudbetSelection, acceptance: object, *,
                                 game_id: str, league: str, watch_tier: str = "live",
                                 seen_ts: float | None = None) -> tuple[str, bool]:
    """Put one accepted Cloudbet quote through the existing sparse market/quote store.

    Only accepted economics are recorded as an executable quote. Rejected, pending, timeout, or
    unknown responses are journaled by the acceptance client but cannot enter ``latest_quotes``.
    """
    from nodes.venue_cloudbet.trading import TERMINAL_STATES

    if acceptance.state not in TERMINAL_STATES or not acceptance.executable:
        raise ValueError("only provider-confirmed Cloudbet economics may enter the quote store")
    locked = selection.accepted_offer(acceptance.accepted_stake, odds=acceptance.accepted_price)
    market_id = f"{selection.event_id}:{selection.market_url}"
    store.market(
        venue="cloudbet", market_id=market_id, family="sports", event_key=game_id,
        outcome=selection.outcome, category=league, created_ts=None, close_ts=None,
        status=acceptance.state.value, settlement_ref="schedule-anchored; venue rules required",
        watch_tier=watch_tier, metadata={"reference_id": acceptance.reference_id,
                                         "market_url": selection.market_url}, seen_ts=seen_ts,
    )
    changed = store.quote(
        venue="cloudbet", market_id=market_id, best_bid=None, best_ask=locked.price,
        bid_depth=0.0, ask_depth=locked.contracts, n_bid_levels=0, n_ask_levels=1,
        two_sided=False, levels=[{"side": "ask", "price": locked.price,
                                  "size": locked.contracts}], seen_ts=seen_ts,
    )
    return market_id, changed


@dataclass(frozen=True)
class CloudbetJoin:
    offers: Mapping[str, tuple[Leg, ...]]
    resolved_entities: tuple[str, ...]
    blocked_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.blocked_reason is None
