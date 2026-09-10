import hashlib
import json
import sqlite3

import pytest

from ops.box.clear_false_maker_latch import audit_and_clear, restore


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
    archive = audit_and_clear(db_path=db, kill_path=kill, archive_dir=tmp_path / "audit",
                              expected_digest=digest, release_sha="abc", now=1001)
    assert archive.name == f"live-cleared-abc-{digest[:12]}.json"
    assert not kill.exists() and archive.stat().st_mode & 0o777 == 0o600
    proof = json.loads(archive.read_text())
    assert proof["client_order_id"] == CID and proof["global"]["active_executions"] == 0
    restore(archive=archive, kill_path=kill)
    assert json.loads(kill.read_text())["latched_utc"] == 1000


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
