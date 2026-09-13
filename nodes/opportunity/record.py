#!/usr/bin/env python3
"""One Evaluation -> one (gated) row. The write path the supervisor AND the replay share.

GATE_TO_LIVE step 4 asks that an offline parity check rebuild every logged decision by importing
the live runner's own constants. That is only mechanical if the live runner and the replay call
the same function with the same thresholds -- so the classification, the hurdle, and the row
shape live here and the grid only decides where the store is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from kernel.schema import OpportunityStatus
from nodes.opportunity.thresholds import EXECUTION_MIN_NET_PROFIT_USD
from nodes.fees.targeting import hurdle_for
from nodes.opportunity.opportunity import Opportunity
from nodes.opportunity.status import status_for


@dataclass(frozen=True)
class Recorded:
    status: OpportunityStatus
    wrote: bool
    gross: float | None
    cost: float | None
    fee: float | None
    locked_return: float | None
    net_profit_usd: float | None = None
    #: L98: the SINGLE-VENUE control's cost per contract, when the unconstrained best cover was
    #: single-venue and the numbers above were therefore re-priced against the two-venue
    #: requirement. None on every row whose best was already sendable.
    control_cost: float | None = None


def record_evaluation(store, ev, *, league: str, fee_params: Mapping[str, Mapping],
                      hurdle: float, opportunities=None) -> Recorded:
    """Classify and offer one evaluation to `store.evaluation` (change-gated). Pure apart from
    the store write. `fee_params` are the venues' own schedules, so the hurdle charges what the
    cover charged."""
    cov = ev.cover
    ok = bool(cov and cov.ok)
    # THE CLASSIFICATION IS THE UNCONSTRAINED COVER'S, ALWAYS. A single-venue best is
    # BLOCKED_MATCH and stays BLOCKED_MATCH: L98 changes what a row REPORTS, never what it blocks.
    status = status_for(cover_ok=ok, reject_reason=cov.reject_reason if cov else None,
                        blocked_by=ev.blocked_by,
                        gross_per_contract=cov.gross_per_contract if ok else None,
                        cost_per_contract=cov.cost_per_contract if ok else None,
                        single_venue=bool(ok and cov.single_venue), hurdle=hurdle)
    # L98 (2026-09-13): the numbers are the SENDABLE cover's. Until now they were the
    # unconstrained best's, which on a single-venue best is a cover the lane can never route --
    # and `cents_from_actionable` then charged a CROSS-venue fee model against INTRA-venue prices.
    # The re-price is gated on exactly that branch, so the ~24 % of rows whose best was already
    # two-venue cost nothing, and the single-venue best is kept beside them as the control it is.
    control = cov if (ok and cov.single_venue) else None
    priced = ev.sendable_cover() if control is not None else cov
    pok = bool(priced and priced.ok)
    gross = priced.gross_per_contract if pok else None
    fee = priced.fee_per_contract if pok else None
    cost = priced.cost_per_contract if pok else None
    ret = (ev.actionable_return if priced is cov
           else (((1.0 - cost) / cost) if cost else None))
    hd = None
    if pok and priced.legs:
        fav = max(l.vwap for l in priced.legs)
        hd = hurdle_for(fav, hurdle=hurdle, overrides_a=fee_params.get("kalshi"),
                        overrides_b=fee_params.get("polymarket"))
    net = (1.0 - cost) * ev.quantity if cost is not None else None
    if status is OpportunityStatus.PROFITABLE_UNEXECUTED and net is not None and net < EXECUTION_MIN_NET_PROFIT_USD:
        status = OpportunityStatus.DISCOVERED      # clears the return hurdle, not the dollar one
    legs = [{"venue": l.venue, "outcome": l.outcome_id, "vwap": round(l.vwap, 6)}
            for l in (priced.legs if pok else ())]
    if control is not None:
        # The control rides in `legs_json` because `stream_evaluations` has no column for it and
        # this node does not own that schema (see the report: one REAL column is the better fix).
        # It is safe here: the only reader of `legs_json`, `nodes/cover_cost/suspect.py`, selects
        # PROFITABLE_UNEXECUTED rows only, and a single-venue best is always BLOCKED_MATCH.
        legs.append({"control": "single_venue",
                     "venues": sorted({l.venue for l in control.legs}),
                     "gross": round(control.gross_per_contract, 6),
                     "cost": round(control.cost_per_contract, 6)})
    wrote = store.evaluation(
        game_id=ev.game_id, league=league, quantity=ev.quantity, status=status.value,
        cost=cost, gross=gross, fees=fee, return_locked=ret,
        required_ask_sum=hd.required_ask_sum if hd else None,
        cents_from_actionable=(round((gross - hd.required_ask_sum) * 100.0, 4)
                               if (hd and gross is not None) else None),
        blocked_by=ev.blocked_by, triggered_by=ev.triggered_by, latency_ms=ev.latency_ms,
        legs=legs,
        seen_ts=ev.evaluated_utc)
    if opportunities is not None and (status is OpportunityStatus.PROFITABLE_UNEXECUTED
                                      or status is OpportunityStatus.DISCOVERED
                                      or Opportunity.id_for(ev.game_id, ev.quantity) in opportunities.live):
        opportunities.observe(event_id=ev.game_id, league=league, quantity=ev.quantity, status=status,
                              now=ev.evaluated_utc, gross=gross, fees=fee,
                              settlement_buffer=priced.settlement_buffer_per_contract if pok else None,
                              net_profit=net, locked_return=ret, blocked_by=ev.blocked_by,
                              legs=[{"venue": l.venue, "outcome": l.outcome_id, "vwap": round(l.vwap, 6)}
                                    for l in (priced.legs if pok else ())],
                              offers=ev.offers if ok else None)
    return Recorded(status, bool(wrote), gross, cost, fee, ret, net,
                    control_cost=control.cost_per_contract if control is not None else None)
