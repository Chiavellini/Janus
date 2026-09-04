#!/usr/bin/env python3
"""Settlement timing for capture-only events: when did the venue list the match for, and when
did it resolve? The forward source for `tennis.delayed_gt7d_rate` (ledger F4).

No results archive keeps a match's SCHEDULED date (L39), so the only honest measurement is
forward: record each event's `gameStartTime` the first time the lane sees it, and later the
venue's resolution. Two caveats, stated once here and in every row that reads this table:

  1. `start_utc` is IMMUTABLE after first sight. Polymarket rewrites gameStartTime in place on
     the same slug when a match moves; the live value lands in `start_utc_last`. Reading the
     current value would make every postponement measure as zero delay.
  2. `resolved_seen_ts` is when WE polled, not when the venue resolved. The daily cadence puts a
     +-24 h box around it -- harmless against a 7-day threshold, but it is a poll time.

`result` is one of: the winning outcome label; "HALF" (closed at 0.5 / 0.5: a walkover or a
match not played inside the venue's window -- the case the wedge prices); NULL while open.

Writes: `record_watch` from the supervisor's apply_watch (on the loop, same transaction as the
slate). `resolve_pending` from a daily oneshot (research/sports/2026-09-04_tennis-delay-forward).
Reads no price, claims no edge.
"""
from __future__ import annotations

import json
import time
from typing import Iterable, Sequence

from nodes.discovery.census import GameEvent
from nodes.reconcile.results import PM_GAMMA

WATCH_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS watch_events(
  event_id TEXT NOT NULL, venue TEXT NOT NULL, league_hint TEXT,
  first_seen_ts REAL NOT NULL, start_utc REAL, start_utc_last REAL, participants TEXT,
  last_seen_ts REAL NOT NULL, last_checked_ts REAL, resolved_seen_ts REAL, result TEXT, resolve_note TEXT,
  PRIMARY KEY(venue, event_id));
CREATE INDEX IF NOT EXISTS watch_events_open ON watch_events(resolved_seen_ts, start_utc);
"""


def league_hint(slug: str) -> str:
    return (slug.split("-", 1)[0] or "").lower()


def record_watch(store, events: Iterable[GameEvent], *, now: float | None = None) -> int:
    """Upsert one row per Polymarket event. first_seen_ts and start_utc are set ONCE; the live
    start and last_seen_ts refresh every pass. Returns the number of rows touched."""
    t = now or time.time()
    store.ensure_ddl(WATCH_EVENTS_DDL)
    n = 0
    for e in events:
        if e.venue != "polymarket" or not e.event_id:
            continue
        store.con.execute(
            "INSERT INTO watch_events(event_id, venue, league_hint, first_seen_ts, start_utc, start_utc_last, participants, last_seen_ts) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(venue, event_id) DO UPDATE SET "
            "start_utc=COALESCE(watch_events.start_utc, excluded.start_utc), start_utc_last=excluded.start_utc_last, "
            "participants=COALESCE(watch_events.participants, excluded.participants), last_seen_ts=excluded.last_seen_ts",
            (e.event_id, e.venue, league_hint(e.event_id), t, e.start_utc, e.start_utc, json.dumps(e.participants), t))
        n += 1
    return n


def polymarket_outcome(market: dict | None) -> str | None:
    """The winning label, "HALF" for a 0.5/0.5 close, None while open or unreadable."""
    if not market or not market.get("closed"):
        return None
    outs, prices = market.get("outcomes"), market.get("outcomePrices")
    if isinstance(outs, str):
        outs = json.loads(outs)
    if isinstance(prices, str):
        prices = json.loads(prices)
    if not outs or not prices or len(outs) != len(prices):
        return None
    ps = [float(p) for p in prices]
    winners = [o for o, p in zip(outs, ps) if p >= 0.999]
    if len(winners) == 1:
        return str(winners[0])
    if all(abs(p - 0.5) < 1e-6 for p in ps):
        return "HALF"
    return None


def fetch_pm_event(slug: str, cl) -> dict | None:
    ev = cl.get_json(f"{PM_GAMMA}/events", params={"slug": slug}, use_cache=False)
    return ev[0] if isinstance(ev, list) and ev else None


def resolve_pending(store, cl, *, now: float | None = None, min_age_s: float = 3600.0, limit: int = 300,
                    fetch=fetch_pm_event, lock_wait_s: float = 150.0) -> dict:
    """Ask the venue about every unresolved event whose start is at least `min_age_s` old, oldest
    first. A match is resolved when its moneyline market is closed with a winner or at 0.5/0.5.

    The network runs first, against a read; the writes land in ONE short transaction afterwards,
    retried for up to `lock_wait_s`: the live lane holds a write transaction between its report
    ticks (about a minute), and a second process writing row by row hits `database is locked`
    (2026-09-04, the first run)."""
    t = now or time.time()
    store.ensure_ddl(WATCH_EVENTS_DDL)
    rows = store.con.execute(
        "SELECT event_id FROM watch_events WHERE venue='polymarket' AND resolved_seen_ts IS NULL AND start_utc IS NOT NULL "
        "AND start_utc < ? ORDER BY start_utc LIMIT ?", (t - min_age_s, limit)).fetchall()
    out = {"checked": 0, "resolved": 0, "half": 0, "open": 0, "errors": 0}
    notes: list[tuple] = []      # (event_id, note)
    done: list[tuple] = []       # (event_id, result)
    for (slug,) in rows:
        out["checked"] += 1
        try:
            ev = fetch(slug, cl)
        except Exception as exc:  # noqa: BLE001 -- one failed fetch must not stop the pass
            out["errors"] += 1
            notes.append((slug, f"fetch failed: {type(exc).__name__}"))
            continue
        ms = [m for m in (ev or {}).get("markets") or [] if m.get("sportsMarketType") == "moneyline"] if ev else []
        market = next((m for m in ms if m.get("slug") == slug), ms[0] if ms else None)
        res = polymarket_outcome(market)
        if res is None:
            out["open"] += 1
            notes.append((slug, "not resolved" if ev else "event not found"))
            continue
        out["resolved" if res != "HALF" else "half"] += 1
        done.append((slug, res))
    _write_with_retry(store, t, notes, done, lock_wait_s)
    return out


def _write_with_retry(store, t: float, notes: list, done: list, lock_wait_s: float) -> None:
    import sqlite3
    deadline = time.time() + lock_wait_s
    while True:
        try:
            con = store.con
            con.commit()                      # close any implicit transaction before an explicit one
            con.execute("BEGIN IMMEDIATE")
            con.executemany("UPDATE watch_events SET last_checked_ts=?, resolve_note=? WHERE venue='polymarket' AND event_id=?",
                            [(t, note, slug) for slug, note in notes])
            con.executemany("UPDATE watch_events SET last_checked_ts=?, resolved_seen_ts=?, result=?, resolve_note=NULL "
                            "WHERE venue='polymarket' AND event_id=?", [(t, t, res, slug) for slug, res in done])
            con.commit()
            return
        except sqlite3.OperationalError as exc:
            try:
                store.con.rollback()
            except Exception:  # noqa: BLE001
                pass
            if "locked" not in str(exc) or time.time() > deadline:
                raise
            time.sleep(2.0)


def delay_rows(store, *, leagues: Sequence[str] = ("atp", "wta")) -> list[tuple]:
    """(event_id, league_hint, start_utc, start_utc_last, resolved_seen_ts, result) for resolved
    rows of the given leagues -- what F4's measurement reads."""
    q = ",".join("?" * len(leagues))
    return store.con.execute(
        f"SELECT event_id, league_hint, start_utc, start_utc_last, resolved_seen_ts, result FROM watch_events "
        f"WHERE venue='polymarket' AND resolved_seen_ts IS NOT NULL AND league_hint IN ({q}) ORDER BY start_utc",
        tuple(leagues)).fetchall()
