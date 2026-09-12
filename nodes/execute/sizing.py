#!/usr/bin/env python3
"""Choose the live equal-payout quantity that maximises locked dollar profit.

This is deliberately a *conditional-fill* selector.  It does not invent a size-dependent maker
fill probability or hedge-tail model: those require prospective evidence.  Every integer quantity
inside the signed contract cap is repriced from the same frozen pair of books, then filtered through
the outer arm, balances and the already-reserved exposure picture without mutating that picture.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from nodes.cover.cover import Cover, Leg, best_cover
from nodes.execute.plan import Plan, plan_from_cover
from nodes.risk.limits import RiskLimits
from nodes.settle_wedge.equivalence import CoverProof


@dataclass(frozen=True)
class SizedCandidate:
    quantity: int
    cover: Cover | None
    plan: Plan | None
    profit_usd: float | None
    capital_usd: float | None
    per_venue_usd: Mapping[str, float]
    refusals: tuple[str, ...]

    @property
    def feasible(self) -> bool:
        return self.plan is not None and not self.refusals


@dataclass(frozen=True)
class SizingDecision:
    candidates: tuple[SizedCandidate, ...]
    selected: SizedCandidate | None
    n_max_feasible: int
    n_star_feasible: int
    binding_constraints: tuple[str, ...]
    risk_context: Mapping[str, object]
    fill_model: str = "BOUNDED_TAKER_V1"

    def audit(self) -> dict:
        selected = self.selected
        return {
            "objective": "MAX_LOCKED_PROFIT_CONDITIONAL_ON_COMPLETION",
            "selection_rule": "max profit_usd; ties lower capital_usd then smaller integer quantity",
            "selected_reason": ("maximum conditional locked dollar profit among feasible candidates"
                                if selected is not None else "no feasible candidate"),
            "n_star_feasible": self.n_star_feasible,
            "n_max_feasible": self.n_max_feasible,
            "binding_constraints": list(self.binding_constraints),
            "risk_context": dict(self.risk_context),
            "fill_model": self.fill_model,
            "candidates": [
                {
                    "quantity": c.quantity,
                    "profit_usd": c.profit_usd,
                    "capital_usd": c.capital_usd,
                    "per_venue_usd": dict(c.per_venue_usd),
                    "refusals": list(c.refusals),
                    "cover": None if c.cover is None else {
                        "cost_per_contract": c.cover.cost_per_contract,
                        "gross_per_contract": c.cover.gross_per_contract,
                        "fee_per_contract": c.cover.fee_per_contract,
                        "settlement_buffer_per_contract": c.cover.settlement_buffer_per_contract,
                        "max_leg_age_s": c.cover.max_leg_age_s,
                        "legs": [dict(venue=leg.venue, outcome_id=leg.outcome_id,
                                      contracts=leg.contracts, gross=leg.gross, fee=leg.fee,
                                      vwap=leg.vwap) for leg in c.cover.legs],
                    },
                    "plan": None if c.plan is None else {
                        "first": dict(c.plan.first.__dict__), "hedge": dict(c.plan.hedge.__dict__),
                        "max_cost_per_contract": c.plan.max_cost_per_contract,
                        "fee_per_contract": c.plan.fee_per_contract,
                        "settlement_buffer_per_contract": c.plan.settlement_buffer_per_contract,
                        "quote_expires_utc": c.plan.quote_expires_utc,
                    },
                    "selected": selected is not None and c.quantity == selected.quantity,
                }
                for c in self.candidates
            ],
        }


def _risk_refusals(*, event_id: str, league: str, per_venue: Mapping[str, float],
                   limits: RiskLimits, ledger, balances: Mapping[str, float], caps: Mapping[str, float],
                   now: float, day_used: float | None = None) -> list[str]:
    """Read-only mirror of the numeric parts of ``nodes.risk.clearance.clear``.

    The real gate still runs and owns the reservation.  This mirror only prevents a quantity known
    to be impossible from winning the size objective.
    """
    out: list[str] = []
    total = float(sum(per_venue.values()))
    stake_cap = float(caps.get("stake_usd", 0.0))
    if total > stake_cap + 1e-9:
        out.append("CAP_STAKE")
    day_cap = float(caps.get("day_notional_usd", 0.0))
    used = float(ledger.day_notional_usd(now)) if day_used is None else float(day_used)   # L79: once per decision
    if used + total > day_cap + 1e-9:
        out.append("CAP_DAY_NOTIONAL")
    for venue, usd in per_venue.items():
        if float(balances.get(venue, 0.0)) + 1e-9 < usd:
            out.append(f"BALANCE:{venue}")
    for refused in ledger.assess(event_id=event_id, league=league, per_venue_usd=per_venue, limits=limits):
        if refused.code == "VENUE_CAPITAL":
            venue = refused.detail.split(":", 1)[0]
            out.append(f"VENUE_CAPITAL:{venue}")
        else:
            out.append(refused.code)
    return out


def choose_live_size(offers: Mapping[str, Sequence[Leg]], *, now_utc: float, proof: CoverProof,
                     event_id: str, league: str, caps: Mapping[str, float], limits: RiskLimits,
                     ledger, balances: Mapping[str, float], max_leg_age_s: float = 5.0,
                     hurdle: float = 0.01, min_net_profit_usd: float = 0.10,
                     max_quote_age_s: float = 3.0) -> SizingDecision:
    """Reprice every whole quantity under the signed cap and select conditional-fill ``N*``.

    Whole quantities preserve equal payout units on Kalshi.  Exhaustive enumeration is intentional
    at the current small live cap (10): it includes every ladder breakpoint and fee-cent step rather
    than assuming monotonic per-contract economics.
    """
    context = {
        "limits_sha": limits.sha,
        "caps": {k: float(v) for k, v in caps.items()},
        "balances_usd": {k: float(v) for k, v in balances.items()},
        "day_notional_used_usd": float(ledger.day_notional_usd(now_utc)),   # the one read (L79)
        "max_unhedged_contracts": float(limits.max_unhedged_contracts),
        "proof": proof.as_record(),
        "required_venues": ["kalshi", "polymarket"],
        "required_leg_count": 2,
        "max_leg_age_s": float(max_leg_age_s),
        "hurdle": float(hurdle),
        "min_net_profit_usd": float(min_net_profit_usd),
    }
    if not caps or any(name not in caps for name in ("stake_usd", "max_contracts", "day_notional_usd")):
        return SizingDecision((), None, 0, 0, ("NO_CAPS",), context)
    max_q = int(math.floor(float(caps["max_contracts"]) + 1e-9))
    if max_q < 1:
        return SizingDecision((), None, 0, 0, ("CAP_CONTRACTS",), context)

    candidates: list[SizedCandidate] = []
    constraints: set[str] = set()
    for q in range(1, max_q + 1):
        cov = best_cover(offers, float(q), now_utc=now_utc, max_leg_age_s=max_leg_age_s, proof=proof,
                         required_venues=frozenset({"polymarket", "kalshi"}), leg_count=2)
        refusals: list[str] = []
        plan = None
        profit = capital = None
        per_venue: dict[str, float] = {}
        if not cov.ok:
            refusals.append(cov.reject_reason or "NOT_PRICED")
        elif cov.single_venue or len(cov.legs) != 2:
            refusals.append("NOT_TWO_VENUE")
        else:
            # Size on the same executable-price taker Plan persisted and executed by the live grid.
            plan = plan_from_cover(
                opportunity_id=f"{event_id}:sizing:{q}", event_id=event_id, league=league,
                cov=cov, offers=offers, hurdle=hurdle, min_net_profit_usd=min_net_profit_usd,
            )
            if plan is None:
                refusals.append("NO_TAKER_PLAN")
            else:
                # Do not credit the passive maker improvement before it fills. The crossed
                # cover's walked gross is the conservative economic basis; replace only its fee
                # with the finalized Plan fee (which includes any affordable maker-pad reprice).
                expected_cost_per_contract = (
                    float(cov.gross_per_contract or 0.0) + plan.fee_per_contract
                    + plan.settlement_buffer_per_contract
                )
                capital = float(q) * expected_cost_per_contract
                profit = float(q) - capital
                locked_return = profit / capital if capital > 0 else 0.0
                if profit + 1e-9 < min_net_profit_usd:
                    refusals.append("MIN_PROFIT")
                if locked_return + 1e-12 < hurdle:
                    refusals.append("MIN_RETURN")
                per_venue = {
                    plan.first.venue: plan.first.contracts * plan.first.limit_price,
                    plan.hedge.venue: plan.hedge.contracts * plan.hedge.limit_price,
                }
                if q > limits.max_unhedged_contracts:
                    refusals.append("MAX_UNHEDGED")
                refusals.extend(_risk_refusals(event_id=event_id, league=league,
                                               per_venue=per_venue, limits=limits, ledger=ledger,
                                               balances=balances, caps=caps, now=now_utc, day_used=context["day_notional_used_usd"]))
        constraints.update(refusals)
        candidates.append(SizedCandidate(q, cov if cov.ok else None, plan, profit, capital,
                                         per_venue, tuple(dict.fromkeys(refusals))))

    feasible = [c for c in candidates if c.feasible]
    if not feasible:
        return SizingDecision(tuple(candidates), None, 0, 0,
                              tuple(sorted(constraints | {"CAP_CONTRACTS"})), context)
    # A smaller quantity wins an exact profit tie: same dollars with less fill and hedge exposure.
    selected = max(feasible, key=lambda c: (float(c.profit_usd or 0.0),
                                             -float(c.capital_usd or 0.0), -c.quantity))
    return SizingDecision(tuple(candidates), selected, max(c.quantity for c in feasible), selected.quantity,
                          tuple(sorted(constraints | {"CAP_CONTRACTS"})), context)
