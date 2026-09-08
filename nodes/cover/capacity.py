#!/usr/bin/env python3
"""How much money the cover is actually worth: the size frontier, not a yes/no at one size.

The lane priced three fixed quantities -- 5, 25 and 100 contracts -- and reported whether each
cleared the hurdle. That answers "is there an edge at 100 contracts". It does not answer "how much
does this make", which is the only question that decides whether the strategy is worth running.

THE SHAPE OF THE PROBLEM. A cover buys equal PAYOUT units, not equal dollars: N contracts of each
complementary outcome, each settling at $1, so exactly $N arrives whichever way it resolves. The
cost of the Nth unit rises as you eat through both ladders, so

    profit(N) = N * (1 - cost(N))          cost(N) = VWAP_a(N) + VWAP_b(N) + fees(N)/N

rises while the marginal unit is still cheap and falls once it is not. Two different numbers matter
and they are not the same N:

    N_max   the largest size that still clears the hurdle -- the capacity of the opportunity
    N_star  the size that maximises total profit -- where you would actually trade

N_star <= N_max always, and on a layered book they are usually far apart. Reporting only whether
some fixed N cleared the bar hides both.

WHY BREAKPOINTS AND NOT A BINARY SEARCH. cost(N) is piecewise linear: it bends exactly where one
ladder's cumulative depth is exhausted and the next level starts filling. Evaluating at those
breakpoints is exact and cheap, where a binary search over a fee curve that steps (Kalshi's ceil is
per order, so cost(N) is not perfectly monotone at small N) can land between the steps and report a
frontier that is off by a level.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from nodes.cover.cover import Cover, Leg, REJECT_BELOW_MIN_ORDER, best_cover
from nodes.settle_wedge.equivalence import CoverProof


#: The pooled slippage buffer, REMOVED by operator decision 2026-09-08 (0.0400 -> 0.0).
#: What it was: ledger L27 (research/sports/2026-09-03_kalshi-hedge-window-slippage), run
#: 20260905T104523Z -- the p95 adverse move of the Kalshi YES ask at 100 contracts measured inside
#: a 3 s hedge window, over 32,149,854 delta instants and 326 tickers, giving four ticks.
#: Why it is gone: 3 s is `max_hedge_latency_ms`, the window's ceiling, not the horizon the box
#: actually runs (L34: box->Kalshi p50 51 ms, box->CLOB 184 ms), and the pooled figure mixes thin
#: tennis books with MLB. A reserve measured at a horizon we do not run priced out nearly every
#: cover the lane printed while insuring a window that never opened. Nothing yet measures the real
#: horizon, so this goes to zero rather than to a smaller invented number: L41 (the stratified
#: per-league row below) is what re-registers a measured value, and MLB already has one.
#: Note this constant has never gated an order -- `slippage_for` is read only by `frontier()`, for
#: the reported N_max/N*, and never by `best_cover` / `plan_from_cover` / `clear`.
SLIPPAGE_PER_CONTRACT = 0.0
#: False since 2026-09-08, with the pooled reserve. "Unmeasured is labelled, never assumed zero" is
#: this module's rule, and a zero reserve carrying `modelled = True` would assert on every recorded
#: row that we measured no slippage. We did not: we withdrew a number measured at the wrong horizon
#: and have nothing yet at the right one. Every frontier and opportunity row for a league without an
#: entry in SLIPPAGE_BY_LEAGUE is therefore labelled unmodelled until L41 lands. This flag is global
#: while the table below is per-league, so MLB's measured 0.01 is under-claimed as unmodelled too --
#: the cautious direction, and L41's row is where the label turns per-league.
SLIPPAGE_MODELLED = False
SLIPPAGE_RESEARCH_REF = "research/sports/2026-09-03_kalshi-hedge-window-slippage/spec.yaml"
#: Per league, from ledger L41 (the stratified row: clean windows only, time-weighted, p95 at 3 s
#: and q = 25), registered only for a league with >= 2,000 instants over >= 4 tickers. Empty until
#: the row's values are entered from its results file; every other league keeps the pooled pin.
SLIPPAGE_BY_LEAGUE: dict[str, float] = {
    # INTERIM (2026-09-07 20:50Z, the operator's decision): MLB from L27's FIRST run
    # (20260903T061757Z: 8 MLB tickers, 2,152 delta instants, p95 at 3 s = 0.0100). Thin, and the
    # only per-league number that exists before L41 lands (~2 h). L41's rule replaces it; the
    # pooled 0.04 stays for every other league until then.
    "mlb": 0.0100,
}
SLIPPAGE_BY_LEAGUE_RESEARCH_REF = "research/sports/2026-09-07_kalshi-slippage-by-league/spec.yaml"


def slippage_for(league: str | None) -> float:
    """The registered slippage reserve for a league: L41's value where it exists, L27's pool otherwise."""
    return SLIPPAGE_BY_LEAGUE.get(league or "", SLIPPAGE_PER_CONTRACT)


@dataclass(frozen=True)
class Rung:
    """One point on the frontier."""
    contracts: float
    cost_per_contract: float
    edge_per_contract: float
    profit: float                 # contracts * edge
    capital: float                # contracts * cost -- what you actually put up
    venues: tuple[str, ...]

    @property
    def return_on_capital(self) -> float:
        return 0.0 if self.capital <= 0 else self.profit / self.capital


@dataclass(frozen=True)
class Frontier:
    """The whole size curve for one matched market at one instant."""
    rungs: tuple[Rung, ...]
    n_max: float                  # largest size clearing the hurdle (0 if none)
    n_star: float                 # size maximising total profit (0 if none)
    best: Rung | None             # the rung at n_star
    limit_reason: str             # why the frontier stops
    #: The cost model this frontier was solved under. `slippage_modelled` is False until the
    #: buffer comes from a registered measurement of captured frames; a False here caps the
    #: mode at PAPER_EXECUTION (spec §6: conservative slippage buffer, never a guess).
    slippage_per_contract: float = 0.0
    slippage_modelled: bool = False
    fixed_cost_usd: float = 0.0

    @property
    def actionable(self) -> bool:
        return self.best is not None and self.best.profit > 0


def _breakpoints(offers: Mapping[str, Sequence[Leg]], cap: float) -> list[float]:
    """Cumulative depths at which either ladder changes level, plus the cap.

    These are the only sizes where the slope of cost(N) changes, so the frontier is fully described
    by evaluating at them. A point just past each breakpoint is included as well, because the rung
    that first becomes unaffordable is the one that defines N_max.
    """
    marks: set[float] = set()
    for legs in offers.values():
        for leg in legs:
            cum = 0.0
            for q in leg.book.asks:
                cum += q.size
                if 0 < cum <= cap:
                    marks.add(round(cum, 6))
    marks.add(cap)
    return sorted(m for m in marks if m > 0)


def frontier(offers: Mapping[str, Sequence[Leg]], *, now_utc: float,
             proof: CoverProof, max_leg_age_s: float = 5.0,
             hurdle: float = 0.0, cap: float = 100_000.0,
             cross_venue_only: bool = True, balances: Mapping[str, float] | None = None,
             fixed_cost_usd: float = 0.0, slippage_per_contract: float = SLIPPAGE_PER_CONTRACT,
             slippage_modelled: bool = SLIPPAGE_MODELLED) -> Frontier:
    """Solve N_max and N_star by walking the ladders' own breakpoints.

    `hurdle` is a minimum return on capital; 0.0 asks only for a locked profit. `cross_venue_only`
    drops same-venue covers, which are the intra-venue no-arb control rather than an opportunity.

    THE TOTAL-COST MODEL (spec §6). A rung's cost is gross + fees over actual fills + the
    settlement reserve (all inside `Cover.cost_per_contract`) + `slippage_per_contract`, and its
    profit is N * (1 - cost) - `fixed_cost_usd`. A rung is refused when a leg is below its venue's
    minimum order (`min_order`) or when a venue's capital would exceed its `balances` entry
    (`balance`; a venue absent from `balances` has zero). Absent `balances` means unchecked --
    the caller (nodes/risk) must supply them before anything is sent.
    """
    rungs: list[Rung] = []
    reason = "cap_reached"
    for n in _breakpoints(offers, cap):
        cov: Cover = best_cover(offers, n, now_utc=now_utc,
                                max_leg_age_s=max_leg_age_s, proof=proof)
        if not cov.ok:
            if cov.reject_reason == REJECT_BELOW_MIN_ORDER:
                reason = "min_order"
                continue                      # a larger rung may clear the minimum
            reason = cov.reject_reason or "not_priced"
            break
        if cross_venue_only and cov.single_venue:
            reason = "single_venue_only"
            continue
        cost = (cov.cost_per_contract or 0.0) + slippage_per_contract
        edge = 1.0 - cost
        profit = n * edge - fixed_cost_usd
        capital = n * cost
        ret = 0.0 if capital <= 0 else profit / capital
        # Strictly positive, not merely non-negative. A cover priced at exactly 1.0000 locks no
        # profit and is not capacity -- and it is the single most common state on a coherent
        # market, so admitting it would report a frontier on every pair in the universe.
        if edge <= 0 or profit <= 0 or ret < hurdle:
            reason = "below_hurdle" if rungs else "never_above_hurdle"
            break
        if balances is not None:
            per_venue: dict[str, float] = {}
            for lc in cov.legs:
                per_venue[lc.venue] = per_venue.get(lc.venue, 0.0) + lc.gross
            over = [v for v, usd in per_venue.items() if usd > float(balances.get(v, 0.0))]
            if over:
                reason = "balance"
                break
        rungs.append(Rung(contracts=n, cost_per_contract=cost, edge_per_contract=edge,
                          profit=profit, capital=capital,
                          venues=tuple(sorted({l.venue for l in cov.legs}))))

    if not rungs:
        return Frontier((), 0.0, 0.0, None, reason, slippage_per_contract, slippage_modelled, fixed_cost_usd)
    best = max(rungs, key=lambda r: r.profit)
    return Frontier(tuple(rungs), rungs[-1].contracts, best.contracts, best, reason,
                    slippage_per_contract, slippage_modelled, fixed_cost_usd)


def selftest() -> None:
    from kernel.schema import Book, Quote
    from kernel.schema import liquidity_source_for
    from nodes.settle_wedge.fixtures import mlb_cover_proof

    def bk(levels):
        return Book(asks=tuple(Quote(p, s) for p, s in levels), fetched_utc=1000.0)

    # The layered book from the worked example: cheap at the touch, dear in the tail.
    offers = {
        "floyd": [Leg("polymarket", liquidity_source_for("polymarket"), "pm", "m",
                      bk([(0.51, 1000), (0.53, 2000), (0.58, 5000), (0.64, 10000)]),
                      {"fee_rate": 0.0})],
        "pacquiao": [Leg("kalshi", liquidity_source_for("kalshi"), "k", "m2",
                         bk([(0.32, 1000), (0.34, 2000), (0.38, 5000), (0.41, 10000)]),
                         {"fee_multiplier": 0.0})],
    }
    f = frontier(offers, now_utc=1000.0, proof=mlb_cover_proof(["floyd", "pacquiao"]))
    print(f"  {'N':>8} {'cost':>8} {'edge':>8} {'profit':>10} {'capital':>10}")
    for r in f.rungs:
        print(f"  {r.contracts:8.0f} {r.cost_per_contract:8.4f} {r.edge_per_contract:+8.4f} "
              f"{r.profit:10.2f} {r.capital:10.2f}")
    print(f"  N_max={f.n_max:.0f}  N_star={f.n_star:.0f}  limit={f.limit_reason}")
    assert f.actionable
    assert f.n_star <= f.n_max
    assert f.best.profit == max(r.profit for r in f.rungs)
    # the last affordable rung must still be under $1 all-in
    assert f.rungs[-1].cost_per_contract < 1.0
    print("cover.capacity selftest OK")


if __name__ == "__main__":
    selftest()
