#!/usr/bin/env python3
"""Clear only the proven false post-only terminality latch, while the lane is stopped.

This is intentionally narrower than a general kill-switch command.  It requires the exact file
digest captured at release start, the matching maker journal to be terminal-zero and unviolated,
the matching execution to be released and unfilled, and the whole execution store to be quiet.
The original latch and every proof are archived before the switch is removed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from nodes.risk.flags import unresolved_flag_rows


ACTIVE_STATES = (
    "DETECTED", "VALIDATED", "CAPITAL_RESERVED", "LEG_A_SUBMITTED", "LEG_A_FILLED",
    "LEG_A_PARTIAL", "LEG_B_SUBMITTED", "LEG_B_PARTIAL",
)
MATERIAL_FLAGS = (
    "ORDER_PERSISTENCE_FAILED", "POST_ONLY_PERSISTENCE_FAILED", "ORPHAN_FILL",
    "POSITION_MISMATCH", "PROTECT_FAILED", "EXEC_CRASHED", "ORDER_OVERFILL",
    "POST_ONLY_ROLE_VIOLATION", "UNHEDGED_POSITION", "RESERVATION_MISSING",
    "F22_PERSISTENCE_FAILED", "F23_PERSISTENCE_FAILED",
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def audit_and_clear(*, db_path: Path, kill_path: Path, archive_dir: Path,
                    expected_digest: str, release_sha: str, now: float | None = None,
                    retain_kill: bool = False) -> Path:
    raw = kill_path.read_bytes()
    actual = _sha(raw)
    if actual != expected_digest:
        raise RuntimeError(f"live kill changed during release ({actual[:12]} != {expected_digest[:12]})")
    try:
        kill = json.loads(raw)
    except ValueError as exc:
        raise RuntimeError("live kill is not valid JSON") from exc
    reason = str(kill.get("reason", ""))
    if not (reason.startswith("unknown provider state:")
            and "post-only cancel/late-fill lifecycle unresolved:" in reason):
        raise RuntimeError("live kill is not the reviewed false maker-terminality signature")
    ids = re.findall(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])", reason.lower())
    if not ids:
        raise RuntimeError("false maker latch names no exact client order id")
    client_id = ids[-1]

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        marker = con.execute(
            "SELECT client_order_id,venue_order_id,terminal_proved,terminal_fingerprint,violated "
            "FROM pm_post_only_orders WHERE client_order_id=?", (client_id,)).fetchone()
        if marker is None or int(marker["terminal_proved"] or 0) != 1 or int(marker["violated"] or 0) != 0:
            raise RuntimeError("matching post-only order lacks clean terminal proof")
        fingerprint = str(marker["terminal_fingerprint"] or "")
        if "CANCELED" not in fingerprint.upper() or not re.search(r'(^|[^0-9])0(?:\.0+)?([^0-9]|$)', fingerprint):
            raise RuntimeError("matching post-only proof is not terminal zero-fill")
        unresolved = int(con.execute(
            "SELECT COUNT(*) FROM pm_post_only_orders WHERE terminal_proved=0 OR violated=1").fetchone()[0])
        open_orders = int(con.execute(
            "SELECT COUNT(*) FROM orders WHERE venue='polymarket' AND (open=1 OR state='UNCONFIRMED')").fetchone()[0])
        active = int(con.execute(
            "SELECT COUNT(*) FROM executions WHERE released=0 AND state IN (" + ",".join("?" for _ in ACTIVE_STATES) + ")",
            ACTIVE_STATES).fetchone()[0])
        unhedged = int(con.execute(
            "SELECT COUNT(*) FROM executions WHERE ABS(COALESCE(unhedged,0)) > 0.01 AND released=0").fetchone()[0])
        flagged = {flag: [int(row[0]) for row in unresolved_flag_rows(con, flag)]
                   for flag in MATERIAL_FLAGS}
        flagged = {flag: ids for flag, ids in flagged.items() if ids}
        execution = con.execute(
            "SELECT execution_id,state,first_filled,hedge_filled,unhedged,released,last_utc "
            "FROM executions WHERE first_client_id=? ORDER BY last_utc DESC LIMIT 1", (client_id,)).fetchone()
        if unresolved or open_orders or active or unhedged or flagged:
            raise RuntimeError(f"money/state not quiet: unresolved={unresolved} open_orders={open_orders} "
                               f"active={active} unhedged={unhedged} flags={flagged}")
        if (execution is None or execution["state"] != "ORDER_UNFILLED"
                or float(execution["first_filled"] or 0) != 0
                or float(execution["hedge_filled"] or 0) != 0
                or float(execution["unhedged"] or 0) != 0 or not int(execution["released"] or 0)):
            raise RuntimeError("matching execution is not a released zero-fill terminal")
        proof = {
            "schema": "janus.live_clear.false_maker.v1", "release_sha": release_sha,
            "cleared_utc": time.time() if now is None else now, "kill_sha256": actual,
            "kill": kill, "kill_raw_b64": base64.b64encode(raw).decode("ascii"),
            "client_order_id": client_id, "maker_marker": dict(marker),
            "execution": dict(execution), "global": {"unresolved_post_only": unresolved,
                "open_pm_orders": open_orders, "active_executions": active,
                "unhedged_executions": unhedged, "material_flags": flagged},
        }
    finally:
        con.close()

    archive_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(archive_dir, 0o700)
    # Include the captured digest so a later false incident on the same deployed SHA cannot
    # overwrite the earlier audit.  A retry of the identical incident deterministically reuses it.
    archive = archive_dir / f"live-cleared-{release_sha}-{actual[:12]}.json"
    tmp = archive.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(proof, sort_keys=True, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, archive)
    if not retain_kill:
        kill_path.unlink()
    return archive


def restore(*, archive: Path, kill_path: Path) -> None:
    proof = json.loads(archive.read_text())
    kill_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = kill_path.with_suffix(".restore")
    encoded = proof.get("kill_raw_b64")
    raw = base64.b64decode(encoded, validate=True) if encoded else (
        json.dumps(proof["kill"], separators=(",", ":")) + "\n").encode()
    tmp.write_bytes(raw)
    os.chmod(tmp, 0o600)
    owner = kill_path.parent.stat()
    os.chown(tmp, owner.st_uid, owner.st_gid)
    os.replace(tmp, kill_path)


def activate(*, archive: Path, kill_path: Path, expected_digest: str) -> None:
    """Remove the retained kill only after post-start health has been proved."""
    raw = kill_path.read_bytes()
    actual = _sha(raw)
    if actual != expected_digest:
        raise RuntimeError(f"live kill changed during warm-up ({actual[:12]} != {expected_digest[:12]})")
    proof = json.loads(archive.read_text())
    if proof.get("kill_sha256") != actual:
        raise RuntimeError("archived proof does not bind the retained live kill")
    kill_path.unlink()


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    clear = sub.add_parser("clear")
    clear.add_argument("--db", type=Path, default=Path("/srv/janus/tuples/tuples.sqlite"))
    clear.add_argument("--kill", type=Path, default=Path("/srv/janus/kill/live"))
    clear.add_argument("--archive-dir", type=Path, default=Path("/srv/janus/release-audit/L64"))
    clear.add_argument("--expected-digest", required=True)
    clear.add_argument("--release-sha", required=True)
    clear.add_argument("--retain", action="store_true")
    recover = sub.add_parser("restore")
    recover.add_argument("--archive", type=Path, required=True)
    recover.add_argument("--kill", type=Path, default=Path("/srv/janus/kill/live"))
    live = sub.add_parser("activate")
    live.add_argument("--archive", type=Path, required=True)
    live.add_argument("--kill", type=Path, default=Path("/srv/janus/kill/live"))
    live.add_argument("--expected-digest", required=True)
    args = ap.parse_args()
    if args.command == "restore":
        restore(archive=args.archive, kill_path=args.kill)
        return 0
    if args.command == "activate":
        activate(archive=args.archive, kill_path=args.kill, expected_digest=args.expected_digest)
        return 0
    archive = audit_and_clear(db_path=args.db, kill_path=args.kill, archive_dir=args.archive_dir,
                              expected_digest=args.expected_digest, release_sha=args.release_sha,
                              retain_kill=args.retain)
    print(f"STOPPED_EXACT_STATE_OK archive={archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
