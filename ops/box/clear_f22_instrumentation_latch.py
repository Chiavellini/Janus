#!/usr/bin/env python3
"""Exact, stopped-lane recovery for the F22 zero-fee instrumentation STOP.

This route is intentionally evidence-only: it never edits an F22 decision/order or appends a
resolution row. It archives only the exact retained kill after proving the two historical rows,
that F23 has no rows, and that the current account state is quiet.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path

EXPECTED_KILL_SHA256 = "d81bbfc267a235ca7f268e7317d77ee7e83c65f5263117590e4e86d1552b1636"
EXPECTED_REASON = "F22 STOP: terminal maker zero-fill fee evidence is NULL; strict report classifies persistence_or_reconciliation_failure"
EXPECTED_LATCHED_UTC = 1789504505.261733
# Complete immutable identity of the two F22 observations that caused the registered STOP.  The
# recovery is allowed to remove that one latch only while these exact historical sources remain
# byte-for-byte identifiable; changing a decision and its linked execution together must not pass.
F22_SOURCES = {
    1: {
        "event_id": "pm:wta:1020895",
        "digest": "7cda17ca58a557da5c180cb466a63a8379f5aa61996d75f9070413a2c595940b",
        "sizing_input_hash": "4f13f4a93dea68d3d823c0b4b109bd4d3e24870fc6f3d2983dcb55e7d26ed4f5",
        "sizing_book_epoch": "8afb845ef36a0063d3e713c5394b3546396ad18b65d1d3a7200fbed7bfb59860",
        "selected_quantity": 10.0,
        "execution_id": "785f1ce65f61402c9d940e001be2f41e",
        "opportunity_id": "pm:wta:1020895:moneyline:v1-taker-taker-moneyline:10",
        "first_client_id": "5ea4b87746e746868432b8f566e20551",
        "venue_order_id": "0x7fc2592a720cabd59023d90a760000ee3afa6f944de7da12820ef49e74ca75ab",
    },
    3: {
        "event_id": "pm:atp:1014928",
        "digest": "be189bbb7d4faa68bfad4977f37b2ac0a0e7dfe51e346be0b3e6ce2f55b7eac5",
        "sizing_input_hash": "be22d540aad6ae9ef9cb07a83147e7450c4b27f29ebf7807c01ee2772c7149b8",
        "sizing_book_epoch": "cffa5f0d8734b910531703891f2a58725b8cb0f2bf13f39789efa3d938a7a1f4",
        "selected_quantity": 25.0,
        "execution_id": "9c19f3decab547c69f4cf7844e6a4ee5",
        "opportunity_id": "pm:atp:1014928:moneyline:v1-taker-taker-moneyline:25",
        "first_client_id": "b9aa55c5b6474ab887d6d94f15e2d154",
        "venue_order_id": "0xc6d23a0c2c367bf25aa3e5f3752eb6459b706d438dfe8383d691505369a36ad2",
    },
}
F22_SOURCE_IDS = tuple(F22_SOURCES)
FULL_SHA256 = 64
FULL_GIT_SHA = 40


def _empty_hedge_ids(raw: object) -> bool:
    """Require the source execution's persisted hedge-id field to be an exact empty JSON list."""
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return False
    return parsed == []


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _kill(kill_path: Path, expected_sha: str) -> tuple[bytes, dict]:
    if expected_sha != EXPECTED_KILL_SHA256:
        raise RuntimeError("F22 instrumentation kill digest is not registered")
    raw = kill_path.read_bytes()
    if _sha(raw) != expected_sha:
        raise RuntimeError("live kill changed (full SHA256 mismatch)")
    try:
        payload = json.loads(raw.decode())
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("live kill is not valid JSON") from exc
    if payload.get("reason") != EXPECTED_REASON or payload.get("latched_utc") != EXPECTED_LATCHED_UTC:
        raise RuntimeError("live kill is not the exact F22 instrumentation STOP")
    return raw, payload


def _checkout(repo: Path, release_sha: str) -> None:
    if len(release_sha) != FULL_GIT_SHA or any(c not in "0123456789abcdef" for c in release_sha):
        raise RuntimeError("release SHA must be a complete lowercase Git SHA")
    got = subprocess.run(("git", "-C", str(repo), "rev-parse", "--verify", "HEAD"),
                         capture_output=True, text=True, check=True).stdout.strip()
    if got != release_sha:
        raise RuntimeError("deployed checkout SHA does not equal requested release SHA")


def _quiet(con: sqlite3.Connection) -> dict:
    required = {"f22_decisions", "executions", "orders", "capital_reservations", "pm_post_only_orders",
                "pm_post_only_admission"}
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError("expected recovery table missing: " + ",".join(missing))
    decisions = con.execute(
        "SELECT id,event_id,forward_row_id,assignment_algorithm,digest,arm,sizing_input_hash,"
        "sizing_occurrence,sizing_book_epoch,selected_quantity,execution_id "
        "FROM f22_decisions WHERE id IN (?,?) ORDER BY id", F22_SOURCE_IDS).fetchall()
    if len(decisions) != 2 or tuple(r[0] for r in decisions) != F22_SOURCE_IDS:
        raise RuntimeError("F22 source decisions are not exactly rows 1 and 3")
    source = []
    for d in decisions:
        expected = F22_SOURCES[d[0]]
        if (d[1] != expected["event_id"] or d[2] != "F22"
                or d[3] != "janus:f22:entry-arm:v1" or d[4] != expected["digest"]
                or d[5] != "maker" or d[6] != expected["sizing_input_hash"]
                or d[7] != 1 or d[8] != expected["sizing_book_epoch"]
                or float(d[9]) != expected["selected_quantity"]
                or d[10] != expected["execution_id"]):
            raise RuntimeError("F22 source decision identity changed")
        ex = con.execute(
            "SELECT execution_id,event_id,opportunity_id,state,first_client_id,hedge_client_ids,first_filled,hedge_filled,unhedged,released "
            "FROM executions WHERE execution_id=?", (expected["execution_id"],)).fetchone()
        if (ex is None or ex[0] != expected["execution_id"] or ex[1] != expected["event_id"]
                or ex[1] != d[1] or ex[2] != expected["opportunity_id"] or ex[3] != "ORDER_UNFILLED"
                or ex[4] != expected["first_client_id"] or not _empty_hedge_ids(ex[5])
                or float(ex[6] or 0) != 0 or float(ex[7] or 0) != 0 or float(ex[8] or 0) != 0
                or not ex[9]):
            raise RuntimeError(f"F22 source execution {expected['execution_id']} changed")
        orders = con.execute(
            "SELECT client_order_id,venue,venue_order_id,state,filled_contracts,avg_price,fee_usd,open,settlement_pending "
            "FROM orders WHERE execution_id=? ORDER BY client_order_id", (expected["execution_id"],)).fetchall()
        pm = [o for o in orders if o[1] == "polymarket"]
        if len(orders) != 1 or len(pm) != 1 or pm[0][0] != expected["first_client_id"] \
                or pm[0][0] != ex[4] or pm[0][2] != expected["venue_order_id"] \
                or pm[0][3] not in {"UNFILLED", "ORDER_UNFILLED"} \
                or float(pm[0][4] or 0) != 0 or pm[0][5] is not None or pm[0][6] is not None \
                or pm[0][7] or pm[0][8]:
            raise RuntimeError(f"F22 source order for {expected['execution_id']} is not unchanged NULL-fee zero-fill")
        marker = con.execute(
            "SELECT terminal_proved,violated FROM pm_post_only_orders WHERE client_order_id=?", (pm[0][0],)
        ).fetchone()
        if marker != (1, 0):
            raise RuntimeError(f"F22 source maker proof for {pm[0][0]} changed")
        source.append({"decision": d, "execution": ex, "orders": orders, "maker_marker": marker})
    f23_count = 0
    if "f23_decisions" in tables:
        f23_count = int(con.execute("SELECT COUNT(*) FROM f23_decisions").fetchone()[0])
    if f23_count:
        raise RuntimeError("F23 decisions exist; recovery must not activate a mixed cohort")
    orders = int(con.execute("SELECT COUNT(*) FROM orders WHERE open IS NOT 0 OR settlement_pending IS NOT 0 OR state='UNCONFIRMED'").fetchone()[0])
    flight = int(con.execute("SELECT COUNT(*) FROM executions WHERE released IS NOT 1").fetchone()[0])
    unhedged = int(con.execute("SELECT COUNT(*) FROM executions WHERE released IS NOT 1 AND ABS(COALESCE(unhedged,0)) > 0.01").fetchone()[0])
    reservations = int(con.execute("SELECT COUNT(*) FROM capital_reservations WHERE released_utc IS NULL").fetchone()[0])
    admission = con.execute("SELECT client_order_id FROM pm_post_only_admission WHERE slot=1").fetchone()
    if orders or flight or unhedged or reservations or admission is None or admission[0] is not None:
        raise RuntimeError(f"account state is not quiet: orders={orders} flight={flight} unhedged={unhedged} reservations={reservations}")
    return {"f22_sources": source, "f23_decisions": f23_count,
            "zero_flight": flight == 0, "zero_unhedged": unhedged == 0,
            "zero_unreleased_capital": reservations == 0, "open_orders": orders}


def prove(*, db_path: Path, kill_path: Path, expected_digest: str, release_sha: str, repo: Path) -> dict:
    _checkout(repo, release_sha)
    raw, payload = _kill(kill_path, expected_digest)
    con = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        quiet = _quiet(con)
    finally:
        con.close()
    return {"schema": "janus.live_clear.f22_instrumentation.v1", "kill_sha256": expected_digest,
            "release_sha": release_sha, "kill": payload, "kill_raw_b64": base64.b64encode(raw).decode(),
            "reason": EXPECTED_REASON, "latched_utc": EXPECTED_LATCHED_UTC, "global": quiet}


def activate(*, db_path: Path, kill_path: Path, archive_dir: Path, expected_digest: str,
             release_sha: str, repo: Path) -> Path:
    before = prove(db_path=db_path, kill_path=kill_path, expected_digest=expected_digest,
                   release_sha=release_sha, repo=repo)
    archive_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(archive_dir, 0o700)
    archive = archive_dir / f"f22-instrumentation-{release_sha}-{expected_digest}.json"
    if archive.exists():
        raise RuntimeError("exclusive F22 instrumentation archive already exists")
    archive.write_text(json.dumps(before, sort_keys=True, indent=2) + "\n")
    os.chmod(archive, 0o600)
    moved = False
    try:
        raw, _ = _kill(kill_path, expected_digest)
        tmp = kill_path.with_name(".f22-instrumentation-kill-quarantine")
        os.rename(kill_path, tmp)
        moved = True
        if _sha(tmp.read_bytes()) != expected_digest:
            os.rename(tmp, kill_path)
            moved = False
            raise RuntimeError("live kill changed during archive")
        tmp.unlink()
    except Exception:
        if moved and not kill_path.exists():
            candidate = kill_path.with_name(".f22-instrumentation-kill-quarantine")
            if candidate.exists():
                os.rename(candidate, kill_path)
        try:
            archive.unlink()
        except FileNotFoundError:
            pass
        raise
    return archive


def restore(*, archive: Path, kill_path: Path, expected_digest: str) -> None:
    raw = base64.b64decode(json.loads(archive.read_text())["kill_raw_b64"], validate=True)
    if _sha(raw) != expected_digest or expected_digest != EXPECTED_KILL_SHA256:
        raise RuntimeError("archive does not contain the exact registered kill")
    if kill_path.exists():
        if _sha(kill_path.read_bytes()) != expected_digest:
            raise RuntimeError("refusing to overwrite changed live kill")
        return
    kill_path.write_bytes(raw)
    os.chmod(kill_path, 0o600)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    for cmd in ("prove", "activate"):
        p = sub.add_parser(cmd); p.add_argument("--db", type=Path, required=True); p.add_argument("--kill", type=Path, required=True)
        p.add_argument("--expected-kill-sha", required=True); p.add_argument("--release-sha", required=True); p.add_argument("--repo", type=Path, required=True)
        if cmd == "activate": p.add_argument("--archive-dir", type=Path, required=True)
    p = sub.add_parser("restore"); p.add_argument("--archive", type=Path, required=True); p.add_argument("--kill", type=Path, required=True); p.add_argument("--expected-kill-sha", required=True)
    a = ap.parse_args(argv)
    try:
        if a.command == "prove": prove(db_path=a.db, kill_path=a.kill, expected_digest=a.expected_kill_sha, release_sha=a.release_sha, repo=a.repo)
        elif a.command == "activate": print(activate(db_path=a.db, kill_path=a.kill, archive_dir=a.archive_dir, expected_digest=a.expected_kill_sha, release_sha=a.release_sha, repo=a.repo))
        else: restore(archive=a.archive, kill_path=a.kill, expected_digest=a.expected_kill_sha)
        return 0
    except (RuntimeError, OSError, sqlite3.Error) as exc:
        print(f"F22_INSTRUMENTATION_RECOVERY_BLOCKED: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
