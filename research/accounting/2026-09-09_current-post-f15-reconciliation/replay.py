#!/usr/bin/env python3
"""Offline L52 source-integrity and cash controls; not a blanket account P&L claim."""
from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from nodes.account_ledger.statements import (read_raw, polymarket_activity, kalshi_settlement,
                                           present_cents, totals)

ROOT = Path('/Volumes/Kilos/janus/accounting/L52')
RUNS = {
    'pm_activity': '20260909T093056Z_pm_activity',
    'pm_positions': '20260909T093018Z_pm_positions',
    'pm_closed_positions': '20260909T092847Z_pm_closed_positions',
    'kalshi_settlements': '20260909T092847Z_kalshi_settlements',
    'kalshi_fills': '20260909T092826Z_kalshi_fills',
    'kalshi_historical_fills': '20260909T094049Z_kalshi_historical_fills',
    'pm_clob_trades': '20260909T093018Z_pm_clob_trades',
}


def pages(name):
    directory = ROOT / RUNS[name]
    manifest = json.loads((directory / 'manifest.json').read_bytes())
    assert manifest['pagination_complete'] is True
    for number in range(manifest['pages']):
        stem = f'{number:04d}'
        metadata = json.loads((directory / (stem + '.meta.json')).read_bytes())
        payload = read_raw((directory / (stem + '.json')).read_bytes(), expected_sha256=metadata['raw_sha256'])
        yield payload, metadata['raw_sha256']


def run():
    pm = [polymarket_activity(row, source_sha256=sha) for payload, sha in pages('pm_activity') for row in payload]
    ks = [kalshi_settlement(row, source_sha256=sha) for payload, sha in pages('kalshi_settlements')
          for row in payload['settlements']]
    pm_positions = [row for payload, _ in pages('pm_positions') for row in payload]
    pm_closed = [row for payload, _ in pages('pm_closed_positions') for row in payload]
    pm_sums = totals(pm)
    totals(ks)
    # Cash source control, independent from the activity feed. Never call a balance P&L.
    balance_dir = ROOT / '20260909T093018Z_pm_clob_balance'
    balance_meta = json.loads((balance_dir / '0000.meta.json').read_bytes())
    balance = read_raw((balance_dir / '0000.json').read_bytes(), expected_sha256=balance_meta['raw_sha256'])
    cash = Decimal(balance['balance']) / Decimal(1_000_000)
    cash_control = sum(pm_sums.values(), Decimal(0)) - cash
    by_asset = defaultdict(lambda: Decimal(0))
    for line in pm:
        if line.kind != 'FUNDING':
            by_asset[line.instrument] += line.amount_usd
    exact_cash = {line.description: str(by_asset[line.instrument]) for line in pm
                  if line.instrument and int(line.timestamp) >= 1788825600}
    recent_ks = {line.instrument: str(line.amount_usd) for line in ks
                 if line.timestamp >= '2026-09-08'}
    all_fills = [row for name in ('kalshi_fills', 'kalshi_historical_fills')
                 for payload, _ in pages(name) for row in payload['fills']]
    unique_fills = {}
    for row in all_fills:
        identity = (row['exchange_index'], row['fill_id'])
        if identity in unique_fills:
            assert unique_fills[identity] == row, 'conflicting duplicate venue fill'
        unique_fills[identity] = row
    recent_fills = [row for row in unique_fills.values() if row['created_time'] >= '2026-09-07']
    recent_settlements = [row for payload, _ in pages('kalshi_settlements')
                          for row in payload['settlements'] if row['settled_time'] >= '2026-09-07']
    # This fixed UTC subtotal is distinct from the unidentified screenshot boundary. Every
    # fill in this window is covered by a settlement; exact count, cost and fee all match.
    assert {row['ticker'] for row in recent_fills} == {row['ticker'] for row in recent_settlements}
    for settlement in recent_settlements:
        fills = [row for row in recent_fills if row['ticker'] == settlement['ticker']]
        for side in ('yes', 'no'):
            subset = [row for row in fills if row['outcome_side'] == side]
            assert sum((Decimal(row['count_fp']) for row in subset), Decimal(0)) == Decimal(settlement[side + '_count_fp'])
            assert sum((Decimal(row['count_fp']) * Decimal(row[side + '_price_dollars']) for row in subset), Decimal(0)) == Decimal(settlement[side + '_total_cost_dollars'])
        assert sum((Decimal(row['fee_cost']) for row in fills), Decimal(0)) == Decimal(settlement['fee_cost'])
    recent_pm = sum((line.amount_usd for line in pm if line.kind != 'FUNDING'
                     and int(line.timestamp) >= 1788739200), Decimal(0))
    recent_kalshi = sum((line.amount_usd for line in ks if line.timestamp >= '2026-09-07'), Decimal(0))
    return {
        'status': 'STOP_CURRENT_TOTAL_WITHHELD',
        'source_manifest_directories': RUNS,
        'pm_lines': len(pm),
        'pm_by_kind': dict(Counter(x.kind for x in pm)),
        'pm_all_history_trading_cash_usd': str(pm_sums['TRADE_CASH'] + pm_sums['REDEMPTION_CASH']),
        'pm_all_history_net_funding_usd': str(pm_sums['FUNDING']),
        'pm_cash_control_difference_usd': str(cash_control),
        'pm_cash_control_cent_difference_usd': present_cents(cash_control),
        'pm_positions': len(pm_positions),
        'pm_nonredeemable_positive_positions': [str(row['asset']) for row in pm_positions
            if row.get('redeemable') is not True and Decimal(row['size']) > 0],
        'pm_positive_position_values': [str(row['asset']) for row in pm_positions
            if Decimal(row['currentValue']) > 0],
        'pm_closed_positions': len(pm_closed),
        'pm_recent_asset_lifetime_cash_flow_usd': exact_cash,
        'kalshi_recent_settlement_record_pnl_usd': recent_ks,
        'kalshi_fill_observations': len(all_fills),
        'kalshi_unique_fills': len(unique_fills),
        'kalshi_fill_history_first_utc': min(row['created_time'] for row in all_fills),
        'kalshi_settlement_history_first_utc': min(line.timestamp for line in ks),
        'descriptive_2026_09_07_utc_to_snapshot_subtotals_NOT_a_current_account_total': {
            'pm_trade_redemption_cash_usd': str(recent_pm),
            'kalshi_fill_matched_settlement_pnl_usd': str(recent_kalshi),
            'sum_usd': str(recent_pm + recent_kalshi),
            'sum_cent_presentation': present_cents(recent_pm + recent_kalshi),
            'kalshi_fill_count': len(recent_fills), 'kalshi_settlement_count': len(recent_settlements),
        },
        'maximus_cover_cash_pnl_usd': str(by_asset['22365084490966707252101015936389490534266716679018845032329737758423702381578']
            + next(line.amount_usd for line in ks if line.instrument == 'KXATPCHALLENGERMATCH-26SEP08JONMOR-JON')),
        'limitations': ['Historical screenshot window is unspecified.',
            'Kalshi settlement records alone cannot cover early dispositions.',
            'Maximus execution account row disagrees with authoritative cash by more than one cent.'],
    }


if __name__ == '__main__':
    result = run()
    print(json.dumps(result, indent=2, sort_keys=True))
