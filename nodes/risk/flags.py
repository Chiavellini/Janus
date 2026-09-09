"""Lane flags: a fact the lane noticed that the watchdog must repeat until a human acts.

The first one (2026-09-07) is CAP_BINDS_SMALLEST: the override's cap refused a cover at the
SMALLEST quantity the lane prices. By the operator's rule ("the smallest amount that doesn't cause
fill failures") that is a misconfiguration, not a limit, and it must never be silent. One table,
append-only; the watchdog reads the last day."""
from __future__ import annotations

import sqlite3
import time
import hashlib
import json
from decimal import Decimal
from pathlib import Path

FLAGS_DDL = """
CREATE TABLE IF NOT EXISTS lane_flags(
  id INTEGER PRIMARY KEY AUTOINCREMENT, seen_ts REAL NOT NULL, flag TEXT NOT NULL, detail TEXT);
CREATE INDEX IF NOT EXISTS lane_flags_ts ON lane_flags(flag, seen_ts);
"""

EXACT_RESOLUTION_PREFIX = 'EXACT_INCIDENTS_V1 '


def flag_snapshot(row) -> dict:
    return {'id': int(row[0]), 'seen_ts': format(Decimal(str(row[1])).normalize(), 'f'),
            'flag': row[2], 'detail': row[3] or ''}


def unresolved_flag_rows(con, flag: str, *, since_ts: float = 0) -> list[tuple]:
    """Legacy markers retain their boundary; exact markers close named IDs only."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lane_flags'").fetchone():
        return []
    floor, closed = (since_ts, -1), set()
    for rid, ts, marker, detail in con.execute('SELECT id,seen_ts,flag,detail FROM lane_flags WHERE flag IN (?,?)',
                                               (flag + '_RESOLVED', flag + '_RESOLVED_EXACT')):
        if marker == flag + '_RESOLVED_EXACT':
            try:
                if not (detail or '').startswith(EXACT_RESOLUTION_PREFIX):
                    continue
                payload = json.loads(detail[len(EXACT_RESOLUTION_PREFIX):])
                if set(payload) != {'ids', 'rows_sha256', 'detail'} or not isinstance(payload['ids'], list):
                    continue
                if not all(type(value) is int and value > 0 for value in payload['ids']):
                    continue
                rows = [con.execute('SELECT id,seen_ts,flag,detail FROM lane_flags WHERE id=? AND flag=?', (value, flag)).fetchone()
                        for value in payload['ids']]
                if any(row is None for row in rows):
                    continue
                raw = json.dumps([flag_snapshot(row) for row in rows], sort_keys=True, separators=(',', ':'))
                if hashlib.sha256(raw.encode()).hexdigest() == payload['rows_sha256']:
                    closed.update(payload['ids'])
            except (TypeError, ValueError):
                continue  # A broken exact marker is not a blanket legacy resolution.
        else:
            floor = max(floor, (float(ts), int(rid)))
    return [row for row in con.execute('SELECT id,seen_ts,flag,detail FROM lane_flags WHERE flag=? ORDER BY seen_ts,id', (flag,))
            if (float(row[1]), int(row[0])) > floor and row[0] not in closed]


def resolve_exact_flags(store, flag: str, acknowledged: list[dict], detail: str, *, now: float, verify=None) -> bool:
    """Atomic all-incident coverage check; never resolves a row absent from confirmation."""
    con = store.con
    if con.in_transaction:
        raise ValueError('exact flag resolution requires its own writer transaction')
    con.execute('BEGIN IMMEDIATE')
    try:
        if verify is not None and not verify():
            con.rollback()
            return False
        rows = unresolved_flag_rows(con, flag)
        allowed = {row['id']: row for row in acknowledged}
        if (not rows or len(allowed) != len(acknowledged)
                or any(allowed.get(row[0]) != flag_snapshot(row) for row in rows)):
            con.rollback()
            return False
        snapshots = [flag_snapshot(row) for row in rows]
        payload = {'ids': [row[0] for row in rows], 'detail': detail,
                   'rows_sha256': hashlib.sha256(json.dumps(snapshots, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}
        con.execute('INSERT INTO lane_flags(seen_ts,flag,detail) VALUES(?,?,?)',
                    (now, flag + '_RESOLVED_EXACT', EXACT_RESOLUTION_PREFIX + json.dumps(payload, sort_keys=True, separators=(',', ':'))))
        con.commit()
        return True
    except Exception:
        con.rollback()
        raise


def raise_flag(store, flag: str, detail: str = "", *, now: float | None = None) -> None:
    store.ensure_ddl(FLAGS_DDL)
    store.con.execute("INSERT INTO lane_flags(seen_ts, flag, detail) VALUES(?,?,?)", (now or time.time(), flag, detail[:300]))
    store.con.commit()


def resolve_flag(store, flag: str, detail: str = "", *, now: float | None = None) -> bool:
    """Append a resolution marker when `flag` currently has an unresolved occurrence.

    Flags are an audit log, so a false or no-longer-current alarm is never deleted. The marker
    makes the watchdog quiet without rewriting history. Returns False when the latest marker is
    already a resolution, which keeps periodic healthy passes from growing the table forever.
    """
    store.ensure_ddl(FLAGS_DDL)
    resolved = f"{flag}_RESOLVED"
    row = store.con.execute(
        "SELECT flag FROM lane_flags WHERE flag IN (?,?) ORDER BY seen_ts DESC, id DESC LIMIT 1",
        (flag, resolved),
    ).fetchone()
    if row is None or row[0] == resolved:
        return False
    store.con.execute("INSERT INTO lane_flags(seen_ts, flag, detail) VALUES(?,?,?)",
                      (now or time.time(), resolved, detail[:300]))
    store.con.commit()
    return True


def recent_flags(db_path: Path | str, flag: str, *, since_s: float = 24 * 3600, now: float | None = None) -> list[tuple[float, str]]:
    """Unresolved `(seen_ts, detail)` rows of `flag` in the recent window.

    A later `<FLAG>_RESOLVED` marker suppresses older occurrences while preserving them in the
    append-only table. A new occurrence after that marker becomes visible again.
    """
    t = now or time.time()
    p = Path(db_path)
    if not p.exists():
        return []
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='lane_flags'").fetchall():
            return []
        return [(row[1], row[3]) for row in reversed(unresolved_flag_rows(con, flag, since_ts=t - since_s))]
    finally:
        con.close()
