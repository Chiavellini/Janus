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


def recent_flags(db_path: Path | str, flag: str, *, since_s: float = 24 * 3600, now: float | None = None) -> list[tuple[float, str]]:
    """(seen_ts, detail) rows of `flag` in the last `since_s`, newest first; [] when the table is absent."""
    t = now or time.time()
    p = Path(db_path)
    if not p.exists():
        return []
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='lane_flags'").fetchall():
            return []
        return con.execute("SELECT seen_ts, detail FROM lane_flags WHERE flag=? AND seen_ts > ? ORDER BY seen_ts DESC",
                           (flag, t - since_s)).fetchall()
    finally:
        con.close()
