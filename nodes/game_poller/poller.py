#!/usr/bin/env python3
"""One live game, four books, evaluated on every event.

The unit of work is a GAME, not a sweep. A poller owns the four replicas for one event -- two
outcomes on each of two venues -- and re-prices the cover whenever any one of them moves. Nothing
here runs on a timer: a timer samples a market, and a market that moves 28c between samples cannot
be sampled into an answer.

WHY THE POLLER DOES NOT OWN ITS SOCKETS. Kalshi authenticates one connection and multiplexes by
market_ticker; Polymarket takes an assets_ids list on one socket and supports mid-connection
subscribe/unsubscribe. A socket per game would mean fifteen authenticated connections per venue,
wasting every handshake and running into connection limits for no gain. Connections are shared
infrastructure owned by the stream nodes; the poller subscribes and is fed. It stays an actor --
it owns state and a lifecycle -- it simply is not a connection.

WHAT IT REFUSES TO DO. It will not price a cover unless every replica is SYNCED and inside the
freshness bound, and it will not price one at all unless the outcome set is PROVEN exhaustive.
Those are the two ways a streaming arbitrage system lies to itself: a drifted replica invents a
gap, and an incomplete outcome set turns "the draw is invisible" into a 31% return.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping
from enum import Enum

from nodes.book_replica.replica import BookReplica, Fault
from nodes.cover.cover import Cover, Leg, best_cover
from nodes.rules_exhaustive.rules import ExhaustiveOutcomeSet, NotExhaustive, prove
from kernel.schema import liquidity_source_for


class PollerState(str, Enum):
    WARMING = "WARMING"        # replicas still syncing; nothing priced yet
    WATCHING = "WATCHING"      # all four synced, pricing on every event
    BLOCKED = "BLOCKED"        # a structural refusal: rules, matching, exhaustiveness
    DRAINING = "DRAINING"      # game over; stop, unsubscribe, report


@dataclass(frozen=True)
class Evaluation:
    """One re-pricing, triggered by one book event."""
    game_id: str
    triggered_by: str          # the market_id whose event caused this
    quantity: float
    cover: Cover | None
    blocked_by: str | None
    evaluated_utc: float
    latency_ms: float          # event arrival -> decision
    #: The exact legs this was priced from, so a consumer can solve the size frontier without
    #: re-reading the replicas (which will have moved by then).
    offers: Mapping[str, tuple] = field(default_factory=dict)

    @property
    def actionable_return(self) -> float | None:
        c = self.cover
        if c is None or not c.ok or not c.cost_per_contract:
            return None
        return (1.0 - c.cost_per_contract) / c.cost_per_contract


@dataclass
class GamePoller:
    """The actor. One per live event."""
    game_id: str
    league: str
    #: outcome_id -> {venue: market_id}. Two outcomes, two venues, four replicas.
    outcomes: dict[str, dict[str, str]]
    quantities: tuple[float, ...] = (5.0, 25.0, 100.0)
    max_book_age_s: float = 5.0
    min_return: float = 0.01
    #: venue -> fee params from the venue's OWN payload (Kalshi series fee_type/fee_multiplier;
    #: Polymarket market feeSchedule). A venue absent here blocks its legs with
    #: FEE_SCHEDULE_MISSING. Never a constant: KXMLBGAME is 0.5x and PM sports was 0.03 on the
    #: day this was measured, against the 1.0x and 0.05 the lane had been charging.
    fee_params: dict[str, Mapping[str, Any]] = field(default_factory=dict)

    #: Set by the supervisor to stop pricing for a reason the poller cannot see (an unhealthy
    #: clock today; a kill switch or a venue disconnect later). Evaluations are still emitted,
    #: blocked with this name, so the outage is recorded rather than silent.
    halt: str | None = None

    state: PollerState = PollerState.WARMING
    replicas: dict[tuple[str, str], BookReplica] = field(default_factory=dict)
    proof: ExhaustiveOutcomeSet | None = None
    block_reason: str | None = None

    events: int = 0
    evaluations: int = 0
    opportunities: int = 0

    def __post_init__(self) -> None:
        # Exhaustiveness is settled ONCE, at spawn. A game whose outcome set cannot be proven
        # complete should never have a poller burning a subscription on it.
        got = prove(self.league, "moneyline", "game", sorted(self.outcomes))
        if isinstance(got, NotExhaustive):
            self.state = PollerState.BLOCKED
            self.block_reason = got.code
            return
        self.proof = got
        for outcome, venues in self.outcomes.items():
            for venue, market_id in venues.items():
                # Kalshi's seq is per SUBSCRIPTION, so its replicas are verified by the stream.
                # Polymarket has no sequence at all and needs an outside REST check.
                self.replicas[(venue, outcome)] = BookReplica(
                    venue=venue, market_id=market_id,
                    verification="stream" if venue == "kalshi" else "external")

    # ── subscriptions ───────────────────────────────────────────────────
    def market_ids(self, venue: str) -> list[str]:
        """What this poller needs the shared socket to subscribe to."""
        return [v[venue] for v in self.outcomes.values() if venue in v]

    def replica_for(self, venue: str, market_id: str) -> BookReplica | None:
        for (v, _o), r in self.replicas.items():
            if v == venue and r.market_id == market_id:
                return r
        return None

    # ── the event path ──────────────────────────────────────────────────
    def on_event(self, venue: str, market_id: str, *, now: float | None = None) -> list[Evaluation]:
        """A replica for this game moved. Re-price, at every tested size.

        Returns one Evaluation per quantity -- including the blocked ones, because "we could not
        price this and here is why" is the observation that distinguishes no-edge from no-data.
        """
        t = now or time.time()
        self.events += 1
        if self.state is PollerState.BLOCKED:
            return []
        if self.state is PollerState.DRAINING:
            return []

        offers, blocked = {}, (f"supervisor:halt:{self.halt}" if self.halt else None)
        for outcome, venues in self.outcomes.items():
            legs = []
            for v in venues:
                rep = self.replicas.get((v, outcome))
                if rep is None:
                    continue
                fault = rep.check(t, max_age_s=self.max_book_age_s)
                if fault is not None:
                    blocked = blocked or f"{v}:{outcome}:{fault.value}"
                    continue
                book = rep.snapshot(t, max_age_s=self.max_book_age_s)
                if book is None or not book.asks:
                    blocked = blocked or f"{v}:{outcome}:NO_ASKS"
                    continue
                fees = self.fee_params.get(v)
                if fees is None:
                    blocked = blocked or f"{v}:{outcome}:FEE_SCHEDULE_MISSING"
                    continue
                legs.append(Leg(v, liquidity_source_for(v), rep.market_id, rep.market_id, book,
                                dict(fees)))
            if legs:
                offers[outcome] = legs

        ready = len(offers) == len(self.outcomes) and blocked is None
        self.state = PollerState.WATCHING if ready else PollerState.WARMING

        out = []
        for q in self.quantities:
            cov = None
            if ready:
                cov = best_cover(offers, q, now_utc=t,
                                 max_leg_age_s=self.max_book_age_s, exhaustive=self.proof)
            ev = Evaluation(self.game_id, market_id, q, cov, blocked, t,
                            latency_ms=(time.time() - t) * 1000.0,
                            offers={k: tuple(v) for k, v in offers.items()} if ready else {})
            self.evaluations += 1
            r = ev.actionable_return
            if r is not None and r >= self.min_return and cov is not None and not cov.single_venue:
                self.opportunities += 1
            out.append(ev)
        return out

    def drain(self) -> None:
        self.state = PollerState.DRAINING

    def stats(self) -> dict:
        return {"game_id": self.game_id, "league": self.league, "state": self.state.value,
                "events": self.events, "evaluations": self.evaluations,
                "opportunities": self.opportunities, "block_reason": self.block_reason,
                "replicas": {f"{v}:{o}": r.state.value for (v, o), r in self.replicas.items()}}
