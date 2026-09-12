#!/usr/bin/env python3
"""Four different nulls, four different names."""
from __future__ import annotations

from kernel.schema import OpportunityStatus as S
from nodes.opportunity.status import status_for


def ok(gross, cost, single=False, hurdle=0.01):
    return status_for(cover_ok=True, reject_reason=None, blocked_by=None, gross_per_contract=gross,
                      cost_per_contract=cost, single_venue=single, hurdle=hurdle)


def test_the_venues_agreeing_is_no_edge():
    assert ok(1.0000, 1.0150) is S.NO_EDGE
    assert ok(1.0200, 1.0350) is S.NO_EDGE


def test_a_divergence_the_fee_floor_eats_is_blocked_fees_not_no_edge():
    assert ok(0.9900, 1.0050) is S.BLOCKED_FEES


def test_the_two_thresholds_are_distinct():
    assert ok(0.9850, 0.9950) is S.DISCOVERED               # +0.5% locked, below the 1% hurdle
    assert ok(0.9700, 0.9850) is S.PROFITABLE_UNEXECUTED    # +1.5%
    assert ok(0.9700, 0.9850, hurdle=0.02) is S.DISCOVERED


def test_replica_faults_are_stale_and_missing_asks_are_depth():
    for f in ("SEQ_GAP", "HASH_MISMATCH", "HEARTBEAT_LOST", "UNVERIFIED_TOO_LONG", "STALE",
              "NOT_SYNCED", "CROSSED_BOOK"):
        assert status_for(cover_ok=False, reject_reason=None, blocked_by=f"kalshi:home:{f}",
                          gross_per_contract=None, cost_per_contract=None, single_venue=False,
                          hurdle=0.01) is S.BLOCKED_STALE, f
    assert status_for(cover_ok=False, reject_reason=None, blocked_by="polymarket:away:NO_ASKS",
                      gross_per_contract=None, cost_per_contract=None, single_venue=False,
                      hurdle=0.01) is S.BLOCKED_DEPTH
    assert status_for(cover_ok=False, reject_reason=None, blocked_by="polymarket:away:FEE_SCHEDULE_MISSING",
                      gross_per_contract=None, cost_per_contract=None, single_venue=False,
                      hurdle=0.01) is S.BLOCKED_FEES


def test_cover_rejections_map_by_name_and_unknown_is_match():
    def rej(r):
        return status_for(cover_ok=False, reject_reason=r, blocked_by=None, gross_per_contract=None,
                          cost_per_contract=None, single_venue=False, hurdle=0.01)
    assert rej("stale_leg") is S.BLOCKED_STALE
    assert rej("insufficient_depth") is S.BLOCKED_DEPTH
    assert rej("outcome_set_not_proven_exhaustive") is S.BLOCKED_RULES
    assert rej("shared_liquidity_source") is S.BLOCKED_MATCH
    assert rej("something_new") is S.BLOCKED_MATCH
    assert rej(None) is S.BLOCKED_MATCH


def test_the_intra_venue_control_is_never_an_opportunity():
    assert ok(0.9000, 0.9200, single=True) is S.BLOCKED_MATCH


def test_a_gross_too_low_to_be_a_cover_is_a_match_failure_not_a_200_percent_return():
    """L88: a proven partition pays $1, so its legs cost about $1. The three-leg soccer and MLS rows
    the board showed at 0.31 gross were reported as 201 % locked returns; a three-way partition
    cannot sum to a third of its payout, so those legs did not span the outcomes -- a stale leg, a
    wrong token, or a side read as its own complement. The exhaustiveness check cannot catch it
    (it compares labels minted from the same dict it checks); the arithmetic can."""
    from nodes.opportunity.status import MIN_CREDIBLE_GROSS
    # the exact MLS row: kalshi 0.17 + polymarket 0.09 + kalshi 0.05
    assert ok(0.31, 0.3316) is S.BLOCKED_MATCH
    assert ok(0.43, 0.4552) is S.BLOCKED_MATCH, "the Atalanta-shaped three-leg row"
    assert ok(MIN_CREDIBLE_GROSS - 0.0001, 0.72) is S.BLOCKED_MATCH


def test_the_floor_admits_every_real_cover_this_lane_has_settled():
    """0dfc6df3 is the richest cover on record that actually paid (+$0.38): planned 16.7 %, gross
    ~0.83. A floor that refused it would be refusing money, so this pins the headroom."""
    assert ok(0.83, 0.857) is S.PROFITABLE_UNEXECUTED
    assert ok(0.9500, 0.9808) is S.PROFITABLE_UNEXECUTED, "the DJERE plan, a normal cover"
