import sqlite3

import pytest

from nodes.risk.flags import (EXACT_RESOLUTION_PREFIX, flag_snapshot, raise_flag, recent_flags,
                              resolve_exact_flags, unresolved_flag_rows)
from nodes.store_tuples.store import TupleStore


def test_exact_resolution_is_consumed_and_never_hides_same_timestamp_new_incident(tmp_path):
    store = TupleStore(tmp_path / 'flags.sqlite', enforce_volume=False)
    raise_flag(store, 'ORPHAN_FILL', 'original', now=1000)
    snapshots = [flag_snapshot(row) for row in unresolved_flag_rows(store.con, 'ORPHAN_FILL')]
    assert resolve_exact_flags(store, 'ORPHAN_FILL', snapshots, 'explicit reviewed incidents', now=1001)
    assert recent_flags(tmp_path / 'flags.sqlite', 'ORPHAN_FILL', now=1001) == []
    raise_flag(store, 'ORPHAN_FILL', 'new same timestamp', now=1001)
    assert recent_flags(tmp_path / 'flags.sqlite', 'ORPHAN_FILL', now=1001) == [(1001, 'new same timestamp')]
    assert not resolve_exact_flags(store, 'ORPHAN_FILL', snapshots, 'stale confirmation', now=1002)
    # Invalid exact-marker text must never turn into a blanket legacy resolution.
    raise_flag(store, 'ORPHAN_FILL_RESOLVED_EXACT', '', now=2000)
    assert recent_flags(tmp_path / 'flags.sqlite', 'ORPHAN_FILL', now=2000) == [(1001, 'new same timestamp')]


def test_verification_and_coverage_check_share_writer_transaction(tmp_path):
    store = TupleStore(tmp_path / 'flags.sqlite', enforce_volume=False)
    raise_flag(store, 'ORDER_OVERFILL', 'original', now=1000)
    snapshots = [flag_snapshot(row) for row in unresolved_flag_rows(store.con, 'ORDER_OVERFILL')]
    def verify():
        assert store.con.in_transaction
        with sqlite3.connect(tmp_path / 'flags.sqlite', timeout=.01) as other:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                other.execute('INSERT INTO lane_flags(seen_ts,flag,detail) VALUES(1001,"ORDER_OVERFILL","concurrent")')
        return True
    assert resolve_exact_flags(store, 'ORDER_OVERFILL', snapshots, 'atomic exact coverage', now=1001, verify=verify)
    raise_flag(store, 'ORDER_OVERFILL', 'after lock released', now=1001)
    assert recent_flags(tmp_path / 'flags.sqlite', 'ORDER_OVERFILL', now=1001) == [(1001, 'after lock released')]


def test_false_verification_and_unknown_old_incident_do_not_resolve(tmp_path):
    store = TupleStore(tmp_path / 'flags.sqlite', enforce_volume=False)
    raise_flag(store, 'ORPHAN_FILL', 'known', now=1000)
    snapshots = [flag_snapshot(row) for row in unresolved_flag_rows(store.con, 'ORPHAN_FILL')]
    assert not resolve_exact_flags(store, 'ORPHAN_FILL', snapshots, 'revoked during read', now=1001, verify=lambda: False)
    raise_flag(store, 'ORPHAN_FILL', 'older unseen incident', now=500)
    assert not resolve_exact_flags(store, 'ORPHAN_FILL', snapshots, 'incomplete ownership', now=1001)
    assert len(recent_flags(tmp_path / 'flags.sqlite', 'ORPHAN_FILL', now=1001)) == 2
