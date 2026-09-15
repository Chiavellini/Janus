#!/usr/bin/env python3
"""Operator-only exact recovery for the registered guard-failure incident set.

This is not a general kill clearer.  It accepts only the L133 incident set, proves the current
database is complete and quiet, appends an exact joint resolution for source rows 1169 and 1170,
and moves the unchanged kill bytes to an exclusive audit archive.  No order, mode, account, or SSM
API is used.
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
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodes.risk.flags import flag_snapshot, resolve_exact_flags, unresolved_flag_rows


FLAG = "GUARD_FAILED"
SOURCE_ROWS = (
    (1169, 1789484735.5243115,
     "RuntimeError: RuntimeError: incomplete guard snapshot: balance:polymarket: venue did not "
     "return a balance; fills:polymarket: PROJECTION_BATCH_INCOMPLETE: trade read: PolyApiExcepti"),
    (1170, 1789488958.056143,
     "RuntimeError: RuntimeError: incomplete guard snapshot: missing complete fills/positions proof"),
)
SOURCE_IDS = [row[0] for row in SOURCE_ROWS]
EXPECTED_KILL_SHA256 = "dcc4c761ee8fb5f903475e0400b54a0ef57db8246cd7d378d4846cf181c96d83"
EXPECTED_LATCHED_UTC = 1789484735.5242064
EXPECTED_REASON = (
    "guard failed: RuntimeError: RuntimeError: incomplete guard snapshot: "
    "balance:polymarket: venue did not return a balance; fills:polymarket: "
    "PROJECTION_BATCH_INCOMPLETE: trade read: PolyApiExcepti"
)
FULL_SHA256 = re.compile(r"^[0-9a-f]{64}$")
FULL_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")

REQUIRED_TABLES = {
    "lane_flags", "orders", "executions", "capital_reservations", "execution_settlements",
    "pm_post_only_orders", "pm_post_only_admission", "pm_post_only_violations", "socket_health",
}
REQUIRED_COLUMNS = {
    "lane_flags": {"id", "seen_ts", "flag", "detail"},
    "orders": {"venue", "open", "settlement_pending", "state"},
    "executions": {"released", "unhedged", "state"},
    "capital_reservations": {"released_utc"},
    "pm_post_only_orders": {"client_order_id", "terminal_proved", "violated"},
    "pm_post_only_admission": {"slot", "client_order_id", "claimed_utc"},
    "pm_post_only_violations": {"client_order_id", "code", "detail", "seen_utc"},
    "socket_health": {"seen_ts", "venue", "connected"},
}
MATERIAL_FLAGS = (
    "ORDER_PERSISTENCE_FAILED", "POST_ONLY_PERSISTENCE_FAILED", "ORPHAN_FILL",
    "POSITION_MISMATCH", "PROTECT_FAILED", "EXEC_CRASHED", "ORDER_OVERFILL",
    "POST_ONLY_ROLE_VIOLATION", "UNHEDGED_POSITION", "RESERVATION_MISSING",
    "FEE_ABOVE_PIN", "F22_PERSISTENCE_FAILED", FLAG,
)
RESOLUTION_PREFIX = "L133 exact guard-failure-set recovery snapshot_sha256="


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_full(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise RuntimeError(f"{label} must be the complete lowercase digest")
    return value


def _tables_and_columns(con: sqlite3.Connection) -> None:
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = sorted(REQUIRED_TABLES - tables)
    if missing:
        raise RuntimeError("expected safety table missing: " + ",".join(missing))
    for table, required in REQUIRED_COLUMNS.items():
        columns = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
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


def _open_regular(path: Path, label: str) -> tuple[int, os.stat_result]:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise RuntimeError(f"{label} is not a regular non-symlink file") from exc
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        os.close(fd)
        raise RuntimeError(f"{label} is not a regular file")
    return fd, st


def _read_kill(kill_path: Path, expected_digest: str) -> tuple[bytes, dict]:
    _require_full(expected_digest, FULL_SHA256, "kill SHA256")
    if expected_digest != EXPECTED_KILL_SHA256:
        raise RuntimeError("kill SHA256 is not the registered L133 incident digest")
    fd, _ = _open_regular(kill_path, "live kill")
    try:
        with os.fdopen(fd, "rb") as stream:
            raw = stream.read()
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    actual = _sha(raw)
    if actual != expected_digest:
        raise RuntimeError("live kill changed (full SHA256 mismatch)")
    try:
        kill = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("live kill is not valid JSON") from exc
    if not isinstance(kill, dict) or kill.get("reason") != EXPECTED_REASON:
        raise RuntimeError("live kill is not the exact reviewed guard-failure reason")
    if kill.get("latched_utc") != EXPECTED_LATCHED_UTC:
        raise RuntimeError("live kill latched UTC is not the registered incident timestamp")
    return raw, kill


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise RuntimeError("database is missing")
    return sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True, timeout=30)


def _incident(con: sqlite3.Connection, *, resolved: bool = False) -> tuple[list[dict], str]:
    rows = list(con.execute(
        "SELECT id,seen_ts,flag,detail FROM lane_flags WHERE flag=? ORDER BY seen_ts,id", (FLAG,)
    ))
    if len(rows) != len(SOURCE_ROWS):
        raise RuntimeError("GUARD_FAILED source rows are not exactly the registered set 1169,1170")
    for actual, expected in zip(rows, SOURCE_ROWS):
        if (int(actual[0]), float(actual[1]), actual[3] or "") != expected:
            raise RuntimeError(f"GUARD_FAILED source row {expected[0]} changed from its registered snapshot")
    if not resolved and unresolved_flag_rows(con, FLAG) != rows:
        raise RuntimeError("GUARD_FAILED unresolved rows are not exactly the registered set 1169,1170")
    snapshots = [flag_snapshot(row) for row in rows]
    raw = json.dumps(snapshots, sort_keys=True, separators=(",", ":")).encode()
    return snapshots, _sha(raw)


def _valid_exact_resolution_ids(con: sqlite3.Connection, flag: str) -> set[int]:
    """Return IDs covered by cryptographically valid exact markers, never legacy blanket markers."""
    closed: set[int] = set()
    for detail, in con.execute("SELECT detail FROM lane_flags WHERE flag=?", (flag + "_RESOLVED_EXACT",)):
        if not (detail or "").startswith("EXACT_INCIDENTS_V1 "):
            continue
        try:
            payload = json.loads(detail[len("EXACT_INCIDENTS_V1 "):])
            ids = payload["ids"]
            if set(payload) != {"ids", "rows_sha256", "detail"} or not ids \
                    or not all(type(value) is int and value > 0 for value in ids):
                continue
            rows = [con.execute(
                "SELECT id,seen_ts,flag,detail FROM lane_flags WHERE id=? AND flag=?", (value, flag)
            ).fetchone() for value in ids]
            if any(row is None for row in rows):
                continue
            raw = json.dumps([flag_snapshot(row) for row in rows], sort_keys=True,
                             separators=(",", ":")).encode()
            if _sha(raw) == payload["rows_sha256"]:
                closed.update(ids)
        except (KeyError, TypeError, ValueError):
            continue
    return closed


def _post_only_violation_history(con: sqlite3.Connection) -> int:
    """Require every retained violation to have clean terminal state and exact flag resolution."""
    unresolved = 0
    rows = con.execute(
        "SELECT client_order_id,code FROM pm_post_only_violations ORDER BY seen_utc,client_order_id"
    ).fetchall()
    by_flag: dict[str, set[int]] = {}
    for client_id, code in rows:
        marker = con.execute(
            "SELECT terminal_proved,violated FROM pm_post_only_orders WHERE client_order_id=?",
            (client_id,),
        ).fetchone()
        if marker != (1, 0):
            unresolved += 1
            continue
        if code not in by_flag:
            by_flag[code] = _valid_exact_resolution_ids(con, code)
        sources = con.execute(
            "SELECT id FROM lane_flags WHERE flag=? AND instr(COALESCE(detail,''),?)>0",
            (code, str(client_id)),
        ).fetchall()
        if not sources or not any(int(source[0]) in by_flag[code] for source in sources):
            unresolved += 1
    return unresolved


def _quiet(con: sqlite3.Connection, *, allow_source: bool) -> dict:
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
    admissions = int(con.execute(
        "SELECT COUNT(*) FROM pm_post_only_admission WHERE client_order_id IS NOT NULL OR claimed_utc IS NOT NULL"
    ).fetchone()[0])
    # The table is append-only. Historical rows pass only through exact durable flag resolution
    # plus clean terminal maker state; a blanket marker or a clean order row alone is insufficient.
    violations = _post_only_violation_history(con)
    post_only = int(con.execute(
        "SELECT COUNT(*) FROM pm_post_only_orders WHERE terminal_proved IS NOT 1 OR violated IS NOT 0"
    ).fetchone()[0])
    flags: dict[str, list[int]] = {}
    for flag in MATERIAL_FLAGS:
        ids = [int(row[0]) for row in unresolved_flag_rows(con, flag)]
        if allow_source and flag == FLAG and ids == SOURCE_IDS:
            ids = []
        if ids:
            flags[flag] = ids
    if orders or executions or unhedged or reservations or admissions or violations or post_only or flags:
        raise RuntimeError(
            f"safety state not quiet: orders={orders} executions={executions} unhedged={unhedged} "
            f"reservations={reservations} admissions={admissions} violations={violations} "
            f"post_only={post_only} flags={flags}"
        )
    return {"orders": orders, "unreleased_executions": executions, "materially_unhedged": unhedged,
            "unreleased_reservations": reservations, "unresolved_admissions": admissions,
            "post_only_violations": violations, "unresolved_post_only_orders": post_only,
            "material_flags": flags}


def _resolution_marker(con: sqlite3.Connection, snapshot_sha256: str) -> None:
    rows = list(con.execute(
        "SELECT id,seen_ts,flag,detail FROM lane_flags WHERE flag=? ORDER BY seen_ts,id",
        (FLAG + "_RESOLVED_EXACT",),
    ))
    expected = RESOLUTION_PREFIX + snapshot_sha256
    found = False
    for row in rows:
        detail = row[3] or ""
        if not detail.startswith("EXACT_INCIDENTS_V1 "):
            continue
        try:
            payload = json.loads(detail[len("EXACT_INCIDENTS_V1 "):])
        except (TypeError, ValueError):
            continue
        if payload.get("ids") == SOURCE_IDS and payload.get("rows_sha256") == snapshot_sha256 \
                and payload.get("detail") == expected:
            found = True
            break
    if not found:
        raise RuntimeError("exact GUARD_FAILED resolution marker for sources 1169,1170 is missing")
    if unresolved_flag_rows(con, FLAG):
        raise RuntimeError("GUARD_FAILED remains unresolved after exact resolution")


def prove(*, db_path: Path, kill_path: Path, expected_digest: str, release_sha: str,
          repo: Path = Path("."), resolved: bool = False) -> dict:
    """Read-only identity and quiet-state proof; ``resolved`` is used only after the append."""
    _require_full(release_sha, FULL_GIT_SHA, "release SHA")
    if _checkout_sha(repo) != release_sha:
        raise RuntimeError("deployed checkout SHA does not equal requested release SHA")
    raw, kill = _read_kill(kill_path, expected_digest)
    con = _connect_ro(db_path)
    try:
        _tables_and_columns(con)
        snapshots, snapshot_sha256 = _incident(con, resolved=resolved)
        if resolved:
            _resolution_marker(con, snapshot_sha256)
        quiet = _quiet(con, allow_source=not resolved)
    finally:
        con.close()
    return {"schema": "janus.live_clear.guard_failure_set.v1", "kill_sha256": expected_digest,
            "release_sha": release_sha, "reason": EXPECTED_REASON, "latched_utc": EXPECTED_LATCHED_UTC,
            "sources": snapshots, "snapshot_sha256": snapshot_sha256, "global": quiet,
            "kill_raw_b64": base64.b64encode(raw).decode("ascii"), "kill": kill}


def _archive_path(archive_dir: Path, release_sha: str, digest: str) -> Path:
    return archive_dir / f"guard-failure-1169-1170-cleared-{release_sha}-{digest}.json"


def _exclusive_move(src: Path, dst: Path, expected_digest: str) -> None:
    """Archive exact bytes and atomically quarantine the source, restoring on every failure."""
    lock = src.parent / ".guard-failure-1169-1170.lock"
    lock_fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    import fcntl
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        source_fd, opened = _open_regular(src, "live kill")
        try:
            with os.fdopen(os.dup(source_fd), "rb") as stream:
                src_raw = stream.read()
            if _sha(src_raw) != expected_digest:
                raise RuntimeError("live kill changed during archive")
            quarantine = Path(tempfile.mkdtemp(prefix=".guard-failure-1169-1170-", dir=src.parent))
            staged = quarantine / "live"
            archived = False
            try:
                archive_fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    with os.fdopen(archive_fd, "wb") as stream:
                        stream.write(src_raw); stream.flush(); os.fsync(stream.fileno())
                except Exception:
                    try: dst.unlink()
                    except FileNotFoundError: pass
                    raise
                archived = True
                dst_stat = dst.stat(follow_symlinks=False)
                if not stat.S_ISREG(dst_stat.st_mode) or _sha(dst.read_bytes()) != expected_digest:
                    raise RuntimeError("audit archive bytes changed during archive")
                os.rename(src, staged)
                moved = staged.read_bytes()
                moved_stat = staged.stat(follow_symlinks=False)
                if ((moved_stat.st_dev, moved_stat.st_ino) != (opened.st_dev, opened.st_ino)
                        or _sha(moved) != expected_digest):
                    raise RuntimeError("live kill changed during atomic quarantine")
                os.unlink(staged)
            except Exception as original:
                errors = []
                if not src.exists():
                    recovered = False
                    for recovery in (staged, dst if archived else None):
                        if recovery is None or not recovery.exists():
                            continue
                        try:
                            os.link(recovery, src, follow_symlinks=False)
                            recovered = True
                            break
                        except FileExistsError:
                            recovered = True
                            break
                        except OSError as exc:
                            errors.append(f"{recovery}: {type(exc).__name__}: {exc}")
                    if not recovered and not src.exists():
                        raise RuntimeError(
                            "live kill rollback failed; lane must remain stopped; "
                            f"recovery_archive={dst}; errors={errors}"
                        ) from original
                raise
            finally:
                try:
                    if staged.exists() and src.exists(): staged.unlink()
                    quarantine.rmdir()
                except OSError:
                    pass
        finally:
            os.close(source_fd)
    finally:
        try: fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except Exception: pass
        os.close(lock_fd)


def _append_resolution(db_path: Path, proof: dict, *, now: float) -> None:
    con = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    try:
        store = SimpleNamespace(con=con)
        detail = RESOLUTION_PREFIX + proof["snapshot_sha256"]
        acknowledged = list(proof["sources"])
        if not resolve_exact_flags(store, FLAG, acknowledged, detail, now=now,
                                   verify=lambda: _sha(Path(proof["kill_path"]).read_bytes()) == proof["kill_sha256"]):
            raise RuntimeError("exact GUARD_FAILED resolution did not cover only sources 1169,1170")
    finally:
        con.close()


def activate(*, db_path: Path, kill_path: Path, archive_dir: Path, expected_digest: str,
             release_sha: str, repo: Path = Path("."), now: float | None = None) -> Path:
    """Append only the exact resolution, re-prove, then exclusively archive exact kill bytes."""
    already_resolved = False
    try:
        first = prove(db_path=db_path, kill_path=kill_path, expected_digest=expected_digest,
                      release_sha=release_sha, repo=repo)
    except RuntimeError:
        # A prior attempt may have committed the append and then failed while restarting.  The
        # exact marker is itself immutable evidence: accept it only if a resolved proof, including
        # the original source row and current quiet state, succeeds; never blanket-resolve again.
        first = prove(db_path=db_path, kill_path=kill_path, expected_digest=expected_digest,
                      release_sha=release_sha, repo=repo, resolved=True)
        already_resolved = True
    if not already_resolved:
        first["kill_path"] = str(kill_path)
        _append_resolution(db_path, first, now=time.time() if now is None else now)
    final = prove(db_path=db_path, kill_path=kill_path, expected_digest=expected_digest,
                  release_sha=release_sha, repo=repo, resolved=True)
    archive_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(archive_dir, 0o700)
    archive = _archive_path(archive_dir, release_sha, expected_digest)
    if archive.exists():
        raise RuntimeError("exclusive audit archive already exists")
    proof_path = archive.with_suffix(".proof.json")
    evidence = {"before": first, "after": final, "resolved_utc": time.time() if now is None else now}
    fd = os.open(proof_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(evidence, stream, sort_keys=True, indent=2); stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        _exclusive_move(kill_path, archive, expected_digest)
    except Exception:
        try: proof_path.unlink()
        except FileNotFoundError: pass
        raise
    return archive


def restore(*, archive: Path, kill_path: Path, expected_digest: str) -> None:
    """Restore exact archived bytes, never overwriting a changed/new kill."""
    _require_full(expected_digest, FULL_SHA256, "kill SHA256")
    raw = archive.read_bytes()
    if _sha(raw) != expected_digest:
        raise RuntimeError("audit archive bytes do not match expected kill SHA256")
    if kill_path.exists() or kill_path.is_symlink():
        fd, _ = _open_regular(kill_path, "live kill")
        os.close(fd)
        if _sha(kill_path.read_bytes()) != expected_digest:
            raise RuntimeError("refusing to overwrite a changed or new live kill")
        return
    kill_path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{kill_path.name}.restore-", dir=kill_path.parent)
    tmp = Path(name); os.fchmod(fd, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.link(tmp, kill_path, follow_symlinks=False); tmp.unlink()
    except Exception:
        try: tmp.unlink()
        except FileNotFoundError: pass
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
                               expected_digest=args.expected_kill_sha, release_sha=args.release_sha, repo=args.repo)
            print(f"GUARD_FAILURE_1169_1170_CLEAR_COMPLETE archive={archive}")
        return 0
    except (RuntimeError, OSError, sqlite3.Error) as exc:
        print(f"GUARD_FAILURE_1169_1170_CLEAR_BLOCKED: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
