#!/usr/bin/env python3
"""The shared vocabulary. These names are the faithfulness contract; the tests pin them."""
from __future__ import annotations

import pytest

from kernel.schema import (Book, ExecutionState, FillState, Mode, NormMarket, OpportunityStatus,
                           Quote, SettleRef)


def test_the_opportunity_statuses_exist_and_blocks_know_they_are_blocks():
    names = {s.value for s in OpportunityStatus}
    assert names >= {"DISCOVERED", "BLOCKED_MATCH", "BLOCKED_RULES", "BLOCKED_STALE", "BLOCKED_DEPTH",
                     "BLOCKED_FEES", "BLOCKED_BALANCE", "PROFITABLE_UNEXECUTED", "EXECUTION_PENDING",
                     "PARTIALLY_FILLED", "HEDGED", "FAILED_HEDGE", "SETTLED", "RECONCILED", "NO_EDGE"}
    assert OpportunityStatus.BLOCKED_FEES.is_block and not OpportunityStatus.NO_EDGE.is_block


def test_execution_failures_are_terminal_and_the_happy_path_is_not():
    assert ExecutionState.ORDER_TIMEOUT.is_failure and ExecutionState.ORDER_TIMEOUT.is_terminal
    assert ExecutionState.UNKNOWN_PROVIDER_STATE.is_failure
    assert not ExecutionState.LEG_A_FILLED.is_failure and not ExecutionState.LEG_A_FILLED.is_terminal
    assert ExecutionState.RECONCILED.is_terminal and not ExecutionState.RECONCILED.is_failure


def test_fill_state_is_three_way():
    assert {f.value for f in FillState} == {"FILLED", "PARTIAL", "UNFILLED", "UNCONFIRMED", "REJECTED"}


def test_modes_are_ordered_and_never_imply_a_higher_one():
    assert Mode.SHADOW_LIVE.allows(Mode.OFFLINE_REPLAY)
    assert not Mode.SHADOW_LIVE.allows(Mode.PAPER_EXECUTION)
    assert Mode.OFFLINE_REPLAY.allows(Mode.PAPER_EXECUTION) and not Mode.OFFLINE_REPLAY.allows(Mode.DEMO_EXECUTION)
    assert Mode.OFFLINE_REPLAY.executes and not Mode.SHADOW_LIVE.executes and Mode.PAPER_EXECUTION.executes
    assert not Mode.PAPER_EXECUTION.sends_real_orders and Mode.DEMO_EXECUTION.sends_real_orders
    assert not Mode.DEMO_EXECUTION.risks_capital and Mode.LIMITED_LIVE.risks_capital
    ranks = [m.rank for m in (Mode.OFFLINE_REPLAY, Mode.SHADOW_LIVE, Mode.PAPER_EXECUTION,
                              Mode.DEMO_EXECUTION, Mode.LIMITED_LIVE, Mode.PRODUCTION)]
    assert ranks == sorted(ranks) and len(set(ranks)) == 6


def test_a_book_labels_its_source_and_rejects_an_unknown_one():
    b = Book(asks=(Quote(0.5, 10.0),), fetched_utc=1.0)
    assert b.source == "unknown" and b.server_utc is None and b.received_mono is None
    ws = Book(asks=(Quote(0.5, 10.0),), fetched_utc=1.0, source="ws", server_utc=0.9, received_mono=12.5)
    assert ws.source == "ws" and ws.received_mono == 12.5
    with pytest.raises(ValueError, match="Book.source"):
        Book(source="cache")


def test_normmarket_carries_a_proof_not_a_bool():
    m = NormMarket(venue="kalshi", liquidity_source="kalshi_clob", venue_market_id="X", outcomes=(),
                   fee_model_id="kalshi_quadratic", settle_ref=SettleRef(), raw_title="t", fetched_utc=0.0)
    assert m.proof is None and not hasattr(m, "exhaustive")
