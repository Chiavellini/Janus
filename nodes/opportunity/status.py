#!/usr/bin/env python3
"""One evaluation -> one `OpportunityStatus`. The classifier every writer uses.

Before this existed each grid computed a status inline from three literals and fell through to a
lowercase `reject_reason` when the cover failed, so `stream_evaluations.status` held
`ACTIONABLE`, `NO_EDGE`, `NO_PRICE`, `stale_leg`, `insufficient_depth` and `kalshi:home:SEQ_GAP`
side by side. The fine-grained reason is still recorded (`blocked_by`); the status is the enum.

Two thresholds, deliberately distinct (spec §7):
    discovery threshold   gross edge > 0            -> DISCOVERED
    execution threshold   locked return >= hurdle   -> PROFITABLE_UNEXECUTED
A cover with a positive gross edge that fees eat is BLOCKED_FEES, not NO_EDGE: the venues
disagreed and the fee floor won, which is a different finding from the venues agreeing.
"""

from __future__ import annotations

from kernel.schema import OpportunityStatus as S

#: `nodes/cover` reject reasons -> status. Anything not listed is BLOCKED_MATCH, the safe default:
#: an unknown refusal is treated as "identity not proven", never as a price finding.
_REJECT = {
    "stale_leg": S.BLOCKED_STALE,
    "insufficient_depth": S.BLOCKED_DEPTH,
    "outcome_set_not_proven_exhaustive": S.BLOCKED_RULES,
    "cover_proof_missing": S.BLOCKED_RULES,
    "settlement_not_equivalent": S.BLOCKED_RULES,
    "shared_liquidity_source": S.BLOCKED_MATCH,
    "quote_not_accepted": S.BLOCKED_DEPTH,
    "below_min_order": S.BLOCKED_DEPTH,
}

#: `nodes/game_poller` blocked_by suffixes (`venue:outcome:<FAULT>`) -> status.
_FAULT = {
    "SEQ_GAP": S.BLOCKED_STALE, "HASH_MISMATCH": S.BLOCKED_STALE, "HEARTBEAT_LOST": S.BLOCKED_STALE,
    "UNVERIFIED_TOO_LONG": S.BLOCKED_STALE, "STALE": S.BLOCKED_STALE, "NOT_SYNCED": S.BLOCKED_STALE,
    "CROSSED_BOOK": S.BLOCKED_STALE,
    "NO_ASKS": S.BLOCKED_DEPTH,
    "FEE_SCHEDULE_MISSING": S.BLOCKED_FEES,
    "CLOCK_UNHEALTHY": S.BLOCKED_STALE,       # every freshness bound is fiction on a bad clock
}


def status_for(*, cover_ok: bool, reject_reason: str | None, blocked_by: str | None,
               gross_per_contract: float | None, cost_per_contract: float | None,
               single_venue: bool, hurdle: float) -> S:
    """Classify one evaluation. Pure. `hurdle` is the execution threshold on locked return."""
    if blocked_by:
        key = blocked_by.rsplit(":", 1)[-1]
        return _FAULT.get(key, S.BLOCKED_STALE)
    if not cover_ok:
        return _REJECT.get(reject_reason or "", S.BLOCKED_MATCH)
    if single_venue:
        return S.BLOCKED_MATCH                    # the intra-venue control is not a cross-venue pair
    if gross_per_contract is None or cost_per_contract is None or cost_per_contract <= 0:
        return S.BLOCKED_MATCH
    if gross_per_contract >= 1.0:
        return S.NO_EDGE
    if cost_per_contract >= 1.0:
        return S.BLOCKED_FEES
    ret = (1.0 - cost_per_contract) / cost_per_contract
    return S.PROFITABLE_UNEXECUTED if ret >= hurdle else S.DISCOVERED
