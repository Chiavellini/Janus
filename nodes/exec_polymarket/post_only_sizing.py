"""Exact sizing for the maker-only BUY premise, not proof of that premise.

At the reviewed V2 exchange, a maker fill of f collateral units receives
floor(f * takerAmount / makerAmount) shares. Depleting makerAmount therefore
bounds cumulative maker receipts by takerAmount. A taker BUY has no such bound.
The matching service must separately enforce post-only; these helpers neither
sign an order nor establish the service's matching role.
"""

from decimal import Decimal, InvalidOperation, localcontext


TOKEN_UNITS = 1_000_000
SHARE_CENT_UNITS = 10_000
MAX_MAKER_AMOUNT = (1 << 248) - 1
MAX_UINT256 = (1 << 256) - 1


def _positive_decimal(value, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite positive decimal")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite positive decimal") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{name} must be a finite positive decimal")
    return result


def _wire_integer(value, name: str, maximum: int) -> int:
    amount = _positive_decimal(value, name)
    if amount > maximum or amount != amount.to_integral_value():
        raise ValueError(f"{name} must be an in-range positive integer")
    return int(amount)


def validate_post_only_amounts(
    *, maker_amount, taker_amount, requested_contracts, limit_price
) -> tuple[int, int]:
    """Validate actual unsigned/signed wire amounts against the authorized request.

    Decimal inputs are compared by exact integer cross-products, not rounded
    division or binary floats. Parsing a float uses its decimal spelling, so
    callers retaining a more precise authorization should pass that Decimal.
    The two-decimal share bound applies to the encoded amount, not the request:
    an SDK may safely floor 10.009 requested shares to 10.00, never round up.
    """
    maker = _wire_integer(maker_amount, "maker_amount", MAX_MAKER_AMOUNT)
    taker = _wire_integer(taker_amount, "taker_amount", MAX_UINT256)
    requested = _positive_decimal(requested_contracts, "requested_contracts")
    limit = _positive_decimal(limit_price, "limit_price")
    if taker % SHARE_CENT_UNITS:
        raise ValueError("taker_amount must encode at most two share decimals")
    requested_num, requested_den = requested.as_integer_ratio()
    if taker * requested_den > requested_num * TOKEN_UNITS:
        raise ValueError("taker_amount exceeds authorized requested_contracts")
    limit_num, limit_den = limit.as_integer_ratio()
    if maker * limit_den > taker * limit_num:
        raise ValueError("encoded BUY ratio exceeds authorized limit_price")
    return maker, taker


def maker_price(*, best_ask, ceiling, tick) -> float | None:
    """Floor min(ceiling, best_ask - tick) to a positive binary-market tick.

    This is a snapshot-derived resting price, not a guarantee against a later
    matching race. Reject a float projection that would lose exact tick alignment.
    """
    try:
        ask = _positive_decimal(best_ask, "best_ask")
        cap = _positive_decimal(ceiling, "ceiling")
        step = _positive_decimal(tick, "tick")
        ask_num, ask_den = ask.as_integer_ratio()
        cap_num, cap_den = cap.as_integer_ratio()
        tick_num, tick_den = step.as_integer_ratio()
        # Integer floor division avoids Decimal context rounding at a tick edge.
        ask_ticks = (ask_num * tick_den - tick_num * ask_den) // (ask_den * tick_num)
        cap_ticks = (cap_num * tick_den) // (cap_den * tick_num)
        count = min(ask_ticks, cap_ticks)
        if count <= 0:
            return None
        with localcontext() as ctx:
            ctx.prec = max(28, len(str(count)) + len(step.as_tuple().digits))
            exact = Decimal(count) * step
        if not 0 < exact < 1 or exact >= ask or exact > cap:
            return None
        result = float(exact)
        if Decimal(str(result)) != exact:
            return None
        return result
    except (InvalidOperation, OverflowError, TypeError, ValueError):
        return None
