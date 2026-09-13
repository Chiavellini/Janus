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
from nodes.cover.cover import PM_MIN_NOTIONAL_USD
from nodes.rules_exhaustive.rules import NotExhaustive, prove
from nodes.settle_wedge.equivalence import CoverProof, NotEquivalent, SettlementEquivalence, certify_cover
from kernel.schema import liquidity_source_for


class PollerState(str, Enum):
    WARMING = "WARMING"        # replicas still syncing; nothing priced yet
    WATCHING = "WATCHING"      # all four synced, pricing on every event
    BLOCKED = "BLOCKED"        # a structural refusal: rules, matching, exhaustiveness
    DRAINING = "DRAINING"      # game over; stop, unsubscribe, report


#: The SEND path's own cover requirement, as `nodes/execute/sizing.choose_live_size` applies it to
#: every size it considers: exactly two legs, one on each of the two venues. A cover of any other
#: shape cannot become an order however cheap it is, so it cannot answer "how close were we".
LIVE_REQUIRED_VENUES = frozenset({"polymarket", "kalshi"})
LIVE_LEG_COUNT = 2


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
    #: The pricing CONTEXT `cover` was produced under, carried so a consumer can re-price these
    #: same books under a different requirement. Carried and never re-derived: a proof minted
    #: downstream would be a label this code path invented, which is the defect L88 named.
    proof: CoverProof | None = None
    max_leg_age_s: float | None = None

    @property
    def actionable_return(self) -> float | None:
        c = self.cover
        if c is None or not c.ok or not c.cost_per_contract:
            return None
        return (1.0 - c.cost_per_contract) / c.cost_per_contract

    def sendable_cover(self) -> Cover | None:
        """The cheapest cover over these SAME books that the lane could actually send: two legs,
        one per venue, exactly the requirement `choose_live_size` imposes.

        L98 (2026-09-13): `cover` is the UNCONSTRAINED best, and on ~76 % of a 24 h window's
        BLOCKED_MATCH rows that best was SINGLE-VENUE -- so the `gross`, `required_ask_sum` and
        `cents_from_actionable` recorded from it describe a cover the lane can never send, and
        `cents_from_actionable` reached the further absurdity of pricing INTRA-venue legs through
        the CROSS-venue fee model. A row measured at -11.53c (past actionable) re-priced to
        +5.35c (short of it): a 16.9c error with the wrong sign, on the metric the lane uses to
        decide whether it is being too conservative.

        None when there is no context to re-price from. A `Cover` that is not `ok` means the books
        held no sendable cover at this size, which is a finding, not a missing measurement.
        """
        if not self.offers or not isinstance(self.proof, CoverProof):
            return None
        kw = {} if self.max_leg_age_s is None else {"max_leg_age_s": float(self.max_leg_age_s)}
        return best_cover({k: list(v) for k, v in self.offers.items()}, self.quantity,
                          now_utc=self.evaluated_utc, proof=self.proof,
                          required_venues=LIVE_REQUIRED_VENUES, leg_count=LIVE_LEG_COUNT, **kw)


#: The evaluation coalescing window per slate tier (2026-09-08). Every co-listed game in the
#: 6 h window used to price on every frame at the in-play window (0.2 s): on the box, 92 pre-match
#: pollers wrote a third of the rows while one vCPU sat at 100 % and the loop stamped frames late
#: enough to HALT CLOCK. A game hours from kickoff is priced every 5 s, one starting within two
#: hours every second, a game in play on every frame as before. The lane sets it on every
#: discovery pass; the replay harness applies the same map from the recorded tier timeline, so
#: the rows stay identical (GATE step 4 parity).
EVAL_INTERVAL_BY_TIER = {"live": 0.2, "starting_soon": 1.0, "newborn": 5.0, "recently_listed": 5.0,
                         "closing_soon": 5.0, "long_term": 5.0}


def eval_interval_for(tier: str | None, *, default: float = 0.2) -> float:
    return float(EVAL_INTERVAL_BY_TIER.get(tier or "", default))


def smallest_executable(offers) -> float:
    """The smallest size every leg on offer can be sent at: the venues' share minimums and, for a
    Polymarket leg, one dollar of notional at its best ask (ceil). Never below 1."""
    import math
    q = 1.0
    for legs in offers.values():
        for l in legs:
            q = max(q, float(l.min_order_contracts or 1.0))
            if l.venue == "polymarket" and l.book.asks:
                q = max(q, float(math.ceil(PM_MIN_NOTIONAL_USD / l.book.asks[0].price - 1e-9)))
    return q


@dataclass
class GamePoller:
    """The actor. One per live event."""
    game_id: str
    league: str
    #: outcome_id -> {venue: market_id}. Two outcomes, two venues, four replicas.
    outcomes: dict[str, dict[str, str]]
    quantities: tuple[float, ...] = (5.0, 25.0, 100.0)
    max_book_age_s: float = 5.0
    #: A book adopted from a REST reconcile is a fallback and is held to a stricter bound
    #: (spec §8: REST fallback visibly labelled, stricter freshness).
    max_rest_book_age_s: float = 3.0
    min_return: float = 0.01
    #: venue -> fee params from the venue's OWN payload (Kalshi series fee_type/fee_multiplier;
    #: Polymarket market feeSchedule). A venue absent here blocks its legs with
    #: FEE_SCHEDULE_MISSING. Never a constant: KXMLBGAME is 0.5x and PM sports was 0.03 on the
    #: day this was measured, against the 1.0x and 0.05 the lane had been charging.
    fee_params: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    #: The settlement-equivalence proof for this pair, minted by nodes/settle_wedge from the
    #: venues' own rules text. None blocks the poller at spawn: an unproven settlement basis
    #: is how two venues pay differently on the same game.
    equivalence: SettlementEquivalence | None = None
    #: venue -> {min_order_contracts, tick} as the venue reported (Polymarket: Gamma). A venue
    #: absent here gets the schema defaults (1 contract, 1c), which is Kalshi's actual minimum.
    order_limits: dict[str, Mapping[str, float]] = field(default_factory=dict)

    #: Set by the supervisor to stop pricing for a reason the poller cannot see (an unhealthy
    #: clock today; a kill switch or a venue disconnect later). Evaluations are still emitted,
    #: blocked with this name, so the outage is recorded rather than silent.
    halt: str | None = None
    #: COALESCING (2026-09-04, ledger L37/L38). Every delta on either socket used to re-price
    #: the game -- ~3,400 evaluations a second in bursts, the loop saturated, and the venues'
    #: stamps fell 14-42 s behind. Inside this window (measured on the caller's `now`, the frame's
    #: receive time, so replay reproduces it exactly) an event is folded into the books and not
    #: priced, UNLESS the store's 15 s heartbeat is due or a replica's state or fault changed,
    #: so every BLOCKED/STALE transition still lands on the frame it happened. 0.0 = every event.
    min_eval_interval_s: float = 0.0
    heartbeat_s: float = 15.0
    _last_eval_utc: float = field(default=-1e18, repr=False)
    _last_marks: dict = field(default_factory=dict, repr=False)
    skipped: int = 0

    state: PollerState = PollerState.WARMING
    replicas: dict[tuple[str, str], BookReplica] = field(default_factory=dict)
    proof: CoverProof | None = None
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
        if self.equivalence is None:
            self.state = PollerState.BLOCKED
            self.block_reason = "SETTLEMENT_UNPROVEN"
            return
        cp = certify_cover(got, self.equivalence)
        if isinstance(cp, NotEquivalent):
            self.state = PollerState.BLOCKED
            self.block_reason = cp.code
            return
        self.proof = cp
        for outcome, venues in self.outcomes.items():
            for venue, market_id in venues.items():
                if venue == "polymarket_no":
                    continue                      # built below, keyed ("polymarket_no", outcome)
                # Kalshi's seq is per SUBSCRIPTION, so its replicas are verified by the stream.
                # Polymarket has no sequence at all and needs an outside REST check.
                self.replicas[(venue, outcome)] = BookReplica(
                    venue=venue, market_id=market_id,
                    verification="stream" if venue == "kalshi" else "external")
        # THE COMPLEMENTARY NO LADDER. A Kalshi event carries one market per participant, and
        # buying NO on the other participant's market is the same exposure as YES on this one:
        # a different order book with its own depth and price, in the SAME orderbook frames.
        # Measured +67% to +563% takeable depth on live MLB (a0a79f5) -- and until now only the
        # retired REST lane read it. The replica keys as ("kalshi_no", outcome) and registers
        # on the OTHER outcome's ticker with side "no".
        if len(self.outcomes) == 2:
            a, b = sorted(self.outcomes)
            for outcome, other in ((a, b), (b, a)):
                other_ticker = self.outcomes[other].get("kalshi")
                if other_ticker:
                    self.replicas[("kalshi_no", outcome)] = BookReplica(
                        venue="kalshi", market_id=other_ticker, verification="stream")
        # THE POLYMARKET NO TOKEN (2026-09-04). On a three-way game every side is its own Yes/No
        # market, so NO on a team market pays on the OTHER TWO outcomes: one leg covering a set,
        # which is what makes a soccer cover two legs (Kalshi YES on the side + Polymarket NO on
        # it). Discovery carries the token as `polymarket_no`; the replica keys ("polymarket_no",
        # outcome) and its leg is filed under the compound key of the outcomes it covers.
        for outcome, venues in self.outcomes.items():
            tok_no = venues.get("polymarket_no")
            if tok_no:
                self.replicas[("polymarket_no", outcome)] = BookReplica(
                    venue="polymarket", market_id=tok_no, verification="external")

    # ── subscriptions ───────────────────────────────────────────────────
    def market_ids(self, venue: str) -> list[str]:
        """What this poller needs the shared socket to subscribe to: every replica's market on
        that venue, NO tokens included (derived from the replicas so a reap unregisters all)."""
        out: list[str] = []
        for (key, _outcome), rep in self.replicas.items():
            v = "kalshi" if key in ("kalshi", "kalshi_no") else "polymarket"
            if v == venue and rep.market_id not in out:
                out.append(rep.market_id)
        return out

    def registrations(self) -> list[tuple[str, str, str, BookReplica]]:
        """(venue, market_id, side, replica) for every replica: what a supervisor registers with
        the shared sockets. The supervisor and the replay harness both use this, so the set of
        books a game is priced from is defined in exactly one place."""
        out = []
        for (key, _outcome), rep in self.replicas.items():
            venue = {"kalshi_no": "kalshi", "polymarket_no": "polymarket"}.get(key, key)
            side = "no" if key == "kalshi_no" else "yes"          # a PM NO token is its own asset
            out.append((venue, rep.market_id, side, rep))
        return out

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
        if self.min_eval_interval_s > 0:
            marks = {k: (r.state, r.last_fault) for k, r in self.replicas.items()}
            since = t - self._last_eval_utc
            if since < self.min_eval_interval_s and since < self.heartbeat_s and marks == self._last_marks:
                self.skipped += 1
                return []
            self._last_marks = marks
        self._last_eval_utc = t

        offers, blocked = {}, (f"supervisor:halt:{self.halt}" if self.halt else None)
        for outcome, venues in self.outcomes.items():
            legs = []
            for v in venues:
                if v == "polymarket_no":          # a token, not a venue: its leg is built below
                    continue
                rep = self.replicas.get((v, outcome))
                if rep is None:
                    continue
                book = self._usable(rep, t)
                if isinstance(book, str):
                    blocked = blocked or f"{v}:{outcome}:{book}"
                    continue
                fees = self.fee_params.get(v)
                if fees is None:
                    blocked = blocked or f"{v}:{outcome}:FEE_SCHEDULE_MISSING"
                    continue
                lim = self.order_limits.get(v, {})
                legs.append(Leg(v, liquidity_source_for(v), rep.market_id, rep.market_id, book,
                                dict(fees), min_order_contracts=float(lim.get("min_order_contracts", 1.0)),
                                tick=float(lim.get("tick", 0.01))))
            # The complementary NO ladder is EXTRA depth, never a requirement: a fault on it
            # drops the leg, it does not block the cover the four primary books can price.
            rep = self.replicas.get(("kalshi_no", outcome))
            fees = self.fee_params.get("kalshi")
            if rep is not None and fees is not None:
                book = self._usable(rep, t)
                if not isinstance(book, str):
                    legs.append(Leg("kalshi", liquidity_source_for("kalshi"), f"{rep.market_id}:NO",
                                    rep.market_id, book, dict(fees)))
            if legs:
                offers[outcome] = legs
            # THE POLYMARKET NO LEG: extra depth covering the other outcomes, never a requirement.
            rep = self.replicas.get(("polymarket_no", outcome))
            fees = self.fee_params.get("polymarket")
            if rep is not None and fees is not None and len(self.outcomes) > 2:
                book = self._usable(rep, t)
                if not isinstance(book, str):
                    others = frozenset(self.outcomes) - {outcome}
                    key = "|".join(sorted(others))
                    lim = self.order_limits.get("polymarket", {})
                    yes_tok = venues.get("polymarket", "")
                    offers.setdefault(key, []).append(
                        Leg("polymarket", liquidity_source_for("polymarket"), f"{yes_tok}:NO", rep.market_id, book,
                            dict(fees), min_order_contracts=float(lim.get("min_order_contracts", 1.0)),
                            tick=float(lim.get("tick", 0.01)), covers=others))

        covered = set().union(*(frozenset(k.split("|")) for k in offers)) if offers else set()
        ready = covered >= set(self.outcomes) and blocked is None
        self.state = PollerState.WATCHING if ready else PollerState.WARMING

        out = []
        # The SMALLEST quantity is the smallest size both venues will execute for these books, not
        # a fixed rung (the operator's rule, 2026-09-07: "as long as there is a single contract we
        # should take it"). Polymarket sets it: its share minimum (`orderMinSize`) and its $1 of
        # notional for a marketable buy (9 shares at $0.12, 2 at $0.50); Kalshi takes one. The
        # fixed rungs above it stay for the frontier and the record.
        quantities = self.quantities
        if ready and offers:
            q_min = smallest_executable(offers)
            quantities = tuple(sorted({q_min} | {q for q in self.quantities if q > q_min}))
        for q in quantities:
            cov = None
            if ready:
                cov = best_cover(offers, q, now_utc=t,
                                 max_leg_age_s=self.max_book_age_s, proof=self.proof)
            ev = Evaluation(self.game_id, market_id, q, cov, blocked, t,
                            latency_ms=(time.time() - t) * 1000.0,
                            offers={k: tuple(v) for k, v in offers.items()} if ready else {},
                            proof=self.proof if ready else None,
                            max_leg_age_s=self.max_book_age_s)
            self.evaluations += 1
            r = ev.actionable_return
            if r is not None and r >= self.min_return and cov is not None and not cov.single_venue:
                self.opportunities += 1
            out.append(ev)
        return out

    def _usable(self, rep: BookReplica, t: float):
        """A Book, or the name of why not. REST-sourced books get the stricter bound."""
        max_age = self.max_rest_book_age_s if rep.source == "rest" else self.max_book_age_s
        fault = rep.check(t, max_age_s=max_age)
        if fault is not None:
            return fault.value
        book = rep.snapshot(t, max_age_s=max_age, checked=True)
        if book is None or not book.asks:
            return "NO_ASKS"
        return book

    def drain(self) -> None:
        self.state = PollerState.DRAINING

    def stats(self) -> dict:
        return {"game_id": self.game_id, "league": self.league, "state": self.state.value, "skipped": self.skipped,
                "events": self.events, "evaluations": self.evaluations,
                "opportunities": self.opportunities, "block_reason": self.block_reason,
                "replicas": {f"{v}:{o}": r.state.value for (v, o), r in self.replicas.items()},
                "halt": self.halt}
