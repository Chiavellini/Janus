"""Exact historical non-maker lock-label acknowledgement, never a cash or kill repair.

Prepare and dry-run are read-only. Explicit operator/digest confirmation appends a
source-bound immutable record. A separate fresh idle guard pass resolves exact IDs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import time

from nodes.execution.dispositions import canonical, digest, exact_fields, source_from_git, verify_source
from nodes.execution.overfill_ack import _rows, _stable, _decimal, settled_snapshot
from nodes.risk.flags import flag_snapshot, resolve_exact_flags, unresolved_flag_rows

FLAG = 'POST_ONLY_PERSISTENCE_FAILED'
TABLE = 'historical_legacy_incident_acknowledgements'
DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE}(
 id INTEGER PRIMARY KEY AUTOINCREMENT, flag_id INTEGER NOT NULL,
 supersedes_id INTEGER REFERENCES {TABLE}(id), record_json TEXT NOT NULL, record_sha256 TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS legacy_incident_no_update BEFORE UPDATE ON {TABLE}
BEGIN SELECT RAISE(ABORT,'legacy incident acknowledgements are append-only'); END;
CREATE TRIGGER IF NOT EXISTS legacy_incident_no_delete BEFORE DELETE ON {TABLE}
BEGIN SELECT RAISE(ABORT,'legacy incident acknowledgements are append-only'); END;
CREATE TRIGGER IF NOT EXISTS legacy_incident_linear BEFORE INSERT ON {TABLE}
WHEN (NEW.supersedes_id IS NULL AND EXISTS(SELECT 1 FROM {TABLE} WHERE flag_id=NEW.flag_id))
OR (NEW.supersedes_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM {TABLE}
 WHERE id=NEW.supersedes_id AND flag_id=NEW.flag_id
 AND id=(SELECT MAX(id) FROM {TABLE} WHERE flag_id=NEW.flag_id)))
BEGIN SELECT RAISE(ABORT,'incident must supersede exact latest row'); END;
"""


def _positive_id(value):
    if type(value) is not int or value <= 0:
        raise ValueError('exact positive integer ID required')
    return value


def idle_database(con):
    """Require known schemas and exact empty risk; missing tables are not zero."""
    if con.execute('SELECT 1 FROM pm_post_only_orders LIMIT 1').fetchone():
        raise ValueError('post-only order history present; not the historical empty-maker state')
    admission = _rows(con, 'SELECT * FROM pm_post_only_admission')
    if admission != [{'slot': 1, 'client_order_id': None, 'claimed_utc': None}]:
        raise ValueError('post-only admission is not exactly empty')
    if con.execute("SELECT 1 FROM orders WHERE open IS NOT 0 OR settlement_pending IS NOT 0 OR state='UNCONFIRMED' LIMIT 1").fetchone():
        raise ValueError('open, unresolved or cash-pending order remains')
    if con.execute('SELECT 1 FROM executions WHERE released IS NOT 1 LIMIT 1').fetchone():
        raise ValueError('unreleased execution remains')
    if con.execute('SELECT 1 FROM capital_reservations WHERE released_utc IS NULL LIMIT 1').fetchone():
        raise ValueError('unreleased capital reservation remains')


def incident_snapshot(con, cid, flag_id, violation_id, *, require_idle=True):
    _positive_id(flag_id)
    _positive_id(violation_id)
    settled = settled_snapshot(con, cid)
    if settled['order']['venue'] != 'polymarket' or settled['order']['time_in_force'].lower() != 'ioc':
        raise ValueError('only the settled legacy Polymarket IOC mechanism is covered')
    if _decimal(settled['execution']['unhedged']) != 0:
        raise ValueError('bound incident execution is not exactly zero-unhedged')
    if require_idle:
        idle_database(con)
    flags = con.execute('SELECT id,seen_ts,flag,detail FROM lane_flags WHERE id=?', (flag_id,)).fetchall()
    violations = _rows(con, 'SELECT * FROM pm_post_only_violations WHERE id=?', (violation_id,))
    if len(flags) != 1 or len(violations) != 1:
        raise ValueError('exact incident flag or violation absent')
    flag, violation = flag_snapshot(flags[0]), _stable(violations[0])
    expected = f'{FLAG}: {cid}: OperationalError: database is locked'
    if (flag['flag'] != FLAG or flag['detail'] != f'{cid}: {expected}'
            or violation != dict(id=violation_id, client_order_id=cid, code=FLAG,
                                 detail=expected, seen_utc=flag['seen_ts'])):
        raise ValueError('flag and violation do not prove the same exact legacy lock incident')
    if require_idle and con.execute('SELECT COUNT(*) FROM pm_post_only_violations').fetchone()[0] != 1:
        raise ValueError('other post-only violation evidence remains')
    return dict(settled=settled, flag=flag, violation=violation)


def prepare_manifest(raw, *, repo='.'):
    exact_fields(raw, {'version', 'client_order_id', 'action', 'snapshot', 'source', 'source_lines', 'reason', 'supersedes_id'})
    if type(raw['version']) is not int or raw['version'] != 1 or raw['action'] not in {'acknowledge_legacy_lock_label', 'revoke'}:
        raise ValueError('version1 explicit action required')
    cid = raw['client_order_id']
    if not isinstance(cid, str) or not cid or not isinstance(raw['reason'], str) or len(raw['reason'].strip()) < 16:
        raise ValueError('exact client identity and substantive operator reason required')
    if raw['supersedes_id'] is not None:
        _positive_id(raw['supersedes_id'])
    exact_fields(raw['snapshot'], {'settled', 'flag', 'violation'})
    snapshot = raw['snapshot']
    exact_fields(snapshot['flag'], {'id', 'seen_ts', 'flag', 'detail'})
    exact_fields(snapshot['violation'], {'id', 'client_order_id', 'code', 'detail', 'seen_utc'})
    _positive_id(snapshot['flag']['id'])
    _positive_id(snapshot['violation']['id'])
    if snapshot['settled']['order']['client_order_id'] != cid or snapshot['violation']['client_order_id'] != cid:
        raise ValueError('snapshot client mismatch')
    source = raw['source']
    if set(source) == {'git_commit', 'ref', 'sha256'}:
        source = source_from_git(repo, source['git_commit'], source['ref'], source['sha256'])
    verify_source(source)
    bounds = raw['source_lines']
    lines = source['content'].splitlines()
    if not isinstance(bounds, list) or len(bounds) != 2 or any(type(n) is not int for n in bounds) or not 1 <= bounds[0] <= bounds[1] <= len(lines):
        raise ValueError('exact source line locator required')
    excerpt = '\n'.join(lines[bounds[0]-1:bounds[1]])
    if (source['ref'] != 'nodes/execute/guard.py'
            or 'if callable(getattr(adapter, "_persistence_failure", None)):' not in excerpt
            or 'adapter._persistence_failure(cid or vid, exc)' not in excerpt
            or 'post_only' in excerpt.replace('_persistence_failure', '')):
        raise ValueError('source excerpt does not bind the reviewed unconditional legacy guard hook')
    return dict(raw, source=source)


def prepare_from_database(con, proposal, *, repo='.'):
    exact_fields(proposal, {'version', 'client_order_id', 'flag_id', 'violation_id', 'source', 'source_lines', 'reason', 'supersedes_id'})
    snapshot = incident_snapshot(con, proposal['client_order_id'], proposal['flag_id'], proposal['violation_id'])
    return prepare_manifest(dict(version=proposal['version'], client_order_id=proposal['client_order_id'],
        action='acknowledge_legacy_lock_label', snapshot=snapshot, source=proposal['source'],
        source_lines=proposal['source_lines'], reason=proposal['reason'], supersedes_id=proposal['supersedes_id']), repo=repo)


def _history(con, flag_id):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone():
        return []
    return con.execute(f'SELECT id,supersedes_id,record_json,record_sha256 FROM {TABLE} WHERE flag_id=? ORDER BY id', (flag_id,)).fetchall()


def confirmation_plan(con, db, manifest, operator):
    manifest = prepare_manifest(manifest)
    if not isinstance(operator, str) or len(operator.strip()) < 3:
        raise ValueError('explicit operator identity required')
    flag_id, violation_id = manifest['snapshot']['flag']['id'], manifest['snapshot']['violation']['id']
    history = _history(con, flag_id)
    head = history[-1][0] if history else None
    if manifest['supersedes_id'] != head:
        raise ValueError('stale incident acknowledgement head')
    if manifest['action'] != 'revoke' and incident_snapshot(con, manifest['client_order_id'], flag_id, violation_id) != manifest['snapshot']:
        raise ValueError('exact incident/settled state changed')
    payload = dict(database=str(Path(db).resolve()), manifest_sha256=digest(manifest), head=head, operator=operator.strip())
    return dict(payload, confirm_sha256=digest(payload))


def append_confirmed(con, db, manifest, operator, confirmation, *, now):
    manifest = prepare_manifest(manifest)
    if con.in_transaction or _decimal(now) <= 0:
        raise ValueError('own writer transaction and positive time required')
    if confirmation_plan(con, db, manifest, operator)['confirm_sha256'] != confirmation:
        raise ValueError('confirmation digest mismatch')
    con.executescript(DDL)
    try:
        con.execute('BEGIN IMMEDIATE')
        plan = confirmation_plan(con, db, manifest, operator)
        if plan['confirm_sha256'] != confirmation:
            raise ValueError('stale confirmation')
        record = dict(manifest=manifest, confirmation=plan, recorded_utc=str(now))
        cursor = con.execute(f'INSERT INTO {TABLE}(flag_id,supersedes_id,record_json,record_sha256) VALUES(?,?,?,?)',
            (manifest['snapshot']['flag']['id'], manifest['supersedes_id'], canonical(record), digest(record)))
        con.commit()
        return cursor.lastrowid
    except Exception:
        con.rollback()
        raise


def match_incident(con, flag_id, *, require_idle=True):
    history = _history(con, flag_id)
    if not history:
        return None
    database = str(Path(next(r[2] for r in con.execute('PRAGMA database_list') if r[1] == 'main')).resolve())
    previous = None
    for row_id, supersedes, raw, sha in history:
        record = json.loads(raw)
        exact_fields(record, {'manifest', 'confirmation', 'recorded_utc'})
        if digest(record) != sha or _decimal(record['recorded_utc']) <= 0:
            raise ValueError('incident record hash/time mismatch')
        manifest, plan = prepare_manifest(record['manifest']), record['confirmation']
        exact_fields(plan, {'database', 'manifest_sha256', 'head', 'operator', 'confirm_sha256'})
        if (manifest['snapshot']['flag']['id'] != flag_id or supersedes != previous
                or manifest['supersedes_id'] != previous or plan['head'] != previous
                or plan['database'] != database or plan['manifest_sha256'] != digest(manifest)
                or not isinstance(plan['operator'], str) or len(plan['operator'].strip()) < 3
                or plan['confirm_sha256'] != digest({k: v for k, v in plan.items() if k != 'confirm_sha256'})):
            raise ValueError('incident confirmation or linear chain mismatch')
        previous = row_id
    if manifest['action'] == 'revoke':
        raise ValueError('incident acknowledgement revoked')
    if incident_snapshot(con, manifest['client_order_id'], flag_id, manifest['snapshot']['violation']['id'], require_idle=require_idle) != manifest['snapshot']:
        raise ValueError('acknowledged incident state changed')
    return dict(id=previous, flag=manifest['snapshot']['flag'], reason=manifest['reason'])


def resolve_idle_incidents(store, *, now, verify_pass, position_evidence=None):
    """No kill mutation. Every active class incident must match under the writer lock."""
    if not unresolved_flag_rows(store.con, FLAG):
        return False  # Later legitimate maker activity cannot reopen a resolved historical label.
    acknowledged = []
    def verify():
        if not verify_pass():
            return False
        idle_database(store.con)
        acknowledged.clear()
        for row in unresolved_flag_rows(store.con, FLAG):
            match = match_incident(store.con, row[0])
            if match is None:
                return False
            acknowledged.append(match['flag'])
        return bool(acknowledged)
    if not verify():
        return False
    return resolve_exact_flags(store, FLAG, acknowledged,
        'Fresh complete idle guard; exact operator-confirmed historical legacy IOC lock label; kill unchanged; positions=' + canonical(position_evidence),
        now=now, verify=verify)


_MIGRATION_FALSE_ALARM_PREFIX = 'LEGACY_INCIDENT_ACK_INVALID flag='
_MIGRATION_FALSE_ALARM_SUFFIX = ': ValueError: acknowledged incident state changed'


def _migration_source_id(detail):
    if not isinstance(detail, str) or not detail.startswith(_MIGRATION_FALSE_ALARM_PREFIX) or not detail.endswith(_MIGRATION_FALSE_ALARM_SUFFIX):
        return None
    raw = detail[len(_MIGRATION_FALSE_ALARM_PREFIX):-len(_MIGRATION_FALSE_ALARM_SUFFIX)]
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 and detail == f'{_MIGRATION_FALSE_ALARM_PREFIX}{value}{_MIGRATION_FALSE_ALARM_SUFFIX}' else None


def _empty_admission_state(rows):
    required = {'slot', 'client_order_id', 'claimed_utc'}
    if len(rows) != 1 or not required <= set(rows[0]):
        return False
    row = rows[0]
    if row['slot'] != 1 or row['client_order_id'] is not None:
        return False
    return row['claimed_utc'] is None or _decimal(row['claimed_utc']) > 0


def _settled_current_database(con):
    """Current risk must be empty; terminal maker history is allowed after the original L56 pass."""
    admission = _rows(con, 'SELECT * FROM pm_post_only_admission')
    return (_empty_admission_state(admission)
            and not con.execute("SELECT 1 FROM pm_post_only_orders WHERE terminal_proved IS NOT 1 OR violated IS NOT 0 LIMIT 1").fetchone()
            and not con.execute("SELECT 1 FROM orders WHERE open IS NOT 0 OR settlement_pending IS NOT 0 OR state='UNCONFIRMED' LIMIT 1").fetchone()
            and not con.execute('SELECT 1 FROM executions WHERE released IS NOT 1 LIMIT 1').fetchone()
            and not con.execute('SELECT 1 FROM capital_reservations WHERE released_utc IS NULL LIMIT 1').fetchone())


def resolve_migration_false_alarms(store, *, now, verify_pass):
    """Close only exact false alarms emitted by the v1 SELECT-* compatibility regression.

    The source acknowledgement must validate now, its original flag must already be resolved, and
    every current row must have the one exact error string the faulty release emitted. No kill or
    source row is changed.
    """
    evidence = []

    def verify():
        if not verify_pass() or not _settled_current_database(store.con):
            return False
        current_rows = unresolved_flag_rows(store.con, FLAG)
        current_ids = {row[0] for row in current_rows}
        current = []
        for row in current_rows:
            source_id = _migration_source_id(row[3])
            if source_id is None or source_id in current_ids:
                return False
            try:
                if match_incident(store.con, source_id, require_idle=False) is None:
                    return False
            except (ValueError, TypeError, KeyError, IndexError, ArithmeticError, sqlite3.Error):
                return False
            current.append(flag_snapshot(row))
        return bool(current) and (not evidence or current == evidence)

    if not verify():
        return False
    evidence.extend(flag_snapshot(row) for row in unresolved_flag_rows(store.con, FLAG))
    return resolve_exact_flags(store, FLAG, evidence,
        'Fresh complete guard; exact false alarms from additive orders.execution_id v1 snapshot migration; original acknowledgement valid; kill unchanged',
        now=now, verify=verify)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--operator', required=True)
    parser.add_argument('--repo', type=Path, default=Path('.'))
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--confirm')
    args = parser.parse_args(argv)
    try:
        raw = json.loads(args.manifest.read_text())
        uri = args.db.resolve().as_uri()
        with sqlite3.connect(uri + '?mode=ro', uri=True) as con:
            if args.prepare:
                if args.confirm or args.output is None:
                    raise ValueError('prepare requires separate new output, never confirmation')
                manifest = prepare_from_database(con, raw, repo=args.repo)
                with args.output.open('x') as output:
                    output.write(json.dumps(manifest, indent=2) + '\n')
                print(json.dumps(dict(mode='prepared_read_only', manifest_sha256=digest(manifest), output=str(args.output))))
                return 0
            if args.output:
                raise ValueError('output is only valid for prepare')
            manifest = prepare_manifest(raw, repo=args.repo)
            plan = confirmation_plan(con, args.db, manifest, args.operator)
        if args.confirm:
            if args.confirm != plan['confirm_sha256']:
                raise ValueError('confirmation digest mismatch')
            with sqlite3.connect(uri + '?mode=rw', uri=True) as con:
                plan['appended_id'] = append_confirmed(con, args.db, manifest, args.operator, args.confirm, now=time.time())
        bounds = manifest['source_lines']
        plan.update(mode='confirmed_append' if args.confirm else 'dry_run', snapshot=manifest['snapshot'], reason=manifest['reason'],
                    source_excerpt='\n'.join(manifest['source']['content'].splitlines()[bounds[0]-1:bounds[1]]))
        print(json.dumps(plan, indent=2))
        return 0
    except (ValueError, TypeError, KeyError, IndexError, ArithmeticError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f'LEGACY_INCIDENT_BLOCKED: {type(exc).__name__}: {exc}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
