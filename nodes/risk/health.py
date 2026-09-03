#!/usr/bin/env python3
"""Risk state as watchdog alarms. Each has a firing test in ops/watchdog.selftest, per the
GATE_TO_LIVE rule that a monitor which has never emitted is untested."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from nodes.risk.breaker import BREAKER_PATH
from nodes.risk.kill import KILL_ROOT

DEFAULT_DB = Path("/Volumes/Kilos/janus/tuples/tuples.sqlite")
MAX_UNRECONCILED_S = 15 * 60


def risk_alerts(*, kill_root: Path | str = KILL_ROOT, breaker_path: Path | str = BREAKER_PATH,
                db_path: Path | str = DEFAULT_DB, max_unreconciled_s: float = MAX_UNRECONCILED_S,
                now: float | None = None) -> list[str]:
    t = time.time() if now is None else now
    out: list[str] = []
    root = Path(kill_root)
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
                oldest = con.execute("SELECT MIN(created_utc) FROM capital_reservations WHERE released_utc IS NULL").fetchone()[0]
                if oldest is not None and t - oldest > max_unreconciled_s:
                    out.append(f"risk: UNRECONCILED_TOO_LONG — a reservation has been open {int(t - oldest)}s "
                               f"(limit {int(max_unreconciled_s)}s); both venues must reconcile before release")
            con.close()
        except sqlite3.Error as exc:
            out.append(f"risk: LEDGER_UNREADABLE — {type(exc).__name__}")
    return out
