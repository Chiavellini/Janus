"""Lane flags: a fact the lane noticed that the watchdog must repeat until a human acts.

The first one (2026-09-07) is CAP_BINDS_SMALLEST: the override's cap refused a cover at the
SMALLEST quantity the lane prices. By the operator's rule ("the smallest amount that doesn't cause
fill failures") that is a misconfiguration, not a limit, and it must never be silent. One table,
append-only; the watchdog reads the last day."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

FLAGS_DDL = """
CREATE TABLE IF NOT EXISTS lane_flags(
  id INTEGER PRIMARY KEY AUTOINCREMENT, seen_ts REAL NOT NULL, flag TEXT NOT NULL, detail TEXT);
CREATE INDEX IF NOT EXISTS lane_flags_ts ON lane_flags(flag, seen_ts);
"""


def raise_flag(store, flag: str, detail: str = "", *, now: float | None = None) -> None:
    store.ensure_ddl(FLAGS_DDL)
    store.con.execute("INSERT INTO lane_flags(seen_ts, flag, detail) VALUES(?,?,?)", (now or time.time(), flag, detail[:300]))
    store.con.commit()


def resolve_flag(store, flag: str, detail: str = "", *, now: float | None = None) -> bool:
    """Append a resolution marker when `flag` currently has an unresolved occurrence.

    Flags are an audit log, so a false or no-longer-current alarm is never deleted. The marker
    makes the watchdog quiet without rewriting history. Returns False when the latest marker is
    already a resolution, which keeps periodic healthy passes from growing the table forever.
    """
    store.ensure_ddl(FLAGS_DDL)
    resolved = f"{flag}_RESOLVED"
    row = store.con.execute(
        "SELECT flag FROM lane_flags WHERE flag IN (?,?) ORDER BY seen_ts DESC, id DESC LIMIT 1",
        (flag, resolved),
    ).fetchone()
    if row is None or row[0] == resolved:
        return False
    store.con.execute("INSERT INTO lane_flags(seen_ts, flag, detail) VALUES(?,?,?)",
                      (now or time.time(), resolved, detail[:300]))
    store.con.commit()
    return True


def recent_flags(db_path: Path | str, flag: str, *, since_s: float = 24 * 3600, now: float | None = None) -> list[tuple[float, str]]:
    """Unresolved `(seen_ts, detail)` rows of `flag` in the recent window.

    A later `<FLAG>_RESOLVED` marker suppresses older occurrences while preserving them in the
    append-only table. A new occurrence after that marker becomes visible again.
    """
    t = now or time.time()
    p = Path(db_path)
    if not p.exists():
        return []
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='lane_flags'").fetchall():
            return []
        resolved = f"{flag}_RESOLVED"
        marker = con.execute("SELECT MAX(seen_ts) FROM lane_flags WHERE flag=?", (resolved,)).fetchone()[0]
        floor = max(t - since_s, float(marker or 0.0))
        return con.execute("SELECT seen_ts, detail FROM lane_flags WHERE flag=? AND seen_ts > ? ORDER BY seen_ts DESC",
                           (flag, floor)).fetchall()
    finally:
        con.close()
