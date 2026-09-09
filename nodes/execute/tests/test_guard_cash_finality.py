from dataclasses import replace

import pytest

from kernel.execution_protocol import Ack, FillRecord, OrderRequest
from kernel.schema import FillState
from nodes.execute.guard import PositionGuard
from nodes.execution.journal import Journal
from nodes.store_tuples.store import TupleStore


def test_guard_requires_every_fill_cash_final_even_without_a_price_change(tmp_path):
    journal = Journal(TupleStore(tmp_path / 'cash.sqlite', enforce_volume=False))
    journal.pending(OrderRequest('polymarket', 'token', 'token', 'buy_yes', .5, 10,
                                 'ioc', 'client', 'opportunity'), mode='LIMITED_LIVE', now=1)
    journal.record(Ack('polymarket', 'client', 'order', FillState.FILLED, 10, .5, .1,
                       'matched', 2), kind='ack')
    guard = PositionGuard.__new__(PositionGuard)
    guard.journal, guard.clock = journal, lambda: 3
    first = FillRecord('polymarket', 'order', 'one', 5, .5, .05, True, 2, True)
    second = FillRecord('polymarket', 'order', 'two', 5, .5, .05, True, 2, False)
    journal.record_fill(first)
    journal.record_fill(second)
    guard._sync_order_from_fills(journal.get('client'))
    assert journal.get('client')['settlement_pending'] == 1
    journal.record_fill(replace(second, final=True))
    guard._sync_order_from_fills(journal.get('client'))
    assert journal.get('client')['settlement_pending'] == 0
    assert journal.get('client')['filled_contracts'] == 10


def test_cash_only_correction_updates_execution_and_settlement_without_reopening(tmp_path):
    from kernel.schema import ExecutionState as X
    from nodes.execute.guard import GuardReport, GuardSnapshot
    from nodes.execute.plan import LegPlan
    from nodes.execute.records import Execution, ExecutionRecords
    from nodes.reconcile.settle_executions import SETTLEMENTS_DDL, refresh_settlement_accounting
    from nodes.risk.limits import ProtectLimits

    store = TupleStore(tmp_path / 'execution.sqlite', enforce_volume=False)
    journal, records = Journal(store), ExecutionRecords(store)
    first = LegPlan('polymarket', 'token', 'token', 'buy_yes', .36, 10, 'ioc')
    hedge = LegPlan('kalshi', 'K-JON', 'K-JON:NO', 'buy_no', .65, 10.17, 'ioc')
    ex = Execution('execution', 'opportunity', 'event', 'atp', 'LIMITED_LIVE', 10, 1,
                   state=X.RECONCILED, first_client_id='first', hedge_client_ids=['hedge'],
                   first_filled=10.166667, first_avg_price=.36, hedge_filled=10.17,
                   hedge_avg_price=.65, released=True, detail='old settlement')
    records.start(ex, plan={'first': first.__dict__, 'hedge': hedge.__dict__, 'max_cost': 1, 'fee': 0}, books={})
    records.sync(ex, now=2)
    for cid, leg, qty, price, fee, pending in (
            ('first', first, 10.166667, .354098349, .116260000467217, True),
            ('hedge', hedge, 10.17, .65, .162, False)):
        journal.pending(OrderRequest(leg.venue, leg.market_id, leg.outcome_id, leg.side,
                                     leg.limit_price, qty, 'ioc', cid, 'opportunity'), mode='LIMITED_LIVE', now=1)
        journal.record(Ack(leg.venue, cid, cid + '-order', FillState.FILLED, qty, price,
                           fee, 'confirmed', 2, settlement_pending=pending), kind='authoritative_cash')
    guard = PositionGuard(venues={}, journal=journal, records=records, store=store,
                          limits=ProtectLimits(), started_utc=1, log=lambda *_: None, clock=lambda: 3)
    guard._reconcile_execution('execution', [], GuardSnapshot(now=3), GuardReport())
    assert records.load('execution').first_avg_price == .36, 'provisional accounting cannot replace final display'
    store.con.execute("UPDATE orders SET settlement_pending=0 WHERE client_order_id='first'")
    store.ensure_ddl(SETTLEMENTS_DDL)
    store.con.execute("INSERT INTO execution_settlements(execution_id,opportunity_id,event_id,league,mode,settled_ts,"
                      "kalshi_winner,polymarket_winner,realized_usd,released,legs_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      ('execution', 'opportunity', 'event', 'atp', 'LIMITED_LIVE', 2, 'OTHER', 'other-token', -.2765, 1, '[]'))
    store.con.commit()
    before_events = store.con.execute('SELECT id,raw_json FROM order_events').fetchall()
    report = GuardReport()
    guard._reconcile_execution('execution', [], GuardSnapshot(now=4), report)
    current = records.load('execution')
    assert current.first_avg_price == pytest.approx(.354098349, abs=1e-12)
    assert (current.state, current.released, current.first_filled, current.hedge_filled) == (X.RECONCILED, True, 10.166667, 10.17)
    assert report.corrected == ['execution'] and not report.to_protect
    transition = store.con.execute('SELECT from_state,to_state,detail FROM execution_transitions ORDER BY id DESC LIMIT 1').fetchone()
    assert transition[:2] == ('RECONCILED', 'RECONCILED') and 'authoritative cash' in transition[2]
    assert refresh_settlement_accounting(store, now=4, log=lambda *_: None) == 1
    assert store.con.execute('SELECT realized_usd FROM execution_settlements').fetchone()[0] == pytest.approx(-.318760, abs=1e-12)
    assert 'settled -0.3188 USD' in records.load('execution').detail
    assert store.con.execute('SELECT old_realized_usd,new_realized_usd FROM execution_settlement_revisions').fetchone() == pytest.approx((-.2765, -.318760), abs=1e-12)
    assert store.con.execute('SELECT id,raw_json FROM order_events').fetchall() == before_events
    assert refresh_settlement_accounting(store, now=5, log=lambda *_: None) == 0
