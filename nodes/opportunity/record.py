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
from nodes.fees.targeting import hurdle_for
from nodes.opportunity.status import status_for


@dataclass(frozen=True)
class Recorded:
    status: OpportunityStatus
    wrote: bool
    gross: float | None
    cost: float | None
    fee: float | None
    locked_return: float | None


def record_evaluation(store, ev, *, league: str, fee_params: Mapping[str, Mapping],
                      hurdle: float) -> Recorded:
    """Classify and offer one evaluation to `store.evaluation` (change-gated). Pure apart from
    the store write. `fee_params` are the venues' own schedules, so the hurdle charges what the
    cover charged."""
    cov = ev.cover
    ok = bool(cov and cov.ok)
    gross = cov.gross_per_contract if ok else None
    fee = cov.fee_per_contract if ok else None
    cost = cov.cost_per_contract if ok else None
    ret = ev.actionable_return
    hd = None
    if ok and cov.legs:
        fav = max(l.vwap for l in cov.legs)
        hd = hurdle_for(fav, hurdle=hurdle, overrides_a=fee_params.get("kalshi"),
                        overrides_b=fee_params.get("polymarket"))
    status = status_for(cover_ok=ok, reject_reason=cov.reject_reason if cov else None,
                        blocked_by=ev.blocked_by, gross_per_contract=gross, cost_per_contract=cost,
                        single_venue=bool(ok and cov.single_venue), hurdle=hurdle)
    wrote = store.evaluation(
        game_id=ev.game_id, league=league, quantity=ev.quantity, status=status.value,
        cost=cost, gross=gross, fees=fee, return_locked=ret,
        required_ask_sum=hd.required_ask_sum if hd else None,
        cents_from_actionable=(round((gross - hd.required_ask_sum) * 100.0, 4)
                               if (hd and gross is not None) else None),
        blocked_by=ev.blocked_by, triggered_by=ev.triggered_by, latency_ms=ev.latency_ms,
        legs=[{"venue": l.venue, "outcome": l.outcome_id, "vwap": round(l.vwap, 6)}
              for l in (cov.legs if ok else ())],
        seen_ts=ev.evaluated_utc)
    return Recorded(status, bool(wrote), gross, cost, fee, ret)
