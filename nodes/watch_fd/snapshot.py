#!/usr/bin/env python3
"""A daily snapshot of football-data.org's fixture lists: the forward source for soccer's
postponement and cancellation rates (ledger F6), and a TRUE original-kickoff source for the
leagues L33/L35 measured by a round-window proxy labelled FLOOR.

football-data.org v4 carries the status flags (SCHEDULED, TIMED, POSTPONED, CANCELLED, AWARDED,
FINISHED) but REWRITES utcDate in place when a match moves (research/sports/2026-09-03_soccer-
settlement-wedge-rates/DESIGN.md). So, as nodes/watch_settle does for tennis, the first-seen
kickoff is recorded ONCE and never overwritten; the live value lands in `utc_date_last`. A match
whose kickoff moved more than 48 h from its first-seen value, or whose status ended CANCELLED, is
what the wedge prices.

Coverage is the free tier's: PL (epl), ELC (elc), PD (lal), BL1 (bun), SA (ita), FL1 (fl1),
DED (ere), PPL (por). MLS, the Scottish Premiership, the Belgian Pro League and League One are
NOT on it; they stay blocked by name until another source exists. The token is the operator's
(`FD_TOKEN` in the credentials env); without it nothing runs and nothing is guessed.

Reads no price, claims no edge.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Iterable, Mapping

FD_BASE = "https://api.football-data.org/v4"
#: football-data.org competition code -> Janus league code (the free tier, 2026-09-05)
COMPETITIONS: dict[str, str] = {"PL": "epl", "ELC": "elc", "PD": "lal", "BL1": "bun", "SA": "ita",
                                "FL1": "fl1", "DED": "ere", "PPL": "por"}
MOVED_S = 48 * 3600.0
TERMINAL = ("FINISHED", "AWARDED", "CANCELLED")

FD_MATCHES_DDL = """
CREATE TABLE IF NOT EXISTS fd_matches(
  competition TEXT NOT NULL, league TEXT NOT NULL, match_id INTEGER NOT NULL, season TEXT, matchday INTEGER,
  home TEXT, away TEXT, first_seen_ts REAL NOT NULL, utc_date_first REAL, utc_date_last REAL,
  status_first TEXT, status_last TEXT, last_updated TEXT, last_seen_ts REAL NOT NULL,
  PRIMARY KEY(competition, match_id));
CREATE INDEX IF NOT EXISTS fd_matches_league ON fd_matches(league, status_last);
"""


def _ts(iso: str | None) -> float | None:
    if not iso:
        return None
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def fetch_matches(code: str, cl, *, token: str) -> list[dict]:
    """GET /v4/competitions/{code}/matches for the current season. The token goes in the header,
    never the URL. Returns the venue's match dicts as they are."""
    if not token:
        raise ValueError("FD_TOKEN is not set: the snapshotter refuses to run without the operator's token")
    d = cl.get_json(f"{FD_BASE}/competitions/{code}/matches", headers={"X-Auth-Token": token}, use_cache=False)
    return list((d or {}).get("matches") or [])


def record(store, code: str, matches: Iterable[Mapping], *, now: float | None = None) -> int:
    """Upsert one row per match. first_seen_ts, utc_date_first and status_first are set ONCE; the
    live kickoff, status and lastUpdated refresh every pass. Returns rows touched."""
    t = now or time.time()
    league = COMPETITIONS.get(code, code.lower())
    store.ensure_ddl(FD_MATCHES_DDL)
    n = 0
    for m in matches:
        mid = m.get("id")
        if mid is None:
            continue
        kick = _ts(m.get("utcDate"))
        status = m.get("status")
        store.con.execute(
            "INSERT INTO fd_matches(competition, league, match_id, season, matchday, home, away, first_seen_ts, utc_date_first, "
            "utc_date_last, status_first, status_last, last_updated, last_seen_ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(competition, match_id) DO UPDATE SET utc_date_last=excluded.utc_date_last, status_last=excluded.status_last, "
            "last_updated=excluded.last_updated, last_seen_ts=excluded.last_seen_ts, matchday=COALESCE(excluded.matchday, fd_matches.matchday)",
            (code, league, int(mid), str((m.get("season") or {}).get("startDate") or "")[:4] or None, m.get("matchday"),
             (m.get("homeTeam") or {}).get("name"), (m.get("awayTeam") or {}).get("name"), t, kick, kick, status, status,
             m.get("lastUpdated"), t))
        n += 1
    return n


def rates(store) -> dict[str, dict]:
    """Per league: matches first seen as scheduled, those since terminal, moved > 48 h from the
    first-seen kickoff, cancelled -- and the two rates over the TERMINAL denominator. A match still
    open is not a denominator: it may yet move."""
    store.ensure_ddl(FD_MATCHES_DDL)
    out: dict[str, dict] = {}
    for league, n_all, n_term, moved, cancelled in store.con.execute(
            "SELECT league, COUNT(*), SUM(status_last IN ('FINISHED','AWARDED','CANCELLED')), "
            "SUM(status_last IN ('FINISHED','AWARDED','CANCELLED') AND utc_date_first IS NOT NULL AND utc_date_last IS NOT NULL "
            f"AND ABS(utc_date_last - utc_date_first) > {MOVED_S}), "
            "SUM(status_last = 'CANCELLED') FROM fd_matches GROUP BY league ORDER BY league"):
        n_term = int(n_term or 0)
        out[league] = {"matches": int(n_all), "terminal": n_term, "moved_gt48h": int(moved or 0), "cancelled": int(cancelled or 0),
                       "postponed_gt48h_rate": round(int(moved or 0) / n_term, 6) if n_term else None,
                       "cancelled_rate": round(int(cancelled or 0) / n_term, 6) if n_term else None}
    return out
