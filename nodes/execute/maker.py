#!/usr/bin/env python3
"""Pure safety primitives for a continuously supervised maker-first session.

This module deliberately owns no clocks, sockets, databases, or venue clients.  A caller supplies
one immutable authorization and fresh observations.  Session transitions return new values and
never refresh the authorization's absolute monotonic deadline.
"""

from __future__ import annotations

import hashlib
import math

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_DOWN
from enum import Enum
from typing import Iterable


CENT = Decimal("0.01")


def _nonnegative_decimal(value: object, *, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:  # Decimal raises several exception types for hostile inputs.
        raise ValueError(f"{label} must be a finite non-negative number") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"{label} must be a finite non-negative number, got {value!r}")
    return result


def floor_to_cent(value: object) -> Decimal:
    """Floor a non-negative contract quantity to venue share precision."""
    return _nonnegative_decimal(value, label="value").quantize(CENT, rounding=ROUND_DOWN)


def _canonical_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


@dataclass(frozen=True)
class HedgeLevel:
    """One ask level available for an immediate protective buy."""

    price: Decimal
    contracts: Decimal

    def __post_init__(self) -> None:
        price = _nonnegative_decimal(self.price, label="price")
        contracts = _nonnegative_decimal(self.contracts, label="contracts")
        if price > 1:
            raise ValueError(f"price must be <= 1, got {price}")
        object.__setattr__(self, "price", price)
        object.__setattr__(self, "contracts", contracts)


def book_fingerprint(
    asks: Iterable[HedgeLevel | tuple[object, object]],
    *,
    venue: str = "",
    market_id: str = "",
) -> str:
    """Return a stable content fingerprint suitable for suppressing same-book retries.

    Duplicate prices are aggregated and zero-size levels are omitted.  Receive timestamps are
    intentionally absent: a heartbeat carrying unchanged executable depth is still the same book.
    """

    by_price: dict[Decimal, Decimal] = {}
    for item in asks:
        level = item if isinstance(item, HedgeLevel) else HedgeLevel(item[0], item[1])
        if level.contracts:
            by_price[level.price] = by_price.get(level.price, Decimal(0)) + level.contracts
    payload = [str(venue), str(market_id)]
    payload.extend(
        f"{_canonical_decimal(price)}:{_canonical_decimal(by_price[price])}"
        for price in sorted(by_price)
    )
    return hashlib.sha256("\n".join(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MakerRestAuthorization:
    """Risk authority that may only expire, never slide with later observations.

    ``deadline_mono`` is an absolute monotonic-clock instant.  It is not a TTL and no session
    transition has an API that can replace it.
    """

    authorization_id: str
    maker_client_order_id: str
    authorized_contracts: Decimal
    deadline_mono: float
    hard_hedge_limit: Decimal
    max_hedge_book_age_s: float

    def __post_init__(self) -> None:
        if not self.authorization_id or not self.maker_client_order_id:
            raise ValueError("authorization and maker client-order ids are required")
        quantity = _nonnegative_decimal(self.authorized_contracts, label="authorized_contracts")
        limit = _nonnegative_decimal(self.hard_hedge_limit, label="hard_hedge_limit")
        if quantity <= 0:
            raise ValueError("authorized_contracts must be > 0")
        if limit > 1:
            raise ValueError("hard_hedge_limit must be <= 1")
        if not math.isfinite(self.deadline_mono):
            raise ValueError("deadline_mono must be finite")
        if not math.isfinite(self.max_hedge_book_age_s) or self.max_hedge_book_age_s <= 0:
            raise ValueError("max_hedge_book_age_s must be finite and > 0")
        object.__setattr__(self, "authorized_contracts", quantity)
        object.__setattr__(self, "hard_hedge_limit", limit)


@dataclass(frozen=True)
class MakerRestInputs:
    """One complete, point-in-time proof that the maker remainder may keep resting."""

    now_mono: float
    hedge_book_received_mono: float
    hedge_asks: tuple[HedgeLevel, ...]
    maker_connected: bool
    hedge_connected: bool
    clock_healthy: bool
    kill_active: bool
    breaker_active: bool
    hedge_budget_usd: Decimal
    session_budget_usd: Decimal
    stake_cap_usd: Decimal
    contract_cap: Decimal
    day_cost_used_usd: Decimal
    day_cost_cap_usd: Decimal
    fixed_session_cost_usd: Decimal = Decimal(0)
    committed_hedge_cost_usd: Decimal = Decimal(0)
    hedge_fee_reserve_usd: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        if not math.isfinite(self.now_mono) or not math.isfinite(self.hedge_book_received_mono):
            raise ValueError("monotonic clock values must be finite")
        object.__setattr__(self, "hedge_asks", tuple(
            level if isinstance(level, HedgeLevel) else HedgeLevel(*level)
            for level in self.hedge_asks
        ))
        for name in (
            "hedge_budget_usd", "session_budget_usd", "stake_cap_usd", "contract_cap",
            "day_cost_used_usd", "day_cost_cap_usd", "fixed_session_cost_usd",
            "committed_hedge_cost_usd", "hedge_fee_reserve_usd",
        ):
            object.__setattr__(self, name, _nonnegative_decimal(getattr(self, name), label=name))


class RestBlock(str, Enum):
    DEADLINE_REACHED = "deadline_reached"
    KILL_ACTIVE = "kill_active"
    BREAKER_ACTIVE = "breaker_active"
    CLOCK_UNHEALTHY = "clock_unhealthy"
    VENUE_DISCONNECTED = "venue_disconnected"
    HEDGE_BOOK_STALE = "hedge_book_stale"
    CONTRACT_CAP_EXCEEDED = "contract_cap_exceeded"
    HEDGE_DEPTH_INSUFFICIENT = "hedge_depth_insufficient"
    HARD_HEDGE_LIMIT_EXCEEDED = "hard_hedge_limit_exceeded"
    HEDGE_BUDGET_EXCEEDED = "hedge_budget_exceeded"
    SESSION_BUDGET_EXCEEDED = "session_budget_exceeded"
    STAKE_CAP_EXCEEDED = "stake_cap_exceeded"
    DAY_COST_CAP_EXCEEDED = "day_cost_cap_exceeded"
    MAKER_COMPLETE = "maker_complete"


@dataclass(frozen=True)
class MakerRestDecision:
    allowed: bool
    block: RestBlock | None
    remaining_contracts: Decimal
    projected_hedge_cost_usd: Decimal = Decimal(0)
    projected_session_cost_usd: Decimal = Decimal(0)
    worst_hedge_price: Decimal | None = None


@dataclass(frozen=True)
class HedgeDeltaPlan:
    """The immediate idempotent hedge delta implied by cumulative venue truth."""

    confirmed_fill_high_water: Decimal
    authorized_contracts: Decimal
    hedged_high_water: Decimal
    target_contracts: Decimal
    delta_contracts: Decimal
    unhedgeable_dust: Decimal
    overfill_contracts: Decimal
    overhedged_contracts: Decimal


@dataclass(frozen=True)
class MakerFillSession:
    """Immutable cumulative-fill state; observations may advance but never reverse it."""

    authorization: MakerRestAuthorization
    confirmed_fill_high_water: Decimal = Decimal(0)
    hedged_high_water: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        object.__setattr__(self, "confirmed_fill_high_water", _nonnegative_decimal(
            self.confirmed_fill_high_water, label="confirmed_fill_high_water"))
        object.__setattr__(self, "hedged_high_water", _nonnegative_decimal(
            self.hedged_high_water, label="hedged_high_water"))

    def observe_fill(self, cumulative_contracts: object) -> "MakerFillSession":
        """Merge an authoritative cumulative fill without trusting message order."""
        observed = _nonnegative_decimal(cumulative_contracts, label="cumulative_contracts")
        return replace(self, confirmed_fill_high_water=max(self.confirmed_fill_high_water, observed))

    def observe_hedge(self, cumulative_contracts: object) -> "MakerFillSession":
        """Merge an authoritative cumulative hedge fill without trusting message order."""
        observed = _nonnegative_decimal(cumulative_contracts, label="cumulative_contracts")
        return replace(self, hedged_high_water=max(self.hedged_high_water, observed))

    @property
    def remaining_authorized_contracts(self) -> Decimal:
        confirmed_within_authority = min(
            self.confirmed_fill_high_water, self.authorization.authorized_contracts)
        return max(Decimal(0), self.authorization.authorized_contracts - confirmed_within_authority)

    def plan_hedge_delta(self) -> HedgeDeltaPlan:
        """Plan only newly confirmed cents, bounded by the original authorization."""
        authorized = self.authorization.authorized_contracts
        confirmed_target = min(self.confirmed_fill_high_water, authorized)
        target = floor_to_cent(confirmed_target)
        delta = floor_to_cent(max(Decimal(0), target - self.hedged_high_water))
        protected_after_plan = self.hedged_high_water + delta
        return HedgeDeltaPlan(
            confirmed_fill_high_water=self.confirmed_fill_high_water,
            authorized_contracts=authorized,
            hedged_high_water=self.hedged_high_water,
            target_contracts=target,
            delta_contracts=delta,
            unhedgeable_dust=max(Decimal(0), confirmed_target - protected_after_plan),
            overfill_contracts=max(Decimal(0), self.confirmed_fill_high_water - authorized),
            overhedged_contracts=max(Decimal(0), self.hedged_high_water - target),
        )

    def validate_rest(self, inputs: MakerRestInputs) -> MakerRestDecision:
        """Prove the unfilled authorized remainder remains immediately hedgeable."""
        remaining = self.remaining_authorized_contracts

        def blocked(reason: RestBlock) -> MakerRestDecision:
            return MakerRestDecision(False, reason, remaining)

        # Fail closed in an order that surfaces operational stops before market economics.
        if inputs.now_mono >= self.authorization.deadline_mono:
            return blocked(RestBlock.DEADLINE_REACHED)
        if inputs.kill_active:
            return blocked(RestBlock.KILL_ACTIVE)
        if inputs.breaker_active:
            return blocked(RestBlock.BREAKER_ACTIVE)
        book_age = inputs.now_mono - inputs.hedge_book_received_mono
        if not inputs.clock_healthy or book_age < 0:
            return blocked(RestBlock.CLOCK_UNHEALTHY)
        if not inputs.maker_connected or not inputs.hedge_connected:
            return blocked(RestBlock.VENUE_DISCONNECTED)
        if book_age > self.authorization.max_hedge_book_age_s:
            return blocked(RestBlock.HEDGE_BOOK_STALE)
        if self.authorization.authorized_contracts > inputs.contract_cap:
            return blocked(RestBlock.CONTRACT_CAP_EXCEEDED)
        if remaining == 0:
            return blocked(RestBlock.MAKER_COMPLETE)

        levels = sorted(inputs.hedge_asks, key=lambda level: level.price)
        total_depth = sum((level.contracts for level in levels), Decimal(0))
        if total_depth < remaining:
            return blocked(RestBlock.HEDGE_DEPTH_INSUFFICIENT)
        eligible = [level for level in levels if level.price <= self.authorization.hard_hedge_limit]
        eligible_depth = sum((level.contracts for level in eligible), Decimal(0))
        if eligible_depth < remaining:
            return blocked(RestBlock.HARD_HEDGE_LIMIT_EXCEEDED)

        need = remaining
        hedge_cost = Decimal(0)
        worst: Decimal | None = None
        for level in eligible:
            take = min(need, level.contracts)
            if take:
                hedge_cost += take * level.price
                worst = level.price
                need -= take
            if need == 0:
                break

        if hedge_cost > inputs.hedge_budget_usd:
            return MakerRestDecision(False, RestBlock.HEDGE_BUDGET_EXCEEDED, remaining,
                                     projected_hedge_cost_usd=hedge_cost, worst_hedge_price=worst)
        projected = (inputs.fixed_session_cost_usd + inputs.committed_hedge_cost_usd
                     + hedge_cost + inputs.hedge_fee_reserve_usd)
        if projected > inputs.session_budget_usd:
            reason = RestBlock.SESSION_BUDGET_EXCEEDED
        elif projected > inputs.stake_cap_usd:
            reason = RestBlock.STAKE_CAP_EXCEEDED
        elif inputs.day_cost_used_usd + projected > inputs.day_cost_cap_usd:
            reason = RestBlock.DAY_COST_CAP_EXCEEDED
        else:
            reason = None
        return MakerRestDecision(
            reason is None,
            reason,
            remaining,
            projected_hedge_cost_usd=hedge_cost,
            projected_session_cost_usd=projected,
            worst_hedge_price=worst,
        )
