#!/usr/bin/env python3
"""Fee-net cover cost. The one number Stage 3 exists to measure.

Registered spec: research/sports/2026-08-17_stage3-divergence/spec.yaml (ledger L12).

A "cover" buys every outcome of a market so that exactly $1 arrives whichever way it settles.
Cover for less than $1 and the difference is arbitrage. The whole of Stage 3 is: what does that
cost, honestly, at size, across venues, repeatedly?

FOUR WAYS THIS NUMBER IS ROUTINELY FAKED, AND WHAT IS DONE ABOUT EACH
─────────────────────────────────────────────────────────────────────
1. **Quoting the touch.** The best ask usually has trivial size behind it. Cost here is the
   VOLUME-WEIGHTED price to actually fill q contracts, walking the ladder. If the ladder cannot
   fill q, the cover does not exist — it is not priced at the touch and flagged.

2. **Assuming fees are separable.** `min` per outcome is only valid pre-fee. Kalshi's ceil is per
   ORDER and net-winnings commission aggregates per venue-market, so the cheapest-per-leg
   combination need not be the cheapest overall. Greedy therefore only GENERATES candidates; every
   reported number is re-priced exactly with the full fee engine over the enumerated combinations.

3. **Mixing stale legs.** Polymarket's rate limiter QUEUES rather than rejecting, so a throttled
   response is a stale quote wearing a fresh wall-clock timestamp. Two legs fetched seconds apart,
   one minutes stale, manufactures divergence from nothing. Any cover whose oldest leg exceeds
   `max_leg_quote_age_s` is HARD-REJECTED, never down-weighted.

4. **Covering a book with itself.** Robinhood, Webull and IBKR all route to Kalshi's CLOB. Two legs
   sharing a `liquidity_source` are an accounting error, not an arbitrage.

And one that is not about arithmetic at all: a cover is only a cover if the outcome set is PROVEN
exhaustive. `mutually_exclusive` does not mean exhaustive. MLB moneyline has no draw, so two
outcomes are exhaustive BY THE SPORT'S RULES — that is the justification, and it is sport-specific.
Soccer is three-way and a two-leg "cover" there pays nothing on a draw.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from nodes.fees.models import Fill
from nodes.settle_wedge.equivalence import CoverProof
from nodes.fees.registry import model_for, params_for
from kernel.schema import Book

#: Rejected outright rather than scored. Each is a category error, not a bad price.
REJECT_STALE = "stale_leg"
REJECT_SAME_BOOK = "shared_liquidity_source"
REJECT_NOT_EXHAUSTIVE = "outcome_set_not_proven_exhaustive"
REJECT_NO_DEPTH = "insufficient_depth"
REJECT_NOT_EXECUTABLE = "quote_not_accepted"
REJECT_NO_PROOF = "cover_proof_missing"          # no CoverProof: neither proof reached the pricer
REJECT_BELOW_MIN_ORDER = "below_min_order"        # a leg cannot be sent at this size


@dataclass(frozen=True)
class Leg:
    """One venue's offer on one outcome."""
    venue: str
    liquidity_source: str
    outcome_id: str
    market_id: str
    book: Book
    fee_overrides: Mapping[str, object] = field(default_factory=dict)
    #: The venue's order limits for this market (Polymarket: Gamma orderMinSize / tick; Kalshi: 1
    #: contract, 1c). A cover below a leg's minimum cannot be sent, so it is not a cover.
    min_order_contracts: float = 1.0
    tick: float = 0.01
    executable: bool = True


@dataclass(frozen=True)
class LegCost:
    venue: str
    outcome_id: str
    contracts: float
    gross: float          # dollars paid to the book
    fee: float            # dollars paid to the venue
    vwap: float           # gross / contracts
    filled: bool


@dataclass(frozen=True)
class Cover:
    cost_per_contract: float | None
    contracts: float
    legs: tuple[LegCost, ...]
    ok: bool
    reject_reason: str | None = None
    max_leg_age_s: float | None = None
    gross_per_contract: float | None = None
    fee_per_contract: float | None = None
    #: Which outcome winning produces the highest total cost. Empty when no venue charges at
    #: settlement. Non-empty means the reported cost is a WORST CASE, which is the only kind of
    #: number an arbitrage claim may rest on.
    worst_settlement_state: str = ""
    #: True when every leg sits on ONE venue. Such covers are legal and are the cheap structure,
    #: but on a CLOB with the complement identity they are also a CONTROL that should essentially
    #: never price below 1.0 — L1 measured 0 intra-venue violations in 124,437 markets. A
    #: single_venue cover printing an edge is a BUG SIGNAL first and a discovery second.
    single_venue: bool = False
    #: The settlement-risk reserve per contract (nodes/settle_wedge), already inside `cost`.
    settlement_buffer_per_contract: float | None = None

    @property
    def edge_per_contract(self) -> float | None:
        """Dollars of arbitrage per $1 of payout. Positive means cover costs less than it pays."""
        return None if self.cost_per_contract is None else 1.0 - self.cost_per_contract


def walk_ladder(book: Book, contracts: float) -> tuple[float, bool]:
    """(gross dollars to buy `contracts`, fully_filled). Walks levels; never uses the touch alone."""
    need, gross = contracts, 0.0
    for q in book.asks:                       # asks are ascending by construction
        if need <= 0:
            break
        take = min(need, q.size)
        gross += take * q.price
        need -= take
    return gross, need <= 1e-9


def _fills_for(leg: Leg, contracts: float, order_seq: int) -> tuple[list[Fill], float, bool]:
    """One Fill PER LADDER LEVEL consumed, all under one order_seq.

    Fees are charged on the fills that actually happen (spec §6: "over the actual fills, not
    merely added to the best ask"). A single VWAP fill slightly OVERSTATES a p(1-p) fee -- the
    parabola is concave -- so the old shape was conservative but not exact, and Kalshi's ceil is
    per order, which one order_seq for all the levels preserves.
    """
    need, gross, fills = contracts, 0.0, []
    for q in leg.book.asks:
        if need <= 1e-9:
            break
        take = min(need, q.size)
        gross += take * q.price
        need -= take
        fills.append(Fill(venue=leg.venue, market_id=leg.market_id, outcome_id=leg.outcome_id,
                          side="yes", price=q.price, contracts=take, liquidity="taker",
                          order_seq=order_seq))
    return fills, gross, need <= 1e-9


def _fill_for(leg: Leg, contracts: float, order_seq: int) -> tuple[Fill, float, bool]:
    """The leg as ONE fill at VWAP -- candidate ranking only. Pricing uses `_fills_for`."""
    fills, gross, filled = _fills_for(leg, contracts, order_seq)
    vwap = gross / contracts if contracts else 0.0
    return (Fill(venue=leg.venue, market_id=leg.market_id, outcome_id=leg.outcome_id,
                 side="yes", price=vwap, contracts=contracts, liquidity="taker",
                 order_seq=order_seq), gross, filled)


def price_leg(leg: Leg, contracts: float, *, order_seq: int = 0) -> LegCost:
    """Cost of one leg in ISOLATION — entry fees only.

    Used for CANDIDATE GENERATION only. It deliberately omits settlement cost, because settlement
    cost is a property of the whole cover (which leg wins) and cannot be attributed to one leg.
    Never report this as a cost.
    """
    fill, gross, filled = _fill_for(leg, contracts, order_seq)
    model = model_for(leg.venue)
    fee = model.entry_cost([fill], params_for(leg.venue, leg.fee_overrides))
    return LegCost(leg.venue, leg.outcome_id, contracts, gross, fee, fill.price, filled)


def _cover_fees(legs: Sequence[Leg], fills_per_leg: Sequence[Sequence[Fill]]) -> tuple[float, float, str]:
    """(entry fees, WORST-CASE settlement fees, the state that produces the worst case).

    WHY WORST CASE, NOT EXPECTED. Commission on net winnings is charged only where you finish
    ahead, so the total cost of a cover DEPENDS ON WHICH OUTCOME WINS. Exactly one will. An
    "arbitrage" that is only profitable when the favourite wins is not an arbitrage -- it is a
    directional bet with extra steps. Taking the max over settlement states is what makes the
    reported edge a guarantee rather than an average.

    This matters precisely for the venues L7 identified as cheap: SX Bet and the betting exchanges
    charge nothing at entry and everything at settlement, so a screen that only counted entry fees
    would rate them free.
    """
    by_venue: dict[str, list[Fill]] = {}
    for l, fs in zip(legs, fills_per_leg):
        by_venue.setdefault(l.venue, []).extend(fs)

    entry = sum(model_for(v).entry_cost(fs, params_for(v, _ov(legs, v)))
                for v, fs in by_venue.items())

    worst, worst_state = 0.0, ""
    for winner in legs:                       # exactly one outcome settles YES
        won = {l.outcome_id: (l.outcome_id == winner.outcome_id) for l in legs}
        s = sum(model_for(v).settlement_cost(fs, won, params_for(v, _ov(legs, v)))
                for v, fs in by_venue.items())
        if s > worst:
            worst, worst_state = s, winner.outcome_id
    return entry, worst, worst_state


def _ov(legs: Sequence[Leg], venue: str) -> Mapping[str, object]:
    for l in legs:
        if l.venue == venue:
            return l.fee_overrides
    return {}


def price_combination(legs: Sequence[Leg], contracts: float, *, now_utc: float,
                      max_leg_age_s: float, proof: CoverProof | None) -> Cover:
    """Exact cost of one specific assignment of outcomes to venues. No greed, no approximation.

    `proof` is a `CoverProof` -- the exhaustiveness proof from `nodes/rules_exhaustive` composed
    with the settlement-equivalence proof from `nodes/settle_wedge`. Neither can be asserted by
    a caller: a bool let `grids/live_sports` price 3-way EPL at +31%, and an unproven settlement
    basis is how two venues pay differently on the same game. The proof also supplies the
    settlement-risk reserve, which is part of the cost.
    """
    if not isinstance(proof, CoverProof):
        return Cover(None, contracts, (), False, REJECT_NO_PROOF)

    if any(not l.executable for l in legs):
        return Cover(None, contracts, (), False, REJECT_NOT_EXECUTABLE)

    # SAME-BOOK COVERS ARE LEGAL AND ARE KEPT, LABELLED.
    # Buying outcome A and outcome B on ONE venue is a perfectly real cover — L7 showed it is the
    # CHEAP case, because net-winnings commission then applies to the arb edge alone rather than
    # to a full leg. What the liquidity_source guard actually exists to prevent is treating two
    # renderings of the SAME OUTCOME as independent venues (Kalshi and Robinhood are one book), so
    # that is what it now checks. Rejecting all same-venue covers would have thrown away both the
    # cheapest structure and the intra-venue no-arb control.
    seen: set[tuple[str, str]] = set()
    for l in legs:
        k = (l.liquidity_source, l.outcome_id)
        if k in seen:
            return Cover(None, contracts, (), False, REJECT_SAME_BOOK)
        seen.add(k)

    ages = [now_utc - l.book.fetched_utc for l in legs if l.book.fetched_utc]
    max_age = max(ages) if ages else None
    if max_age is None or max_age > max_leg_age_s:
        return Cover(None, contracts, (), False, REJECT_STALE, max_age)

    # Below a leg's minimum order the venue will not take it: not a cover, and named as such.
    if any(contracts < l.min_order_contracts for l in legs):
        return Cover(None, contracts, (), False, REJECT_BELOW_MIN_ORDER, max_age)

    made = [_fills_for(l, contracts, i) for i, l in enumerate(legs)]
    if not all(filled for _, _, filled in made):
        costs = tuple(LegCost(l.venue, l.outcome_id, contracts, g, 0.0, (g / contracts if contracts else 0.0), ok)
                      for l, (_, g, ok) in zip(legs, made))
        return Cover(None, contracts, costs, False, REJECT_NO_DEPTH, max_age)

    fills_per_leg = [fs for fs, _, _ in made]
    gross = sum(g for _, g, _ in made)
    entry, settle, state = _cover_fees(legs, fills_per_leg)
    fee = entry + settle
    # The settlement-risk reserve: probability x worst-case loss on each bounded dimension,
    # charged at the fill prices. A cover is only a cover net of it.
    buf = proof.settlement_buffer([(l.venue, g / contracts) for l, (_, g, _) in zip(legs, made)])
    costs = tuple(LegCost(l.venue, l.outcome_id, contracts, g, 0.0, g / contracts, True)
                  for l, (_, g, _) in zip(legs, made))
    return Cover((gross + fee) / contracts + buf, contracts, costs, True, None, max_age,
                 gross / contracts, fee / contracts, worst_settlement_state=state,
                 single_venue=len({l.venue for l in legs}) == 1,
                 settlement_buffer_per_contract=buf)


def best_cover(offers: Mapping[str, Sequence[Leg]], contracts: float, *, now_utc: float,
               max_leg_age_s: float = 30.0, proof: CoverProof | None = None,
               top_k: int = 8) -> Cover:
    """Cheapest fee-net cover over `offers` = {outcome_id: [Leg, ...]}.

    TWO PHASES, deliberately.
      GENERATE — rank each outcome's venues by fee-INCLUSIVE cost in isolation and keep the top
                 few. This is the greedy step and its output is a candidate list, never a number.
      RE-PRICE — evaluate the full cartesian product of those survivors EXACTLY. This is what
                 recovers the cases greedy gets wrong, which exist because Kalshi's ceil is per
                 order and net-winnings commission aggregates per venue-market.

    `top_k` bounds the product. With 2 outcomes and 3 venues the product is 9 and the bound never
    binds; it exists so a 3-way soccer market across many venues stays tractable. When it DOES
    bind, that is a silently-dropped combination, so the count is reported by the caller.
    """
    if not offers or any(not v for v in offers.values()):
        return Cover(None, contracts, (), False, REJECT_NO_DEPTH)

    ranked: list[list[Leg]] = []
    for _, legs in sorted(offers.items()):
        scored = []
        for l in legs:
            c = price_leg(l, contracts)
            # unfillable legs sort last but are not discarded — a 2-venue market where one leg is
            # thin must report insufficient_depth, not silently fall back to the other venue
            scored.append(((0 if c.filled else 1, c.gross + c.fee), l))
        scored.sort(key=lambda x: x[0])
        ranked.append([l for _, l in scored[:top_k]])

    best = Cover(None, contracts, (), False, REJECT_NO_DEPTH)
    for combo in itertools.product(*ranked):
        cov = price_combination(list(combo), contracts, now_utc=now_utc,
                                max_leg_age_s=max_leg_age_s, proof=proof)
        if not cov.ok:
            if not best.ok and best.reject_reason in (REJECT_NO_DEPTH, None):
                best = cov          # keep the most informative rejection
            continue
        if not best.ok or cov.cost_per_contract < best.cost_per_contract:
            best = cov
    return best


def selftest() -> None:
    from kernel.schema import Quote
    from nodes.settle_wedge.fixtures import mlb_cover_proof

    #: A real proof, minted from the mlb_no_draw rule. Tests may not forge one.
    MLB2 = mlb_cover_proof(["a", "b"])

    def bk(levels, age=0.0):
        return Book(asks=tuple(Quote(p, s) for p, s in levels), fetched_utc=1000.0 - age)

    NOW = 1000.0
    # ── ladder walking: VWAP, not the touch ──────────────────────────────
    b = bk([(0.40, 10), (0.50, 990)])
    gross, filled = walk_ladder(b, 100)
    assert filled and abs(gross - (10 * 0.40 + 90 * 0.50)) < 1e-9, gross
    assert abs(gross / 100 - 0.49) < 1e-9, "vwap must exceed the 0.40 touch"
    assert walk_ladder(b, 5000)[1] is False, "must report an unfillable ladder"

    # ── exhaustiveness is PROVEN, never assumed ──────────────────────────
    offers = {"A": [Leg("kalshi", "kalshi_clob", "a", "m", bk([(0.45, 1000)]))],
              "B": [Leg("polymarket", "pm_clob", "b", "m", bk([(0.45, 1000)]))]}
    assert best_cover(offers, 100, now_utc=NOW).reject_reason == REJECT_NO_PROOF
    good = best_cover(offers, 100, now_utc=NOW, proof=MLB2)
    assert good.ok, good.reject_reason
    # 0.45+0.45 = 0.90 gross, plus both venues' fees -> still well under 1.0
    assert abs(good.gross_per_contract - 0.90) < 1e-9, good.gross_per_contract
    assert good.fee_per_contract > 0, "fees must be charged, not skipped"
    assert good.edge_per_contract > 0

    # ── a stale leg is REJECTED, not discounted ──────────────────────────
    stale = {"A": [Leg("kalshi", "kalshi_clob", "a", "m", bk([(0.45, 1000)], age=120))],
             "B": [Leg("polymarket", "pm_clob", "b", "m", bk([(0.45, 1000)]))]}
    assert best_cover(stale, 100, now_utc=NOW, proof=MLB2).reject_reason == REJECT_STALE

    # ── two legs on the SAME book is an accounting error ─────────────────
    # same book, DIFFERENT outcomes -> a legal same-venue cover, kept and labelled
    same_ok = {"A": [Leg("kalshi", "kalshi_clob", "a", "m", bk([(0.45, 1000)]))],
               "B": [Leg("robinhood", "kalshi_clob", "b", "m", bk([(0.45, 1000)]))]}
    c = best_cover(same_ok, 100, now_utc=NOW, proof=MLB2)
    assert c.ok, c.reject_reason
    assert c.single_venue is False        # two venue NAMES, one underlying book
    # same book, SAME outcome twice -> double-counting one book as two, rejected
    dbl = {"A": [Leg("kalshi", "kalshi_clob", "a", "m", bk([(0.45, 1000)]))],
           "B": [Leg("robinhood", "kalshi_clob", "a", "m", bk([(0.45, 1000)]))]}
    assert best_cover(dbl, 100, now_utc=NOW, proof=MLB2).reject_reason == REJECT_SAME_BOOK

    # ── depth binds BEFORE price: a great touch with no size is no cover ─
    thin = {"A": [Leg("kalshi", "kalshi_clob", "a", "m", bk([(0.10, 5)]))],
            "B": [Leg("polymarket", "pm_clob", "b", "m", bk([(0.45, 1000)]))]}
    assert best_cover(thin, 100, now_utc=NOW, proof=MLB2).reject_reason == REJECT_NO_DEPTH

    # ── cost RISES with size when the ladder is layered ──────────────────
    lad = {"A": [Leg("kalshi", "kalshi_clob", "a", "m", bk([(0.40, 50), (0.48, 5000)]))],
           "B": [Leg("polymarket", "pm_clob", "b", "m", bk([(0.45, 50), (0.50, 5000)]))]}
    small = best_cover(lad, 50, now_utc=NOW, proof=MLB2)
    big = best_cover(lad, 500, now_utc=NOW, proof=MLB2)
    assert small.ok and big.ok
    assert big.cost_per_contract > small.cost_per_contract, "depth-aware cost must rise with size"

    # ── settlement-fee venues are priced at the WORST settlement state ───
    # SX Bet charges 0 at entry. If it charged on net winnings, a screen counting only entry fees
    # would rate the cover free. Betfair (5% on net winnings) makes the effect visible.
    bf = {"A": [Leg("betfair", "betfair_exchange", "a", "m", bk([(0.45, 5000)]))],
          "B": [Leg("polymarket", "pm_clob", "b", "m", bk([(0.45, 5000)]))]}
    cov = best_cover(bf, 100, now_utc=NOW, proof=MLB2)
    assert cov.ok and cov.fee_per_contract > 0
    assert cov.worst_settlement_state == "a", cov.worst_settlement_state
    # the Betfair leg winning costs 5% of its (1-p) net winnings; the PM leg winning costs nothing
    # on Betfair. So the worst state must be the one where the BETFAIR leg wins.
    entry_only = sum(price_leg(l, 100).fee for legs in bf.values() for l in legs)
    assert cov.fee_per_contract * 100 > entry_only, "settlement fee must be counted"

    # ── the venue chosen per leg is the fee-NET cheapest, not the cheapest gross ──
    # SX Bet is 0% commission; Kalshi charges ~1.75c at the money. A slightly worse SX gross can
    # still win once fees are counted, which is the entire point of pricing before choosing.
    two = {"A": [Leg("kalshi", "kalshi_clob", "a", "m", bk([(0.50, 5000)])),
                 Leg("sxbet", "sxbet_clob", "a2", "m", bk([(0.505, 5000)]))],
           "B": [Leg("polymarket", "pm_clob", "b", "m", bk([(0.45, 5000)]))]}
    got = best_cover(two, 100, now_utc=NOW, proof=MLB2)
    assert got.ok and got.legs[0].venue == "sxbet", [l.venue for l in got.legs]

    print("nodes.cover.cover selftest OK")


if __name__ == "__main__":
    selftest()
