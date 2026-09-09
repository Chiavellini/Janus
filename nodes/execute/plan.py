#!/usr/bin/env python3
"""From a priced cover to an executable two-leg plan. PURE.

LEG ORDER IS FIXED: Polymarket first, Kalshi hedge. Kalshi leads Polymarket by 5-10 s and 36% of
Polymarket reprices never happen within 60 s (AGENTS.md), so the opportunity IS a stale
Polymarket price and Polymarket is the less reliable executor. Leg A is therefore the leg most
likely to zero-fill: a FAK that rejects or authoritatively cancels leaves no position, while an
ambiguous acknowledgement is exposure until the authenticated account stream or REST proves its
outcome. Leg B is the hedge, on the venue whose REST ack reports the fill count synchronously and
whose fee is deterministic. The order is never reversed at runtime, and
the partial-fill policy is pre-declared here rather than improvised (GATE cross-venue #2).

THE HEDGE LIMIT IS A PER-LEVEL PRICE, THE BUDGET IS A VWAP (2026-09-05). Until F3's first
unhedged paper leg the coordinator sent `hedge_budget` -- the most the hedge may AVERAGE for the
cover still to clear the hurdle after what leg A paid -- as the IOC's limit. An IOC limit is
per level: the venue fills nothing above it. MIL @ CIN, q=100: the pricer walked Kalshi
64.18 @ 0.84 + 35.82 @ 0.85 (VWAP 0.8436, under the 0.8452 budget) and the IOC at 0.8452 took
the 0.84 level and stopped; two more attempts at the same limit against the same book filled
nothing, 35.82 contracts sat unhedged. So: `hedge_limit` is the worst level the pricer walked
for this size, tightened by any amount leg A paid over its own priced VWAP and floored to the
venue tick; `hedge_budget` is kept and recorded so a hedge that averaged above it is labelled
ABOVE_BUDGET (a cover below the hurdle, still a cover -- hedging beats an open leg). Above the
limit the coordinator stops (HEDGE_SLIPPAGE_EXCEEDED) rather than chase.
"""

from __future__ import annotations

import math

from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from kernel.schema import Book
from nodes.cover.cover import Cover, Leg
from nodes.fees.models import Fill
from nodes.fees.registry import model_for, params_for
from nodes.opportunity.thresholds import (
    EXECUTION_MIN_LOCKED_RETURN,
    EXECUTION_MIN_NET_PROFIT_USD,
    STRATEGY_VERSION,
)

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
    vwap: float = 0.0         # what the pricer expects this leg to average at this size
    tick: float = 0.01        # the venue's price increment for this market
    post_only: bool = False


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
    #: The bounded settlement-reference reserve from CoverProof. It is part of the cost of
    #: keeping a two-leg cover to settlement, but not a venue fee (and not paid on an unwind).
    #: Before 2026-09-08 the execution budget omitted it even though the opportunity pricer
    #: included it, so a padded first leg or chased hedge could cross the registered hurdle.
    settlement_buffer_per_contract: float = 0.0
    strategy_version: str = STRATEGY_VERSION
    quote_expires_utc: float | None = None

    @classmethod
    def from_dict(cls, d: Mapping, *, opportunity_id: str, event_id: str, league: str, quantity: float,
                  strategy_version: str = STRATEGY_VERSION) -> "Plan":
        """The plan back from `executions.plan_json` (what ExecutionRecords.start wrote: first,
        hedge, max_cost, fee) plus the row's ids: the position guard re-runs the protection
        layer from the record (2026-09-08)."""
        def leg(x: Mapping) -> LegPlan:
            return LegPlan(x["venue"], x["market_id"], x["outcome_id"], x["side"], float(x["limit_price"]),
                           float(x["contracts"]), x.get("time_in_force", "ioc"), vwap=float(x.get("vwap") or 0.0),
                           tick=float(x.get("tick") or 0.01), post_only=bool(x.get("post_only", False)))
        return cls(opportunity_id, event_id, league, float(quantity), leg(d["first"]), leg(d["hedge"]),
                   max_cost_per_contract=float(d["max_cost"]), fee_per_contract=float(d["fee"]),
                   settlement_buffer_per_contract=float(d.get("settlement_buffer") or 0.0),
                   strategy_version=strategy_version, quote_expires_utc=d.get("quote_expires_utc"))

    @property
    def holding_reserve_per_contract(self) -> float:
        """Every non-gross cost of holding the completed cover."""
        return self.fee_per_contract + self.settlement_buffer_per_contract

    def hedge_budget(self, first_paid: float) -> float:
        """The most the hedge may AVERAGE per contract for the cover to clear the hurdle, given
        what leg A actually paid. A VWAP, never an order limit; recorded beside every attempt."""
        return round(self.max_cost_per_contract - self.holding_reserve_per_contract - first_paid, 4)

    def hedge_break_even(self, first_paid: float) -> float:
        """The hedge VWAP at which the held pair has zero reserved profit."""
        return round(1.0 - self.holding_reserve_per_contract - first_paid, 4)

    def hedge_limit(self, first_paid: float) -> float:
        """The IOC limit for leg B: the worst level the pricer walked for this size, less what leg
        A paid over its own priced VWAP, floored to the hedge venue's tick."""
        overpay = max(0.0, first_paid - self.first.vwap) if self.first.vwap else 0.0
        raw = self.hedge.limit_price - overpay
        tick = self.hedge.tick or 0.01
        return round(math.floor(raw / tick + 1e-9) * tick, 4)


def marginal_price(book: Book, contracts: float) -> float | None:
    """The price of the level at which cumulative ask depth reaches `contracts`."""
    cum = 0.0
    for q in book.asks:
        cum += q.size
        if cum >= contracts - 1e-9:
            return q.price
    return None


def maker_plan_from_cover(*, max_quote_age_s: float = 3.0, **kwargs) -> Plan | None:
    """Live maker-first variant; the original executable cover gates eligibility unchanged.

    This passive quote is not a claimed executable fill or an inherited EV estimate.
    Historical/paper plans continue to use plan_from_cover without reinterpretation.
    """
    from nodes.exec_polymarket.post_only_sizing import maker_price
    plan = plan_from_cover(**kwargs)
    if plan is None:
        return None
    source = next((leg for legs in kwargs["offers"].values() for leg in legs
                   if leg.venue == plan.first.venue and leg.outcome_id == plan.first.outcome_id), None)
    if source is None or not source.book.asks:
        return None
    price = maker_price(best_ask=source.book.asks[0].price, ceiling=plan.first.limit_price, tick=plan.first.tick)
    if price is None:
        return None
    selected = {(plan.first.venue, plan.first.outcome_id), (plan.hedge.venue, plan.hedge.outcome_id)}
    times = [leg.book.fetched_utc for legs in kwargs["offers"].values() for leg in legs
             if (leg.venue, leg.outcome_id) in selected]
    if len(times) != 2 or any(not x for x in times) or not 0 < max_quote_age_s <= 5:
        return None
    return replace(plan, first=replace(plan.first, limit_price=price, time_in_force="gtc", post_only=True),
                   quote_expires_utc=min(times) + max_quote_age_s)


def _leg_side(leg: Leg) -> tuple[str, str]:
    """(market_id, side). A Kalshi complementary-NO leg has outcome_id '<ticker>:NO' and is a
    buy_no on that ticker. A Polymarket NO leg (outcome_id '<yes token>:NO', market_id = the NO
    token) is a buy_yes of the NO token: Polymarket outcomes are separate tokens (the adapter
    refuses any other side, by design)."""
    if leg.venue == "kalshi" and leg.outcome_id.endswith(":NO"):
        return leg.market_id, "buy_no"
    return leg.market_id, "buy_yes"


def plan_from_cover(*, opportunity_id: str, event_id: str, league: str, cov: Cover,
                    offers: Mapping[str, Sequence[Leg]], hurdle: float = EXECUTION_MIN_LOCKED_RETURN,
                    min_net_profit_usd: float = EXECUTION_MIN_NET_PROFIT_USD) -> Plan | None:
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
                               "ioc", vwap=float(lc.vwap), tick=float(leg.tick or 0.01))
    # Both registered economics are hard ceilings.  The percentage hurdle alone leaves more room
    # than the dollar floor at the live q=5/q=10 sizes: spending a one-cent entry pad can turn a
    # $0.12 candidate into a $0.07 trade while the original evaluation still clears risk.  Carry
    # the tighter ceiling through the plan so every later hedge budget preserves both promises.
    profit_cost = 1.0 - max(0.0, float(min_net_profit_usd)) / float(cov.contracts)
    max_cost = min(1.0 / (1.0 + hurdle), profit_cost)
    fee = float(cov.fee_per_contract or 0.0)
    settlement = float(cov.settlement_buffer_per_contract or 0.0)
    first, hedge = plans[FIRST_VENUE], plans[HEDGE_VENUE]
    # The first leg is FILL-AND-KILL at one tick above the walked level, when the cover still
    # clears the hurdle at that price. 2026-09-07, the first ten real orders from Mexico: every
    # fill-or-kill at the walked level came back "couldn't be fully filled" -- the CLOB's book was
    # a step past ours by the time the order landed (replica drift, 200 ms of balances and
    # transit) -- and the lane re-priced and sent again. FAK takes what is there at the limit
    # (a partial first leg is hedged for exactly what filled, LEG_A_PARTIAL); the pad buys the
    # step. The hedge limit tightens by whatever the first leg pays above its VWAP, so the pad
    # never buys a cover below the hurdle.
    padded_price = round(first.limit_price + first.tick, 4)
    padded_fee = fee
    # The venue fee can move with probability (Polymarket uses p*(1-p)).  Reprice the padded first
    # leg at its worst fill price and preserve every other fee already in the cover.  A failed fee
    # reprice removes the optional pad; it never creates free room.
    try:
        source_leg = legs_by_id[(first.venue, first.outcome_id)]
        need = first.contracts
        original_fills = []
        for quote in source_leg.book.asks:
            if need <= 1e-9:
                break
            take = min(need, quote.size)
            original_fills.append(Fill(first.venue, first.market_id, first.outcome_id, "yes",
                                       quote.price, take, "taker", 0))
            need -= take
        original_leg_fee = model_for(first.venue).entry_cost(
            original_fills, params_for(first.venue, source_leg.fee_overrides)
        )
        worst_fee = model_for(first.venue).entry_cost(
            [Fill(first.venue, first.market_id, first.outcome_id, "yes", padded_price,
                  first.contracts, "taker", 0)],
            params_for(first.venue, source_leg.fee_overrides),
        )
        padded_fee += max(0.0, float(worst_fee) - float(original_leg_fee)) / float(cov.contracts)
    except Exception:  # noqa: BLE001 -- an optional price pad is refused when its fee is not provable
        padded_price = first.limit_price
    room = max_cost - hedge.vwap - padded_fee - settlement - padded_price
    if padded_price > first.limit_price and room >= -1e-9:
        first = LegPlan(first.venue, first.market_id, first.outcome_id, first.side,
                        padded_price, first.contracts, first.time_in_force,
                        vwap=first.vwap, tick=first.tick)
        fee = padded_fee
    return Plan(opportunity_id, event_id, league, cov.contracts, first, hedge,
                max_cost_per_contract=max_cost, fee_per_contract=fee,
                settlement_buffer_per_contract=settlement)
