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
