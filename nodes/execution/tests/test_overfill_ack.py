"""L56 exact acknowledgement and legacy lock regressions; frozen local fixtures only."""
import base64
from copy import deepcopy
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from kernel.execution_protocol import Ack, FillRecord, OrderRequest
from kernel.schema import FillState
from nodes.execute.guard import GuardReport, GuardSnapshot
from nodes.execute.tests.test_guard import _world, _gea_row, T0, TOK
from nodes.execution.dispositions import canonical, digest, git_hash
from nodes.execution.overfill_ack import (append_confirmed, confirmation_plan, match_overfill_ack,
    prepare_manifest, prepare_from_database, settled_snapshot, main)
from nodes.reconcile.settle_executions import SETTLEMENTS_DDL
from nodes.risk.flags import FLAGS_DDL, flag_snapshot, unresolved_flag_rows
from nodes.risk.kill import KillSwitches
from nodes.risk.ledger import LEDGER_DDL


def source():
    content = '{"fixture":"settled exact order a1, redemption and authoritative cash"}'
    blob = content.encode()
    tree = b'100644 proof.json\0' + bytes.fromhex(git_hash('blob', blob))
    commit = f'tree {git_hash("tree", tree)}\n\nfrozen offline fixture\n'.encode()
    return dict(git_commit=git_hash('commit', commit), ref='proof.json', content=content,
                sha256=hashlib.sha256(blob).hexdigest(), commit_object=base64.b64encode(commit).decode(),
                tree_objects=[base64.b64encode(tree).decode()])


def world(tmp_path):
    kill = KillSwitches(tmp_path / 'kill', enforce_volume=False)
    store, journal, records, guard = _world(tmp_path, venues={'polymarket': object(), 'kalshi': object()}, kill=kill)
    ex = _gea_row(journal, records)
    journal.record(Ack('polymarket', 'a1', 'pm-order', FillState.FILLED, 10.166667, .354, .11626, 'confirmed', T0 + 200), kind='ack')
    con = journal.store.con
    con.executescript(SETTLEMENTS_DDL + LEDGER_DDL + FLAGS_DDL)
    con.execute("UPDATE executions SET state='RECONCILED',released=1,reservation_id='reservation',first_filled=10.166667,first_avg_price=.354,unhedged=0")
    con.execute("INSERT INTO capital_reservations(reservation_id, event_id, league, per_venue_json, opportunity_id, created_utc, released_utc, release_reason) VALUES('reservation',?,?,?, ?,?,?,?)", (ex.event_id, ex.league, '{"polymarket":3.72}', ex.opportunity_id, T0, T0 + 250, 'settled winners'))
    leg = dict(venue='polymarket', client_order_id='a1', outcome_id=TOK, side='buy_yes', state='FILLED',
               contracts=10.166667, price=.354, fee_usd=.11626, final=True)
    con.execute('INSERT INTO execution_settlements(execution_id,opportunity_id,event_id,league,mode,settled_ts,realized_usd,released,legs_json) VALUES(?,?,?,?,?,?,?,?,?)',
                (ex.execution_id, ex.opportunity_id, ex.event_id, ex.league, ex.mode, T0 + 250, 6.44, 1, json.dumps([leg])))
    con.execute("INSERT INTO lane_flags(seen_ts,flag,detail) VALUES(?, 'ORDER_OVERFILL','polymarket a1: requested 10, venue filled 10.1667')", (T0 + 201,))
    con.commit()
    flag = flag_snapshot(con.execute('SELECT id,seen_ts,flag,detail FROM lane_flags').fetchone())
    manifest = prepare_manifest({'version': 1, 'acknowledgements': [dict(client_order_id='a1', action='acknowledge_settled_overfill',
        snapshot=settled_snapshot(con, 'a1'), sources=[source()], reason='Operator reviewed exact settled historical overfill evidence.', supersedes_id=None, flag_evidence=[flag])]})
    return store, journal, guard, kill, manifest


def confirm(tmp_path, journal, manifest):
    db = tmp_path / 't.sqlite'
    plan = confirmation_plan(journal.store.con, db, manifest, 'fixture operator')
    return append_confirmed(journal.store.con, db, manifest, 'fixture operator', plan['confirm_sha256'], now=T0 + 270)


def complete_snapshot(**kwargs):
    return GuardSnapshot(now=T0 + 300, positions={'polymarket': [], 'kalshi': []}, fills_read_complete=True, **kwargs)


def test_exact_confirmation_preserves_all_accounting_and_only_resolves_approved_flag(tmp_path):
    store, journal, guard, kill, manifest = world(tmp_path)
    con = journal.store.con
    before = {t: con.execute(f'SELECT * FROM {t}').fetchall() for t in ('orders', 'executions', 'execution_settlements', 'capital_reservations')}
    kill.latch('live', 'historical STOP must remain')
    assert confirm(tmp_path, journal, manifest) == [1]
    assert match_overfill_ack(con, 'a1')['id'] == 1
    report = guard.apply(complete_snapshot())
    assert any('HISTORICAL_OVERFILL_ACKNOWLEDGED' in x for x in report.findings)
    assert any('ORDER_OVERFILL_RESOLVED' in x for x in report.findings)
    assert not unresolved_flag_rows(con, 'ORDER_OVERFILL')
    assert kill.active(live=True) == ['live']
    assert before == {t: con.execute(f'SELECT * FROM {t}').fetchall() for t in before}
    assert con.execute("SELECT COUNT(*) FROM lane_flags WHERE flag='ORDER_OVERFILL'").fetchone()[0] == 1


def test_exact_ack_closes_only_later_duplicate_findings_with_the_same_economic_identity(tmp_path):
    store, journal, guard, _, manifest = world(tmp_path)
    confirm(tmp_path, journal, manifest)
    guard.apply(complete_snapshot())
    con = store.con
    detail = manifest['acknowledgements'][0]['flag_evidence'][0]['detail']
    con.execute("INSERT INTO lane_flags(seen_ts,flag,detail) VALUES(?, 'ORDER_OVERFILL', ?)", (T0 + 301, detail))
    con.execute("INSERT INTO lane_flags(seen_ts,flag,detail) VALUES(?, 'ORDER_OVERFILL', ?)", (T0 + 302, detail))
    con.commit()
    report = guard.apply(complete_snapshot())
    assert any('ORDER_OVERFILL_RESOLVED' in finding for finding in report.findings)
    assert not unresolved_flag_rows(con, 'ORDER_OVERFILL')


def _add_bounded_taker_residual(journal, *, flag=False):
    con = journal.store.con
    journal.pending(OrderRequest('polymarket', TOK, TOK, 'buy_yes', .36, 10, 'ioc',
                                 'bounded', 'bounded-opportunity'),
                    mode='LIMITED_LIVE', now=T0 + 280)
    journal.record(Ack('polymarket', 'bounded', 'bounded-order', FillState.FILLED,
                       10.2, .35, 0, 'confirmed', T0 + 281), kind='ack')
    con.execute("CREATE TABLE IF NOT EXISTS pm_bounded_taker_orders("
                "client_order_id TEXT PRIMARY KEY,max_accepted_excess TEXT)")
    con.execute("INSERT INTO pm_bounded_taker_orders VALUES('bounded','1')")
    if flag:
        con.execute("INSERT INTO lane_flags(seen_ts,flag,detail) VALUES(?, 'ORDER_OVERFILL', ?)",
                    (T0 + 282, 'polymarket bounded: requested 10, venue filled 10.2'))
    con.commit()


def test_bounded_taker_residual_does_not_block_other_exact_overfill_resolution(tmp_path):
    _, journal, guard, _, manifest = world(tmp_path)
    confirm(tmp_path, journal, manifest)
    _add_bounded_taker_residual(journal)
    report = guard.apply(complete_snapshot())
    assert any('BOUNDED_TAKER_RESIDUAL_ACCEPTED' in finding for finding in report.findings)
    assert any('ORDER_OVERFILL_RESOLVED' in finding for finding in report.findings)
    assert not unresolved_flag_rows(journal.store.con, 'ORDER_OVERFILL')


def test_bounded_taker_exemption_never_closes_its_own_unacknowledged_flag(tmp_path):
    _, journal, guard, _, manifest = world(tmp_path)
    confirm(tmp_path, journal, manifest)
    _add_bounded_taker_residual(journal, flag=True)
    guard._resolve_acknowledged_overfills(complete_snapshot(), GuardReport())
    rows = unresolved_flag_rows(journal.store.con, 'ORDER_OVERFILL')
    assert {row[3] for row in rows} == {
        'polymarket a1: requested 10, venue filled 10.1667',
        'polymarket bounded: requested 10, venue filled 10.2',
    }


def test_exact_ack_never_closes_a_later_different_overfill_finding(tmp_path):
    store, journal, guard, _, manifest = world(tmp_path)
    confirm(tmp_path, journal, manifest)
    guard.apply(complete_snapshot())
    store.con.execute("INSERT INTO lane_flags(seen_ts,flag,detail) VALUES(?, 'ORDER_OVERFILL', ?)",
                      (T0 + 301, 'polymarket a1: requested 10, venue filled 10.2'))
    store.con.commit()
    guard._resolve_acknowledged_overfills(complete_snapshot(), GuardReport())
    assert unresolved_flag_rows(store.con, 'ORDER_OVERFILL')


def test_additive_order_ownership_migration_does_not_invalidate_version_one_evidence(tmp_path):
    _, journal, _, _, manifest = world(tmp_path)
    confirm(tmp_path, journal, manifest)
    con = journal.store.con
    before = settled_snapshot(con, 'a1')
    assert 'execution_id' not in before['order']
    con.execute("UPDATE orders SET execution_id='789ad9b2' WHERE client_order_id='a1'")
    con.commit()
    assert settled_snapshot(con, 'a1') == before
    assert match_overfill_ack(con, 'a1')['id'] == 1


def test_additive_order_owner_conflict_invalidates_version_one_evidence(tmp_path):
    _, journal, _, _, manifest = world(tmp_path)
    confirm(tmp_path, journal, manifest)
    con = journal.store.con
    con.execute("UPDATE orders SET execution_id='a-different-execution' WHERE client_order_id='a1'")
    con.commit()
    with pytest.raises(ValueError, match='owner contradicts'):
        match_overfill_ack(con, 'a1')


def test_additive_reverse_owner_conflict_invalidates_version_one_evidence(tmp_path):
    _, journal, _, _, manifest = world(tmp_path)
    confirm(tmp_path, journal, manifest)
    con = journal.store.con
    journal.pending(OrderRequest('kalshi', 'extra', 'extra', 'buy_yes', .4, 1, 'ioc', 'extra',
                                 manifest['acknowledgements'][0]['snapshot']['execution']['opportunity_id'],
                                 execution_id='789ad9b2'), mode='LIMITED_LIVE', now=T0 + 290)
    with pytest.raises(ValueError, match='claims order absent'):
        match_overfill_ack(con, 'a1')


@pytest.mark.parametrize('change', [
    "UPDATE orders SET filled_contracts=10.2", "UPDATE orders SET contracts=10.2",
    "UPDATE orders SET open=1", "UPDATE orders SET settlement_pending=1",
    "UPDATE orders SET venue_order_id='different'", "UPDATE orders SET avg_price=.355",
    "UPDATE orders SET fee_usd=.117", "UPDATE orders SET mode='PAPER'",
    "UPDATE executions SET state='HEDGED'", "UPDATE executions SET released=0",
    "UPDATE capital_reservations SET released_utc=NULL", "DELETE FROM capital_reservations",
    "UPDATE execution_settlements SET realized_usd=6.45", "UPDATE execution_settlements SET released=0",
    "UPDATE lane_flags SET detail='different incident' WHERE id=1", "DELETE FROM orders",
])
def test_any_changed_bound_field_remains_overfill_stop_even_when_quantity_no_longer_over(tmp_path, change):
    _, journal, guard, kill, manifest = world(tmp_path)
    confirm(tmp_path, journal, manifest)
    journal.store.con.execute(change)
    journal.store.con.commit()
    report = GuardReport()
    guard._detect_order_overfills(complete_snapshot(), report)
    assert kill.active(live=True)
    assert any('OVERFILL_ACK_INVALID' in x for x in report.findings)
    assert any(x.startswith('ORDER_OVERFILL ') for x in report.findings)


@pytest.mark.parametrize('case', ['incomplete', 'error', 'missing_venue', 'missing_positions', 'new_flag', 'same_timestamp', 'second_overfill'])
def test_incomplete_or_unacknowledged_incident_never_resolves(tmp_path, case):
    _, journal, guard, kill, manifest = world(tmp_path)
    confirm(tmp_path, journal, manifest)
    snap = complete_snapshot()
    con = journal.store.con
    if case == 'incomplete': snap.fills_read_complete = False
    elif case == 'error': snap.errors['persistence:polymarket'] = 'database is locked'
    elif case == 'missing_venue': guard.venues = {'polymarket': object()}
    elif case == 'missing_positions': snap.positions['kalshi'] = None
    elif case in {'new_flag', 'same_timestamp'}:
        con.execute("INSERT INTO lane_flags(seen_ts,flag,detail) VALUES(?, 'ORDER_OVERFILL', 'unknown incident')", (T0 + (300 if case == 'new_flag' else 201),))
    else:
        journal.pending(OrderRequest('polymarket', TOK, TOK, 'buy_yes', .36, 10, 'ioc', 'other', 'other'), mode='LIMITED_LIVE', now=T0)
        journal.record(Ack('polymarket', 'other', 'other-order', FillState.FILLED, 11, .36, .1, 'confirmed', T0 + 200), kind='ack')
    con.commit()
    guard._resolve_acknowledged_overfills(snap, GuardReport())
    assert unresolved_flag_rows(con, 'ORDER_OVERFILL')
    assert not con.execute("SELECT 1 FROM lane_flags WHERE flag LIKE 'ORDER_OVERFILL_RESOLVED%'").fetchone()


def test_no_blanket_released_skip(tmp_path):
    _, journal, guard, kill, _ = world(tmp_path)
    guard._detect_order_overfills(complete_snapshot(), GuardReport())
    assert kill.active(live=True)


def test_unrelated_no_order_execution_and_exact_zero_fill_hedge_are_allowed(tmp_path):
    _, journal, _, _, manifest = world(tmp_path)
    con = journal.store.con
    con.execute("INSERT INTO executions(execution_id,opportunity_id,event_id,league,mode,state,started_utc,last_utc,quantity) VALUES('empty','other','other','nfl','LIMITED_LIVE','DETECTED',1,1,10)")
    journal.pending(OrderRequest('kalshi', 'ks', 'ks', 'buy_yes', .4, 10, 'ioc', 'zero', manifest['acknowledgements'][0]['snapshot']['execution']['opportunity_id']), mode='LIMITED_LIVE', now=T0)
    journal.record(Ack('kalshi', 'zero', 'ks-order', FillState.REJECTED, 0, None, None, 'rejected', T0 + 200), kind='ack')
    con.execute("UPDATE executions SET hedge_client_ids='[\"zero\"]' WHERE execution_id='789ad9b2'")
    legs = json.loads(con.execute('SELECT legs_json FROM execution_settlements').fetchone()[0])
    legs.append(dict(client_order_id='zero', venue='kalshi', outcome_id='ks', side='buy_yes', state='REJECTED', contracts=0, price=0, fee_usd=0, final=True))
    con.execute('UPDATE execution_settlements SET legs_json=?', (json.dumps(legs),))
    con.commit()
    assert len(settled_snapshot(con, 'a1')['orders']) == 2
    con.execute("UPDATE orders SET filled_contracts=1 WHERE client_order_id='zero'")
    with pytest.raises((ValueError, ArithmeticError)):
        settled_snapshot(con, 'a1')


@pytest.mark.parametrize('field,value', [('id', True), ('id', -1), ('id', 0), ('seen_ts', float('nan')), ('detail', 'a10: unrelated'), ('flag', 'ORPHAN_FILL')])
def test_flag_identity_validation_is_strict(tmp_path, field, value):
    *_, manifest = world(tmp_path)
    manifest['acknowledgements'][0]['flag_evidence'][0][field] = value
    with pytest.raises((ValueError, ArithmeticError)):
        prepare_manifest(manifest)


def test_append_only_revocation_and_hash_consistent_confirmation_corruption(tmp_path):
    _, journal, guard, kill, manifest = world(tmp_path)
    confirm(tmp_path, journal, manifest)
    con = journal.store.con
    for sql in ('DELETE FROM historical_order_overfill_acknowledgements', "UPDATE historical_order_overfill_acknowledgements SET record_sha256='bad'"):
        with pytest.raises(sqlite3.IntegrityError): con.execute(sql)
        con.rollback()
    revoked = deepcopy(manifest)
    revoked['acknowledgements'][0].update(action='revoke', supersedes_id=1)
    confirm(tmp_path, journal, revoked)
    guard._detect_order_overfills(complete_snapshot(), GuardReport())
    assert kill.active(live=True)
    record = json.loads(con.execute('SELECT record_json FROM historical_order_overfill_acknowledgements WHERE id=2').fetchone()[0])
    record['confirmation']['confirm_sha256'] = '0' * 64
    con.execute('INSERT INTO historical_order_overfill_acknowledgements(client_order_id,supersedes_id,record_json,record_sha256) VALUES(?,?,?,?)', ('a1', 2, canonical(record), digest(record)))
    con.commit()
    with pytest.raises(ValueError): match_overfill_ack(con, 'a1')


def test_cli_dry_run_creates_nothing_and_exact_confirm_is_required(tmp_path, capsys):
    _, journal, _, _, manifest = world(tmp_path)
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest))
    args = ['--db', str(tmp_path / 't.sqlite'), '--manifest', str(path), '--operator', 'fixture operator']
    assert main(args) == 0
    dry = json.loads(capsys.readouterr().out)
    assert not journal.store.con.execute("SELECT 1 FROM sqlite_master WHERE name='historical_order_overfill_acknowledgements'").fetchone()
    assert main(args + ['--confirm', '0' * 64]) == 2
    capsys.readouterr()
    assert main(args + ['--confirm', dry['confirm_sha256']]) == 0
    capsys.readouterr()
    assert match_overfill_ack(journal.store.con, 'a1')


@pytest.mark.parametrize('post_only', [False, True])
def test_fallback_lock_labels_only_genuine_post_only_orders(tmp_path, monkeypatch, post_only):
    store, journal, guard, kill, _ = world(tmp_path)
    con = journal.store.con
    calls = []
    guard.venues = {'polymarket': SimpleNamespace(_persistence_failure=lambda *args: calls.append(args))}
    if post_only:
        con.execute('CREATE TABLE pm_post_only_orders(client_order_id TEXT,terminal_proved INTEGER)')
        con.execute("INSERT INTO pm_post_only_orders VALUES('a1',0)")
        con.commit()
    def locked(*args, **kwargs):
        raise sqlite3.OperationalError('database is locked')
    monkeypatch.setattr(journal, 'record', locked)
    fill = FillRecord('polymarket', 'pm-order', 'late', 11, .36, .1, True, T0 + 299, False, market_id=TOK, side='buy_yes')
    snap = complete_snapshot(fills=[fill])
    report = GuardReport()
    guard._preserve_unpersisted_fills(snap, report)
    assert snap.errors['persistence:guard:a1']
    assert bool(calls) is post_only
    if not post_only:
        assert kill.active(live=True)
        assert unresolved_flag_rows(con, 'ORDER_PERSISTENCE_FAILED')
        assert not unresolved_flag_rows(con, 'POST_ONLY_PERSISTENCE_FAILED')


def proposal(manifest):
    return {'version': 1, 'acknowledgements': [dict(client_order_id=e['client_order_id'], sources=e['sources'], reason=e['reason'],
            supersedes_id=e['supersedes_id'], flag_ids=[f['id'] for f in e['flag_evidence']]) for e in manifest['acknowledgements']]}


def test_prepare_cli_exports_only_exact_candidates_without_mutation_or_overwrite(tmp_path, capsys):
    _, journal, _, _, manifest = world(tmp_path)
    input_path, output = tmp_path / 'request.json', tmp_path / 'prepared.json'
    input_path.write_text(json.dumps(proposal(manifest)))
    before = journal.store.con.iterdump()
    before = '\n'.join(before)
    args = ['--db', str(tmp_path / 't.sqlite'), '--manifest', str(input_path), '--operator', 'fixture operator', '--prepare', '--output', str(output)]
    assert main(args) == 0
    capsys.readouterr()
    assert json.loads(output.read_text()) == manifest
    assert '\n'.join(journal.store.con.iterdump()) == before
    assert main(args) == 2
    assert 'FileExistsError' in capsys.readouterr().out
    assert json.loads(output.read_text()) == manifest


@pytest.mark.parametrize('case', ['missing_candidate', 'extra_candidate', 'unbound_flag', 'bad_source', 'open_order', 'duplicate_flag'])
def test_prepare_refuses_unexpected_set_source_state_or_flags(tmp_path, case):
    _, journal, _, _, manifest = world(tmp_path)
    raw = proposal(manifest)
    con = journal.store.con
    if case == 'missing_candidate': raw['acknowledgements'] = []
    elif case == 'extra_candidate': raw['acknowledgements'].append(dict(raw['acknowledgements'][0], client_order_id='unknown'))
    elif case == 'unbound_flag': raw['acknowledgements'][0]['flag_ids'] = []
    elif case == 'bad_source': raw['acknowledgements'][0]['sources'][0]['content'] += 'changed'
    elif case == 'open_order': con.execute('UPDATE orders SET open=1')
    else: raw['acknowledgements'][0]['flag_ids'] = [1, 1]
    with pytest.raises(ValueError): prepare_from_database(con, raw)


@pytest.mark.parametrize('case', ['content', 'commit', 'confirmation', 'database'])
def test_hash_consistent_corrupt_source_or_confirmation_still_relatches(tmp_path, case):
    _, journal, guard, kill, manifest = world(tmp_path)
    confirm(tmp_path, journal, manifest)
    con = journal.store.con
    record = json.loads(con.execute('SELECT record_json FROM historical_order_overfill_acknowledgements').fetchone()[0])
    entry = record['manifest']['acknowledgements'][0]
    entry['supersedes_id'] = 1
    record['confirmation']['heads'] = [1]
    if case == 'content':
        entry['sources'][0]['content'] += 'changed'
        entry['sources'][0]['sha256'] = hashlib.sha256(entry['sources'][0]['content'].encode()).hexdigest()
    elif case == 'commit': entry['sources'][0]['git_commit'] = '0' * 40
    elif case == 'database': record['confirmation']['database'] = '/wrong/database'
    record['confirmation']['manifest_sha256'] = digest(record['manifest'])
    record['confirmation']['confirm_sha256'] = digest({k: v for k, v in record['confirmation'].items() if k != 'confirm_sha256'})
    if case == 'confirmation': record['confirmation']['confirm_sha256'] = '0' * 64
    con.execute('INSERT INTO historical_order_overfill_acknowledgements(client_order_id,supersedes_id,record_json,record_sha256) VALUES(?,?,?,?)', ('a1', 1, canonical(record), digest(record)))
    con.commit()
    rep = GuardReport()
    guard._detect_order_overfills(complete_snapshot(), rep)
    assert kill.active(live=True) and any('OVERFILL_ACK_INVALID' in x for x in rep.findings)


def test_prepare_then_order_change_refuses_confirmation(tmp_path):
    _, journal, _, _, manifest = world(tmp_path)
    plan = confirmation_plan(journal.store.con, tmp_path / 't.sqlite', manifest, 'fixture operator')
    journal.store.con.execute('UPDATE orders SET filled_contracts=11')
    journal.store.con.commit()
    with pytest.raises(ValueError):
        append_confirmed(journal.store.con, tmp_path / 't.sqlite', manifest, 'fixture operator', plan['confirm_sha256'], now=T0 + 270)


def test_settled_snapshot_change_at_resolution_lock_is_not_accepted_or_left_unlatched(tmp_path, monkeypatch):
    _, journal, guard, kill, manifest = world(tmp_path)
    confirm(tmp_path, journal, manifest)
    from nodes.risk.flags import resolve_exact_flags
    def raced(*args, **kwargs):
        journal.store.con.execute('UPDATE orders SET filled_contracts=11')
        journal.store.con.commit()
        return resolve_exact_flags(*args, **kwargs)
    monkeypatch.setattr('nodes.execute.guard.resolve_exact_flags', raced)
    rep = GuardReport()
    guard._resolve_acknowledged_overfills(complete_snapshot(), rep)
    assert kill.active(live=True)
    assert unresolved_flag_rows(journal.store.con, 'ORDER_OVERFILL')
    assert any('OVERFILL_ACK_INVALID' in f for f in rep.findings)
