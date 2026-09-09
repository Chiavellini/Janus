"""L56 exact historical ownership acknowledgements; no venue calls or live writes."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from kernel.execution_protocol import FillRecord
from nodes.execution.dispositions import (DDL, append_confirmed, canonical, confirmation_plan,
    digest, fill_identity, main, match_disposition, prepare_manifest, verify_source)
from nodes.execute.guard import GuardSnapshot
from nodes.execute.tests.test_guard import _world
from nodes.risk.kill import KillSwitches

ROOT = Path(__file__).resolve().parents[3]
PROPOSAL = ROOT / 'research/exec/2026-09-09_historical-proof-dispositions/prepared.json'


@pytest.fixture(scope='module')
def manifest():
    return prepare_manifest(json.loads(PROPOSAL.read_text()), repo=ROOT)


def fills(manifest):
    return [FillRecord(**{k: float(v) if k in {'contracts', 'price', 'fee_usd', 'ts'} else v
                         for k, v in entry['fill'].items()}) for entry in manifest['dispositions']]


def confirm(con, db, manifest):
    con.executescript(DDL)
    con.execute('BEGIN IMMEDIATE')
    result = append_confirmed(con, db, manifest, confirmation_plan(con, db, manifest)['confirm_sha256'], now=1000)
    con.commit()
    return result


def world(tmp_path, manifest):
    kill = KillSwitches(tmp_path / 'kill', enforce_volume=False)
    store, journal, records, guard = _world(tmp_path, venues={}, kill=kill)
    confirm(journal.store.con, tmp_path / 't.sqlite', manifest)
    return journal, guard, kill


def test_exact_disposition_reports_only_historical_orphans_and_preserves_other_stop(tmp_path, manifest):
    journal, guard, kill = world(tmp_path, manifest)
    historical = fills(manifest)
    before = journal.store.con.execute('SELECT * FROM orders').fetchall()
    report = guard.apply(GuardSnapshot(now=1788940800, fills=historical))
    assert not report.orphans and len(report.dispositions) == 2
    assert not kill.active(live=True)
    assert sum('EXTERNAL_FILL_DISPOSITION' in f for f in report.findings) == 2
    assert historical[1].final is False
    assert journal.store.con.execute('SELECT * FROM orders').fetchall() == before
    stranger = replace(historical[0], fill_id='unregistered')
    report = guard.apply(GuardSnapshot(now=1788940801, fills=historical + [stranger]))
    assert report.orphans == [stranger] and kill.active(live=True) == ['live']


@pytest.mark.parametrize('field,value', [('venue', 'other'), ('fill_id', 'changed'), ('venue_order_id', 'changed'),
    ('contracts', 5.131578), ('price', .37999994930000003), ('fee_usd', .06044000017095391),
    ('ts', 1788756163.000001), ('is_taker', False), ('final', True), ('market_id', 'changed'), ('side', 'sell_yes')])
def test_every_changed_field_is_still_orphan_stop(tmp_path, manifest, field, value):
    _, guard, kill = world(tmp_path, manifest)
    changed = replace(fills(manifest)[1], **{field: value})
    report = guard.apply(GuardSnapshot(now=1788940800, fills=[changed]))
    assert report.orphans == [changed] and kill.active(live=True) == ['live']


@pytest.mark.parametrize('field,value', [('final', 1), ('final', 'false'), ('is_taker', 0), ('contracts', float('nan')),
                                       ('price', float('inf')), ('fee_usd', '-Infinity'), ('ts', True)])
def test_invalid_numbers_and_boolean_coercions_are_rejected(manifest, field, value):
    raw = dict(manifest['dispositions'][0]['fill'], **{field: value})
    with pytest.raises((ValueError, ArithmeticError)):
        fill_identity(raw)


def test_full_precision_and_exact_field_set(manifest):
    raw = dict(manifest['dispositions'][1]['fill'], price='0.38000008535243746', fee_usd='0.06039999999999979')
    identity = fill_identity(raw)
    assert identity['price'] == '0.38000008535243746' and identity['fee_usd'] == '0.06039999999999979'
    with pytest.raises(ValueError): fill_identity(dict(raw, ignored=True))
    raw.pop('ts')
    with pytest.raises(ValueError): fill_identity(raw)


def test_source_bytes_are_cryptographically_bound_to_commit_ref(manifest):
    source = deepcopy(manifest['dispositions'][0]['source'])
    verify_source(source)
    source['content'] += '\nforged replacement\n'
    source['sha256'] = hashlib.sha256(source['content'].encode()).hexdigest()
    with pytest.raises(ValueError, match='belong to commit'): verify_source(source)
    source = deepcopy(manifest['dispositions'][0]['source'])
    source['git_commit'] = '0' * 40
    with pytest.raises(ValueError, match='commit object'): verify_source(source)


def test_append_only_revocation_and_stale_correction_race(tmp_path, manifest):
    journal, guard, kill = world(tmp_path, manifest)
    con = journal.store.con
    original = con.execute('SELECT * FROM external_fill_dispositions').fetchall()
    for statement in ('UPDATE external_fill_dispositions SET record_sha256="bad"', 'DELETE FROM external_fill_dispositions'):
        with pytest.raises(sqlite3.IntegrityError): con.execute(statement)
        con.rollback()
    revoked = deepcopy(manifest)
    revoked['dispositions'] = [dict(manifest['dispositions'][0], action='revoked', supersedes_id=1)]
    old_confirmation = confirmation_plan(con, tmp_path / 't.sqlite', revoked)['confirm_sha256']
    confirm(con, tmp_path / 't.sqlite', revoked)
    with pytest.raises(ValueError, match='stale'):
        append_confirmed(con, tmp_path / 't.sqlite', revoked, old_confirmation, now=1001)
    report = guard.apply(GuardSnapshot(now=1788940800, fills=[fills(manifest)[0]]))
    assert report.orphans and kill.active(live=True)
    assert con.execute('SELECT * FROM external_fill_dispositions WHERE id<=2').fetchall() == original


def test_corrupt_record_is_not_accepted_as_an_orphan_exemption(tmp_path, manifest):
    journal, guard, kill = world(tmp_path, manifest)
    con = journal.store.con
    row = con.execute('SELECT record_json FROM external_fill_dispositions WHERE id=1').fetchone()[0]
    con.execute('INSERT INTO external_fill_dispositions(venue,fill_id,supersedes_id,record_json,record_sha256) VALUES(?,?,?,?,?)',
                ('kalshi', fills(manifest)[0].fill_id, 1, row, '0' * 64))
    con.commit()
    report = guard.apply(GuardSnapshot(now=1788940800, fills=[fills(manifest)[0]]))
    assert report.orphans and kill.active(live=True)
    assert any('DISPOSITION_INVALID' in f for f in report.findings)


@pytest.mark.parametrize('corruption', ['empty_confirmation', 'changed_confirmation', 'changed_membership', 'changed_target'])
def test_hash_consistent_unconfirmed_or_wrong_envelope_never_exempts(tmp_path, manifest, corruption):
    journal, guard, kill = world(tmp_path, manifest)
    con = journal.store.con
    record = json.loads(con.execute('SELECT record_json FROM external_fill_dispositions WHERE id=1').fetchone()[0])
    if corruption == 'empty_confirmation': record['confirmed_sha256'] = ''
    elif corruption == 'changed_confirmation': record['confirmed_sha256'] = '0' * 64
    elif corruption == 'changed_membership': record['entry']['reason'] += ' altered without new confirmation'
    else:
        record['confirmation']['database'] = '/different/database.sqlite'
        record['confirmed_sha256'] = digest(record['confirmation'])
    record['entry']['supersedes_id'] = 1
    con.execute('INSERT INTO external_fill_dispositions(venue,fill_id,supersedes_id,record_json,record_sha256) VALUES(?,?,?,?,?)',
                ('kalshi', fills(manifest)[0].fill_id, 1, canonical(record), digest(record)))
    con.commit()
    report = guard.apply(GuardSnapshot(now=1788940800, fills=[fills(manifest)[0]]))
    assert report.orphans and kill.active(live=True)
    assert any('DISPOSITION_INVALID' in f for f in report.findings)


def test_cli_dry_confirm_is_target_bound_and_archive_only(tmp_path, manifest, capsys, monkeypatch):
    db = tmp_path / 't.sqlite'
    sqlite3.connect(db).close()
    proposal = tmp_path / 'prepared.json'
    proposal.write_text(json.dumps(manifest))
    monkeypatch.setattr('nodes.execution.dispositions._git', lambda *a: pytest.fail('prepared source needs no Git runtime'))
    args = ['--db', str(db), '--manifest', str(proposal)]
    assert main(args) == 0
    dry = json.loads(capsys.readouterr().out)
    with sqlite3.connect(db) as con:
        assert not con.execute('SELECT name FROM sqlite_master').fetchall()
    assert main(args + ['--confirm', '0' * 64]) == 2
    capsys.readouterr()
    assert main(args + ['--confirm', dry['confirm_sha256']]) == 0
    confirmed = json.loads(capsys.readouterr().out)
    assert confirmed['appended_ids'] == [1, 2]
    with sqlite3.connect(db) as con:
        assert match_disposition(con, fills(manifest)[0])['id'] == 1
    assert main(args + ['--confirm', dry['confirm_sha256']]) == 2


def seed_flags(journal, manifest):
    from nodes.risk.flags import FLAGS_DDL
    journal.store.ensure_ddl(FLAGS_DDL)
    for entry in manifest['dispositions']:
        for row in entry['orphan_flags']:
            journal.store.con.execute('INSERT INTO lane_flags(id,seen_ts,flag,detail) VALUES(?,?,?,?)',
                                      (row['id'], float(row['seen_ts']), row['flag'], row['detail']))
    journal.store.con.commit()


@pytest.mark.parametrize('block', [None, 'unknown', 'incomplete', 'missing_positions', 'missing_adapter', 'error', 'changed_fill'])
def test_exact_orphan_resolution_requires_complete_pass_and_full_incident_coverage(tmp_path, manifest, block):
    from nodes.risk.flags import raise_flag, recent_flags
    journal, guard, kill = world(tmp_path, manifest)
    seed_flags(journal, manifest)
    guard.venues = {'kalshi': object(), 'polymarket': object()}
    now = 1788973600
    snap = GuardSnapshot(now=now, fills=fills(manifest), fills_read_complete=True,
                         positions={'kalshi': [], 'polymarket': []})
    if block == 'unknown': raise_flag(journal.store, 'ORPHAN_FILL', 'older unknown fill outside current cursor', now=1788973500)
    if block == 'incomplete': snap.fills_read_complete = False
    if block == 'missing_positions': snap.positions['polymarket'] = None
    if block == 'missing_adapter': guard.venues.pop('polymarket')
    if block == 'error': snap.errors['fills'] = 'incomplete read'
    if block == 'changed_fill': snap.fills[1] = replace(snap.fills[1], contracts=6)
    kill.latch('live', 'preexisting live STOP is not cleared by ownership attribution')
    report = guard.apply(snap)
    remaining = recent_flags(tmp_path / 't.sqlite', 'ORPHAN_FILL', now=now)
    assert bool(remaining) is (block is not None)
    assert bool(any('ORPHAN_FILL_RESOLVED_EXACT' in f for f in report.findings)) is (block is None)
    assert kill.active(live=True) == ['live']
    if block is None:
        # A later incident at the exact same wall clock must not disappear behind a marker.
        raise_flag(journal.store, 'ORPHAN_FILL', 'new unacknowledged fill at same timestamp', now=now)
        assert recent_flags(tmp_path / 't.sqlite', 'ORPHAN_FILL', now=now) == [(now, 'new unacknowledged fill at same timestamp')]


def test_revoked_disposition_never_resolves_old_incident_flags(tmp_path, manifest):
    from nodes.risk.flags import recent_flags
    journal, guard, _ = world(tmp_path, manifest)
    seed_flags(journal, manifest)
    revoked = {'version': 1, 'dispositions': [dict(manifest['dispositions'][0], action='revoked', supersedes_id=1)]}
    confirm(journal.store.con, tmp_path / 't.sqlite', revoked)
    guard.venues = {'kalshi': object(), 'polymarket': object()}
    guard.apply(GuardSnapshot(now=1788973600, fills=fills(manifest), fills_read_complete=True, positions={'kalshi': [], 'polymarket': []}))
    assert recent_flags(tmp_path / 't.sqlite', 'ORPHAN_FILL', now=1788973600)


class FakeKill:
    def __init__(self):
        self.calls = []
        self.fail = False

    def latch(self, name, reason):
        if self.fail:
            raise OSError('synthetic kill-channel failure')
        self.calls.append((name, reason))


@pytest.mark.parametrize('change', ['revoke', 'changed_fill', 'corrupt'])
def test_same_guard_reorphan_after_acceptance_relatches_and_flags(tmp_path, manifest, change):
    kill = FakeKill()
    _, journal, _, guard = _world(tmp_path, venues={}, kill=kill)
    fill = fills(manifest)[0]
    assert guard.apply(GuardSnapshot(now=1788973600, fills=[fill])).orphans == [fill]
    confirm(journal.store.con, tmp_path / 't.sqlite', manifest)
    accepted = guard.apply(GuardSnapshot(now=1788973601, fills=[fill]))
    assert not accepted.orphans and accepted.dispositions
    kill.calls.clear()  # Operator reset simulation: never touches a live kill file.
    if change == 'revoke':
        revoked = {'version': 1, 'dispositions': [dict(manifest['dispositions'][0], action='revoked', supersedes_id=1)]}
        confirm(journal.store.con, tmp_path / 't.sqlite', revoked)
    elif change == 'changed_fill':
        fill = replace(fill, contracts=fill.contracts + 1)
    else:
        row = journal.store.con.execute('SELECT record_json FROM external_fill_dispositions WHERE id=1').fetchone()[0]
        journal.store.con.execute('INSERT INTO external_fill_dispositions(venue,fill_id,supersedes_id,record_json,record_sha256) VALUES(?,?,?,?,?)',
                                  (fill.venue, fill.fill_id, 1, row, '0' * 64))
        journal.store.con.commit()
    report = guard.apply(GuardSnapshot(now=1788973602, fills=[fill]))
    assert report.orphans == [fill]
    assert kill.calls and kill.calls[-1][0] == 'live'
    assert any(f.startswith('ORPHAN_FILL ') for f in report.findings)
    assert journal.store.con.execute("SELECT COUNT(*) FROM lane_flags WHERE flag='ORPHAN_FILL'").fetchone()[0] == 2


def test_failed_orphan_latch_does_not_poison_retry_cache(tmp_path, manifest):
    kill = FakeKill()
    kill.fail = True
    _, _, _, guard = _world(tmp_path, venues={}, kill=kill)
    fill = fills(manifest)[0]
    report = guard.apply(GuardSnapshot(now=1788973600, fills=[fill]))
    assert any('kill latch failed' in f for f in report.findings)
    kill.fail = False
    report = guard.apply(GuardSnapshot(now=1788973601, fills=[fill]))
    assert kill.calls and any(f.startswith('ORPHAN_FILL ') for f in report.findings)
