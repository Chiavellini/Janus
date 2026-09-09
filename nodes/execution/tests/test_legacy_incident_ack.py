"""L56 exact legacy incident; temporary databases and no venue/live I/O."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

import pytest

from nodes.execute.guard import GuardReport
from nodes.exec_polymarket.post_only import POST_ONLY_DDL
from nodes.exec_polymarket.position_evidence import capture, sha
from kernel.execution_protocol import Position
from nodes.execution.dispositions import canonical, digest, source_from_git
from nodes.execution.legacy_incident_ack import (DDL, FLAG, TABLE, append_confirmed, confirmation_plan,
    incident_snapshot, main, match_incident, prepare_manifest, prepare_from_database, resolve_idle_incidents)
from nodes.execution.tests.test_overfill_ack import world as overfill_world, confirm as overfill_confirm, complete_snapshot as base_snapshot, T0
from nodes.risk.flags import unresolved_flag_rows, recent_flags

ROOT = Path(__file__).resolve().parents[3]


def complete_snapshot(**kwargs):
    snap = base_snapshot(**kwargs)
    paging = dict(user='0x' + '1' * 40, sizeThreshold=0, limit=500, complete=True,
                  pages=[dict(offset=0, count=0, sha256=sha([]))])
    snap.position_evidence['polymarket'] = capture([], paging, observed_utc=snap.now)
    return snap


@pytest.fixture(scope='module')
def proof():
    return source_from_git(ROOT, 'f51620e53cdbafe9b4584bbc33d59a9d8fca19eb', 'nodes/execute/guard.py',
                           '8c7cdfbf3408be50d31a74538d67b2b2125a1bc80b1511ef20cdafd10e7fad71')


def world(tmp_path, proof):
    store, journal, guard, kill, overfill = overfill_world(tmp_path)
    overfill_confirm(tmp_path, journal, overfill)
    con = store.con
    con.executescript(POST_ONLY_DDL)
    detail = f'{FLAG}: a1: OperationalError: database is locked'
    con.execute('INSERT INTO lane_flags(id,seen_ts,flag,detail) VALUES(211,?,?,?)', (T0 + 260, FLAG, 'a1: ' + detail))
    con.execute('INSERT INTO pm_post_only_violations(id,client_order_id,code,detail,seen_utc) VALUES(1,?,?,?,?)', ('a1', FLAG, detail, T0 + 260))
    con.commit()
    proposal = dict(version=1, client_order_id='a1', flag_id=211, violation_id=1, source=proof, source_lines=[292, 301],
                    reason='Operator reviewed exact old guard lock label and settled IOC evidence.', supersedes_id=None)
    manifest = prepare_from_database(con, proposal)
    return store, journal, guard, kill, manifest, proposal


def confirm(tmp_path, store, manifest):
    db = tmp_path / 't.sqlite'
    plan = confirmation_plan(store.con, db, manifest, 'offline operator')
    return append_confirmed(store.con, db, manifest, 'offline operator', plan['confirm_sha256'], now=T0 + 280)


def test_exact_guard_resolution_preserves_every_source_row_and_kill(tmp_path, proof):
    store, _, guard, kill, manifest, _ = world(tmp_path, proof)
    tables = ['orders', 'executions', 'capital_reservations', 'execution_settlements', 'pm_post_only_violations']
    before = {table: store.con.execute(f'SELECT * FROM {table}').fetchall() for table in tables}
    kill.latch('live', 'preexisting operator STOP')
    assert confirm(tmp_path, store, manifest) == 1
    assert match_incident(store.con, 211)['id'] == 1
    report = guard.apply(complete_snapshot())
    assert any('POST_ONLY_PERSISTENCE_FAILED_RESOLVED_EXACT' in f for f in report.findings)
    assert not unresolved_flag_rows(store.con, FLAG)
    assert not recent_flags(tmp_path / 't.sqlite', FLAG, now=T0 + 300)
    assert kill.active(live=True) == ['live']
    assert before == {table: store.con.execute(f'SELECT * FROM {table}').fetchall() for table in tables}
    store.con.execute("INSERT INTO pm_post_only_orders(client_order_id,maker_amount,taker_amount,wire_json) VALUES('later-valid-maker','1','1','{}')")
    store.con.commit()
    later = GuardReport()
    guard._resolve_legacy_incidents(complete_snapshot(), later)
    assert later.findings == []  # Empty-maker gate applies to resolution, not later valid trading.


@pytest.mark.parametrize('change', [
    "UPDATE lane_flags SET detail='changed' WHERE id=211",
    "UPDATE pm_post_only_violations SET detail='changed' WHERE id=1",
    "UPDATE orders SET time_in_force='gtc'",
    "UPDATE orders SET filled_contracts=11",
    "UPDATE orders SET settlement_pending=1",
    "UPDATE orders SET open=1",
    "UPDATE executions SET released=0",
    "UPDATE executions SET unhedged=1",
    "UPDATE execution_settlements SET realized_usd=99",
    "UPDATE capital_reservations SET released_utc=NULL",
    "UPDATE pm_post_only_admission SET client_order_id='new'",
    "INSERT INTO pm_post_only_orders(client_order_id,maker_amount,taker_amount,wire_json) VALUES('new','1','1','{}')",
    "INSERT INTO pm_post_only_violations(client_order_id,code,detail,seen_utc) VALUES('other','OTHER','new',1)",
])
def test_changed_incident_or_current_risk_never_resolves(tmp_path, proof, change):
    store, _, guard, _, manifest, _ = world(tmp_path, proof)
    confirm(tmp_path, store, manifest)
    store.con.execute(change)
    store.con.commit()
    guard._resolve_legacy_incidents(complete_snapshot(), GuardReport())
    assert unresolved_flag_rows(store.con, FLAG)
    assert not store.con.execute("SELECT 1 FROM lane_flags WHERE flag=?", (FLAG + '_RESOLVED_EXACT',)).fetchone()


@pytest.mark.parametrize('case', ['incomplete', 'error', 'position', 'missing_position', 'missing_venue', 'new_flag', 'equal_timestamp'])
def test_incomplete_pass_or_new_incident_blocks(tmp_path, proof, case):
    from nodes.execute.guard import GuardReport
    store, _, guard, _, manifest, _ = world(tmp_path, proof)
    confirm(tmp_path, store, manifest)
    snap = complete_snapshot()
    if case == 'incomplete': snap.fills_read_complete = False
    elif case == 'error': snap.errors['persistence:polymarket'] = 'reader unavailable'
    elif case == 'position': snap.positions['polymarket'] = [object()]
    elif case == 'missing_position': snap.positions['kalshi'] = None
    elif case == 'missing_venue': guard.venues.pop('kalshi')
    else:
        store.con.execute('INSERT INTO lane_flags(seen_ts,flag,detail) VALUES(?,?,?)', (T0 + (260 if case == 'equal_timestamp' else 301), FLAG, 'new incident'))
        store.con.commit()
    guard._resolve_legacy_incidents(snap, GuardReport())
    assert unresolved_flag_rows(store.con, FLAG)


def test_append_only_revocation_stale_confirmation_and_corruption(tmp_path, proof):
    store, _, _, _, manifest, _ = world(tmp_path, proof)
    confirm(tmp_path, store, manifest)
    for query in (f'DELETE FROM {TABLE}', f"UPDATE {TABLE} SET record_sha256='bad'"):
        with pytest.raises(sqlite3.IntegrityError): store.con.execute(query)
        store.con.rollback()
    with pytest.raises(ValueError, match='stale'): confirm(tmp_path, store, manifest)
    revoked = dict(manifest, action='revoke', supersedes_id=1)
    assert confirm(tmp_path, store, revoked) == 2
    with pytest.raises(ValueError, match='revoked'): match_incident(store.con, 211)
    record = json.loads(store.con.execute(f'SELECT record_json FROM {TABLE} WHERE id=2').fetchone()[0])
    record['manifest']['action'] = 'acknowledge_legacy_lock_label'
    record['manifest']['supersedes_id'] = 2
    record['confirmation']['head'] = 2
    record['confirmation']['manifest_sha256'] = digest(record['manifest'])
    record['confirmation']['confirm_sha256'] = ''
    store.con.execute(f'INSERT INTO {TABLE}(flag_id,supersedes_id,record_json,record_sha256) VALUES(211,2,?,?)', (canonical(record), digest(record)))
    store.con.commit()
    with pytest.raises(ValueError, match='confirmation'): match_incident(store.con, 211)


def test_source_semantics_and_bytes_cannot_be_substituted(tmp_path, proof):
    *_, manifest, _ = world(tmp_path, proof)
    changed = deepcopy(manifest)
    changed['source_lines'] = [1, 3]
    with pytest.raises(ValueError, match='source excerpt'): prepare_manifest(changed)
    changed = deepcopy(manifest)
    changed['source']['content'] += 'forged'
    with pytest.raises(ValueError): prepare_manifest(changed)


def test_cli_prepare_dry_and_confirm_are_separate_exact_target_steps(tmp_path, proof, capsys):
    store, _, _, _, _, proposal = world(tmp_path, proof)
    input_path, output = tmp_path / 'proposal.json', tmp_path / 'prepared.json'
    input_path.write_text(json.dumps(proposal))
    args = ['--db', str(tmp_path / 't.sqlite'), '--manifest', str(input_path), '--operator', 'offline operator']
    assert main(args + ['--prepare', '--output', str(output)]) == 0
    assert main(args + ['--prepare', '--output', str(output)]) == 2
    assert not store.con.execute('SELECT 1 FROM sqlite_master WHERE name=?', (TABLE,)).fetchone()
    args[3] = str(output)
    capsys.readouterr()
    assert main(args) == 0
    plan = json.loads(capsys.readouterr().out)
    assert main(args + ['--confirm', '0' * 64]) == 2
    assert not store.con.execute('SELECT 1 FROM sqlite_master WHERE name=?', (TABLE,)).fetchone()
    assert main(args + ['--confirm', plan['confirm_sha256']]) == 0
    assert unresolved_flag_rows(store.con, FLAG)  # Confirmation never resolves by itself.
    assert match_incident(store.con, 211)


def test_idle_and_ack_revalidation_are_inside_resolution_writer_lock(tmp_path, proof):
    store, _, _, _, manifest, _ = world(tmp_path, proof)
    confirm(tmp_path, store, manifest)
    calls = []
    def verify():
        calls.append(store.con.in_transaction)
        if store.con.in_transaction:
            return False  # Simulate state changing after the preliminary read.
        return True
    assert not resolve_idle_incidents(store, now=T0 + 300, verify_pass=verify)
    assert calls == [False, True] and unresolved_flag_rows(store.con, FLAG)


def test_released_directional_history_is_not_current_inventory(tmp_path, proof):
    store, _, guard, _, manifest, _ = world(tmp_path, proof)
    confirm(tmp_path, store, manifest)
    store.con.execute("INSERT INTO executions(execution_id,opportunity_id,event_id,league,mode,state,started_utc,last_utc,quantity,released,unhedged) VALUES('historical','historical','historical','mlb','LIMITED_LIVE','RECONCILED',1,2,10.175439,1,10.175439)")
    store.con.commit()
    report = GuardReport()
    guard._resolve_legacy_incidents(complete_snapshot(), report)
    assert not unresolved_flag_rows(store.con, FLAG)
    assert store.con.execute("SELECT unhedged FROM executions WHERE execution_id='historical'").fetchone()[0] == 10.175439


def remnant_snapshot():
    rows = [dict(asset=str(100000 + i), proxyWallet='0x' + '1' * 40, conditionId='0x' + '2' * 64,
                 size=10.1666 if i == 0 else .0019, avgPrice=.35, currentValue=0, curPrice=0,
                 redeemable=True, mergeable=False, endDate='2026-09-16') for i in range(73)]
    snap = complete_snapshot()
    snap.positions['polymarket'] = [Position('polymarket', r['asset'], 'yes', r['size'], r['avgPrice'], snap.now) for r in rows]
    paging = dict(user='0x' + '1' * 40, sizeThreshold=0, limit=500, complete=True,
                  pages=[dict(offset=0, count=len(rows), sha256=sha(rows))])
    snap.position_evidence = {'polymarket': capture(rows, paging, observed_utc=snap.now)}
    return snap


def test_realistic_terminal_remnants_resolve_without_removing_physical_positions(tmp_path, proof):
    store, _, guard, _, manifest, _ = world(tmp_path, proof)
    confirm(tmp_path, store, manifest)
    snap = remnant_snapshot()
    before = deepcopy(snap.positions)
    report = GuardReport()
    guard._resolve_legacy_incidents(snap, report)
    assert not unresolved_flag_rows(store.con, FLAG)
    assert snap.positions == before and len(snap.positions['polymarket']) == 73
    marker = store.con.execute('SELECT detail FROM lane_flags WHERE flag=?', (FLAG + '_RESOLVED_EXACT',)).fetchone()[0]
    assert snap.position_evidence['polymarket']['source_sha256'] in marker


@pytest.mark.parametrize('change', ['revoke', 'corrupt', 'changed_flag'])
def test_resolved_legacy_ack_revoke_or_corruption_relatches_same_guard(tmp_path, proof, change):
    from nodes.execution.tests.test_dispositions import FakeKill
    store, _, guard, _, manifest, _ = world(tmp_path, proof)
    guard.kill = FakeKill()
    confirm(tmp_path, store, manifest)
    guard._resolve_legacy_incidents(complete_snapshot(), GuardReport())
    assert not unresolved_flag_rows(store.con, FLAG)
    guard.kill.calls.clear()
    if change == 'revoke':
        confirm(tmp_path, store, dict(manifest, action='revoke', supersedes_id=1))
    elif change == 'corrupt':
        row = store.con.execute(f'SELECT record_json FROM {TABLE} WHERE id=1').fetchone()[0]
        store.con.execute(f'INSERT INTO {TABLE}(flag_id,supersedes_id,record_json,record_sha256) VALUES(211,1,?,?)', (row, '0' * 64))
        store.con.commit()
    else:
        store.con.execute("UPDATE lane_flags SET detail='corrupt old flag evidence' WHERE id=211")
        store.con.commit()
    snap = complete_snapshot()
    snap.errors['positions:kalshi'] = 'read failed; static invalidity must still STOP'
    report = GuardReport()
    guard._resolve_legacy_incidents(snap, report)
    assert guard.kill.calls and unresolved_flag_rows(store.con, FLAG)
    assert any('LEGACY_INCIDENT_ACK_INVALID' in f for f in report.findings)
