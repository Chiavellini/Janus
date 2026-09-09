"""Pure parsing of authoritative statement amounts, without rounding or position inference.

Polymarket activity's usdcSize is the cash amount; size times displayed price is not an
acceptable substitute. A trade cash line is not automatically realized P&L. Kalshi settlement
P&L covers that settlement record only, never unrelated disposals or deposits.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from typing import Iterable, Mapping


def decimal_amount(value: object) -> Decimal:
    if isinstance(value, (bool, float)) or value is None:
        raise ValueError('financial numbers require decimal strings or Decimal, never floats')
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError('invalid decimal amount') from error
    if not number.is_finite():
        raise ValueError('financial number must be finite')
    return number


def present_cents(amount: Decimal) -> str:
    """Presentation only: sum exact source amounts first, then round half away from zero."""
    return format(decimal_amount(amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), '.2f')


def read_raw(raw: bytes, *, expected_sha256: str):
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('source SHA256 mismatch')
    return json.loads(raw, parse_float=Decimal)


def required(row: Mapping, name: str) -> str:
    value = row.get(name)
    if value is None or value == '':
        raise ValueError(f'missing source field: {name}')
    return str(value)


@dataclass(frozen=True)
class StatementLine:
    source_id: str
    source_sha256: str
    venue: str
    kind: str
    amount_usd: Decimal
    instrument: str
    description: str
    timestamp: str


def polymarket_activity(row: Mapping, *, source_sha256: str) -> StatementLine:
    kind = required(row, 'type')
    allowed = {'TRADE', 'REDEEM', 'DEPOSIT', 'WITHDRAWAL'}
    if kind not in allowed:
        raise ValueError(f'unsupported activity type requires review: {kind}')
    wallet = required(row, 'proxyWallet').lower()
    transaction = required(row, 'transactionHash').lower()
    timestamp = required(row, 'timestamp')
    asset = required(row, 'asset') if kind == 'TRADE' else str(row.get('asset') or '') if kind == 'REDEEM' else ''
    amount = decimal_amount(row.get('usdcSize'))
    if amount < 0:
        raise ValueError('source usdcSize must be nonnegative')
    side = row.get('side', '')
    if kind == 'TRADE':
        if side not in {'BUY', 'SELL'}:
            raise ValueError('unknown trade side')
        amount *= -1 if side == 'BUY' else 1
        line_kind = 'TRADE_CASH'
    elif kind == 'REDEEM':
        line_kind = 'REDEMPTION_CASH'
    else:
        amount *= -1 if kind == 'WITHDRAWAL' else 1
        line_kind = 'FUNDING'
    # A transaction can redeem several conditions/outcomes. Never dedupe on tx hash alone.
    condition = required(row, 'conditionId') if kind in {'TRADE', 'REDEEM'} else ''
    outcome = required(row, 'outcomeIndex') if kind in {'TRADE', 'REDEEM'} else ''
    source_id = ':'.join(('polymarket', wallet, transaction, kind, condition, asset, outcome, str(side)))
    return StatementLine(source_id, source_sha256, 'polymarket', line_kind, amount,
                         asset or ('unattributed_condition:' + condition if condition else ''),
                         str(row.get('title') or kind), timestamp)


def kalshi_settlement(row: Mapping, *, source_sha256: str) -> StatementLine:
    ticker = required(row, 'ticker')
    settled = required(row, 'settled_time')
    exchange = required(row, 'exchange_index')
    # revenue is integer cents; costs and fees are already dollar decimals, with subcents.
    revenue = decimal_amount(row.get('revenue'))
    if revenue != revenue.to_integral_value() or revenue < 0:
        raise ValueError('settlement revenue must be nonnegative integer cents')
    yes = decimal_amount(row.get('yes_total_cost_dollars'))
    no = decimal_amount(row.get('no_total_cost_dollars'))
    fee = decimal_amount(row.get('fee_cost'))
    if min(yes, no, fee) < 0:
        raise ValueError('settlement costs must be nonnegative')
    source_id = ':'.join(('kalshi', exchange, ticker, settled))
    return StatementLine(source_id, source_sha256, 'kalshi', 'SETTLEMENT_PNL',
                         revenue / Decimal(100) - yes - no - fee, ticker, ticker, settled)


def totals(lines: Iterable[StatementLine]) -> dict[str, Decimal]:
    """Keep cash flows, terminal settlement P&L and funding in distinct totals."""
    result: dict[str, Decimal] = {}
    ids = set()
    for line in lines:
        if line.source_id in ids:
            raise ValueError(f'duplicate source identity: {line.source_id}')
        ids.add(line.source_id)
        result[line.kind] = result.get(line.kind, Decimal(0)) + line.amount_usd
    return result
