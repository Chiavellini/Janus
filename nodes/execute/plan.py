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
from nodes.cover.cover import PM_MIN_NOTIONAL_USD, PM_WIRE_MIN_SHARES, Cover, Leg, walk_ladder
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
    #: Live-only audit of the cap-aware quantity decision. Historical/paper callers leave this
    #: empty; it never changes cover economics or grants risk authority.
    sizing: Mapping | None = None

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
                   strategy_version=strategy_version, quote_expires_utc=d.get("quote_expires_utc"),
                   sizing=d.get("sizing"))

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


#: The most a Kalshi per-order fee ceil can add to a whole order, in dollars. Its fee is
#: `ceil(0.07 * C * p * (1-p))` in CENTS per order, so shrinking an order raises the per-contract
#: cost by at most one cent spread over the contracts that remain. Used to bound a downsize's fee
#: without re-pricing the cover, which needs offers the coordinator does not hold.
CEIL_CENTS_USD = 0.01


def pm_wire_shares(contracts: float, *, top: float | None, limit: float) -> float:
    """The share count that actually reaches the CLOB for `contracts` at a padded `limit`.

    L83 caps an order's collateral at `contracts x the venue's best ask`, and the adapter then
    divides that ceiling by the price it sends (`wire = collateral / price`,
    exec_polymarket/client.py), so the nominal size shrinks by `top / limit` on every order priced
    above the top of the book -- which is every padded order and every multi-level walk.
    """
    if top is None or not (0.0 < top < limit):
        return float(contracts)
    return float(contracts) * (float(top) / float(limit))


def pm_floors_ok(shares: float, price: float) -> bool:
    """Both of the CLOB's floors on one order: 5.00 nominal shares, and $1.00 of maker notional."""
    return (float(shares) + 1e-9 >= PM_WIRE_MIN_SHARES
            and float(shares) * float(price) + 1e-9 >= PM_MIN_NOTIONAL_USD)


def pm_wire_ok(contracts: float, *, top: float | None, limit: float,
               sent_at_top: bool = False) -> bool:
    """Whether a Polymarket order for `contracts` clears the CLOB's two floors as it is PRICED.

    L96 (2026-09-13): at five contracts the shrink lands under the five-share floor at EVERY price --
    top 0.95 with a one-cent pad gives 4.948, top 0.30 gives 4.84 -- which is exactly how all seven
    of 2026-09-13's capped PRECISION rejections happened, and why L95's downsize could turn a decline
    into a rejection instead of a fill. `wire x limit` is `contracts x top` when the ceiling binds:
    the collateral actually committed, which is what the venue measures its dollar floor against.

    `sent_at_top=True` asks the different question the SIZER has to ask -- is this size sendable at
    all? -- and it is a different question because the entry reprices leg A to the venue's own ask
    when a pad would shrink the wire under the floor. The size reaching the venue is then `contracts`
    itself, so no pad can make a size unsendable and only the venue's own floors can. Answering the
    priced question there instead would refuse five-contract covers the entry can now send.
    """
    if sent_at_top:
        return pm_floors_ok(contracts, top if top else limit)
    return pm_floors_ok(pm_wire_shares(contracts, top=top, limit=limit), limit)


def best_supported_size(first_book: Book, hedge_book: Book, plan, *, min_net_profit_usd: float,
                        max_size: float) -> int | None:
    """The largest whole size at or under `max_size` that BOTH venues' own books can fill inside the
    plan's economics, or None when no size can.

    L95 (2026-09-13): the pre-send reads used to be a verdict on one size -- the book either covered
    the planned quantity or the entry was refused outright. On the night of 2026-09-12, 25 of 42
    attempts died that way, and a decline says only that the FULL size was unavailable; it never
    asked whether half of it was. Shrinking is the one direction that is always legal here: the
    reservation, the stake cap, the contract cap, the day notional and the ledger were all cleared
    against the larger size, so anything smaller is inside every one of them.

    Every test below is the one the entry already applies, re-asked per size:
      * leg A's worst level for `n` is at or under the plan's limit (`marginal_price`, as L77);
      * the hedge's AVERAGE for `n` is at or under break-even (`vwap_for_size`, as L85) -- the
        threshold is per contract, so it does not move with `n`;
      * the all-in cost still clears the plan's own ceiling, and the cover still earns the dollar
        floor, which is the test that actually bites on the way down because profit is size-linear;
      * the Polymarket $1 notional minimum still holds.
    Fees are not re-priced -- that needs the offers, which live on the loop -- so the Kalshi ceil is
    bounded by `CEIL_CENTS_USD / n`, the worst it can cost per contract at the smaller size.
    """
    limit = float(plan.first.limit_price)
    break_even = plan.hedge_break_even(limit)
    settle = float(plan.settlement_buffer_per_contract or 0.0)
    ceiling = float(plan.max_cost_per_contract)
    floor = max(0.0, float(min_net_profit_usd))
    # L96 (2026-09-13): a size has to clear the venue's own floors, or the downsize converts a
    # BOOK_MOVED decline into a PRECISION rejection instead of into a fill. The entry reprices leg A
    # to `top` when a pad would shrink the wire under the five-share floor, so the size that reaches
    # the venue is `n` itself -- which is the question asked here.
    top = first_book.asks[0].price if first_book.asks else None
    for n in range(int(max_size), 0, -1):
        if not pm_wire_ok(n, top=top, limit=limit, sent_at_top=True):
            continue                       # under a venue floor; smaller is only worse
        want = marginal_price(first_book, float(n))
        if want is None or want > limit + 1e-9:
            continue
        hedge_vwap = vwap_for_size(hedge_book, float(n))
        if hedge_vwap is None or hedge_vwap > break_even + 1e-9:
            continue
        fee = float(plan.fee_per_contract or 0.0) + CEIL_CENTS_USD / n
        all_in = limit + hedge_vwap + fee + settle
        if all_in > ceiling + 1e-9:
            continue
        if n * (1.0 - all_in) + 1e-9 < floor:
            continue
        return n
    return None


def vwap_for_size(book: Book, contracts: float) -> float | None:
    """The average price of buying `contracts` off `book`, or None when the depth is short.

    `marginal_price` is the WORST level the walk touches; the budgets in `hedge_budget` and
    `hedge_break_even` are averages. Comparing a marginal price to either of them refuses covers
    whose average is inside the budget, so a check that means to test the economics must walk.
    """
    gross, full = walk_ladder(book, contracts)
    return round(gross / contracts, 6) if full and contracts > 0 else None


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
