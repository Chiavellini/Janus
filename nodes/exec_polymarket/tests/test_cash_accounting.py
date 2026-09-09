"""Cash finality is independent of a match or chain confirmation (L52)."""
from decimal import Decimal
import json

import pytest

from kernel.execution_protocol import Ack, FillRecord, OrderRequest
from kernel.schema import FillState, Mode
from nodes.exec_polymarket.client import PolymarketExecution, PyClobTransport, authoritative_cash_fill
from nodes.execution.journal import Journal
from nodes.store_tuples.store import TupleStore


def trade():
    return dict(id='a9bfe2a5-470d-4c59-96df-2460af495118', taker_order_id='order',
                asset_id='token', transaction_hash='0xtransaction', side='BUY',
                trader_side='TAKER', size='10.166667', price='0.35', fee_rate_bps='0',
                status='CONFIRMED', match_time=1000)


def activity():
    return dict(type='TRADE', asset='token', transactionHash='0xtransaction', side='BUY',
                size=Decimal('10.166667'), price=Decimal('0.354098349'),
                usdcSize=Decimal('3.71626'))


class Transport:
    def __init__(self):
        self.trades_payload = [trade()]
        self.activity_payload = [activity()]

    def trades(self, *, after_ts):
        return self.trades_payload

    def trade_activity(self, *, after_ts):
        if isinstance(self.activity_payload, Exception):
            raise self.activity_payload
        return self.activity_payload


def venue(tmp_path):
    transport = Transport()
    journal = Journal(TupleStore(tmp_path / 'cash.sqlite', enforce_volume=False))
    journal.pending(OrderRequest('polymarket', 'token', 'token', 'buy_yes', .36, 10,
                                 'ioc', 'client', 'opportunity'), mode='LIMITED_LIVE', now=999)
    journal.record(Ack('polymarket', 'client', 'order', FillState.FILLED, 10.166667,
                       .36, None, 'matched', 1000, settlement_pending=True), kind='ack')
    adapter = PolymarketExecution(transport, journal, Mode.LIMITED_LIVE, clock=lambda: 1001)
    adapter.fee_params = {'fee_rate': .05}
    return adapter, journal, transport


def test_maximus_cash_controls_vwap_and_fee_instead_of_first_maker_price(tmp_path):
    adapter, journal, _ = venue(tmp_path)
    fill = adapter.fills(since_utc=0)[0]
    assert fill.final and fill.price == .354098349
    assert fill.contracts * fill.price + fill.fee_usd == pytest.approx(3.71626, abs=1e-12)
    assert fill.fee_usd == pytest.approx(.116260000467217, abs=1e-12)
    assert adapter.last_fee_source == 'venue activity cash'
    adapter.fills(since_utc=0)
    events = journal.store.con.execute("SELECT raw_json FROM order_events WHERE kind='authoritative_cash'").fetchall()
    assert len(events) == 1, 'identical immutable source is not double-counted'
    source = json.loads(events[0][0])
    assert source['fill_id'] == trade()['id']
    assert source['activity']['usdcSize'] == '3.71626'


@pytest.mark.parametrize('payload', [[], [activity(), activity()], TimeoutError('late')])
def test_missing_ambiguous_or_unavailable_cash_keeps_confirmed_fill_provisional(tmp_path, payload):
    adapter, journal, transport = venue(tmp_path)
    transport.activity_payload = payload
    fill = adapter.fills(since_utc=0)[0]
    assert not fill.final and fill.contracts == 10.166667
    assert 'provisional' in adapter.last_fee_source
    assert journal.store.con.execute('SELECT final FROM venue_fills').fetchone()[0] == 0
    transport.activity_payload = [activity()]
    assert adapter.fills(since_utc=0)[0].final
    assert journal.store.con.execute('SELECT COUNT(*),MIN(final) FROM venue_fills').fetchone() == (1, 1)


def test_two_clob_trades_sharing_one_cash_line_are_not_allocated_by_estimate(tmp_path):
    adapter, _, transport = venue(tmp_path)
    second = trade()
    second['id'] = 'other-fill'
    transport.trades_payload.append(second)
    assert not any(fill.final for fill in adapter.fills(since_utc=0))


@pytest.mark.parametrize('field,value', [('size', '10'), ('asset', 'different'),
                                       ('usdcSize', '2'), ('price', 'NaN'), ('side', 'UNKNOWN')])
def test_inconsistent_cash_is_rejected(field, value):
    row = activity()
    row[field] = value
    with pytest.raises(ValueError):
        authoritative_cash_fill(trade(), row)


def test_sell_fee_preserves_actual_cash_credit():
    tr, row = trade(), activity()
    tr['side'] = row['side'] = 'SELL'
    row['usdcSize'] = Decimal('3.48374')
    price, fee = authoritative_cash_fill(tr, row)
    assert float(tr['size']) * price - fee == pytest.approx(3.48374, abs=1e-12)


def test_get_order_price_is_explicitly_provisional(tmp_path):
    adapter, _, _ = venue(tmp_path)
    state = adapter._state_from_order(dict(id='order', status='MATCHED', size_matched='10', price='.36'),
                                     'client', 10, 1001)
    assert state.settlement_pending and 'provisional' in state.detail


def test_cash_transport_is_get_only_decimal_and_requires_empty_terminal_page(monkeypatch):
    from urllib.parse import parse_qs, urlparse
    requests = []
    payloads = [b'[{"usdcSize":3.71626}]', b'[]']
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return payloads.pop(0)
    def get(request, *, timeout):
        requests.append(request)
        return Response()
    monkeypatch.setenv('JANUS_PM_FUNDER', 'public-wallet')
    monkeypatch.setattr('urllib.request.urlopen', get)
    transport = PyClobTransport.__new__(PyClobTransport)
    assert transport.trade_activity(after_ts=1000) == [{'usdcSize': Decimal('3.71626')}]
    assert len(requests) == 2 and all(request.get_method() == 'GET' for request in requests)
    query = parse_qs(urlparse(requests[1].full_url).query)
    assert query['offset'] == ['1'] and query['start'] == ['880'] and query['type'] == ['TRADE']


@pytest.mark.parametrize('failure', ['timeout', 'absent_reader', 'empty', 'ambiguous', 'malformed'])
@pytest.mark.parametrize('later_status', ['CONFIRMED', 'MATCHED'])
def test_proved_cash_survives_later_reader_failure_restart_and_guard_sync(tmp_path, failure, later_status):
    from nodes.execute.guard import PositionGuard
    from nodes.reconcile.reconcile import releasable, settle
    adapter, journal, transport = venue(tmp_path)
    proved = adapter.fills(since_utc=0)[0]
    snapshot = journal.store.con.execute('SELECT * FROM venue_fills').fetchall()
    source = journal.store.con.execute('SELECT * FROM pm_cash_sources').fetchall()
    guard = PositionGuard.__new__(PositionGuard)
    guard.journal, guard.clock = journal, lambda: 1002
    guard._sync_order_from_fills(journal.get('client'))
    assert journal.get('client')['settlement_pending'] == 0
    if failure == 'timeout': transport.activity_payload = TimeoutError('late')
    elif failure == 'absent_reader': transport.trade_activity = None
    elif failure == 'empty': transport.activity_payload = []
    elif failure == 'ambiguous': transport.activity_payload = [activity(), activity()]
    else: transport.activity_payload = [dict(activity(), usdcSize='2')]
    adapter = PolymarketExecution(transport, journal, Mode.LIMITED_LIVE, clock=lambda: 1003)
    transport.trades_payload[0]['status'] = later_status  # stale chain status is not a reversal
    reread = adapter.fills(since_utc=0)[0]
    assert reread == proved
    assert journal.store.con.execute('SELECT * FROM venue_fills').fetchall() == snapshot
    assert journal.store.con.execute('SELECT * FROM pm_cash_sources').fetchall() == source
    assert 'durable' in adapter.last_fee_source
    guard._sync_order_from_fills(journal.get('client'))
    row = journal.get('client')
    assert row['settlement_pending'] == 0 and row['avg_price'] == pytest.approx(.354098349, abs=1e-12)
    assert row['filled_contracts'] * row['avg_price'] + row['fee_usd'] == pytest.approx(3.71626, abs=1e-12)
    legs = [dict(venue='polymarket', client_order_id='client', outcome_id='token', side='buy_yes',
                 contracts=row['filled_contracts'], price=row['avg_price'], fee_usd=row['fee_usd'],
                 state=row['state'], final=not row['settlement_pending'])]
    realized = settle(legs=legs, winners={'polymarket': 'loser-complement'}, now=1003)
    assert releasable(realized) and realized[0].realized_usd == pytest.approx(-3.71626, abs=1e-12)


def test_orphan_cash_is_durable_before_order_adoption(tmp_path):
    transport = Transport()
    journal = Journal(TupleStore(tmp_path / 'orphan.sqlite', enforce_volume=False))
    adapter = PolymarketExecution(transport, journal, Mode.LIMITED_LIVE)
    proved = adapter.fills(since_utc=0)[0]
    assert journal.store.con.execute('SELECT COUNT(*) FROM orders').fetchone()[0] == 0
    assert journal.store.con.execute('SELECT COUNT(*) FROM pm_cash_sources').fetchone()[0] == 1
    transport.activity_payload = []
    assert PolymarketExecution(transport, journal, Mode.LIMITED_LIVE).fills(since_utc=0)[0] == proved


def test_legacy_model_final_without_cash_provenance_remains_unproven(tmp_path):
    adapter, journal, transport = venue(tmp_path)
    tr = trade()
    journal.record_fill(FillRecord('polymarket', 'order', tr['id'], 10.166667, .35, .115645837125,
                                  True, 1000, True, market_id='token', side='buy_yes'))
    transport.activity_payload = []
    fill = adapter.fills(since_utc=0)[0]
    assert not fill.final and fill.price == .36
    assert journal.store.con.execute('SELECT COUNT(*) FROM pm_cash_sources').fetchone()[0] == 0


def test_explicit_new_cash_correction_appends_and_preserves_old_authority(tmp_path):
    adapter, journal, transport = venue(tmp_path)
    first = adapter.fills(since_utc=0)[0]
    original_source = journal.store.con.execute('SELECT source_json FROM pm_cash_sources').fetchone()[0]
    transport.activity_payload = [dict(activity(), usdcSize=Decimal('3.72626'))]
    corrected = adapter.fills(since_utc=0)[0]
    assert corrected.final and corrected.fee_usd - first.fee_usd == pytest.approx(.01, abs=1e-12)
    assert journal.store.con.execute('SELECT source_json FROM pm_cash_sources ORDER BY id').fetchall()[0][0] == original_source
    assert journal.store.con.execute('SELECT COUNT(*) FROM pm_cash_sources').fetchone()[0] == 2
    assert journal.store.con.execute("SELECT COUNT(*) FROM order_events WHERE kind='authoritative_cash'").fetchone()[0] == 2
    transport.activity_payload = TimeoutError('late')
    assert adapter.fills(since_utc=0)[0] == corrected


def test_missing_cash_uses_maker_vwap_then_buy_ceiling_not_first_maker_price(tmp_path):
    adapter, _, transport = venue(tmp_path)
    transport.activity_payload = []
    transport.trades_payload[0]['maker_orders'] = [
        dict(asset_id='other-token', side='BUY', price='.65', matched_amount='6'),
        dict(asset_id='token', side='SELL', price='.3599999712000023', matched_amount='4.166667')]
    fill = adapter.fills(since_utc=0)[0]
    assert not fill.final and fill.price == pytest.approx(3.60 / 10.166667, abs=1e-12)
    del transport.trades_payload[0]['maker_orders']
    fill = adapter.fills(since_utc=0)[0]
    assert not fill.final and fill.price == .36 and fill.price != .35


def test_unknown_orphan_price_uses_binary_bounds_not_a_fictional_average(tmp_path):
    transport = Transport()
    transport.activity_payload = []
    journal = Journal(TupleStore(tmp_path / 'unproved.sqlite', enforce_volume=False))
    adapter = PolymarketExecution(transport, journal, Mode.LIMITED_LIVE)
    assert adapter.fills(since_utc=0)[0].price == 1
    transport.trades_payload[0].update(id='sell', side='SELL')
    sell = adapter.fills(since_utc=0)[0]
    assert sell.price == 0 and not sell.final


@pytest.mark.parametrize('batch_failure', ['null_before_duplicate', 'generator_raises'])
@pytest.mark.parametrize('prior_authority', [False, True])
def test_activity_batch_is_atomic_on_index_or_iteration_failure(tmp_path, batch_failure, prior_authority):
    adapter, journal, transport = venue(tmp_path)
    proved = adapter.fills(since_utc=0)[0] if prior_authority else None
    sources_before = journal.store.con.execute('SELECT * FROM pm_cash_sources').fetchall()
    audit_before = journal.store.con.execute("SELECT * FROM order_events WHERE kind='authoritative_cash'").fetchall()
    # A plausible changed cash amount must not be accepted from an incomplete batch.
    candidate = dict(activity(), usdcSize=Decimal('3.72626'))
    if batch_failure == 'null_before_duplicate':
        transport.activity_payload = [candidate, None, dict(candidate)]
    else:
        def incomplete():
            yield candidate
            raise RuntimeError('activity iterator failed after first row')
        transport.activity_payload = incomplete()
    result = adapter.fills(since_utc=0)[0]
    assert journal.store.con.execute('SELECT * FROM pm_cash_sources').fetchall() == sources_before
    assert journal.store.con.execute("SELECT * FROM order_events WHERE kind='authoritative_cash'").fetchall() == audit_before
    assert 'CASH_ACTIVITY_PENDING' in adapter.last_error
    if prior_authority:
        assert result == proved and 'durable' in adapter.last_fee_source
        assert result.contracts * result.price + result.fee_usd == pytest.approx(3.71626, abs=1e-12)
    else:
        assert not result.final and result.price == .36
        assert 'provisional' in adapter.last_fee_source
    assert journal.store.con.execute('SELECT final FROM venue_fills').fetchone()[0] == int(prior_authority)
