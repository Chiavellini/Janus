#!/usr/bin/env python3
"""Operator-only recovery for the reviewed flag-211 legacy acknowledgement latch.

This module is deliberately independent of ``clear_false_maker_latch``.  It accepts one exact
historical invalidation reason, proves the acknowledgement and current database state, and moves
the unchanged kill bytes to an exclusive audit path.  It has no SSM, mode, order, or arm APIs.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodes.execution.legacy_incident_ack import match_incident
from nodes.risk.flags import unresolved_flag_rows


FLAG_ID = 211
EXPECTED_REASON = "LEGACY_INCIDENT_ACK_INVALID flag=211: ValueError: acknowledged incident state changed"
FULL_SHA256 = re.compile(r"^[0-9a-f]{64}$")
FULL_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")

# These are the tables and columns needed by this proof.  Missing schema is a block, never an
# empty/quiet result.  The acknowledgement matcher additionally checks the historical evidence
# tables it reads; keeping this list explicit makes the global safety queries fail closed.
REQUIRED_TABLES = {
    "historical_legacy_incident_acknowledgements", "pm_post_only_orders", "pm_post_only_admission",
    "pm_post_only_violations", "execution_settlements", "lane_flags", "orders", "executions",
    "capital_reservations", "socket_health",
}
REQUIRED_COLUMNS = {
    "historical_legacy_incident_acknowledgements": {"id", "supersedes_id", "flag_id", "record_json", "record_sha256"},
    "lane_flags": {"id", "seen_ts", "flag", "detail"},
    "orders": {"venue", "open", "settlement_pending", "state"},
    "executions": {"released", "unhedged", "state"},
    "capital_reservations": {"released_utc"},
    "socket_health": {"seen_ts", "venue", "connected"},
}
MATERIAL_FLAGS = (
    "ORDER_PERSISTENCE_FAILED", "POST_ONLY_PERSISTENCE_FAILED", "ORPHAN_FILL",
    "POSITION_MISMATCH", "PROTECT_FAILED", "EXEC_CRASHED", "ORDER_OVERFILL",
    "POST_ONLY_ROLE_VIOLATION", "UNHEDGED_POSITION", "RESERVATION_MISSING",
    "FEE_ABOVE_PIN", "GUARD_FAILED",
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_full(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise RuntimeError(f"{label} must be the complete lowercase digest")
    return value


def _tables_and_columns(con: sqlite3.Connection) -> None:
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = sorted(REQUIRED_TABLES - tables)
    if missing:
        raise RuntimeError("expected safety table missing: " + ",".join(missing))
    for table, required in REQUIRED_COLUMNS.items():
        columns = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        absent = sorted(required - columns)
        if absent:
            raise RuntimeError(f"expected columns missing from {table}: {','.join(absent)}")


def _checkout_sha(repo: Path) -> str:
    try:
        got = subprocess.run(("git", "-C", str(repo), "rev-parse", "--verify", "HEAD"),
                             check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("cannot verify deployed checkout") from exc
    if not FULL_GIT_SHA.fullmatch(got):
        raise RuntimeError("deployed checkout did not return a full commit SHA")
    return got


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise RuntimeError("database is missing")
    return sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True, timeout=30)


def _read_kill(kill_path: Path, expected_digest: str) -> tuple[bytes, dict]:
    _require_full(expected_digest, FULL_SHA256, "kill SHA256")
    try:
        raw = kill_path.read_bytes()
    except OSError as exc:
        raise RuntimeError("exact live kill is missing or unreadable") from exc
    actual = _sha(raw)
    if actual != expected_digest:
        raise RuntimeError("live kill changed (full SHA256 mismatch)")
    try:
        kill = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("live kill is not valid JSON") from exc
    if not isinstance(kill, dict) or kill.get("reason") != EXPECTED_REASON:
        raise RuntimeError("live kill is not the exact reviewed flag-211 invalidation")
    return raw, kill


def _quiet(con: sqlite3.Connection) -> dict:
    _tables_and_columns(con)
    orders = int(con.execute(
        "SELECT COUNT(*) FROM orders WHERE open IS NOT 0 OR settlement_pending IS NOT 0 "
        "OR state='UNCONFIRMED'"
    ).fetchone()[0])
    executions = int(con.execute("SELECT COUNT(*) FROM executions WHERE released IS NOT 1").fetchone()[0])
    unhedged = int(con.execute(
        "SELECT COUNT(*) FROM executions WHERE released IS NOT 1 AND ABS(COALESCE(unhedged,0)) > 0.01"
    ).fetchone()[0])
    reservations = int(con.execute(
        "SELECT COUNT(*) FROM capital_reservations WHERE released_utc IS NULL"
    ).fetchone()[0])
    flags = {}
    for flag in MATERIAL_FLAGS:
        rows = unresolved_flag_rows(con, flag)
        if rows:
            flags[flag] = [int(row[0]) for row in rows]
    if orders or executions or unhedged or reservations or flags:
        raise RuntimeError(
            f"safety state not quiet: orders={orders} executions={executions} "
            f"unhedged={unhedged} reservations={reservations} flags={flags}"
        )
    return {"orders": orders, "unreleased_executions": executions,
            "materially_unhedged": unhedged, "unreleased_reservations": reservations,
            "material_flags": flags}


def prove(*, db_path: Path, kill_path: Path, expected_digest: str, release_sha: str,
          repo: Path = Path("."), incident_matcher: Callable | None = None) -> dict:
    """Return an immutable proof of the exact incident and quiet current state.

    This is read-only.  The connection is held open for all checks so the caller can use the
    returned proof as the final pre-activation observation; ``activate`` repeats it immediately
    before the exclusive move.
    """
    _require_full(expected_digest, FULL_SHA256, "kill SHA256")
    _require_full(release_sha, FULL_GIT_SHA, "release SHA")
    if _checkout_sha(repo) != release_sha:
        raise RuntimeError("deployed checkout SHA does not equal requested release SHA")
    raw, kill = _read_kill(kill_path, expected_digest)
    con = _connect_ro(db_path)
    try:
        _tables_and_columns(con)
        try:
            incident = (match_incident if incident_matcher is None else incident_matcher)(con, FLAG_ID)
        except Exception as exc:
            raise RuntimeError(f"match_incident(211) failed: {exc}") from exc
        if incident is None:
            raise RuntimeError("match_incident(211) found no historical acknowledgement")
        quiet = _quiet(con)
    finally:
        con.close()
    return {"schema": "janus.live_clear.legacy_incident.v1", "kill_sha256": expected_digest,
            "release_sha": release_sha, "reason": EXPECTED_REASON,
            "incident": incident, "global": quiet,
            "kill_raw_b64": base64.b64encode(raw).decode("ascii"), "kill": kill}


def _archive_path(archive_dir: Path, release_sha: str, digest: str) -> Path:
    return archive_dir / f"legacy-incident-211-cleared-{release_sha}-{digest}.json"


def _exclusive_move(src: Path, dst: Path, expected_digest: str) -> None:
    """Publish exact recovery bytes, then atomically quarantine and unlink ``src``.

    The recovery archive is an independent, fsynced, exclusive copy made while the live kill is
    still present. The opened source inode is then moved to a fresh same-filesystem quarantine and
    rechecked before unlink. A path swap is restored rather than cleared. Once the rename happens,
    every failure path retains ``dst`` and either restores ``src`` or raises an explicit rollback
    failure naming the durable archive; it never suppresses loss of the live latch.
    """
    lock = src.parent / ".legacy-incident-211.lock"
    lock_fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        import fcntl
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        try:
            source_fd = os.open(src, os.O_RDONLY | nofollow)
        except OSError as exc:
            raise RuntimeError("live kill is not a regular non-symlink file") from exc
        opened = os.fstat(source_fd)
        if not stat.S_ISREG(opened.st_mode):
            os.close(source_fd)
            raise RuntimeError("live kill is not a regular file")
        with os.fdopen(os.dup(source_fd), "rb") as source_stream:
            src_raw = source_stream.read()
        if _sha(src_raw) != expected_digest:
            os.close(source_fd)
            raise RuntimeError("live kill changed during archive")
        quarantine = Path(tempfile.mkdtemp(prefix=".legacy-incident-211-", dir=src.parent))
        staged = quarantine / "live"
        archived = False
        try:
            archive_fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(archive_fd, "wb") as archive_stream:
                    archive_stream.write(src_raw)
                    archive_stream.flush()
                    os.fsync(archive_stream.fileno())
            except Exception:
                try:
                    dst.unlink()
                except FileNotFoundError:
                    pass
                raise
            archived = True
            if not stat.S_ISREG(dst.stat(follow_symlinks=False).st_mode) or _sha(dst.read_bytes()) != expected_digest:
                raise RuntimeError("audit archive bytes changed during archive")
            os.rename(src, staged)
            moved = staged.read_bytes()
            staged_stat = staged.stat(follow_symlinks=False)
            if ((staged_stat.st_dev, staged_stat.st_ino) != (opened.st_dev, opened.st_ino)
                    or _sha(moved) != expected_digest):
                raise RuntimeError("live kill changed during atomic quarantine")
            os.unlink(staged)
        except Exception as original:
            restore_errors = []
            if not src.exists():
                recovered = False
                for recovery_source in (staged, dst if archived else None):
                    if recovery_source is None or not recovery_source.exists():
                        continue
                    try:
                        os.link(recovery_source, src, follow_symlinks=False)
                        recovered = True
                        break
                    except FileExistsError:
                        recovered = True  # a concurrent/new kill won; never overwrite it
                        break
                    except OSError as exc:
                        restore_errors.append(f"{recovery_source}: {type(exc).__name__}: {exc}")
                if not recovered and not src.exists():
                    raise RuntimeError(
                        "live kill rollback failed; lane must remain stopped; "
                        f"recovery_archive={dst}; errors={restore_errors}"
                    ) from original
            raise
        finally:
            os.close(source_fd)
            try:
                if staged.exists() and src.exists():
                    staged.unlink()
                quarantine.rmdir()
            except OSError:
                pass
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(lock_fd)


def activate(*, db_path: Path, kill_path: Path, archive_dir: Path, expected_digest: str,
             release_sha: str, repo: Path = Path("."), now: float | None = None,
             incident_matcher: Callable | None = None) -> Path:
    """Final stopped-lane proof and exact kill archive.  No other latch is touched."""
    proof = prove(db_path=db_path, kill_path=kill_path, expected_digest=expected_digest,
                  release_sha=release_sha, repo=repo, incident_matcher=incident_matcher)
    archive_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(archive_dir, 0o700)
    archive = _archive_path(archive_dir, release_sha, expected_digest)
    if archive.exists():
        raise RuntimeError("exclusive audit archive already exists")
    # A companion proof is also exclusive and written before the kill move.  It is not used as
    # the source of truth for recovery: the archived file itself is the exact kill bytes.
    proof_path = archive.with_suffix(".proof.json")
    import time
    proof["cleared_utc"] = time.time() if now is None else now
    fd = os.open(proof_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(proof, out, sort_keys=True, indent=2)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        _exclusive_move(kill_path, archive, expected_digest)
    except Exception:
        try:
            proof_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return archive


def restore(*, archive: Path, kill_path: Path, expected_digest: str) -> None:
    """Restore exact bytes only when the kill path is absent; never overwrite a new latch."""
    _require_full(expected_digest, FULL_SHA256, "kill SHA256")
    raw = archive.read_bytes()
    if _sha(raw) != expected_digest:
        raise RuntimeError("audit archive bytes do not match expected kill SHA256")
    if kill_path.exists():
        current = _sha(kill_path.read_bytes())
        if current != expected_digest:
            raise RuntimeError("refusing to overwrite a changed or new live kill")
        return
    kill_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{kill_path.name}.restore-", dir=kill_path.parent)
    tmp = Path(tmp_name)
    os.fchmod(fd, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(raw); out.flush(); os.fsync(out.fileno())
        # link is an exclusive create at the destination.  This closes the check-then-rename
        # race: a concurrent stronger/new kill is never overwritten by rollback.
        os.link(tmp, kill_path, follow_symlinks=False)
        tmp.unlink()
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    for command in ("prove", "activate"):
        p = sub.add_parser(command)
        p.add_argument("--db", type=Path, required=True)
        p.add_argument("--kill", type=Path, required=True)
        p.add_argument("--archive-dir", type=Path, required=command == "activate")
        p.add_argument("--expected-kill-sha", required=True)
        p.add_argument("--release-sha", required=True)
        p.add_argument("--repo", type=Path, required=True)
    restore_p = sub.add_parser("restore")
    restore_p.add_argument("--archive", type=Path, required=True)
    restore_p.add_argument("--kill", type=Path, required=True)
    restore_p.add_argument("--expected-kill-sha", required=True)
    args = ap.parse_args(argv)
    try:
        if args.command == "restore":
            restore(archive=args.archive, kill_path=args.kill, expected_digest=args.expected_kill_sha)
        elif args.command == "prove":
            prove(db_path=args.db, kill_path=args.kill, expected_digest=args.expected_kill_sha,
                  release_sha=args.release_sha, repo=args.repo)
        else:
            archive = activate(db_path=args.db, kill_path=args.kill, archive_dir=args.archive_dir,
                               expected_digest=args.expected_kill_sha, release_sha=args.release_sha,
                               repo=args.repo)
            print(f"LEGACY_211_CLEAR_COMPLETE archive={archive}")
        return 0
    except (RuntimeError, OSError, sqlite3.Error) as exc:
        print(f"LEGACY_211_CLEAR_BLOCKED: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
