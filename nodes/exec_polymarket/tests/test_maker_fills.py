"""L54 offline owned-maker attribution; fixture values are synthetic, no venue access."""
from copy import deepcopy
from decimal import Decimal

import pytest

from kernel.execution_protocol import Ack, OrderRequest
from kernel.schema import FillState, Mode
from nodes.exec_polymarket.client import PolymarketExecution
from nodes.exec_polymarket.fill_projection import project_account_trade
from nodes.execution.journal import Journal
from nodes.risk.kill import KillSwitches
from nodes.store_tuples.store import TupleStore


def raw_trade(*, tid='trade-1', qty='6', role='MAKER', oid='maker-order', side='BUY', asset='owned-token'):
    return dict(id=tid, trader_side=role, taker_order_id='other-taker', asset_id='taker-token',
                side='SELL', size='100', price='.01', status='CONFIRMED', match_time=1000,
                transaction_hash='tx-' + tid, maker_orders=[
                    dict(order_id='foreign-maker', matched_amount='94', price='.01',
                         asset_id='foreign-token', side='BUY', maker_address='foreign-wallet'),
                    dict(order_id=oid, matched_amount=qty, price='.65', asset_id=asset, side=side,
                         fee_rate_bps='', maker_address='our-wallet')])


def cash(*, tid='trade-1', qty='6', side='BUY', asset='owned-token'):
    return dict(type='TRADE', transactionHash='tx-' + tid, asset=asset, side=side,
                size=Decimal(qty), price=Decimal('.65'), usdcSize=Decimal(qty) * Decimal('.65'))


class Transport:
    def __init__(self):
        self.raw = [raw_trade()]
        self.cash = [cash()]
        self.before_cash = lambda: None
    def trades(self, *, after_ts): return self.raw
    def trade_activity(self, *, after_ts):
        self.before_cash()
        if isinstance(self.cash, Exception): raise self.cash
        return self.cash


def own(journal, *, cid='client', oid='maker-order', post_only=True, side='buy_yes', asset='owned-token'):
    journal.pending(OrderRequest('polymarket', asset, asset, side, .65, 10, 'gtc', cid, 'opportunity'),
                    mode='LIMITED_LIVE', now=999)
    journal.record(Ack('polymarket', cid, oid, FillState.UNCONFIRMED, 0, None, None, 'live', 999,
                       open=True, settlement_pending=True), kind='ack')
    if post_only:
        journal.store.con.execute('INSERT INTO pm_post_only_orders(client_order_id,venue_order_id,maker_amount,taker_amount,wire_json) VALUES(?,?,?,?,?)',
                                  (cid, oid, '6500000', '10000000', '{}'))
        journal.store.con.commit()


def world(tmp_path, *, owned=True, post_only=True):
    journal = Journal(TupleStore(tmp_path / 'maker.sqlite', enforce_volume=False))
    transport = Transport()
    kill = KillSwitches(tmp_path / 'kill', enforce_volume=False)
    adapter = PolymarketExecution(transport, journal, Mode.LIMITED_LIVE, clock=lambda: 1001, kill=kill)
    if owned: own(journal, post_only=post_only)
    return adapter, journal, transport, kill


def guard_for(adapter, journal, kill):
    from kernel.execution_protocol import OrderState
    from kernel.schema import ExecutionState as X
    from nodes.execute.guard import PositionGuard
    from nodes.execute.plan import LegPlan
    from nodes.execute.records import Execution, ExecutionRecords
    from nodes.risk.limits import ProtectLimits
    records = ExecutionRecords(journal.store)
    first = LegPlan('polymarket', 'owned-token', 'owned-token', 'buy_yes', .65, 10, 'gtc')
    hedge = LegPlan('kalshi', 'other', 'other', 'buy_yes', .3, 10, 'ioc')
    execution = Execution('execution', 'opportunity', 'event', 'atp', 'LIMITED_LIVE', 10, 900,
                          state=X.UNKNOWN_PROVIDER_STATE, first_client_id='client')
    records.start(execution, plan={'first': first.__dict__, 'hedge': hedge.__dict__, 'max_cost': 1, 'fee': 0}, books={})
    records.sync(execution, now=900)
    # Isolate the real fill/guard path from independently tested lifecycle/status I/O.
    adapter.status = lambda cid: OrderState('polymarket', cid, 'maker-order', FillState.UNCONFIRMED,
                                             0, None, None, 'pending', 1001, open=True)
    return PositionGuard(venues={'polymarket': adapter}, journal=journal, records=records,
                         store=journal.store, limits=ProtectLimits(), started_utc=999,
                         kill=kill, clock=lambda: 1200, log=lambda *_: None)


def test_owned_maker_uses_own_order_size_price_token_side_and_cash(tmp_path):
    adapter, journal, _, kill = world(tmp_path)
    fill = adapter.fills(since_utc=0)[0]
    assert (fill.venue_order_id, fill.fill_id, fill.contracts, fill.price, fill.market_id, fill.side) == (
        'maker-order', 'trade-1:maker:maker-order', 6, .65, 'owned-token', 'buy_yes')
    assert fill.final and not fill.is_taker and fill.fee_usd == pytest.approx(0, abs=1e-12)
    assert fill.contracts * fill.price + fill.fee_usd == pytest.approx(3.9, abs=1e-12)
    assert not kill.active(live=True)
    source = journal.store.con.execute('SELECT source_json FROM pm_cash_sources').fetchone()[0]
    assert 'other-taker' in source and 'foreign-maker' in source, 'original source parties retained in provenance'


def test_complementary_buy_maker_never_inherits_other_token_taker_side(tmp_path):
    adapter, _, transport, _ = world(tmp_path)
    transport.raw[0].update(side='BUY', asset_id='complement-token', price='.35')
    fill = adapter.fills(since_utc=0)[0]
    assert fill.final and fill.side == 'buy_yes' and fill.price == .65 and fill.market_id == 'owned-token'


def test_ordinary_maker_sell_is_projected_as_owned_sell_credit(tmp_path):
    adapter, journal, transport, _ = world(tmp_path, owned=False)
    own(journal, post_only=False, side='sell_yes')
    transport.raw = [raw_trade(side='SELL')]
    transport.cash = [cash(side='SELL')]
    fill = adapter.fills(since_utc=0)[0]
    assert fill.final and fill.side == 'sell_yes' and fill.venue_order_id == 'maker-order'


def test_partial_then_complete_maker_fills_are_distinct_and_cumulative(tmp_path):
    adapter, journal, transport, kill = world(tmp_path)
    transport.raw, transport.cash = [raw_trade(tid='first', qty='4')], [cash(tid='first', qty='4')]
    assert adapter.fills(since_utc=0)[0].contracts == 4
    transport.raw, transport.cash = [raw_trade(tid='second', qty='6')], [cash(tid='second', qty='6')]
    assert adapter.fills(since_utc=0)[0].contracts == 6
    adapter.fills(since_utc=0)
    assert journal.store.con.execute('SELECT COUNT(*),SUM(contracts),MIN(final) FROM venue_fills').fetchone() == (2, 10, 1)
    assert not kill.active(live=True)


def test_maker_aggregate_cap_violation_is_durable_before_cash_read(tmp_path):
    adapter, journal, transport, kill = world(tmp_path)
    adapter.fills(since_utc=0)  # six already confirmed
    transport.raw, transport.cash = [raw_trade(tid='second', qty='5')], [cash(tid='second', qty='5')]
    def check_stop():
        assert kill.active(live=True) == ['live']
        assert journal.store.con.execute("SELECT COUNT(*) FROM pm_post_only_violations WHERE code='ORDER_OVERFILL'").fetchone()[0] == 1
    transport.before_cash = check_stop
    fill = adapter.fills(since_utc=0)[0]
    assert fill.contracts == 5 and not fill.final
    assert journal.store.con.execute('SELECT SUM(contracts) FROM venue_fills').fetchone()[0] == 11


def test_post_only_order_observed_as_taker_latches_before_cash_and_keeps_quantity(tmp_path):
    adapter, journal, transport, kill = world(tmp_path)
    transport.raw = [dict(raw_trade(), taker_order_id='maker-order', trader_side='TAKER',
                          asset_id='owned-token', side='BUY', size='4', price='.65', maker_orders=[])]
    transport.cash = [cash(qty='4')]
    def check_stop():
        assert kill.active(live=True) == ['live']
        assert journal.store.con.execute("SELECT COUNT(*) FROM pm_post_only_violations WHERE code='POST_ONLY_ROLE_VIOLATION'").fetchone()[0] == 1
    transport.before_cash = check_stop
    fill = adapter.fills(since_utc=0)[0]
    assert fill.venue_order_id == 'maker-order' and fill.contracts == 4 and fill.is_taker and not fill.final
    assert journal.store.con.execute('SELECT COUNT(*) FROM pm_cash_sources').fetchone()[0] == 0


@pytest.mark.parametrize('role', [None, '', 'UNKNOWN'])
def test_unknown_maker_role_remains_provisional(tmp_path, role):
    adapter, journal, transport, _ = world(tmp_path)
    transport.raw[0]['trader_side'] = role
    fill = adapter.fills(since_utc=0)[0]
    assert fill.contracts == 6 and fill.price == .65 and not fill.final
    assert journal.store.con.execute('SELECT COUNT(*) FROM pm_cash_sources').fetchone()[0] == 0


def test_unknown_post_only_role_retains_durable_cash_but_not_finality(tmp_path):
    adapter, journal, transport, _ = world(tmp_path)
    proved = adapter.fills(since_utc=0)[0]
    before = journal.store.con.execute('SELECT * FROM pm_cash_sources').fetchall()
    transport.raw[0]['trader_side'] = None
    transport.cash = TimeoutError('late')
    fill = adapter.fills(since_utc=0)[0]
    assert not fill.final and fill.price == proved.price and fill.fee_usd == proved.fee_usd
    assert journal.store.con.execute('SELECT * FROM pm_cash_sources').fetchall() == before


def test_taker_activity_is_not_owned_maker_cash(tmp_path):
    adapter, journal, transport, _ = world(tmp_path)
    transport.cash = [dict(cash(), asset='taker-token', side='SELL', size=Decimal(100), usdcSize=Decimal(1), price=Decimal('.01'))]
    fill = adapter.fills(since_utc=0)[0]
    assert not fill.final and fill.contracts == 6 and fill.price == .65
    assert journal.store.con.execute('SELECT COUNT(*) FROM pm_cash_sources').fetchone()[0] == 0


def test_multiple_owned_makers_keep_ids_and_do_not_allocate_aggregate_cash(tmp_path):
    adapter, journal, transport, _ = world(tmp_path)
    own(journal, cid='second-client', oid='second-maker')
    transport.raw[0]['maker_orders'].append(dict(transport.raw[0]['maker_orders'][1], order_id='second-maker', matched_amount='4'))
    transport.cash = [cash(qty='10')]
    fills = adapter.fills(since_utc=0)
    assert {(f.venue_order_id, f.contracts) for f in fills} == {('maker-order', 6), ('second-maker', 4)}
    assert len({f.fill_id for f in fills}) == 2 and not any(f.final for f in fills)


def test_orphan_maker_exact_funder_ownership_survives_adoption_and_cash_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv('JANUS_PM_FUNDER', 'OUR-WALLET')
    adapter, journal, transport, _ = world(tmp_path, owned=False)
    proved = adapter.fills(since_utc=0)[0]
    assert proved.final and proved.venue_order_id == 'maker-order'
    own(journal)
    transport.cash = TimeoutError('late')
    again = PolymarketExecution(transport, journal, Mode.LIMITED_LIVE, clock=lambda: 1002).fills(since_utc=0)[0]
    assert again == proved


@pytest.mark.parametrize('prior', [False, True])
def test_maker_atomic_activity_failure_keeps_only_prior_authority(tmp_path, prior):
    adapter, journal, transport, _ = world(tmp_path)
    proved = adapter.fills(since_utc=0)[0] if prior else None
    before = journal.store.con.execute('SELECT * FROM pm_cash_sources').fetchall()
    transport.cash = [cash(), None, cash()]
    fill = adapter.fills(since_utc=0)[0]
    assert fill.final is prior
    if prior: assert fill == proved
    assert journal.store.con.execute('SELECT * FROM pm_cash_sources').fetchall() == before


def test_unattributable_maker_cannot_turn_into_taker_or_zero_fill():
    with pytest.raises(ValueError, match='no proven owned maker'):
        project_account_trade(raw_trade(), owned_order_ids=set())


def test_malformed_or_duplicate_owned_maker_identity_is_rejected():
    raw = raw_trade()
    raw['maker_orders'].append(deepcopy(raw['maker_orders'][1]))
    with pytest.raises(ValueError, match='duplicate owned maker'):
        project_account_trade(raw, owned_order_ids={'maker-order'})


def test_unrelated_bad_maker_projection_cannot_hide_observed_owned_taker_stop(tmp_path):
    adapter, journal, transport, kill = world(tmp_path)
    taker = dict(raw_trade(), taker_order_id='maker-order', trader_side='TAKER',
                 asset_id='owned-token', side='BUY', size='4', maker_orders=[])
    bad = raw_trade(tid='bad', oid='unowned')
    transport.raw = [taker, bad]
    guard = guard_for(adapter, journal, kill)
    snap = guard.fetch()
    assert [(f.contracts, f.final) for f in snap.fills] == [(4, False)]
    assert adapter.projection_batch_error and snap.errors['fills:polymarket'] == adapter.projection_batch_error
    assert journal.store.con.execute('SELECT contracts,final FROM venue_fills').fetchone() == (4, 0)
    report = guard.apply(snap)
    assert guard.records.load('execution').first_filled == 4
    assert 'execution' in report.to_protect
    assert journal.get('client')['filled_contracts'] == 4
    assert journal.get('client')['settlement_pending']
    assert kill.active(live=True) == ['live']
    assert journal.store.con.execute("SELECT COUNT(*) FROM pm_post_only_violations WHERE code='POST_ONLY_ROLE_VIOLATION'").fetchone()[0] == 1


@pytest.mark.parametrize('quantity', [8, 11])
@pytest.mark.parametrize('stale_cash_available', [False, True])
def test_quantity_increase_survives_smaller_durable_cash_restart_stale_read_and_guard(tmp_path, quantity, stale_cash_available):
    adapter, journal, transport, kill = world(tmp_path)
    transport.cash = [dict(cash(), usdcSize=Decimal('4.02'))]  # $0.12 cash-proved fee covers six only.
    guard = guard_for(adapter, journal, kill)
    guard.apply(guard.fetch())
    authority = journal.store.con.execute('SELECT * FROM pm_cash_sources').fetchall()
    assert journal.get('client')['filled_contracts'] == 6 and authority
    transport.raw = [raw_trade(qty=str(quantity))]
    transport.cash = TimeoutError('cash unavailable')
    snap = guard.fetch()
    assert [(f.contracts, f.final) for f in snap.fills] == [(quantity, False)]
    assert snap.fills[0].fee_usd == 0, 'provisional maker fee must not present the covered-six cash fee as full-quantity authority'
    assert journal.store.con.execute('SELECT contracts,final FROM venue_fills').fetchone() == (quantity, 0)
    report = guard.apply(snap)
    assert journal.get('client')['filled_contracts'] == quantity and journal.get('client')['settlement_pending']
    assert guard.records.load('execution').first_filled == quantity and 'execution' in report.to_protect
    if quantity > 10: assert kill.active(live=True) == ['live']
    # A restarted reader repeating the older six-share line cannot imply reversal.
    restarted = PolymarketExecution(transport, journal, Mode.LIMITED_LIVE, clock=lambda: 1201, kill=kill)
    transport.raw = [raw_trade(qty='6')]
    if stale_cash_available: transport.cash = [dict(cash(), usdcSize=Decimal('4.02'))]
    assert [(f.contracts, f.final) for f in restarted.fills(since_utc=0)] == [(quantity, False)]
    assert journal.store.con.execute('SELECT contracts,final FROM venue_fills').fetchone() == (quantity, 0)
    assert journal.store.con.execute('SELECT * FROM pm_cash_sources').fetchall() == authority
    assert 'cash covers 6' in restarted.last_fee_source


@pytest.mark.parametrize('prior', [False, True])
@pytest.mark.parametrize('bad_neighbor', ['malformed', 'iterator_failure'])
def test_incomplete_projection_returns_valid_maker_but_mints_no_cash_authority(tmp_path, prior, bad_neighbor):
    adapter, journal, transport, _ = world(tmp_path)
    if prior: assert adapter.fills(since_utc=0)[0].final
    authority = journal.store.con.execute('SELECT * FROM pm_cash_sources').fetchall()
    if bad_neighbor == 'malformed':
        transport.raw = [raw_trade(), None]
    else:
        def broken_reader():
            yield raw_trade()
            raise TimeoutError('trade iterator interrupted')
        transport.raw = broken_reader()
    transport.before_cash = lambda: pytest.fail('known-incomplete projection must not delay exposure on a cash read')
    fills = adapter.fills(since_utc=0)
    assert [(f.contracts, f.final) for f in fills] == [(6, False)]
    assert adapter.projection_batch_error
    assert journal.store.con.execute('SELECT contracts,final FROM venue_fills').fetchone() == (6, 0)
    assert journal.store.con.execute('SELECT * FROM pm_cash_sources').fetchall() == authority


@pytest.mark.parametrize('wrong_field,value', [('asset_id', 'wrong-token'), ('side', 'SELL')])
def test_post_only_maker_token_or_side_contradiction_is_not_final(tmp_path, wrong_field, value):
    adapter, _, transport, kill = world(tmp_path)
    transport.raw[0]['maker_orders'][1][wrong_field] = value
    fill = adapter.fills(since_utc=0)[0]
    assert fill.contracts == 6 and not fill.final and kill.active(live=True) == ['live']


def test_cash_price_from_taker_cannot_replace_owned_maker_price(tmp_path):
    adapter, journal, transport, _ = world(tmp_path)
    transport.cash = [dict(cash(), price=Decimal('.01'))]
    fill = adapter.fills(since_utc=0)[0]
    assert not fill.final and fill.price == .65
    assert journal.store.con.execute('SELECT COUNT(*) FROM pm_cash_sources').fetchone()[0] == 0


@pytest.mark.parametrize('quantity,role', [(4, 'MAKER'), (10, 'MAKER'), (11, 'MAKER'), (4, 'TAKER')])
def test_failed_fill_write_returns_quantity_to_guard_and_retains_stop(tmp_path, monkeypatch, quantity, role):
    adapter, journal, transport, kill = world(tmp_path)
    guard = guard_for(adapter, journal, kill)
    transport.raw, transport.cash = [raw_trade(qty=str(quantity))], [cash(qty=str(quantity))]
    if role == 'TAKER':
        transport.raw = [dict(raw_trade(), taker_order_id='maker-order', trader_side=role,
                              asset_id='owned-token', side='BUY', size=str(quantity), maker_orders=[])]
    before = journal.store.con.execute('SELECT * FROM pm_cash_sources').fetchall()
    record_fill = journal.record_fill
    monkeypatch.setattr(journal, 'record_fill', lambda _: (_ for _ in ()).throw(OSError('disk full: fill')))
    snap = guard.fetch()
    assert [(f.contracts, f.final) for f in snap.fills] == [(quantity, False)]
    assert adapter.persistence_error and snap.errors['persistence:polymarket'] == adapter.persistence_error
    assert kill.active(live=True) == ['live']
    assert journal.store.con.execute('SELECT * FROM pm_cash_sources').fetchall() == before
    assert journal.store.con.execute("SELECT COUNT(*) FROM order_events WHERE kind='authoritative_cash'").fetchone()[0] == 0
    report = guard.apply(snap)
    assert guard.records.load('execution').first_filled == quantity and 'execution' in report.to_protect
    # Even before repair, stale and absent rows cannot erase in-process inventory.
    if role == 'TAKER': transport.raw[0]['size'] = '2'
    else: transport.raw[0]['maker_orders'][1]['matched_amount'] = '2'
    transport.cash = TimeoutError('cash unavailable')
    assert [(f.contracts, f.final) for f in adapter.fills(since_utc=0)] == [(quantity, False)]
    transport.raw = []
    assert [(f.contracts, f.final) for f in adapter.fills(since_utc=0)] == [(quantity, False)]
    monkeypatch.setattr(journal, 'record_fill', record_fill)
    assert all(not f.final for f in adapter.fills(since_utc=0))
    assert adapter.persistence_error and kill.active(live=True)


@pytest.mark.parametrize('stage', ['cash_source', 'cash_event'])
def test_cash_persistence_failure_returns_fill_without_committed_false_authority(tmp_path, monkeypatch, stage):
    adapter, journal, _, kill = world(tmp_path)
    def fail(*args, **kwargs): raise OSError('disk full: ' + stage)
    if stage == 'cash_source': monkeypatch.setattr(adapter, '_remember_cash_source', fail)
    else:
        event = journal._event
        def failed_cash_event(cid, kind, state, raw, t):
            if kind == 'authoritative_cash': fail()
            return event(cid, kind, state, raw, t)
        monkeypatch.setattr(journal, '_event', failed_cash_event)
    fills = adapter.fills(since_utc=0)
    assert [(f.contracts, f.final) for f in fills] == [(6, False)]
    assert adapter.persistence_error and kill.active(live=True)
    assert journal.store.con.execute('SELECT COUNT(*) FROM pm_cash_sources').fetchone()[0] == 0
    assert journal.store.con.execute("SELECT COUNT(*) FROM order_events WHERE kind='authoritative_cash'").fetchone()[0] == 0


def test_later_fill_write_failure_returns_whole_prefix_nonfinal(tmp_path, monkeypatch):
    adapter, journal, transport, kill = world(tmp_path)
    guard = guard_for(adapter, journal, kill)
    transport.raw = [raw_trade(tid='first', qty='4'), raw_trade(tid='second', qty='6')]
    transport.cash = [cash(tid='first', qty='4'), cash(tid='second', qty='6')]
    record_fill = journal.record_fill
    def fail_second(fill):
        if fill.fill_id.startswith('second:'): raise OSError('disk full after valid first fill')
        return record_fill(fill)
    monkeypatch.setattr(journal, 'record_fill', fail_second)
    snap = guard.fetch()
    fills = snap.fills
    assert [(f.contracts, f.final) for f in fills] == [(4, False), (6, False)]
    assert adapter.persistence_error and kill.active(live=True)
    sources = journal.store.con.execute('SELECT fill_id FROM pm_cash_sources').fetchall()
    assert sources == [('first:maker:maker-order',)]
    report = guard.apply(snap)
    assert guard.records.load('execution').first_filled == 10 and 'execution' in report.to_protect
    assert journal.get('client')['settlement_pending']


@pytest.mark.parametrize('role,quantity', [('MAKER', 11), ('TAKER', 4)])
def test_unavailable_sql_writes_keep_independent_kill_and_observed_quantity(tmp_path, role, quantity):
    adapter, journal, transport, kill = world(tmp_path)
    transport.raw = [raw_trade(qty=str(quantity))]
    if role == 'TAKER':
        transport.raw = [dict(raw_trade(), taker_order_id='maker-order', trader_side=role,
                              asset_id='owned-token', side='BUY', size=str(quantity), maker_orders=[])]
    original = journal.store.con
    class FailedWrites:
        def __getattr__(self, name): return getattr(original, name)
        def execute(self, sql, *args):
            if sql.strip().split()[0].upper() not in {'SELECT', 'PRAGMA', 'BEGIN'}:
                raise OSError('disk full: all SQL writes unavailable')
            return original.execute(sql, *args)
    journal.store.con = FailedWrites()
    try:
        fills = adapter.fills(since_utc=0)
        assert [(f.contracts, f.final) for f in fills] == [(quantity, False)]
        assert 'durable audit also failed' in adapter.persistence_error
        assert kill.active(live=True) == ['live']
        transport.raw = []
        assert [(f.contracts, f.final) for f in adapter.fills(since_utc=0)] == [(quantity, False)]
        assert original.execute('SELECT COUNT(*) FROM pm_cash_sources').fetchone()[0] == 0
    finally:
        journal.store.con = original
