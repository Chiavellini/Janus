"""Project authenticated account trades onto exact owned orders (L54).

A maker trade's top-level order, size, token and side describe the other party. Never
reuse those fields as the account's fill. Unknown role is preserved as unverified.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Iterable


def _number(value: object, label: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f'invalid maker {label}') from exc
    if not number.is_finite():
        raise ValueError(f'nonfinite maker {label}')
    return number


def project_account_trade(raw: dict, *, owned_order_ids: Iterable[str], funder: str = '') -> list[dict]:
    """Return per-owned-order projections, retaining source trade bytes as parsed fields.

    Known journal IDs prove order ownership; an exact funder-address match permits an
    orphan maker to be seen before adoption. The authenticated account role must agree
    with the maker-list location before that projected role is verified.
    """
    owned = set(owned_order_ids)
    role = str(raw.get('trader_side') or '').upper()
    tid = str(raw.get('id') or '')
    if not tid:
        raise ValueError('missing immutable trade source identity')
    taker_id = str(raw.get('taker_order_id') or raw.get('order_id') or '')
    makers = raw.get('maker_orders') or []
    if not isinstance(makers, list):
        raise ValueError('maker_orders is not a complete list')
    selected = []
    seen = set()
    for maker in makers:
        if not isinstance(maker, dict):
            raise ValueError('malformed maker order')
        oid = str(maker.get('order_id') or '')
        address_owned = bool(funder and str(maker.get('maker_address') or '').lower() == funder.lower())
        if oid not in owned and not address_owned:
            continue
        if not tid or not oid or oid in seen:
            raise ValueError('missing or duplicate owned maker source identity')
        seen.add(oid)
        quantity, price = _number(maker.get('matched_amount'), 'quantity'), _number(maker.get('price'), 'price')
        token, side = str(maker.get('asset_id') or ''), str(maker.get('side') or '').upper()
        if quantity <= 0 or not 0 < price < 1 or not token or side not in {'BUY', 'SELL'}:
            raise ValueError('incomplete owned maker fill fields')
        verified = role == 'MAKER' and taker_id != oid
        selected.append({
            'id': f'{tid}:maker:{oid}', 'order_id': oid, 'size': str(quantity), 'price': str(price),
            'asset_id': token, 'side': side, 'fee_rate_bps': maker.get('fee_rate_bps'),
            'transaction_hash': raw.get('transaction_hash'), 'match_time': raw.get('match_time'),
            'status': raw.get('status'), 'market': raw.get('market'),
            'trader_side': 'MAKER' if verified else 'UNKNOWN',
            '_janus_role_verified': verified, '_janus_projection_role': 'MAKER',
            '_janus_role_conflict': role == 'TAKER' or taker_id == oid,
            '_janus_source_trade_id': tid, '_janus_source_trade': raw, '_janus_source_maker': maker,
        })
    # A known order's placement in taker_order_id is itself a taker-role observation,
    # even when the account role field disagrees. Never suppress it as a maker trade.
    if taker_id in owned or (not selected and role != 'MAKER'):
        projected = dict(raw)
        projected.update(_janus_role_verified=role == 'TAKER', _janus_projection_role='TAKER',
                         _janus_role_conflict=role == 'MAKER', _janus_source_trade_id=tid,
                         _janus_source_trade=raw)
        projected['trader_side'] = 'TAKER' if role == 'TAKER' else 'UNKNOWN'
        selected.append(projected)
    if not selected and role == 'MAKER':
        raise ValueError('authenticated maker trade has no proven owned maker order')
    return selected
