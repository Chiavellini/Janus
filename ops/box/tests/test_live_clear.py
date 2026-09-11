import hashlib
import json
import sqlite3

import pytest

from ops.box.clear_false_maker_latch import activate, audit_and_clear, restore


CID = "a" * 32


def state(tmp_path, *, terminal=1, filled=0):
    db = tmp_path / "t.sqlite"
    c = sqlite3.connect(db)
    c.executescript("""
    CREATE TABLE pm_post_only_orders(client_order_id TEXT,venue_order_id TEXT,terminal_proved INTEGER,
      terminal_fingerprint TEXT,violated INTEGER);
    CREATE TABLE orders(venue TEXT,open INTEGER,state TEXT);
    CREATE TABLE executions(execution_id TEXT,state TEXT,first_client_id TEXT,first_filled REAL,
      hedge_filled REAL,unhedged REAL,released INTEGER,last_utc REAL);
    """)
    c.execute("INSERT INTO pm_post_only_orders VALUES(?,?,?,?,?)",
              (CID, "venue", terminal, '["CANCELED","0",[]]', 0))
    c.execute("INSERT INTO executions VALUES(?,?,?,?,?,?,?,?)",
              ("ex", "ORDER_UNFILLED", CID, filled, 0, filled, int(not filled), 1000))
    c.commit(); c.close()
    kill = tmp_path / "kill" / "live"; kill.parent.mkdir()
    kill.write_text(json.dumps({"reason": "unknown provider state: ex leg A unconfirmed: "
        f"post-only cancel/late-fill lifecycle unresolved: {CID}", "latched_utc": 1000}) + "\n")
    digest = hashlib.sha256(kill.read_bytes()).hexdigest()
    return db, kill, digest


def test_exact_false_latch_is_archived_then_cleared_and_can_be_restored(tmp_path):
    db, kill, digest = state(tmp_path)
    original = kill.read_bytes()
    archive = audit_and_clear(db_path=db, kill_path=kill, archive_dir=tmp_path / "audit",
                              expected_digest=digest, release_sha="abc", now=1001)
    assert archive.name == f"live-cleared-abc-{digest[:12]}.json"
    assert not kill.exists() and archive.stat().st_mode & 0o777 == 0o600
    proof = json.loads(archive.read_text())
    assert proof["client_order_id"] == CID and proof["global"]["active_executions"] == 0
    restore(archive=archive, kill_path=kill)
    assert kill.read_bytes() == original


def test_kill_can_be_retained_through_warmup_then_digest_bound_activation(tmp_path):
    db, kill, digest = state(tmp_path)
    archive = audit_and_clear(db_path=db, kill_path=kill, archive_dir=tmp_path / "audit",
                              expected_digest=digest, release_sha="abc", now=1001,
                              retain_kill=True)
    assert kill.exists()
    activate(archive=archive, kill_path=kill, expected_digest=digest)
    assert not kill.exists()


def test_activation_refuses_a_kill_changed_during_warmup(tmp_path):
    db, kill, digest = state(tmp_path)
    archive = audit_and_clear(db_path=db, kill_path=kill, archive_dir=tmp_path / "audit",
                              expected_digest=digest, release_sha="abc", now=1001,
                              retain_kill=True)
    kill.write_text('{"reason":"stronger incident"}\n')
    with pytest.raises(RuntimeError, match="changed during warm-up"):
        activate(archive=archive, kill_path=kill, expected_digest=digest)
    assert kill.exists()


def test_exact_false_latch_cannot_bypass_a_material_risk_flag(tmp_path):
    db, kill, digest = state(tmp_path)
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE lane_flags(id INTEGER PRIMARY KEY,seen_ts REAL,flag TEXT,detail TEXT)")
        con.execute("INSERT INTO lane_flags VALUES(1,1000,'ORDER_PERSISTENCE_FAILED','unresolved')")
    with pytest.raises(RuntimeError, match="ORDER_PERSISTENCE_FAILED.*1"):
        audit_and_clear(db_path=db, kill_path=kill, archive_dir=tmp_path / "audit",
                        expected_digest=digest, release_sha="abc", now=1001)
    assert kill.exists() and not (tmp_path / "audit").exists()


@pytest.mark.parametrize("change", ["digest", "reason", "terminal", "filled"])
def test_clear_refuses_any_non_exact_state(tmp_path, change):
    db, kill, digest = state(tmp_path, terminal=0 if change == "terminal" else 1,
                             filled=1 if change == "filled" else 0)
    if change == "digest": digest = "0" * 64
    if change == "reason": kill.write_text('{"reason":"operator stop"}\n')
    with pytest.raises(RuntimeError):
        audit_and_clear(db_path=db, kill_path=kill, archive_dir=tmp_path / "audit",
                        expected_digest=digest, release_sha="abc", now=1001)
    assert kill.exists()
