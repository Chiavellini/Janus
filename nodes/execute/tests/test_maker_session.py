"""Pure continuous maker-rest authority and cumulative fill-delta tests."""

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from nodes.execute.maker import (
    HedgeLevel,
    MakerFillSession,
    MakerRestAuthorization,
    MakerRestInputs,
    RestBlock,
    book_fingerprint,
)


def authorization() -> MakerRestAuthorization:
    return MakerRestAuthorization(
        authorization_id="auth-1",
        maker_client_order_id="maker-1",
        authorized_contracts="10",
        deadline_mono=105.0,
        hard_hedge_limit="0.56",
        max_hedge_book_age_s=1.0,
    )


def inputs(**changes) -> MakerRestInputs:
    values = dict(
        now_mono=100.0,
        hedge_book_received_mono=99.5,
        hedge_asks=(HedgeLevel("0.54", "6"), HedgeLevel("0.55", "4")),
        maker_connected=True,
        hedge_connected=True,
        clock_healthy=True,
        kill_active=False,
        breaker_active=False,
        hedge_budget_usd=Decimal("5.50"),
        session_budget_usd=Decimal("10.00"),
        stake_cap_usd=Decimal("10.00"),
        contract_cap=Decimal("10"),
        day_cost_used_usd=Decimal("20"),
        day_cost_cap_usd=Decimal("30"),
        fixed_session_cost_usd=Decimal("4.30"),
        committed_hedge_cost_usd=Decimal("0"),
        hedge_fee_reserve_usd=Decimal("0.10"),
    )
    values.update(changes)
    return MakerRestInputs(**values)


def test_authorization_deadline_is_absolute_frozen_and_never_refreshed_by_observations():
    auth = authorization()
    session = MakerFillSession(auth).observe_fill("2").observe_hedge("2")
    assert session.authorization is auth
    assert session.authorization.deadline_mono == 105.0
    with pytest.raises(FrozenInstanceError):
        auth.deadline_mono = 110.0
    assert session.validate_rest(inputs(now_mono=104.999, hedge_book_received_mono=104.5)).allowed
    assert session.validate_rest(inputs(now_mono=105.0)).block is RestBlock.DEADLINE_REACHED


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"kill_active": True}, RestBlock.KILL_ACTIVE),
        ({"breaker_active": True}, RestBlock.BREAKER_ACTIVE),
        ({"clock_healthy": False}, RestBlock.CLOCK_UNHEALTHY),
        ({"hedge_book_received_mono": 100.1}, RestBlock.CLOCK_UNHEALTHY),
        ({"maker_connected": False}, RestBlock.VENUE_DISCONNECTED),
        ({"hedge_connected": False}, RestBlock.VENUE_DISCONNECTED),
        ({"hedge_book_received_mono": 98.99}, RestBlock.HEDGE_BOOK_STALE),
        ({"contract_cap": Decimal("9.99")}, RestBlock.CONTRACT_CAP_EXCEEDED),
    ],
)
def test_operational_and_cap_inputs_fail_closed(change, reason):
    assert MakerFillSession(authorization()).validate_rest(inputs(**change)).block is reason


def test_rest_requires_full_depth_inside_the_hard_limit():
    session = MakerFillSession(authorization())
    no_depth = inputs(hedge_asks=(HedgeLevel("0.54", "9.99"),))
    assert session.validate_rest(no_depth).block is RestBlock.HEDGE_DEPTH_INSUFFICIENT

    above_limit = inputs(hedge_asks=(HedgeLevel("0.54", "9"), HedgeLevel("0.57", "1")))
    assert session.validate_rest(above_limit).block is RestBlock.HARD_HEDGE_LIMIT_EXCEEDED


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"hedge_budget_usd": Decimal("5.43")}, RestBlock.HEDGE_BUDGET_EXCEEDED),
        ({"session_budget_usd": Decimal("9.83")}, RestBlock.SESSION_BUDGET_EXCEEDED),
        ({"stake_cap_usd": Decimal("9.83")}, RestBlock.STAKE_CAP_EXCEEDED),
        ({"day_cost_cap_usd": Decimal("29.83")}, RestBlock.DAY_COST_CAP_EXCEEDED),
    ],
)
def test_full_depth_still_requires_every_budget_and_cap(change, reason):
    decision = MakerFillSession(authorization()).validate_rest(inputs(**change))
    assert decision.block is reason
    assert decision.allowed is False


def test_rest_proof_walks_full_remainder_and_reports_cost_and_worst_level():
    session = MakerFillSession(authorization()).observe_fill("2")
    decision = session.validate_rest(inputs(
        fixed_session_cost_usd=Decimal("4.30"),
        committed_hedge_cost_usd=Decimal("1.08"),
        hedge_budget_usd=Decimal("4.40"),
    ))
    assert decision.allowed and decision.block is None
    assert decision.remaining_contracts == Decimal("8")
    assert decision.projected_hedge_cost_usd == Decimal("4.34")
    assert decision.projected_session_cost_usd == Decimal("9.82")
    assert decision.worst_hedge_price == Decimal("0.55")


def test_fill_and_hedge_observations_are_monotonic_high_water_marks():
    session = MakerFillSession(authorization()).observe_fill("6.125").observe_fill("4")
    session = session.observe_hedge("3.01").observe_hedge("2")
    assert session.confirmed_fill_high_water == Decimal("6.125")
    assert session.hedged_high_water == Decimal("3.01")
    assert session.plan_hedge_delta().delta_contracts == Decimal("3.11")


def test_fill_delta_is_cent_floored_idempotent_and_never_exceeds_confirmed_or_authorized():
    session = MakerFillSession(authorization()).observe_fill("9.999999")
    first = session.plan_hedge_delta()
    assert first.target_contracts == first.delta_contracts == Decimal("9.99")
    assert first.unhedgeable_dust == Decimal("0.009999")
    session = session.observe_hedge(first.delta_contracts)
    assert session.plan_hedge_delta().delta_contracts == 0

    overfill = session.observe_fill("10.166667").plan_hedge_delta()
    assert overfill.target_contracts == Decimal("10.00")
    assert overfill.delta_contracts == Decimal("0.01")
    assert overfill.overfill_contracts == Decimal("0.166667")
    assert overfill.hedged_high_water + overfill.delta_contracts <= overfill.authorized_contracts
    assert overfill.hedged_high_water + overfill.delta_contracts <= overfill.confirmed_fill_high_water


def test_overhedge_is_reported_but_never_generates_a_negative_or_reversal_order():
    plan = MakerFillSession(authorization(), confirmed_fill_high_water="4", hedged_high_water="5").plan_hedge_delta()
    assert plan.delta_contracts == 0
    assert plan.overhedged_contracts == Decimal("1.00")


def test_content_fingerprint_is_canonical_and_changes_only_with_executable_identity_or_depth():
    one = book_fingerprint(
        [("0.55", "2"), ("0.54", "1"), ("0.55", "2.0"), ("0.60", "0")],
        venue="kalshi", market_id="KX-1",
    )
    same = book_fingerprint(
        [(Decimal("0.540"), Decimal("1.00")), (Decimal("0.550"), Decimal("4"))],
        venue="kalshi", market_id="KX-1",
    )
    changed = book_fingerprint(
        [("0.54", "1"), ("0.55", "3.99")], venue="kalshi", market_id="KX-1")
    other_market = book_fingerprint(
        [("0.54", "1"), ("0.55", "4")], venue="kalshi", market_id="KX-2")
    assert one == same
    assert one != changed
    assert one != other_market
