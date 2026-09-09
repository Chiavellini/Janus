"""Exact historical overfill acknowledgement; never a position/accounting repair.

Dry-run/explicit digest confirmation only. Rows are append-only and bind complete
settled local evidence plus independently verified immutable source membership.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import subprocess
import time

from kernel.schema import Mode
from nodes.execution.dispositions import canonical, digest, exact_fields, source_from_git, verify_source
from nodes.risk.flags import flag_snapshot, unresolved_flag_rows

DDL = """
CREATE TABLE IF NOT EXISTS historical_order_overfill_acknowledgements(
 id INTEGER PRIMARY KEY AUTOINCREMENT, client_order_id TEXT NOT NULL,
 supersedes_id INTEGER REFERENCES historical_order_overfill_acknowledgements(id),
 record_json TEXT NOT NULL, record_sha256 TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS historical_overfill_lookup
 ON historical_order_overfill_acknowledgements(client_order_id,id);
CREATE TRIGGER IF NOT EXISTS historical_overfill_no_update BEFORE UPDATE ON historical_order_overfill_acknowledgements
BEGIN SELECT RAISE(ABORT,'overfill acknowledgements are append-only'); END;
CREATE TRIGGER IF NOT EXISTS historical_overfill_no_delete BEFORE DELETE ON historical_order_overfill_acknowledgements
BEGIN SELECT RAISE(ABORT,'overfill acknowledgements are append-only'); END;
CREATE TRIGGER IF NOT EXISTS historical_overfill_linear BEFORE INSERT ON historical_order_overfill_acknowledgements
WHEN (NEW.supersedes_id IS NULL AND EXISTS(
 SELECT 1 FROM historical_order_overfill_acknowledgements WHERE client_order_id=NEW.client_order_id))
OR (NEW.supersedes_id IS NOT NULL AND NOT EXISTS(
 SELECT 1 FROM historical_order_overfill_acknowledgements WHERE id=NEW.supersedes_id
 AND client_order_id=NEW.client_order_id
 AND id=(SELECT MAX(id) FROM historical_order_overfill_acknowledgements WHERE client_order_id=NEW.client_order_id)))
BEGIN SELECT RAISE(ABORT,'acknowledgement must supersede exact latest row'); END;
"""


def _rows(con, query, params=()):
    cursor = con.execute(query, params)
    return [dict(zip((c[0] for c in cursor.description), row)) for row in cursor.fetchall()]


def _decimal(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('missing or boolean numeric evidence')
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError('nonfinite evidence')
    return number


def _stable(value):
    if isinstance(value, float):
        return format(_decimal(value).normalize(), 'f')
    if isinstance(value, dict):
        return {key: _stable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_stable(item) for item in value]
    return value


def _owned_ids(execution):
    if execution['first_client_id'] is not None and (not isinstance(execution['first_client_id'], str) or not execution['first_client_id']):
        raise ValueError('invalid first-order identity')
    ids = [execution['first_client_id']] if execution['first_client_id'] else []
    for field in ('hedge_client_ids', 'unwind_client_ids'):
        extra = json.loads(execution[field] or '[]')
        if not isinstance(extra, list) or any(not isinstance(x, str) or not x for x in extra):
            raise ValueError('invalid execution order identity')
        ids.extend(extra)
    if len(ids) != len(set(ids)):
        raise ValueError('missing or duplicate execution order identity')
    return ids


def settled_snapshot(con, cid):
    orders = _rows(con, 'SELECT * FROM orders WHERE client_order_id=?', (cid,))
    if len(orders) != 1:
        raise ValueError('exact order absent')
    order = orders[0]
    if not Mode(order['mode']).sends_real_orders or not order['venue_order_id']:
        raise ValueError('only identified real orders can be acknowledged')
    if not _decimal(order['filled_contracts']) > _decimal(order['contracts']) > 0:
        raise ValueError('not an exact positive order overfill')
    if order['open'] != 0 or order['settlement_pending'] != 0:
        raise ValueError('order is open or cash accounting pending')
    executions = [e for e in _rows(con, 'SELECT * FROM executions') if cid in _owned_ids(e)]
    if len(executions) != 1:
        raise ValueError('order must have exactly one execution owner')
    execution = executions[0]
    if execution['state'] != 'RECONCILED' or execution['released'] != 1:
        raise ValueError('execution is not RECONCILED and released')
    if execution['opportunity_id'] != order['opportunity_id'] or execution['mode'] != order['mode']:
        raise ValueError('order/execution identity mismatch')
    owned = _owned_ids(execution)
    if not owned or not execution['reservation_id']:
        raise ValueError('selected execution has no owned orders or reservation')
    reservations = _rows(con, 'SELECT * FROM capital_reservations WHERE reservation_id=?', (execution['reservation_id'],))
    if len(reservations) != 1 or reservations[0]['released_utc'] is None:
        raise ValueError('exact released reservation absent')
    for key in ('event_id', 'league', 'opportunity_id'):
        if reservations[0][key] != execution[key]:
            raise ValueError('reservation/execution identity mismatch')
    all_orders = []
    for owned_cid in sorted(owned):
        candidates = _rows(con, 'SELECT * FROM orders WHERE client_order_id=?', (owned_cid,))
        if len(candidates) != 1 or candidates[0]['open'] != 0 or candidates[0]['settlement_pending'] != 0:
            raise ValueError('owned leg missing, open or accounting pending')
        if any(candidates[0][key] != execution[key] for key in ('opportunity_id', 'mode')):
            raise ValueError('owned leg/execution identity mismatch')
        all_orders.append(candidates[0])
    settlements = _rows(con, 'SELECT * FROM execution_settlements WHERE execution_id=?', (execution['execution_id'],))
    if len(settlements) != 1 or settlements[0]['released'] != 1:
        raise ValueError('exact released settlement absent')
    settlement = settlements[0]
    for key in ('execution_id', 'opportunity_id', 'event_id', 'league', 'mode'):
        if settlement[key] != execution[key]:
            raise ValueError('settlement/execution identity mismatch')
    legs = json.loads(settlement['legs_json'])
    if not isinstance(legs, list) or len(legs) != len(owned) or {x.get('client_order_id') for x in legs} != set(owned):
        raise ValueError('settlement owned-leg coverage mismatch')
    for leg_order in all_orders:
        leg = next(x for x in legs if x['client_order_id'] == leg_order['client_order_id'])
        if leg.get('final') is not True:
            raise ValueError('settlement leg not final')
        for key in ('venue', 'client_order_id', 'outcome_id', 'side', 'state'):
            if leg.get(key) != leg_order[key]:
                raise ValueError('settlement leg/order identity mismatch')
        for target, source in (('contracts', 'filled_contracts'), ('price', 'avg_price'), ('fee_usd', 'fee_usd')):
            amount = leg_order[source]
            if amount is None and source in {'avg_price', 'fee_usd'} and leg_order['filled_contracts'] == 0 and leg_order['state'] in {'UNFILLED', 'REJECTED'}:
                amount = 0  # Exactly the existing settlement serializer's zero-fill rule.
            if _decimal(leg.get(target)) != _decimal(amount):
                raise ValueError('settlement leg/order amount mismatch')
    return _stable({'order': order, 'execution': execution, 'orders': all_orders, 'settlement': settlement,
                    'legs': legs, 'reservation': reservations[0]})


def prepare_manifest(manifest, *, repo='.'):
    exact_fields(manifest, {'version', 'acknowledgements'})
    if type(manifest['version']) is not int or manifest['version'] != 1 or not isinstance(manifest['acknowledgements'], list) or not manifest['acknowledgements']:
        raise ValueError('nonempty version1 acknowledgement manifest required')
    entries, seen = [], set()
    for raw in manifest['acknowledgements']:
        exact_fields(raw, {'client_order_id', 'action', 'snapshot', 'sources', 'reason', 'supersedes_id', 'flag_evidence'})
        cid = raw['client_order_id']
        if not isinstance(cid, str) or not cid or cid in seen:
            raise ValueError('invalid or duplicate exact client order id')
        if raw['action'] not in {'acknowledge_settled_overfill', 'revoke'}:
            raise ValueError('unknown acknowledgement action')
        if not isinstance(raw['reason'], str) or len(raw['reason'].strip()) < 16:
            raise ValueError('explicit substantive reason required')
        if raw['supersedes_id'] is not None and (type(raw['supersedes_id']) is not int or raw['supersedes_id'] <= 0):
            raise ValueError('invalid superseded id')
        exact_fields(raw['snapshot'], {'order', 'execution', 'orders', 'settlement', 'legs', 'reservation'})
        if raw['snapshot']['order']['client_order_id'] != cid:
            raise ValueError('snapshot client identity mismatch')
        if not isinstance(raw['sources'], list) or not raw['sources']:
            raise ValueError('immutable supporting source required')
        if not isinstance(raw['flag_evidence'], list):
            raise ValueError('explicit flag evidence list required')
        flag_ids = set()
        for flag in raw['flag_evidence']:
            exact_fields(flag, {'id', 'seen_ts', 'flag', 'detail'})
            if type(flag['id']) is not int or flag['id'] <= 0 or flag['id'] in flag_ids or flag['flag'] != 'ORDER_OVERFILL':
                raise ValueError('invalid or duplicate exact overfill flag identity')
            if not isinstance(flag['seen_ts'], str) or format(_decimal(flag['seen_ts']).normalize(), 'f') != flag['seen_ts']:
                raise ValueError('flag time must be a canonical exact decimal string')
            if not isinstance(flag['detail'], str) or not {cid, cid + ':'}.intersection(flag['detail'].split()):
                raise ValueError('flag is not attributed to the exact acknowledged order')
            flag_ids.add(flag['id'])
        sources = []
        for source in raw['sources']:
            if isinstance(source, dict) and set(source) == {'git_commit', 'ref', 'sha256'}:
                source = source_from_git(repo, **{'commit': source['git_commit'], 'ref': source['ref'], 'sha256': source['sha256']})
            verify_source(source)
            sources.append(source)
        entries.append(dict(raw, sources=sources))
        seen.add(cid)
    return {'version': 1, 'acknowledgements': entries}


def _history(con, cid):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='historical_order_overfill_acknowledgements'").fetchone():
        return []
    return con.execute('SELECT id,supersedes_id,record_json,record_sha256 FROM historical_order_overfill_acknowledgements WHERE client_order_id=? ORDER BY id', (cid,)).fetchall()


def prepare_from_database(con, proposal, *, repo='.'):
    """Export an exact all-candidate proposal without granting acknowledgement."""
    exact_fields(proposal, {'version', 'acknowledgements'})
    if type(proposal['version']) is not int or proposal['version'] != 1 or not isinstance(proposal['acknowledgements'], list):
        raise ValueError('version1 proposal required')
    entries, cids, bound_flags = [], set(), set()
    for request in proposal['acknowledgements']:
        exact_fields(request, {'client_order_id', 'sources', 'reason', 'supersedes_id', 'flag_ids'})
        cid = request['client_order_id']
        if not isinstance(cid, str) or not cid or cid in cids:
            raise ValueError('invalid or duplicate exact client ID')
        if not isinstance(request['flag_ids'], list) or any(type(x) is not int or x <= 0 for x in request['flag_ids']):
            raise ValueError('positive exact flag IDs required')
        evidence = []
        for fid in request['flag_ids']:
            if fid in bound_flags:
                raise ValueError('duplicate flag attribution')
            row = con.execute('SELECT id,seen_ts,flag,detail FROM lane_flags WHERE id=?', (fid,)).fetchone()
            if row is None:
                raise ValueError('requested exact flag absent')
            evidence.append(flag_snapshot(row))
            bound_flags.add(fid)
        entries.append(dict(client_order_id=cid, action='acknowledge_settled_overfill', snapshot=settled_snapshot(con, cid),
                            sources=request['sources'], reason=request['reason'], supersedes_id=request['supersedes_id'], flag_evidence=evidence))
        cids.add(cid)
    candidates = {row[0] for row in con.execute('SELECT client_order_id,mode FROM orders WHERE filled_contracts>contracts+0.000000001')
                  if Mode(row[1]).sends_real_orders}
    if cids != candidates:
        raise ValueError(f'exact overfill candidate set differs: unexpected={sorted(candidates-cids)}, absent={sorted(cids-candidates)}')
    if any(row[0] not in bound_flags for row in unresolved_flag_rows(con, 'ORDER_OVERFILL')):
        raise ValueError('proposal does not cover every unresolved overfill flag')
    return prepare_manifest({'version': 1, 'acknowledgements': entries}, repo=repo)


def confirmation_plan(con, db, manifest, operator):
    manifest = prepare_manifest(manifest)
    if not isinstance(operator, str) or len(operator.strip()) < 3:
        raise ValueError('explicit operator identity required')
    heads, snapshots = [], []
    for entry in manifest['acknowledgements']:
        history = _history(con, entry['client_order_id'])
        head = history[-1][0] if history else None
        if entry['supersedes_id'] != head:
            raise ValueError('stale acknowledgement head')
        # Revocation is always available, even if the previously acknowledged order changed.
        if entry['action'] != 'revoke' and settled_snapshot(con, entry['client_order_id']) != entry['snapshot']:
            raise ValueError('current settled evidence differs from manifest')
        for flag in entry['flag_evidence']:
            actual = _rows(con, 'SELECT id,seen_ts,flag,detail FROM lane_flags WHERE id=?', (flag['id'],))
            if len(actual) != 1 or flag_snapshot(tuple(actual[0].values())) != flag:
                raise ValueError('exact historical flag evidence changed')
        heads.append(head)
        snapshots.append(digest(entry['snapshot']))
    payload = {'database': str(Path(db).resolve()), 'manifest_sha256': digest(manifest),
               'heads': heads, 'snapshots': snapshots, 'operator': operator.strip()}
    return dict(payload, confirm_sha256=digest(payload))


def append_confirmed(con, db, manifest, operator, confirmation, *, now):
    manifest = prepare_manifest(manifest)
    if _decimal(now) <= 0:
        raise ValueError('positive acknowledgement time required')
    if con.in_transaction:
        raise ValueError('acknowledgement requires its own immediate transaction')
    if confirmation_plan(con, db, manifest, operator)['confirm_sha256'] != confirmation:
        raise ValueError('confirmation digest mismatch')
    con.executescript(DDL)
    try:
        con.execute('BEGIN IMMEDIATE')
        plan = confirmation_plan(con, db, manifest, operator)
        if plan['confirm_sha256'] != confirmation:
            raise ValueError('confirmation became stale')
        ids = []
        for index, entry in enumerate(manifest['acknowledgements']):
            record = {'manifest': manifest, 'entry_index': index, 'confirmation': plan, 'recorded_utc': str(now)}
            cursor = con.execute('INSERT INTO historical_order_overfill_acknowledgements(client_order_id,supersedes_id,record_json,record_sha256) VALUES(?,?,?,?)',
                                 (entry['client_order_id'], entry['supersedes_id'], canonical(record), digest(record)))
            ids.append(cursor.lastrowid)
        con.commit()
        return ids
    except Exception:
        con.rollback()
        raise


def match_overfill_ack(con, cid):
    history = _history(con, cid)
    if not history:
        return None
    previous, active = None, None
    database = str(Path(next(row[2] for row in con.execute('PRAGMA database_list') if row[1] == 'main')).resolve())
    for row_id, supersedes, raw, sha in history:
        record = json.loads(raw)
        if digest(record) != sha:
            raise ValueError('acknowledgement record hash mismatch')
        exact_fields(record, {'manifest', 'entry_index', 'confirmation', 'recorded_utc'})
        if _decimal(record['recorded_utc']) <= 0:
            raise ValueError('invalid acknowledgement time')
        manifest = prepare_manifest(record['manifest'])
        index = record['entry_index']
        if type(index) is not int or not 0 <= index < len(manifest['acknowledgements']):
            raise ValueError('invalid acknowledgement entry index')
        entry, plan = manifest['acknowledgements'][index], record['confirmation']
        exact_fields(plan, {'database', 'manifest_sha256', 'heads', 'snapshots', 'operator', 'confirm_sha256'})
        if (entry['client_order_id'] != cid or supersedes != previous or entry['supersedes_id'] != previous
                or plan['manifest_sha256'] != digest(manifest) or plan['database'] != database
                or len(plan['heads']) != len(manifest['acknowledgements']) or plan['heads'][index] != previous
                or plan['snapshots'] != [digest(e['snapshot']) for e in manifest['acknowledgements']]
                or not isinstance(plan['operator'], str) or len(plan['operator'].strip()) < 3
                or plan['confirm_sha256'] != digest({k: v for k, v in plan.items() if k != 'confirm_sha256'})):
            raise ValueError('operator confirmation or acknowledgement chain mismatch')
        previous, active = row_id, entry
    if active['action'] != 'acknowledge_settled_overfill':
        raise ValueError('historical overfill acknowledgement revoked')
    if settled_snapshot(con, cid) != active['snapshot']:
        raise ValueError('historical overfill evidence changed')
    for flag in active['flag_evidence']:
        actual = _rows(con, 'SELECT id,seen_ts,flag,detail FROM lane_flags WHERE id=?', (flag['id'],))
        if len(actual) != 1 or flag_snapshot(tuple(actual[0].values())) != flag:
            raise ValueError('acknowledged flag evidence changed')
    return {'id': previous, 'reason': active['reason'], 'operator': plan['operator'],
            'snapshot_sha256': digest(active['snapshot']), 'flag_evidence': active['flag_evidence']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--operator', required=True)
    parser.add_argument('--repo', type=Path, default=Path('.'))
    parser.add_argument('--confirm', help='exact digest printed by a prior read-only dry-run')
    parser.add_argument('--prepare', action='store_true', help='export from exact CID/source/flag-ID proposal; no acknowledgement')
    parser.add_argument('--output', type=Path, help='new prepared manifest file; exclusive creation, never overwritten')
    args = parser.parse_args(argv)
    try:
        raw = json.loads(args.manifest.read_text())
        uri = args.db.resolve().as_uri()
        if args.prepare:
            if args.confirm or args.output is None:
                raise ValueError('--prepare requires --output and forbids --confirm')
            with sqlite3.connect(uri + '?mode=ro', uri=True) as con:
                con.execute('BEGIN')
                manifest = prepare_from_database(con, raw, repo=args.repo)
                confirmation_plan(con, args.db, manifest, args.operator)
            with args.output.open('x') as output:
                output.write(json.dumps(manifest, indent=2) + '\n')
            print(json.dumps({'mode': 'prepared_only', 'output': str(args.output.resolve()), 'manifest_sha256': digest(manifest)}))
            return 0
        if args.output is not None:
            raise ValueError('--output is only valid with --prepare')
        manifest = prepare_manifest(raw, repo=args.repo)
        with sqlite3.connect(uri + '?mode=ro', uri=True) as con:
            con.execute('BEGIN')
            plan = confirmation_plan(con, args.db, manifest, args.operator)
        if args.confirm:
            if args.confirm != plan['confirm_sha256']:
                raise ValueError('confirmation digest mismatch; dry-run exact target first')
            with sqlite3.connect(uri + '?mode=rw', uri=True) as con:
                plan['appended_ids'] = append_confirmed(con, args.db, manifest, args.operator, args.confirm, now=time.time())
        plan['mode'] = 'confirmed_append' if args.confirm else 'dry_run'
        plan['acknowledgements'] = [{'client_order_id': e['client_order_id'], 'action': e['action'],
                                    'snapshot': e['snapshot'], 'reason': e['reason'],
                                    'sources': [{k: s[k] for k in ('git_commit', 'ref', 'sha256')} for s in e['sources']]}
                                   for e in manifest['acknowledgements']]
        print(json.dumps(plan, indent=2))
        return 0
    except (ValueError, ArithmeticError, OSError, sqlite3.Error, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(f'OVERFILL_ACK_BLOCKED: {type(exc).__name__}: {exc}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
