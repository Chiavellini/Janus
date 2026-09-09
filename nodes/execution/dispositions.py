"""Explicit, append-only ownership dispositions for exact external historical fills.

Not settlement accounting: no balances, orders, positions, P&L or kill are changed.
Git commit/tree membership travels with the source bytes for archive-only releases.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import asdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import subprocess
import time

from kernel.execution_protocol import FillRecord

DDL = """
CREATE TABLE IF NOT EXISTS external_fill_dispositions(
 id INTEGER PRIMARY KEY AUTOINCREMENT, venue TEXT NOT NULL, fill_id TEXT NOT NULL,
 supersedes_id INTEGER REFERENCES external_fill_dispositions(id),
 record_json TEXT NOT NULL, record_sha256 TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS external_fill_disposition_lookup ON external_fill_dispositions(venue,fill_id,id);
CREATE TRIGGER IF NOT EXISTS external_fill_disposition_no_update BEFORE UPDATE ON external_fill_dispositions
BEGIN SELECT RAISE(ABORT,'fill dispositions are append-only'); END;
CREATE TRIGGER IF NOT EXISTS external_fill_disposition_no_delete BEFORE DELETE ON external_fill_dispositions
BEGIN SELECT RAISE(ABORT,'fill dispositions are append-only'); END;
CREATE TRIGGER IF NOT EXISTS external_fill_disposition_linear BEFORE INSERT ON external_fill_dispositions
WHEN (NEW.supersedes_id IS NULL AND EXISTS(
 SELECT 1 FROM external_fill_dispositions WHERE venue=NEW.venue AND fill_id=NEW.fill_id))
OR (NEW.supersedes_id IS NOT NULL AND NOT EXISTS(
 SELECT 1 FROM external_fill_dispositions WHERE id=NEW.supersedes_id AND venue=NEW.venue AND fill_id=NEW.fill_id
 AND id=(SELECT MAX(id) FROM external_fill_dispositions WHERE venue=NEW.venue AND fill_id=NEW.fill_id)))
BEGIN SELECT RAISE(ABORT,'disposition must supersede the exact latest row'); END;
"""


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def exact_fields(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError('missing or unknown fields')


def fill_identity(fill: FillRecord | dict) -> dict:
    raw = asdict(fill) if isinstance(fill, FillRecord) else fill
    exact_fields(raw, FillRecord.__dataclass_fields__)
    result = dict(raw)
    for key in ('venue', 'fill_id', 'venue_order_id', 'market_id', 'side'):
        if not isinstance(raw[key], str) or not raw[key]:
            raise ValueError(f'fill {key} must be a nonempty string')
    if raw['side'] not in {'buy_yes', 'buy_no', 'sell_yes', 'sell_no'}:
        raise ValueError('unknown fill side')
    for key in ('is_taker', 'final'):
        if type(raw[key]) is not bool:
            raise ValueError(f'fill {key} must be a boolean')
    for key in ('contracts', 'price', 'fee_usd', 'ts'):
        if isinstance(raw[key], bool):
            raise ValueError('boolean is not a numeric field')
        number = Decimal(str(raw[key]))
        if not number.is_finite():
            raise ValueError('fill numbers must be finite')
        if key in {'contracts', 'ts'} and number <= 0:
            raise ValueError('fill quantity/time must be positive')
        if key == 'price' and not 0 <= number <= 1:
            raise ValueError('fill price outside binary bounds')
        result[key] = format(number.normalize(), 'f')
    return result


def git_hash(kind: str, data: bytes) -> str:
    return hashlib.sha1(f'{kind} {len(data)}\0'.encode() + data).hexdigest()


def _git(repo: str | Path, kind: str, oid: str) -> bytes:
    return subprocess.run(['git', '-C', str(repo), 'cat-file', kind, oid], check=True,
                          capture_output=True, timeout=10).stdout


def _tree_child(tree: bytes, name: str) -> tuple[str, str]:
    offset = 0
    while offset < len(tree):
        end = tree.index(b'\0', offset)
        mode, filename = tree[offset:end].split(b' ', 1)
        oid = tree[end + 1:end + 21]
        if len(oid) != 20:
            raise ValueError('truncated Git tree')
        if filename == name.encode():
            return mode.decode(), oid.hex()
        offset = end + 21
    raise ValueError('source ref absent from committed tree')


def verify_source(source: dict) -> None:
    exact_fields(source, {'git_commit', 'ref', 'sha256', 'content', 'commit_object', 'tree_objects'})
    if not isinstance(source['git_commit'], str) or not re.fullmatch('[0-9a-f]{40}', source['git_commit']):
        raise ValueError('full immutable Git SHA1 commit required')
    ref = source['ref']
    if not isinstance(ref, str) or not ref or ref.startswith('/') or '..' in ref.split('/') or str(PurePosixPath(ref)) != ref:
        raise ValueError('source ref must be an exact relative Git file path')
    if not isinstance(source['content'], str) or not isinstance(source['tree_objects'], list):
        raise ValueError('source bytes/tree chain malformed')
    blob = source['content'].encode()
    if len(blob) > 1_000_000 or hashlib.sha256(blob).hexdigest() != source['sha256']:
        raise ValueError('source SHA256 mismatch or oversized source')
    commit = base64.b64decode(source['commit_object'], validate=True)
    if git_hash('commit', commit) != source['git_commit']:
        raise ValueError('source commit object mismatch')
    root = commit.splitlines()[0]
    if not re.fullmatch(b'tree [0-9a-f]{40}', root):
        raise ValueError('invalid source commit tree')
    expected = root[5:].decode()
    parts = ref.split('/')
    if len(parts) != len(source['tree_objects']):
        raise ValueError('source tree chain length mismatch')
    for index, (name, encoded) in enumerate(zip(parts, source['tree_objects'])):
        tree = base64.b64decode(encoded, validate=True)
        if git_hash('tree', tree) != expected:
            raise ValueError('source tree hash mismatch')
        mode, expected = _tree_child(tree, name)
        if mode not in ({'100644', '100755'} if index == len(parts) - 1 else {'40000'}):
            raise ValueError('source ref is not a committed regular file')
    if git_hash('blob', blob) != expected:
        raise ValueError('source bytes do not belong to commit/ref')


def source_from_git(repo: str | Path, commit: str, ref: str, sha256: str) -> dict:
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('full immutable Git commit required')
    raw_commit = _git(repo, 'commit', commit)
    expected = raw_commit.splitlines()[0].split()[1].decode()
    trees = []
    for name in ref.split('/'):
        tree = _git(repo, 'tree', expected)
        trees.append(base64.b64encode(tree).decode())
        _, expected = _tree_child(tree, name)
    source = dict(git_commit=commit, ref=ref, sha256=sha256,
                  content=_git(repo, 'blob', expected).decode(),
                  commit_object=base64.b64encode(raw_commit).decode(), tree_objects=trees)
    verify_source(source)
    return source


def _pointer(document, pointer: str):
    if not isinstance(pointer, str) or not pointer.startswith('/'):
        raise ValueError('exact JSON pointer required')
    value = document
    for component in pointer[1:].split('/'):
        key = component.replace('~1', '/').replace('~0', '~')
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def _archive(source: dict):
    if not isinstance(source['origin'], str) or not source['origin'].startswith('/') or not isinstance(source['content'], str):
        raise ValueError('archive provenance/bytes missing')
    data = source['content'].encode()
    if len(data) > 1_000_000 or hashlib.sha256(data).hexdigest() != source['sha256']:
        raise ValueError('archived proof SHA256 mismatch')
    verify_source(source['git_source'])
    if source['git_source']['content'] != source['content'] or source['git_source']['sha256'] != source['sha256']:
        raise ValueError('archived bytes differ from their committed source')
    return json.loads(source['content'], parse_float=Decimal)


def verify_proof(entry: dict) -> dict:
    proof, fill = entry['proof'], entry['fill']
    exact_fields(proof, {'origin', 'sha256', 'content', 'git_source', 'status_pointer', 'fill_pointer', 'settlement_pointer', 'accounting_differences', 'cash_activity'})
    document = _archive(proof)
    status, old, settled = (_pointer(document, proof[key]) for key in ('status_pointer', 'fill_pointer', 'settlement_pointer'))
    if (document['venue'] != fill['venue'] or status['venue_order_id'] != fill['venue_order_id']
            or old['fill_id'] != fill['fill_id'] or Decimal(str(status['filled_contracts'])) != Decimal(fill['contracts'])
            or Decimal(str(old['contracts'])) != Decimal(fill['contracts'])
            or document.get('token', document.get('ticker')) != fill['market_id']
            or type(old['taker']) is not bool or old['taker'] != fill['is_taker']
            or not isinstance(settled, dict) or not settled.get('result') or not settled.get('at')):
        raise ValueError('archived proof identity/closure does not bind this exact fill')
    differences = {}
    for current, previous in [('price', 'price'), ('fee_usd', 'charged')]:
        number = format(Decimal(str(old[previous])).normalize(), 'f')
        if number != fill[current]:
            differences[current] = {'proof': number, 'observed': fill[current]}
    if proof['accounting_differences'] != differences:
        raise ValueError('proof/current accounting differences are not explicitly acknowledged')
    recognizable = {
        f"{fill['venue']} {fill['market_id'][:16]} {fill['side']} {float(fill['contracts']):g} @ {float(price)} order {fill['venue_order_id'][:12]}"
        for price in (fill['price'], old['price'])}
    if any(row['detail'] not in recognizable or Decimal(row['seen_ts']) < Decimal(fill['ts']) for row in entry['orphan_flags']):
        raise ValueError('confirmed incident detail does not describe the current or historical proof fill')
    cash = proof['cash_activity']
    cash_summary = None
    if cash is not None:
        exact_fields(cash, {'origin', 'sha256', 'content', 'git_source', 'buy_index', 'redeem_index', 'net_cash_usd'})
        rows = _archive(cash)
        if any(type(cash[key]) is not int or cash[key] < 0 for key in ('buy_index', 'redeem_index')):
            raise ValueError('exact activity row locators required')
        buy, redeem = rows[cash['buy_index']], rows[cash['redeem_index']]
        if (buy['type'] != 'TRADE' or buy['side'] != 'BUY' or redeem['type'] != 'REDEEM'
                or buy['asset'] != fill['market_id'] or redeem['asset'] != fill['market_id']
                or Decimal(str(buy['size'])) != Decimal(fill['contracts'])
                or Decimal(str(redeem['size'])) != Decimal(fill['contracts'])
                or Decimal(str(buy['price'])) != Decimal(fill['price'])
                or Decimal(str(buy['usdcSize'])) - Decimal(fill['contracts']) * Decimal(fill['price']) != Decimal(fill['fee_usd'])
                or not buy.get('transactionHash') or not redeem.get('transactionHash')
                or Decimal(str(redeem['usdcSize'])) - Decimal(str(buy['usdcSize'])) != Decimal(cash['net_cash_usd'])):
            raise ValueError('activity BUY/REDEEM does not bind exact token/quantity/cash')
        cash_summary = {'buy': buy, 'redeem': redeem, 'net_cash_usd': cash['net_cash_usd']}
    return {'status': status, 'historical_fill': old, 'historical_settled_record_not_recomputed_pnl': settled,
            'accounting_differences': differences, 'cash': cash_summary}


def prepare_manifest(manifest: dict, *, repo: str | Path = '.') -> dict:
    exact_fields(manifest, {'version', 'dispositions'})
    if type(manifest['version']) is not int or manifest['version'] != 1 or not isinstance(manifest['dispositions'], list) or not manifest['dispositions']:
        raise ValueError('nonempty version1 manifest required')
    entries, seen = [], set()
    for raw in manifest['dispositions']:
        exact_fields(raw, {'fill', 'action', 'source', 'reason', 'supersedes_id', 'source_lines', 'orphan_flags', 'proof'})
        entry = dict(raw, fill=fill_identity(raw['fill']))
        if entry['action'] not in {'settled_external_proof', 'revoked'}:
            raise ValueError('unknown disposition action')
        if not isinstance(entry['reason'], str) or len(entry['reason'].strip()) < 16:
            raise ValueError('explicit substantive disposition reason required')
        if entry['supersedes_id'] is not None and (type(entry['supersedes_id']) is not int or entry['supersedes_id'] <= 0):
            raise ValueError('invalid superseding row id')
        source = entry['source']
        if isinstance(source, dict) and set(source) == {'git_commit', 'ref', 'sha256'}:
            source = source_from_git(repo, source['git_commit'], source['ref'], source['sha256'])
        verify_source(source)
        entry['source'] = source
        entry['proof'] = dict(entry['proof'])
        if entry['proof']['cash_activity'] is not None:
            entry['proof']['cash_activity'] = dict(entry['proof']['cash_activity'])
        for archive in [entry['proof'], entry['proof']['cash_activity']]:
            if archive is None:
                continue
            git_source = archive['git_source']
            if isinstance(git_source, dict) and set(git_source) == {'git_commit', 'ref', 'sha256'}:
                archive['git_source'] = source_from_git(repo, git_source['git_commit'], git_source['ref'], git_source['sha256'])
        lines = entry['source_lines']
        if (not isinstance(lines, list) or len(lines) != 2 or any(type(x) is not int for x in lines)
                or not 1 <= lines[0] <= lines[1] <= len(source['content'].splitlines()) or lines[1] - lines[0] > 30):
            raise ValueError('exact bounded source line locator required')
        if not isinstance(entry['orphan_flags'], list):
            raise ValueError('explicit incident snapshots required')
        for incident in entry['orphan_flags']:
            exact_fields(incident, {'id', 'seen_ts', 'flag', 'detail'})
            if (type(incident['id']) is not int or incident['id'] <= 0 or incident['flag'] != 'ORPHAN_FILL'
                    or not isinstance(incident['detail'], str) or not incident['detail']
                    or not isinstance(incident['seen_ts'], str) or not Decimal(incident['seen_ts']).is_finite()):
                raise ValueError('invalid exact orphan incident snapshot')
        verify_proof(entry)
        key = (entry['fill']['venue'], entry['fill']['fill_id'])
        if key in seen:
            raise ValueError('duplicate fill in proposal')
        seen.add(key)
        entries.append(entry)
    return {'version': 1, 'dispositions': entries}


def latest(con, venue, fill_id):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='external_fill_dispositions'").fetchone():
        return None
    return con.execute('SELECT id,record_json,record_sha256,supersedes_id FROM external_fill_dispositions '
                       'WHERE venue=? AND fill_id=? ORDER BY id DESC LIMIT 1', (venue, fill_id)).fetchone()


def match_disposition(con, fill: FillRecord) -> dict | None:
    """Only exact, intact, latest confirmed ownership evidence changes classification."""
    identity = fill_identity(fill)
    row = latest(con, identity['venue'], identity['fill_id'])
    if row is None:
        return None
    record = json.loads(row[1])
    if digest(record) != row[2]:
        raise ValueError('disposition record SHA256 mismatch')
    exact_fields(record, {'entry', 'confirmed_sha256', 'recorded_utc', 'confirmation', 'manifest'})
    confirmation = record['confirmation']
    exact_fields(confirmation, {'database', 'manifest_sha256', 'heads'})
    if (not isinstance(record['confirmed_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', record['confirmed_sha256'])
            or digest(confirmation) != record['confirmed_sha256']):
        raise ValueError('unconfirmed or corrupt disposition confirmation digest')
    database = con.execute('PRAGMA database_list').fetchone()[2]
    if confirmation['database'] != str(Path(database).resolve()):
        raise ValueError('disposition was confirmed for a different database target')
    manifest = prepare_manifest(record['manifest'])
    if digest(manifest) != confirmation['manifest_sha256']:
        raise ValueError('confirmation manifest hash mismatch')
    if confirmation['heads'] != [entry['supersedes_id'] for entry in manifest['dispositions']]:
        raise ValueError('confirmation head identities mismatch')
    if sum(entry == record['entry'] for entry in manifest['dispositions']) != 1:
        raise ValueError('record is not an exact confirmed manifest entry')
    entry = prepare_manifest({'version': 1, 'dispositions': [record['entry']]})['dispositions'][0]
    if entry['supersedes_id'] != row[3]:
        raise ValueError('disposition chain identity mismatch')
    if entry['action'] != 'settled_external_proof' or entry['fill'] != identity:
        return None
    return {'id': row[0], 'reason': entry['reason'], 'source': entry['source'], 'fill_sha256': digest(identity),
            'orphan_flags': entry['orphan_flags']}


def confirmation_plan(con, db: Path, manifest: dict) -> dict:
    heads = []
    for entry in manifest['dispositions']:
        fill = entry['fill']
        row = latest(con, fill['venue'], fill['fill_id'])
        head = row[0] if row else None
        if entry['supersedes_id'] != head:
            raise ValueError(f"stale proposal for {fill['venue']}:{fill['fill_id']}; latest disposition is {head}")
        heads.append(head)
    payload = {'database': str(db.resolve()), 'manifest_sha256': digest(manifest), 'heads': heads}
    return dict(payload, confirm_sha256=digest(payload))


def append_confirmed(con, db: Path, manifest: dict, confirmation: str, *, now: float) -> list[int]:
    # Caller holds BEGIN IMMEDIATE: check and append share one writer lock.
    plan = confirmation_plan(con, db, manifest)
    if confirmation != plan['confirm_sha256']:
        raise ValueError('confirmation digest does not match exact target/manifest/current heads')
    ids = []
    for entry in manifest['dispositions']:
        record = {'entry': entry, 'confirmed_sha256': confirmation, 'recorded_utc': str(now),
                  'confirmation': {key: plan[key] for key in ('database', 'manifest_sha256', 'heads')},
                  'manifest': manifest}
        fill = entry['fill']
        cursor = con.execute('INSERT INTO external_fill_dispositions(venue,fill_id,supersedes_id,record_json,record_sha256) VALUES(?,?,?,?,?)',
                             (fill['venue'], fill['fill_id'], entry['supersedes_id'], canonical(record), digest(record)))
        ids.append(cursor.lastrowid)
    return ids


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--repo', type=Path, default=Path('.'))
    parser.add_argument('--export', type=Path, help='explicitly export a self-contained source-bound manifest; no database changes')
    parser.add_argument('--confirm', help='exact digest printed by dry-run; appends only, never clears kill/flags')
    args = parser.parse_args(argv)
    try:
        manifest = prepare_manifest(json.loads(args.manifest.read_text(), parse_float=Decimal), repo=args.repo)
        uri = args.db.resolve().as_uri()
        with sqlite3.connect(uri + '?mode=ro', uri=True) as con:
            plan = confirmation_plan(con, args.db, manifest)
        if args.export:
            if args.confirm or args.export.exists():
                raise ValueError('export must be separate from confirmation and must not overwrite a file')
            with args.export.open('x') as output:
                output.write(json.dumps(manifest, indent=2) + '\n')
        if args.confirm:
            if args.confirm != plan['confirm_sha256']:
                raise ValueError('confirmation digest mismatch; dry-run exact target first')
            with sqlite3.connect(uri + '?mode=rw', uri=True) as con:
                con.executescript(DDL)
                con.execute('BEGIN IMMEDIATE')
                ids = append_confirmed(con, args.db, manifest, args.confirm, now=time.time())
                con.commit()
            plan['appended_ids'] = ids
        plan['mode'] = 'confirmed_append' if args.confirm else 'dry_run'
        plan['fills'] = [{'fill': e['fill'], 'fill_sha256': digest(e['fill']), 'reason': e['reason'],
                         'action': e['action'], 'source_commit': e['source']['git_commit'],
                         'source_ref': e['source']['ref'], 'source_sha256': e['source']['sha256'],
                         'source_lines': e['source_lines'], 'source_excerpt': '\n'.join(e['source']['content'].splitlines()[e['source_lines'][0]-1:e['source_lines'][1]]),
                         'proof_origin': e['proof']['origin'], 'proof_sha256': e['proof']['sha256'],
                         'proof_facts': verify_proof(e), 'orphan_flags': e['orphan_flags']} for e in manifest['dispositions']]
        print(json.dumps(plan, indent=2, default=str))
        return 0
    except (ValueError, ArithmeticError, KeyError, IndexError, TypeError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f'DISPOSITION_BLOCKED: {type(exc).__name__}: {exc}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
