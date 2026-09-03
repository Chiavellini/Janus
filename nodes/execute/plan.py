#!/usr/bin/env python3
"""From a priced cover to an executable two-leg plan. PURE.

LEG ORDER IS FIXED: Polymarket first, Kalshi hedge. Kalshi leads Polymarket by 5-10 s and 36% of
Polymarket reprices never happen within 60 s (AGENTS.md), so the opportunity IS a stale
Polymarket price and Polymarket is the less reliable executor. Leg A is therefore the leg that
vanishes and the one whose ambiguity costs nothing: a FOK that rejects, times out or comes back
UNCONFIRMED leaves no position. Leg B is the hedge, on the venue whose REST ack reports the fill
count synchronously and whose fee is deterministic. The order is never reversed at runtime, and
the partial-fill policy is pre-declared here rather than improvised (GATE cross-venue #2).

The hedge limit is the most a contract may cost on leg B for the cover still to clear the
execution threshold after what leg A actually paid; above it the coordinator stops
(HEDGE_SLIPPAGE_EXCEEDED) rather than chase.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from kernel.schema import Book
from nodes.cover.cover import Cover, Leg
from nodes.opportunity.thresholds import EXECUTION_MIN_LOCKED_RETURN, STRATEGY_VERSION

FIRST_VENUE, HEDGE_VENUE = "polymarket", "kalshi"


@dataclass(frozen=True)
class LegPlan:
    venue: str
    market_id: str
    outcome_id: str
    side: str                 # "buy_yes" | "buy_no"
    limit_price: float        # the worst level the walk consumed, for the size
    contracts: float
    time_in_force: str


@dataclass(frozen=True)
class Plan:
    opportunity_id: str
    event_id: str
    league: str
    quantity: float
    first: LegPlan
    hedge: LegPlan
    max_cost_per_contract: float     # 1 / (1 + execution hurdle)
    fee_per_contract: float          # from the cover, at this size
    strategy_version: str = STRATEGY_VERSION

    def hedge_limit(self, first_paid: float) -> float:
        """The most the hedge may pay per contract, given what leg A actually paid."""
        return round(self.max_cost_per_contract - self.fee_per_contract - first_paid, 4)


def marginal_price(book: Book, contracts: float) -> float | None:
    """The price of the level at which cumulative ask depth reaches `contracts`."""
    cum = 0.0
    for q in book.asks:
        cum += q.size
        if cum >= contracts - 1e-9:
            return q.price
    return None


def _leg_side(leg: Leg) -> tuple[str, str]:
    """(market_id, side). A Kalshi complementary-NO leg has outcome_id '<ticker>:NO'."""
    if leg.venue == "kalshi" and leg.outcome_id.endswith(":NO"):
        return leg.market_id, "buy_no"
    return leg.market_id, "buy_yes"


def plan_from_cover(*, opportunity_id: str, event_id: str, league: str, cov: Cover,
                    offers: Mapping[str, Sequence[Leg]], hurdle: float = EXECUTION_MIN_LOCKED_RETURN) -> Plan | None:
    """None when the cover is not a two-venue, two-leg cover with a Polymarket leg to lead."""
    if not cov.ok or len(cov.legs) != 2 or cov.single_venue:
        return None
    by_venue = {lc.venue: lc for lc in cov.legs}
    if set(by_venue) != {FIRST_VENUE, HEDGE_VENUE}:
        return None
    legs_by_id = {(l.venue, l.outcome_id): l for ls in offers.values() for l in ls}
    plans: dict[str, LegPlan] = {}
    for venue, lc in by_venue.items():
        leg = legs_by_id.get((venue, lc.outcome_id))
        if leg is None:
            return None
        limit = marginal_price(leg.book, cov.contracts)
        if limit is None:
            return None
        market_id, side = _leg_side(leg)
        plans[venue] = LegPlan(venue, market_id, lc.outcome_id, side, limit, cov.contracts,
                               "fok" if venue == FIRST_VENUE else "ioc")
    return Plan(opportunity_id, event_id, league, cov.contracts, plans[FIRST_VENUE], plans[HEDGE_VENUE],
                max_cost_per_contract=1.0 / (1.0 + hurdle), fee_per_contract=float(cov.fee_per_contract or 0.0))
