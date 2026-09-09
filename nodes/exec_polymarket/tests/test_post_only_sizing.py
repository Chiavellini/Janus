"""L54: unsigned SDK amounts and the conditional maker-only share bound."""

from decimal import Decimal, localcontext

import pytest

from nodes.exec_polymarket.post_only_sizing import (
    MAX_MAKER_AMOUNT,
    MAX_UINT256,
    maker_price,
    validate_post_only_amounts,
)


def validate(**changes):
    values = dict(maker_amount=3_600_000, taker_amount=10_000_000,
                  requested_contracts="10", limit_price="0.36")
    values.update(changes)
    return validate_post_only_amounts(**values)


@pytest.mark.parametrize("wire_type", [int, str, Decimal])
def test_exact_wire_amounts(wire_type):
    assert validate(maker_amount=wire_type(3_600_000),
                    taker_amount=wire_type(10_000_000)) == (3_600_000, 10_000_000)


@pytest.mark.parametrize("field", ["maker_amount", "taker_amount", "requested_contracts", "limit_price"])
@pytest.mark.parametrize("bad", [None, True, False, "", "NaN", "sNaN", "Infinity", "-Infinity", 0, -1])
def test_invalid_values_fail_closed(field, bad):
    with pytest.raises(ValueError):
        validate(**{field: bad})


@pytest.mark.parametrize("changes", [
    {"maker_amount": "3600000.1"},
    {"taker_amount": "10000000.1"},
    {"maker_amount": MAX_MAKER_AMOUNT + 1},
    {"taker_amount": MAX_UINT256 + 1},
    {"taker_amount": 10_000_001},
    {"taker_amount": 10_010_000},
    {"requested_contracts": "9.999999999999999999999999999999999999999999"},
    {"limit_price": "0.359999999999999999999999999999999999999999"},
    {"maker_amount": 3_600_001},
])
def test_wire_amount_precision_range_and_authorization(changes):
    with pytest.raises(ValueError):
        validate(**changes)


def test_comparison_is_independent_of_decimal_context_precision():
    with localcontext() as ctx:
        ctx.prec = 2
        assert validate() == (3_600_000, 10_000_000)
        with pytest.raises(ValueError):
            validate(requested_contracts="9.999999999999999999999999999999999999999999")
        with pytest.raises(ValueError):
            validate(limit_price="0.359999999999999999999999999999999999999999")
        assert maker_price(best_ask="0.5325", ceiling="0.52875", tick="0.0025") == .5275


@pytest.mark.parametrize("ask,cap,tick,expected", [
    ("0.54", "0.54", "0.01", .53),
    ("0.54", "0.51", "0.01", .51),
    ("0.535", "0.53", "0.01", .52),
    ("0.54", "0.515", "0.01", .51),
    ("0.535", "0.53", "0.005", .53),
    ("0.5325", "0.52875", "0.0025", .5275),
    ("0.54", "0.6", "0.1", .4),
    ("0.5000000000000000000000000001", "0.9", "0.01", .49),
    ("1", "1", "0.01", .99),
    ("0.01", "0.5", "0.01", None),
    ("0.005", "0.5", "0.01", None),
    ("0.5", "0.005", "0.01", None),
    ("2", "2", "0.1", None),
    ("0.9", "0.50000000000000000000001", "0.00000000000000000000001", None),
])
def test_maker_price_floor_and_boundaries(ask, cap, tick, expected):
    assert maker_price(best_ask=ask, ceiling=cap, tick=tick) == expected


@pytest.mark.parametrize("field", ["best_ask", "ceiling", "tick"])
@pytest.mark.parametrize("bad", [None, True, "NaN", "Infinity", "-Infinity", 0, -1])
def test_maker_price_invalid_input(field, bad):
    args = dict(best_ask="0.54", ceiling="0.54", tick="0.01")
    args[field] = bad
    assert maker_price(**args) is None


SDK_TICKS = {
    "0.1": ("0.3", "0.36"),
    "0.01": ("0.36", "0.3651"),
    "0.005": ("0.365", "0.3656"),
    "0.0025": ("0.3625", "0.36256"),
    "0.001": ("0.361", "0.3616"),
    "0.0001": ("0.3601", "0.36016"),
}


@pytest.fixture
def sdk():
    # Neither OrderBuilder(None) nor its amount calculator creates a signer/client.
    return pytest.importorskip("py_clob_client_v2.order_builder.builder")


def test_frozen_sdk_tick_set(sdk):
    assert set(sdk.ROUNDING_CONFIG) == set(SDK_TICKS)


@pytest.mark.parametrize("tick", SDK_TICKS)
@pytest.mark.parametrize("requested,encoded", [
    ("9.98", "9.98"), ("9.99", "9.99"), ("9.999999999", "9.99"),
    ("10", "10"), ("10.000000000000002", "10"), ("10.009", "10"), ("10.01", "10.01"),
])
def test_sdk_unsigned_amounts_near_ten_are_bounded(sdk, tick, requested, encoded):
    price = SDK_TICKS[tick][0]
    _, maker, taker = sdk.OrderBuilder(None).get_order_amounts(
        "BUY", float(requested), float(price), sdk.ROUNDING_CONFIG[tick])
    assert taker == int(Decimal(encoded) * 1_000_000)
    assert maker == int(Decimal(encoded) * Decimal(price) * 1_000_000)
    assert validate_post_only_amounts(maker_amount=maker, taker_amount=taker,
                                     requested_contracts=requested, limit_price=price) == (maker, taker)


@pytest.mark.parametrize("tick", SDK_TICKS)
def test_sdk_float_conversion_cannot_expand_precise_authorization(sdk, tick):
    # This decimal is below 10; its float projection is 10. The original wins.
    requested = "9.9999999999999999"
    price = SDK_TICKS[tick][0]
    _, maker, taker = sdk.OrderBuilder(None).get_order_amounts(
        "BUY", float(requested), float(price), sdk.ROUNDING_CONFIG[tick])
    assert taker == 10_000_000
    with pytest.raises(ValueError, match="exceeds authorized requested_contracts"):
        validate_post_only_amounts(maker_amount=maker, taker_amount=taker,
                                  requested_contracts=requested, limit_price=price)


@pytest.mark.parametrize("tick", SDK_TICKS)
def test_sdk_price_rounding_cannot_expand_limit(sdk, tick):
    price = SDK_TICKS[tick][1]
    _, maker, taker = sdk.OrderBuilder(None).get_order_amounts(
        "BUY", 10, float(price), sdk.ROUNDING_CONFIG[tick])
    with pytest.raises(ValueError, match="ratio exceeds authorized limit_price"):
        validate_post_only_amounts(maker_amount=maker, taker_amount=taker,
                                  requested_contracts=10, limit_price=price)


@pytest.mark.parametrize("parts", [
    [3_600_000], [0, 3_600_000], [1, 3_599_999], [1_234_567, 2_345_433],
    [1_200_000, 1_200_000, 1_200_000], [1_000_000, 1_000_000],
    [360_000] * 10,
])
def test_exact_and_partial_maker_fill_partitions(parts):
    maker, taker = validate()
    remaining = maker
    received = 0
    for fill in parts:
        assert 0 <= fill <= remaining
        remaining -= fill
        received += fill * taker // maker
        assert received <= taker
    assert received <= (maker - remaining) * taker // maker


def test_small_domain_cumulative_maker_bound_including_rounding():
    for maker in range(1, 31):
        for taker in range(31):
            for first in range(maker + 1):
                for second in range(maker - first + 1):
                    third = maker - first - second
                    assert sum(fill * taker // maker for fill in (first, second, third)) <= taker


def test_same_signature_as_taker_has_a_concrete_over_cap_match():
    maker, taker = validate()
    sell_shares, sell_collateral = 10_285_714, 3_600_000
    assert maker * sell_shares >= taker * sell_collateral  # valid crossing
    spent = sell_shares * sell_collateral // sell_shares
    assert spent <= maker
    assert sell_shares >= spent * taker // maker  # taker's minimum passes
    assert sell_shares > taker  # maker-only premise is indispensable


def test_post_only_is_separate_from_order_signature_fixture():
    model = pytest.importorskip("py_clob_client_v2.order_utils.model.order_data_v2")
    exchange = pytest.importorskip("py_clob_client_v2.order_utils.exchange_order_builder_v2")
    order = model.SignedOrderV2(
        salt="1", maker="0x" + "11" * 20, signer="0x" + "11" * 20,
        tokenId="123", makerAmount="3600000", takerAmount="10000000",
        side=model.Side.BUY, signatureType=model.SignatureTypeV2.EOA,
        timestamp="1800000000000", metadata="0x" + "00" * 32,
        builder="0x" + "00" * 32, signature="fixture-not-a-real-signature",
    )
    ordinary = model.order_to_json_v2(order, "fixture", "GTC", post_only=False)
    resting = model.order_to_json_v2(order, "fixture", "GTC", post_only=True)
    assert ordinary["order"] == resting["order"]
    assert ordinary["postOnly"] is False and resting["postOnly"] is True
    assert "postOnly" not in exchange.ORDER_TYPE_STRING
    assert "expiration" not in exchange.ORDER_TYPE_STRING
