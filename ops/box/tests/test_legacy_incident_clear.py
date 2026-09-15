import hashlib
import json
import re
import sqlite3
import subprocess
from pathlib import Path

import pytest

from ops.box import clear_legacy_incident_latch as clear


REASON = clear.EXPECTED_REASON


def test_shell_preamble_requires_exact_full_lowercase_digests():
    script = (Path(__file__).resolve().parents[1] / "clear_legacy_incident_latch.sh").read_text()
    preamble = script[:script.index("DB=/srv/janus/tuples/tuples.sqlite")]
    harness = preamble + "\nprintf 'validated\\n'\n"

    release = "0123456789abcdef" * 2 + "01234567"
    kill = "abcdef0123456789" * 4

    def run(release_sha, kill_sha):
        return subprocess.run(
            ("bash", "-c", harness, "clear-helper", release_sha, kill_sha),
            text=True, capture_output=True, check=False,
        )

    valid = run(release, kill)
    assert valid.returncode == 0
    assert valid.stdout.strip() == "validated"

    invalid_releases = (release[:-1], release + "a", release.upper(), release[:-1] + "g")
    invalid_kills = (kill[:-1], kill + "a", kill.upper(), kill[:-1] + "g")
    for malformed in invalid_releases:
        result = run(malformed, kill)
        assert result.returncode == 2
        assert "validated" not in result.stdout
    for malformed in invalid_kills:
        result = run(release, malformed)
        assert result.returncode == 2
        assert "validated" not in result.stdout


def test_shell_constructs_remote_script_without_expanding_remote_started():
    helper = Path(__file__).resolve().parents[1] / "clear_legacy_incident_latch.sh"
    script = helper.read_text()
    remote_call = 'bash "$HERE/run.sh" "$REMOTE"'
    assert script.count(remote_call) == 1
    heredoc = script.split("<<EOS", 1)[1].split("\nEOS", 1)[0]
    locally_bound = set(re.findall(r"(?<!\\)\$([A-Za-z_][A-Za-z0-9_]*)", heredoc))
    assert locally_bound == {"DB", "KILL", "KILL_SHA", "PY", "RELEASE_SHA"}
    harness = script.replace(remote_call, "printf '%s\\n' \"$REMOTE\"")
    release = "0123456789abcdef" * 2 + "01234567"
    kill = "abcdef0123456789" * 4
    result = subprocess.run(
        ("bash", "-c", harness, str(helper), release, kill),
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "STARTED=$(date +%s.%N)" in result.stdout
    assert "s=float('$STARTED')" in result.stdout
    assert '--archive-dir "$AUDIT"' in result.stdout
    assert '\\"' not in result.stdout
    assert result.stdout.index("STARTED=$(date +%s.%N)") < result.stdout.index("s=float('$STARTED')")


def fixture(tmp_path):
    db = tmp_path / "tuples.sqlite"
    con = sqlite3.connect(db)
    con.executescript("""
      CREATE TABLE historical_legacy_incident_acknowledgements(id INTEGER, supersedes_id INTEGER, flag_id INTEGER, record_json TEXT, record_sha256 TEXT);
      CREATE TABLE pm_post_only_orders(client_order_id TEXT);
      CREATE TABLE pm_post_only_admission(slot INTEGER);
      CREATE TABLE pm_post_only_violations(id INTEGER);
      CREATE TABLE execution_settlements(execution_id TEXT);
      CREATE TABLE lane_flags(id INTEGER PRIMARY KEY, seen_ts REAL, flag TEXT, detail TEXT);
      CREATE TABLE orders(venue TEXT, open INTEGER, settlement_pending INTEGER, state TEXT);
      CREATE TABLE executions(released INTEGER, unhedged REAL, state TEXT);
      CREATE TABLE capital_reservations(released_utc REAL);
      CREATE TABLE socket_health(seen_ts REAL, venue TEXT, connected INTEGER);
    """)
    con.commit(); con.close()
    kill = tmp_path / "kill" / "live"
    kill.parent.mkdir()
    kill.write_bytes((json.dumps({"reason": REASON, "latched_utc": 1}, separators=(",", ":")) + "\n").encode())
    digest = hashlib.sha256(kill.read_bytes()).hexdigest()
    release = subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()
    return db, kill, digest, release


def matcher(_con, flag_id):
    assert flag_id == 211
    return {"id": 7, "flag": {"id": 211}}


def test_prove_requires_exact_reason_full_digests_checkout_and_incident(tmp_path):
    db, kill, digest, release = fixture(tmp_path)
    got = clear.prove(db_path=db, kill_path=kill, expected_digest=digest, release_sha=release,
                      repo=Path("."), incident_matcher=matcher)
    assert got["reason"] == REASON and got["kill_raw_b64"]
    with pytest.raises(RuntimeError, match="complete lowercase"):
        clear.prove(db_path=db, kill_path=kill, expected_digest=digest[:12], release_sha=release,
                    repo=Path("."), incident_matcher=matcher)
    with pytest.raises(RuntimeError, match="checkout SHA"):
        clear.prove(db_path=db, kill_path=kill, expected_digest=digest, release_sha="0" * 40,
                    repo=Path("."), incident_matcher=matcher)
    with pytest.raises(RuntimeError, match="match_incident"):
        clear.prove(db_path=db, kill_path=kill, expected_digest=digest, release_sha=release,
                    repo=Path("."), incident_matcher=lambda *_: None)


@pytest.mark.parametrize("venue", ["kalshi", "polymarket"])
def test_either_venue_open_unconfirmed_or_cash_pending_blocks(tmp_path, venue):
    db, kill, digest, release = fixture(tmp_path)
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO orders VALUES(?,?,?,?)", (venue, 0, 0, "UNCONFIRMED"))
    with pytest.raises(RuntimeError, match="orders=1"):
        clear.activate(db_path=db, kill_path=kill, archive_dir=tmp_path / "audit",
                       expected_digest=digest, release_sha=release, repo=Path("."), incident_matcher=matcher)


@pytest.mark.parametrize("table", ["orders", "executions", "capital_reservations", "socket_health"])
def test_missing_expected_table_is_not_zero_risk(tmp_path, table):
    db, kill, digest, release = fixture(tmp_path)
    with sqlite3.connect(db) as con:
        con.execute(f"DROP TABLE {table}")
    with pytest.raises(RuntimeError, match="expected safety table missing"):
        clear.prove(db_path=db, kill_path=kill, expected_digest=digest, release_sha=release,
                    repo=Path("."), incident_matcher=matcher)


def test_activation_archives_exact_bytes_exclusively_and_restore_is_exact(tmp_path):
    db, kill, digest, release = fixture(tmp_path)
    original = kill.read_bytes()
    archive = clear.activate(db_path=db, kill_path=kill, archive_dir=tmp_path / "audit",
                             expected_digest=digest, release_sha=release, repo=Path("."), incident_matcher=matcher)
    assert archive.read_bytes() == original and not kill.exists()
    clear.restore(archive=archive, kill_path=kill, expected_digest=digest)
    assert kill.read_bytes() == original
    with pytest.raises(RuntimeError, match="already exists"):
        clear.activate(db_path=db, kill_path=kill, archive_dir=tmp_path / "audit",
                       expected_digest=digest, release_sha=release, repo=Path("."), incident_matcher=matcher)


def test_changed_kill_at_activation_is_never_removed(tmp_path):
    db, kill, digest, release = fixture(tmp_path)
    kill.write_bytes(b'{"reason":"new incident"}\n')
    with pytest.raises(RuntimeError, match="mismatch"):
        clear.activate(db_path=db, kill_path=kill, archive_dir=tmp_path / "audit",
                       expected_digest=digest, release_sha=release, repo=Path("."), incident_matcher=matcher)
    assert b"new incident" in kill.read_bytes()


def test_new_material_flag_after_warmup_is_caught_by_final_recheck(tmp_path):
    db, kill, digest, release = fixture(tmp_path)
    clear.prove(db_path=db, kill_path=kill, expected_digest=digest, release_sha=release,
                repo=Path("."), incident_matcher=matcher)
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO lane_flags VALUES(1,2,'FEE_ABOVE_PIN','new after warmup')")
    with pytest.raises(RuntimeError, match="FEE_ABOVE_PIN"):
        clear.activate(db_path=db, kill_path=kill, archive_dir=tmp_path / "audit",
                       expected_digest=digest, release_sha=release, repo=Path("."), incident_matcher=matcher)
    assert kill.exists()


def test_atomic_quarantine_replacement_keeps_replaced_kill(tmp_path, monkeypatch):
    _db, kill, digest, _release = fixture(tmp_path)
    archive = tmp_path / "audit.json"
    original = kill.read_bytes()
    original_rename = clear.os.rename

    def replace_then_rename(src, dst):
        if Path(src) == kill:
            kill.write_bytes(b'{"reason":"stronger-race"}\n')
        return original_rename(src, dst)

    monkeypatch.setattr(clear.os, "rename", replace_then_rename)
    with pytest.raises(RuntimeError, match="atomic quarantine"):
        clear._exclusive_move(kill, archive, digest)
    assert b"stronger-race" in kill.read_bytes()
    assert archive.read_bytes() == original, "the known recovery source survives a failed move"


def test_failed_internal_restore_is_explicit_and_preserves_known_archive(tmp_path, monkeypatch):
    _db, kill, digest, _release = fixture(tmp_path)
    archive = tmp_path / "audit.json"
    original = kill.read_bytes()
    original_unlink = clear.os.unlink

    def fail_staged_unlink(path):
        if Path(path).name == "live" and Path(path).parent.name.startswith(".legacy-incident-211-"):
            raise OSError("simulated activation failure after quarantine")
        return original_unlink(path)

    monkeypatch.setattr(clear.os, "unlink", fail_staged_unlink)
    monkeypatch.setattr(clear.os, "link", lambda *_a, **_k: (_ for _ in ()).throw(OSError("restore unavailable")))
    with pytest.raises(RuntimeError, match="rollback failed.*recovery_archive"):
        clear._exclusive_move(kill, archive, digest)
    assert not kill.exists()
    assert archive.read_bytes() == original


def test_symlink_kill_is_rejected_without_touching_target(tmp_path):
    _db, kill, digest, _release = fixture(tmp_path)
    target = tmp_path / "target"
    target.write_bytes(kill.read_bytes())
    kill.unlink()
    kill.symlink_to(target)
    with pytest.raises(RuntimeError, match="regular non-symlink"):
        clear._exclusive_move(kill, tmp_path / "archive.json", digest)
    assert target.exists() and target.read_bytes() != b""


def test_scratch_directory_cleanup_failure_cannot_discard_the_only_archive(tmp_path, monkeypatch):
    _db, kill, digest, _release = fixture(tmp_path)
    archive = tmp_path / "audit.json"
    original = kill.read_bytes()
    original_rmdir = Path.rmdir

    def fail_only_quarantine(path):
        if path.name.startswith(".legacy-incident-211-"):
            raise OSError("simulated scratch cleanup failure")
        return original_rmdir(path)

    monkeypatch.setattr(Path, "rmdir", fail_only_quarantine)
    clear._exclusive_move(kill, archive, digest)
    assert not kill.exists()
    assert archive.read_bytes() == original


def test_new_kill_is_not_overwritten_by_rollback(tmp_path):
    _db, kill, digest, _release = fixture(tmp_path)
    archive = tmp_path / "archive.json"
    original = kill.read_bytes()
    archive.write_bytes(original)
    kill.unlink()
    kill.write_bytes(b'{"reason":"stronger"}\n')
    with pytest.raises(RuntimeError, match="changed or new"):
        clear.restore(archive=archive, kill_path=kill, expected_digest=digest)
    assert b"stronger" in kill.read_bytes()
