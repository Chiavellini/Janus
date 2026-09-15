import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from ops.box import clear_guard_failure_latch as clear
from nodes.risk.flags import flag_snapshot, resolve_exact_flags


def fixture(tmp_path, monkeypatch):
    db = tmp_path / "tuples.sqlite"
    con = sqlite3.connect(db)
    con.executescript("""
      CREATE TABLE lane_flags(id INTEGER PRIMARY KEY, seen_ts REAL, flag TEXT, detail TEXT);
      CREATE TABLE orders(venue TEXT, open INTEGER, settlement_pending INTEGER, state TEXT);
      CREATE TABLE executions(released INTEGER, unhedged REAL, state TEXT);
      CREATE TABLE capital_reservations(released_utc REAL);
      CREATE TABLE execution_settlements(execution_id TEXT);
      CREATE TABLE pm_post_only_orders(client_order_id TEXT, terminal_proved INTEGER, violated INTEGER);
      CREATE TABLE pm_post_only_admission(slot INTEGER, client_order_id TEXT, claimed_utc REAL);
      CREATE TABLE pm_post_only_violations(client_order_id TEXT, code TEXT, detail TEXT, seen_utc REAL);
      CREATE TABLE socket_health(seen_ts REAL, venue TEXT, connected INTEGER);
    """)
    for source_id, seen_ts, detail in clear.SOURCE_ROWS:
        con.execute("INSERT INTO lane_flags VALUES(?,?,?,?)", (source_id, seen_ts, clear.FLAG, detail))
    con.execute("INSERT INTO pm_post_only_admission VALUES(1,NULL,NULL)")
    con.commit(); con.close()
    kill = tmp_path / "kill" / "live"
    kill.parent.mkdir()
    kill.write_bytes((json.dumps({"reason": clear.EXPECTED_REASON,
                                  "latched_utc": clear.EXPECTED_LATCHED_UTC}, separators=(",", ":")) + "\n").encode())
    digest = hashlib.sha256(kill.read_bytes()).hexdigest()
    monkeypatch.setattr(clear, "EXPECTED_KILL_SHA256", digest)
    release = subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()
    return db, kill, digest, release


def test_exact_guard_failure_is_resolved_append_only_and_archived(tmp_path, monkeypatch):
    db, kill, digest, release = fixture(tmp_path, monkeypatch)
    original = kill.read_bytes()
    archive = clear.activate(db_path=db, kill_path=kill, archive_dir=tmp_path / "audit",
                             expected_digest=digest, release_sha=release, repo=Path("."), now=2000)
    assert archive.read_bytes() == original
    assert not kill.exists()
    with sqlite3.connect(db) as con:
        sources = con.execute(
            "SELECT id,flag,detail FROM lane_flags WHERE id IN (1169,1170) ORDER BY id"
        ).fetchall()
        marker = con.execute("SELECT flag,detail FROM lane_flags WHERE flag='GUARD_FAILED_RESOLVED_EXACT'").fetchone()
    assert sources == [(row[0], clear.FLAG, row[2]) for row in clear.SOURCE_ROWS]
    assert marker and clear.RESOLUTION_PREFIX in marker[1] and digest not in marker[1]
    clear.restore(archive=archive, kill_path=kill, expected_digest=digest)
    assert kill.read_bytes() == original


@pytest.mark.parametrize("change", ["reason", "time", "missing", "changed", "duplicate", "later"])
def test_guard_failure_proof_rejects_changed_or_additional_incident_evidence(tmp_path, monkeypatch, change):
    db, kill, digest, release = fixture(tmp_path, monkeypatch)
    if change == "reason":
        kill.write_bytes(json.dumps({"reason": "guard failed: changed", "latched_utc": clear.EXPECTED_LATCHED_UTC}).encode())
    elif change == "time":
        kill.write_bytes(json.dumps({"reason": clear.EXPECTED_REASON, "latched_utc": 1}).encode())
    elif change == "missing":
        with sqlite3.connect(db) as con:
            con.execute("DELETE FROM lane_flags WHERE id=1170")
    elif change == "changed":
        with sqlite3.connect(db) as con:
            con.execute("UPDATE lane_flags SET detail='changed' WHERE id=1170")
    elif change in ("duplicate", "later"):
        with sqlite3.connect(db) as con:
            con.execute("INSERT INTO lane_flags VALUES(?,?,?,?)", (1171, clear.SOURCE_ROWS[-1][1] + 1,
                         clear.FLAG, clear.SOURCE_ROWS[0][2] if change == "duplicate" else "new"))
    with pytest.raises(RuntimeError):
        clear.prove(db_path=db, kill_path=kill, expected_digest=digest, release_sha=release, repo=Path("."))
    assert kill.exists()


def test_missing_schema_and_symlink_are_stops(tmp_path, monkeypatch):
    db, kill, digest, release = fixture(tmp_path, monkeypatch)
    with sqlite3.connect(db) as con:
        con.execute("DROP TABLE capital_reservations")
    with pytest.raises(RuntimeError, match="expected safety table missing"):
        clear.prove(db_path=db, kill_path=kill, expected_digest=digest, release_sha=release, repo=Path("."))
    target = tmp_path / "target"
    target.write_bytes(kill.read_bytes())
    kill.unlink(); kill.symlink_to(target)
    with pytest.raises(RuntimeError, match="regular non-symlink"):
        clear._read_kill(kill, digest)


def test_historical_violation_is_quiet_only_with_clean_terminal_marker(tmp_path, monkeypatch):
    db, kill, digest, release = fixture(tmp_path, monkeypatch)
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO pm_post_only_orders VALUES(?,?,?)", ("historical", 1, 0))
        con.execute("INSERT INTO pm_post_only_violations VALUES(?,?,?,?)",
                    ("historical", "POST_ONLY_PERSISTENCE_FAILED", "old", 1))
        con.execute("INSERT INTO lane_flags VALUES(200,?,?,?)",
                    (1, "POST_ONLY_PERSISTENCE_FAILED", "historical: old"))
        con.commit()
        row = con.execute("SELECT id,seen_ts,flag,detail FROM lane_flags WHERE id=200").fetchone()
        assert resolve_exact_flags(
            SimpleNamespace(con=con), "POST_ONLY_PERSISTENCE_FAILED", [flag_snapshot(row)],
            "registered historical resolution", now=2,
        )
    clear.prove(db_path=db, kill_path=kill, expected_digest=digest, release_sha=release, repo=Path("."))
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO pm_post_only_violations VALUES(?,?,?,?)", ("unresolved", "ORDER_OVERFILL", "new", 2))
    with pytest.raises(RuntimeError, match="violations=1"):
        clear.prove(db_path=db, kill_path=kill, expected_digest=digest, release_sha=release, repo=Path("."))


def test_legacy_blanket_resolution_does_not_clear_violation_history(tmp_path, monkeypatch):
    db, kill, digest, release = fixture(tmp_path, monkeypatch)
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO pm_post_only_orders VALUES('historical',1,0)")
        con.execute("INSERT INTO pm_post_only_violations VALUES('historical','ORDER_OVERFILL','old',1)")
        con.execute("INSERT INTO lane_flags VALUES(200,1,'ORDER_OVERFILL','historical: old')")
        con.execute("INSERT INTO lane_flags VALUES(201,2,'ORDER_OVERFILL_RESOLVED','blanket')")
    with pytest.raises(RuntimeError, match="violations=1"):
        clear.prove(db_path=db, kill_path=kill, expected_digest=digest, release_sha=release, repo=Path("."))


@pytest.mark.parametrize("sql", [
    "INSERT INTO orders VALUES('kalshi',1,0,'FILLED')",
    "INSERT INTO orders VALUES('polymarket',0,0,'UNCONFIRMED')",
    "INSERT INTO executions VALUES(0,0,'HEDGED')",
    "INSERT INTO executions VALUES(0,1,'HEDGED')",
    "INSERT INTO capital_reservations VALUES(NULL)",
    "INSERT INTO pm_post_only_admission VALUES(2,'claimed',1)",
    "INSERT INTO pm_post_only_orders VALUES('open',0,0)",
    "INSERT INTO pm_post_only_orders VALUES('violated',1,1)",
    "INSERT INTO lane_flags VALUES(300,3,'ORPHAN_FILL','new')",
])
def test_every_material_nonquiet_state_blocks(tmp_path, monkeypatch, sql):
    db, kill, digest, release = fixture(tmp_path, monkeypatch)
    with sqlite3.connect(db) as con:
        con.execute(sql)
    with pytest.raises(RuntimeError, match="safety state not quiet"):
        clear.prove(db_path=db, kill_path=kill, expected_digest=digest, release_sha=release, repo=Path("."))


def test_changed_kill_wins_archive_race_and_is_not_overwritten(tmp_path, monkeypatch):
    db, kill, digest, release = fixture(tmp_path, monkeypatch)
    archive = tmp_path / "audit.json"
    changed = b'{"reason":"new operator stop"}\n'
    original_rename = clear.os.rename
    raced = False

    def replace_then_rename(src, dst):
        nonlocal raced
        if not raced:
            raced = True
            Path(src).write_bytes(changed)
        return original_rename(src, dst)

    monkeypatch.setattr(clear.os, "rename", replace_then_rename)
    with pytest.raises(RuntimeError, match="changed during atomic quarantine"):
        clear._exclusive_move(kill, archive, digest)
    assert kill.read_bytes() == changed
    assert archive.exists(), "the exact original bytes remain recoverable without overwriting the new kill"


def test_shell_orders_two_guards_around_retained_kill_warmup_before_activation():
    script = (Path(__file__).resolve().parents[1] / "clear_guard_failure_latch.sh").read_text()
    stopped = script.index("stop_lane_verified\npre_proved=0")
    preproof = script.index("clear_guard_failure_latch.py prove", stopped)
    first = script.index("STOPPED_GUARD_PASS_1_OK")
    warm_start = script.index("systemctl start janus-live-stream", first)
    streams = script.index("RETAINED_KILL_STREAM_WARMUP_OK")
    second = script.index("STOPPED_GUARD_PASS_2_OK")
    activate = script.index("clear_guard_failure_latch.py activate")
    assert stopped < preproof < first < warm_start < streams < second < activate


def test_activation_retries_after_append_failure_without_a_second_resolution(tmp_path, monkeypatch):
    db, kill, digest, release = fixture(tmp_path, monkeypatch)
    original = kill.read_bytes()
    original_move = clear._exclusive_move
    monkeypatch.setattr(clear, "_exclusive_move", lambda *_args: (_ for _ in ()).throw(RuntimeError("move failed")))
    with pytest.raises(RuntimeError, match="move failed"):
        clear.activate(db_path=db, kill_path=kill, archive_dir=tmp_path / "audit1",
                       expected_digest=digest, release_sha=release, repo=Path("."), now=2000)
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM lane_flags WHERE flag='GUARD_FAILED_RESOLVED_EXACT'").fetchone()[0] == 1
    monkeypatch.setattr(clear, "_exclusive_move", original_move)
    archive = clear.activate(db_path=db, kill_path=kill, archive_dir=tmp_path / "audit2",
                             expected_digest=digest, release_sha=release, repo=Path("."), now=2001)
    assert archive.read_bytes() == original and not kill.exists()
