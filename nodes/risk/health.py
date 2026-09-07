#!/usr/bin/env python3
"""Risk state as watchdog alarms. Each has a firing test in ops/watchdog.selftest, per the
GATE_TO_LIVE rule that a monitor which has never emitted is untested."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from kernel.schema import ExecutionState
from nodes.risk.breaker import BREAKER_PATH
from nodes.risk.gate import override_state, stale_reason
from nodes.risk.kill import KILL_ROOT

from kernel.paths import DB as DEFAULT_DB  # noqa: E402,F401
MAX_UNRECONCILED_S = 15 * 60
#: The box's systemd drop-in (ops/box/mode.sh). Its `--mode` is what the lane will start in; the
#: override checks below run only while it says a capital-risking mode. Absent on the Mac.
MODE_CONF = Path("/etc/systemd/system/janus-live-stream.service.d/mode.conf")
OVERRIDE_EXPIRING_S = 24 * 3600
ROOT = Path(__file__).resolve().parents[2]


def armed_mode(mode_conf: Path | str) -> str | None:
    """The `--mode` the drop-in names, or None when there is no drop-in (or it names none)."""
    p = Path(mode_conf)
    if not p.exists():
        return None
    try:
        words = p.read_text().split()
    except OSError:
        return None
    for i, w in enumerate(words):
        if w == "--mode" and i + 1 < len(words):
            return words[i + 1]
    return None


def override_alerts(*, override_path: Path | str, mode_conf: Path | str = MODE_CONF,
                    code_sha: str | None = None, limits_sha: str | None = None,
                    expiring_s: float = OVERRIDE_EXPIRING_S, now: float | None = None) -> list[str]:
    """OVERRIDE_STALE: the drop-in says LIMITED_LIVE (or PRODUCTION) and the override has expired,
    is missing, or pins another code tree or other limits: the lane refuses real orders
    (ARM_STALE) and a restart would not arm. OVERRIDE_EXPIRING: under `expiring_s` left, so the
    day's release paste (ops/box/release.sh) happens before it lapses. Silent without a drop-in
    (the Mac) or under a paper drop-in. `code_sha`/`limits_sha` None means read the checkout
    and limits.toml here; the selftest passes them."""
    mode = armed_mode(mode_conf)
    if mode not in ("LIMITED_LIVE", "PRODUCTION"):
        return []
    if code_sha is None:
        from kernel.code_sha import code_tree_sha
        code_sha = code_tree_sha(ROOT)
    if limits_sha is None:
        from nodes.risk.limits import load_limits
        limits_sha = load_limits().sha
    st = override_state(override_path, code_sha=code_sha, limits_sha=limits_sha, now=now)
    why = stale_reason(st, code_sha=code_sha, limits_sha=limits_sha)
    if why:
        return [f"risk: OVERRIDE_STALE — the drop-in says {mode} but the {why}; real orders are refused "
                "(ARM_STALE) and a restart would not arm: ops/box/release.sh <sha>"]
    left = float(st["seconds_left"] or 0.0)
    if left < expiring_s:
        return [f"risk: OVERRIDE_EXPIRING — {left / 3600:.1f} h left (expires {st['expires_utc']}); "
                "ops/box/release.sh <sha> before it lapses"]
    return []


def risk_alerts(*, kill_root: Path | str = KILL_ROOT, breaker_path: Path | str = BREAKER_PATH,
                db_path: Path | str = DEFAULT_DB, max_unreconciled_s: float = MAX_UNRECONCILED_S,
                override_path: Path | str | None = None, mode_conf: Path | str = MODE_CONF,
                code_sha: str | None = None, limits_sha: str | None = None,
                now: float | None = None) -> list[str]:
    t = time.time() if now is None else now
    out: list[str] = []
    root = Path(kill_root)
    out.extend(override_alerts(override_path=Path(override_path) if override_path else root / "arming_override.json",
                               mode_conf=mode_conf, code_sha=code_sha, limits_sha=limits_sha, now=t))
    if root.exists():
        present = sorted(p.name for p in root.iterdir() if p.is_file() and p.name != Path(breaker_path).name
                         and p.name != "arming_override.json")
        if present:
            out.append(f"risk: KILL_FILE_PRESENT — {', '.join(present)}")
    bp = Path(breaker_path)
    if bp.exists():
        try:
            d = json.loads(bp.read_text() or "{}")
        except ValueError:
            d = {"latched": True, "reason": "breaker state file unreadable (treated as latched)"}
        if d.get("latched"):
            out.append(f"risk: BREAKER_LATCHED — {d.get('reason', '')}")
    dbp = Path(db_path)
    if dbp.exists():
        try:
            con = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
            rows = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='capital_reservations'").fetchall()
            if rows:
                # A reservation behind a HEDGED (or settled, awaiting release) execution is committed
                # capital held to the game's settlement, not an unreconciled fill; the settlement
                # pass releases it when the venues resolve (2026-09-04). Only the rest are late.
                has_ex = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='executions'").fetchall()
                held = "', '".join(["HEDGED", "SETTLED", *sorted(x.value for x in ExecutionState if x.holds_position)])
                q = ("SELECT MIN(r.created_utc) FROM capital_reservations r LEFT JOIN executions e ON e.reservation_id = r.reservation_id "
                     f"WHERE r.released_utc IS NULL AND (e.state IS NULL OR e.state NOT IN ('{held}'))") if has_ex else \
                    "SELECT MIN(created_utc) FROM capital_reservations WHERE released_utc IS NULL"
                oldest = con.execute(q).fetchone()[0]
                if oldest is not None and t - oldest > max_unreconciled_s:
                    out.append(f"risk: UNRECONCILED_TOO_LONG — a reservation has been open {int(t - oldest)}s "
                               f"(limit {int(max_unreconciled_s)}s); both venues must reconcile before release")
                # UNHEDGED_POSITION: leg A filled, the hedge did not (fully), capital still held. This is
                # the forward paper row's STOP condition (F3 spec: "one unhedged paper leg is a STOP and a
                # design finding"), so it alarms at once, one line per execution, until the settlement
                # pass marks it and releases it (2026-09-05, MIL @ CIN 35.82 unhedged for three hours).
                if has_ex:
                    cols = {r[1] for r in con.execute("PRAGMA table_info(executions)").fetchall()}
                    if {"first_filled", "unhedged", "event_id", "last_utc"} <= cols:
                        holding = "', '".join(sorted(x.value for x in ExecutionState if x.holds_position))
                        for row in con.execute(
                                "SELECT execution_id, event_id, state, unhedged, first_filled, last_utc FROM executions "
                                f"WHERE released = 0 AND first_filled > 0 AND state IN ('{holding}') ORDER BY last_utc").fetchall():
                            out.append(f"risk: UNHEDGED_POSITION — {row[0][:8]} {row[1]} {row[2]} {row[3]:g}/{row[4]:g} "
                                       f"unhedged for {int(t - (row[5] or t))}s (the paper row's STOP condition)")
            con.close()
        except sqlite3.Error as exc:
            out.append(f"risk: LEDGER_UNREADABLE — {type(exc).__name__}")
    return out
