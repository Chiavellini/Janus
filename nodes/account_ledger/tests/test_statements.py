from decimal import Decimal
import hashlib

import pytest

from nodes.account_ledger.statements import (decimal_amount, kalshi_settlement, polymarket_activity,
                                           present_cents, read_raw, totals)


def pm(**overrides):
    return dict(proxyWallet='wallet', transactionHash='transaction', type='TRADE', asset='token',
                conditionId='condition', outcomeIndex=0, side='BUY', timestamp=123,
                title='Example', usdcSize='3.71626', size='10.166667', price='0.35', **overrides)


def test_activity_uses_authoritative_cash_instead_of_price_times_size():
    line = polymarket_activity(pm(), source_sha256='sha')
    assert line.amount_usd == Decimal('-3.71626')
    assert line.kind == 'TRADE_CASH'  # requires terminal proof before calling it realized
    assert present_cents(line.amount_usd) == '-3.72'


def test_funding_and_redemption_are_distinct_and_redemption_identity_includes_token():
    rows = []
    for asset in ('first', 'second'):
        row = pm()
        row.update(type='REDEEM', side='', asset=asset, usdcSize='10')
        rows.append(polymarket_activity(row, source_sha256='sha'))
    deposit = pm()
    deposit.update(type='DEPOSIT', asset='', side='', usdcSize='205.35')
    rows.append(polymarket_activity(deposit, source_sha256='sha'))
    assert totals(rows) == {'REDEMPTION_CASH': Decimal(20), 'FUNDING': Decimal('205.35')}
    with pytest.raises(ValueError, match='duplicate'):
        totals(rows + rows[:1])


def test_maximus_cover_keeps_subcents_and_rounds_only_after_exact_sum():
    settlement = {'ticker': 'EXAMPLE-JON', 'exchange_index': 3, 'settled_time': '2026-09-09T06:22:25Z',
                  'revenue': 1017, 'yes_total_cost_dollars': '0', 'no_total_cost_dollars': '6.610500',
                  'fee_cost': '0.162000'}
    kalshi = kalshi_settlement(settlement, source_sha256='ks-sha')
    poly = polymarket_activity(pm(), source_sha256='pm-sha')
    assert kalshi.amount_usd == Decimal('3.397500')
    assert kalshi.amount_usd + poly.amount_usd == Decimal('-0.318760')
    assert present_cents(kalshi.amount_usd + poly.amount_usd) == '-0.32'
    assert present_cents(Decimal('0.005') + Decimal('0.005')) == '0.01'


@pytest.mark.parametrize('value', [None, True, 0.1, 'NaN', 'Infinity'])
def test_rejects_missing_nonfinite_and_binary_floats(value):
    with pytest.raises(ValueError):
        decimal_amount(value)


def test_raw_json_preserves_decimal_tokens_and_verifies_source_hash():
    raw = b'{"usdcSize":3.71626}'
    parsed = read_raw(raw, expected_sha256=hashlib.sha256(raw).hexdigest())
    assert parsed['usdcSize'] == Decimal('3.71626')
    with pytest.raises(ValueError, match='SHA256'):
        read_raw(raw + b' ', expected_sha256=hashlib.sha256(raw).hexdigest())


def test_unknown_types_and_missing_cash_fail_closed():
    row = pm()
    row['type'] = 'REWARD'
    with pytest.raises(ValueError, match='requires review'):
        polymarket_activity(row, source_sha256='sha')
    row = pm()
    del row['usdcSize']
    with pytest.raises(ValueError):
        polymarket_activity(row, source_sha256='sha')


def test_sell_withdrawal_and_zero_losing_redemption_signs():
    row = pm()
    row.update(side='SELL', usdcSize='1.234567')
    assert polymarket_activity(row, source_sha256='sha').amount_usd == Decimal('1.234567')
    row.update(type='WITHDRAWAL', asset='', usdcSize='10')
    assert polymarket_activity(row, source_sha256='sha').amount_usd == -10
    row.update(type='REDEEM', asset='token', side='', usdcSize='0')
    assert polymarket_activity(row, source_sha256='sha').amount_usd == 0


def test_old_redemption_without_asset_retains_condition_identity_without_invention():
    row = pm()
    row.update(type='REDEEM', asset='', side='', usdcSize='5.123456')
    line = polymarket_activity(row, source_sha256='sha')
    assert line.instrument == 'unattributed_condition:condition'
    assert ':condition::0:' in line.source_id and line.amount_usd == Decimal('5.123456')
