"""The current CLOB BUY wire bounds collateral, not received shares (L53).

`OrderArgsV2.size` becomes takerAmount. For a taker BUY the exchange enforces that
amount as a minimum at full maker-budget consumption; price improvement is surplus
shares. No caller-supplied size, current book, or cent-exact encoding proves a cap.
"""

from decimal import Decimal, InvalidOperation

BUY_CAP_UNPROVEN = (
    "Polymarket BUY received-share cap is unproven: makerAmount caps collateral; "
    "takerAmount is a minimum, not a maximum. Price improvement can exceed requested "
    "contracts. No BUY sent; a reviewed quantity-capped route is required."
)


def taker_trade_vwap(trade: dict) -> float | None:
    """Derive the taker's price from each maker leg, including complementary minting.

    The top-level CLOB trade price need not be the VWAP (L53: .35 versus
    3.60 / 10.166667). Missing or inconsistent leg evidence returns no average;
    protection can conservatively use the journaled BUY ceiling.
    """
    asset = trade.get("asset_id", trade.get("assetId"))
    side = str(trade.get("side", "")).upper()
    makers = trade.get("maker_orders", trade.get("makerOrders"))
    if not asset or side not in ("BUY", "SELL") or not makers:
        return None
    try:
        total = Decimal(str(trade["size"]))
        qty = cost = Decimal(0)
        for maker in makers:
            q = Decimal(str(maker.get("matched_amount", maker.get("matchedAmount"))))
            p = Decimal(str(maker["price"]))
            token = maker.get("asset_id", maker.get("assetId"))
            maker_side = str(maker.get("side", "")).upper()
            if not token or maker_side not in ("BUY", "SELL"):
                return None
            if not q.is_finite() or not p.is_finite() or q <= 0 or not 0 < p < 1:
                return None
            if token == asset and maker_side != side:
                effective = p
            elif token != asset and maker_side == side:
                effective = Decimal(1) - p
            else:
                return None
            qty += q
            cost += q * effective
        if not total.is_finite() or total <= 0 or abs(qty - total) > Decimal("0.000000001"):
            return None
        return float(cost / total)
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return None
