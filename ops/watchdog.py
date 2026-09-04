#!/usr/bin/env python3
"""Dead-man's switch over runs/index.jsonl. Exits non-zero when a job needs attention.

WHY THIS EXISTS
───────────────
Thirteen days of com.janus.convergence crash-looping every 30 seconds went unnoticed because no
surface answered "is this job healthy?". `launchctl list` reports a last exit status with no
history, so a job that has failed 15,207 times and one that failed once look identical.

WHAT IT DETECTS, and why each check is here rather than an obvious alternative:

  CRASH_LOOP    more than `max_starts_per_hour` start rows in the last hour. This is the check
                that catches the convergence failure DIRECTLY, and it needs no cooperation from
                the collector -- a KeepAlive job that dies at import still emits a start row per
                restart. Checking "did it finish" could not have caught it, because a crash-loop
                does technically keep running.
  CRASHED       last row is `started`, its PID is gone, and no terminal row followed. The job
                died without recording an outcome.
  FAILED        last terminal row is FAILED.
  STALE         a `oneshot` job has not completed within its SLA.
  NEVER_RAN     a registered job has no rows at all.
  SOCKET_FLAPPING  a venue socket reconnected `max_reconnects` or more times over the last
                `window_rows` health rows (~15 minutes). A lane whose sockets tear down every
                ten seconds still writes a start row once and keeps its pid, so CRASH_LOOP and
                CRASHED are blind to it: on 2026-09-03 both sockets reconnected 5-20 times a
                minute for hours while this file printed "all registered jobs healthy".
  LANE_SILENT   the lane's own report tick has not written a socket_health row for
                `max_silence_s` while the daemon is up: the process lives, the data stopped.
                The F2 lesson as a rule -- a forward row's collector must be seen writing.
  SOCKET_ERROR  the socket's last error names one of OUR exception classes (IllegalTransition,
                TypeError, ...) and the socket was seen down or its error count rose in the
                window: a bug in the record or pricing path reaching the transport, not the
                venue hanging up.

PER GATE_TO_LIVE.md:29-32 -- "every alarm demonstrated firing against a fake target; a monitor
that has never emitted is untested (Kilos found three silent monitor bugs this way)" -- selftest()
drives every one of these branches against synthetic input and asserts it fires. Do not add a
check here without adding its firing test.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ops.run_index import INDEX, TERMINAL  # noqa: E402


@dataclass(frozen=True)
class Sla:
    kind: str                       # "daemon" (should run continuously) | "oneshot"
    max_age_s: float                # oneshot: max time since last completion
    max_starts_per_hour: int = 4    # daemon: more restarts than this is a crash loop


#: Registered jobs. A job absent here is reported as UNREGISTERED rather than ignored --
#: silently skipping unknown jobs is how a monitor stops covering what it was built for.
SLAS: dict[str, Sla] = {
    # The observation lane. It is a long-lived daemon, so "healthy" means the process is still
    # running and its last row is a start, not a finish. A finish row means it stopped -- which is
    # fine when deliberate and an alert when not.
    # The streaming observation lane. A daemon: healthy means still running, and its last row
    # should be a start rather than a finish.
    "live_stream": Sla(kind="daemon", max_age_s=1800, max_starts_per_hour=6),
    # L28, the co-listing census: one run a day at 14:00 local for seven days (com.janus.census).
    # A day and two hours of silence means the calendar job did not fire or did not finish.
    "census": Sla(kind="oneshot", max_age_s=26 * 3600),
    # nodes/watch_settle's daily resolver (research/sports/2026-09-04_tennis-delay-forward), 13:30 local.
    "watch_settle": Sla(kind="oneshot", max_age_s=26 * 3600),
    # Nothing is currently scheduled except this watchdog. Every Janus collector was stopped on
    # 2026-09-02 (see CHANGELOG.md); the sports lane has never had a plist. Entries return here
    # when a lane is actually deployed -- registering an SLA for a job that does not run is
    # permanent noise, which is the failure mode that let a 13-day crash loop go unread.
}


#: Deliberately not running. Reported as info, never as an alert -- an unloaded job that alerts
#: forever trains the operator to ignore the watchdog, which is how the convergence loop survived
#: thirteen days of a perfectly visible `launchctl list` exit status.
DISABLED: dict[str, str] = {
    "live_sports": "superseded 2026-09-02 by live_stream, which replaces 17s REST polling with two websockets at ~200 evaluations/sec. The grid remains for offline replay.",
    "probe_test": "one-off probe of run_index start/finish on 2026-09-02. The index is append-only, so the row stays; this entry stops it alerting forever.",

    "shadow": "stopped 2026-09-02; ledger F1 closed unscored. Collector removed. Plist preserved; restore with launchctl bootstrap.",
    "convergence": "stopped 2026-09-02 after a 13-day crash loop; ledger F2 closed unscored. Collector removed. Plist preserved; restore with launchctl bootstrap.",
    "newborn": "stopped 2026-09-02; ledger L24 closed, 960 MB capture archived. Collector removed. Plist preserved; restore with launchctl bootstrap.",
    "track_b": "stopped 2026-09-02; IBKR/Track B track retired. Collector removed. Plist preserved; restore with launchctl bootstrap.",
    "wti_ladder": "stopped 2026-09-02; commodities track retired. Collector removed. Plist preserved; restore with launchctl bootstrap.",
    "ibkr_archive": "stopped 2026-09-02; IBKR track retired. Collector removed. Plist preserved; restore with launchctl bootstrap.",
}


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # exists, owned by someone else
    return True


def _rows(index: Path) -> list[dict]:
    if not index.exists():
        return []
    out = []
    for line in index.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue          # a torn line must never blind the watchdog
    return out


#: An exception class in socket_health.last_error that is ours, not the venue's. A transport error
#: reads "ConnectionClosedError: ..." or "TimeoutError: "; these read like a traceback's last line.
_OUR_EXCEPTIONS = ("IllegalTransition", "TypeError", "KeyError", "AttributeError", "ValueError",
                   "AssertionError", "IndexError", "ZeroDivisionError")


def socket_alerts(db_path: Path | str, *, now: float | None = None, window_rows: int = 15,
                  max_reconnects: int = 5, max_row_age_s: float = 3600.0,
                  max_silence_s: float | None = None) -> list[str]:
    """Reads the lane's own socket_health rows (one per report tick per venue). Silent when the
    table is absent, when a venue has fewer than two rows, or when the newest row is older than
    `max_row_age_s` (a stopped lane is the daemon check's business, not this one's)."""
    import sqlite3
    t = time.time() if now is None else now
    out: list[str] = []
    dbp = Path(db_path)
    if not dbp.exists():
        return out
    try:
        con = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
        if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='socket_health'").fetchall():
            con.close()
            return out
        venues = [r[0] for r in con.execute("SELECT DISTINCT venue FROM socket_health").fetchall()]
        newest = con.execute("SELECT MAX(seen_ts) FROM socket_health").fetchone()[0]
        if max_silence_s is not None and newest is not None and t - newest > max_silence_s:
            out.append(f"lane: LANE_SILENT — no socket_health row for {int(t - newest)}s (limit {int(max_silence_s)}s); "
                       f"the report tick stopped writing")
        for venue in sorted(venues):
            rows = con.execute("SELECT seen_ts, connected, errors, last_error FROM socket_health WHERE venue=? "
                               "ORDER BY seen_ts DESC LIMIT ?", (venue, window_rows)).fetchall()
            if len(rows) < 2 or t - rows[0][0] > max_row_age_s:
                continue
            rows = rows[::-1]                                     # oldest first
            errs = [r[2] for r in rows if r[2] is not None]
            rose = (errs[-1] - errs[0]) if len(errs) >= 2 else 0
            toggles = sum(1 for a, b in zip(rows, rows[1:]) if (a[1] or 0) != (b[1] or 0))
            span = int(rows[-1][0] - rows[0][0])
            if rose >= max_reconnects or toggles >= max_reconnects:
                out.append(f"socket {venue}: SOCKET_FLAPPING — {rose} errors and {toggles} connect/disconnect "
                           f"flips over the last {len(rows)} health rows ({span}s); last: {rows[-1][3] or '?'}")
            last = rows[-1][3] or ""
            seen_down = any(not (r[1] or 0) for r in rows)
            if (rose > 0 or seen_down) and last.split(":")[0].strip() in _OUR_EXCEPTIONS:
                out.append(f"socket {venue}: SOCKET_ERROR — our own exception reached the transport and "
                           f"tore the socket down: {last}")
        con.close()
    except sqlite3.Error as exc:
        out.append(f"socket: HEALTH_UNREADABLE — {type(exc).__name__}")
    return out


def check(index: Path = INDEX, *, now: float | None = None,
          slas: dict[str, Sla] | None = None, risk: dict | None = None) -> list[str]:
    """`risk` is the keyword set for nodes/risk/health.risk_alerts (paths); None uses the
    real ones, {} disables the risk checks (tests of the job branches alone)."""
    now = time.time() if now is None else now
    slas = SLAS if slas is None else slas
    rows = _rows(index)

    by_job: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("job"):
            by_job.setdefault(r["job"], []).append(r)
    for v in by_job.values():
        v.sort(key=lambda r: r.get("ts", 0))

    alerts: list[str] = []

    for job in sorted(set(by_job) - set(slas) - set(DISABLED)):
        alerts.append(f"{job}: UNREGISTERED — running but has no SLA in ops/watchdog.py")

    for job, sla in sorted(slas.items()):
        hist = by_job.get(job) or []
        if not hist:
            alerts.append(f"{job}: NEVER_RAN — no rows in the index")
            continue

        starts_last_hour = sum(1 for r in hist
                               if r.get("status") == "started" and now - r.get("ts", 0) <= 3600)
        if starts_last_hour > sla.max_starts_per_hour:
            alerts.append(f"{job}: CRASH_LOOP — {starts_last_hour} starts in the last hour "
                          f"(limit {sla.max_starts_per_hour})")
            continue          # a crash loop subsumes every other symptom; report it once

        last = hist[-1]
        age = now - last.get("ts", 0)

        if last.get("status") == "started":
            if not _pid_alive(last.get("pid")):
                alerts.append(f"{job}: CRASHED — started {int(age)}s ago, pid "
                              f"{last.get('pid')} is gone, no outcome recorded")
            elif sla.kind == "oneshot" and age > sla.max_age_s:
                alerts.append(f"{job}: HUNG — started {int(age)}s ago, still running, "
                              f"SLA {int(sla.max_age_s)}s")
            continue

        if last.get("status") == "FAILED":
            alerts.append(f"{job}: FAILED — last run exited {last.get('exit')} {int(age)}s ago")
        elif sla.kind == "oneshot" and last.get("status") in TERMINAL and age > sla.max_age_s:
            alerts.append(f"{job}: STALE — last completion {int(age)}s ago, SLA "
                          f"{int(sla.max_age_s)}s")
    if risk is None or risk:
        from nodes.risk.health import risk_alerts
        rk = {k: v for k, v in (risk or {}).items() if k != "in_season"}
        alerts.extend(risk_alerts(now=now, **rk))
        db = (risk or {}).get("db_path")
        if risk is None or db:
            try:
                from nodes.discovery.discovery import registry_health
                from nodes.store_tuples.store import DEFAULT_DB, TupleStore
                path = Path(db) if db else DEFAULT_DB
                if path.exists():
                    st = TupleStore(path, enforce_volume=not db)
                    alerts.extend(registry_health(st, now=now, in_season=(risk or {}).get("in_season", True)))
                    st.close()
                    lane_up = any(r.get("job") == "live_stream" and r.get("status") == "started" and _pid_alive(r.get("pid"))
                                  for r in rows)
                    alerts.extend(socket_alerts(path, now=now, max_silence_s=900.0 if lane_up else None))
            except Exception as exc:  # noqa: BLE001 -- the watchdog must report, never crash
                alerts.append(f"registry: UNREADABLE — {type(exc).__name__}")
    return alerts


def selftest() -> None:
    """Every branch is driven and asserted to fire. See the module docstring."""
    import tempfile
    from ops.run_index import _append

    NOW = 1_800_000_000.0
    dead_pid = 999_999                      # not a live pid on any sane host
    S = {"j": Sla("daemon", 3600, max_starts_per_hour=4)}
    S1 = {"j": Sla("oneshot", 300)}

    with tempfile.TemporaryDirectory() as d:
        def fresh(name):
            return Path(d) / f"{name}.jsonl"

        # NEVER_RAN
        assert any("NEVER_RAN" in a for a in check(fresh("a"), now=NOW, slas=S, risk={})), "NEVER_RAN"

        # CRASH_LOOP — the convergence signature: a start row every 30s
        p = fresh("b")
        for i in range(20):
            _append(p, {"ts": NOW - i * 30, "job": "j", "status": "started", "pid": dead_pid})
        assert any("CRASH_LOOP" in a for a in check(p, now=NOW, slas=S, risk={})), "CRASH_LOOP"

        # CRASHED — started, pid gone, no outcome
        p = fresh("c")
        _append(p, {"ts": NOW - 60, "job": "j", "status": "started", "pid": dead_pid})
        assert any("CRASHED" in a for a in check(p, now=NOW, slas=S, risk={})), "CRASHED"

        # FAILED
        p = fresh("d")
        _append(p, {"ts": NOW - 100, "job": "j", "run_id": "r", "status": "started", "pid": dead_pid})
        _append(p, {"ts": NOW - 90, "job": "j", "run_id": "r", "status": "FAILED", "exit": 1})
        assert any("FAILED" in a for a in check(p, now=NOW, slas=S, risk={})), "FAILED"

        # STALE — oneshot completed too long ago
        p = fresh("e")
        _append(p, {"ts": NOW - 9999, "job": "j", "run_id": "r", "status": "OK", "exit": 0})
        assert any("STALE" in a for a in check(p, now=NOW, slas=S1, risk={})), "STALE"

        # HUNG — oneshot still running past SLA, pid alive
        p = fresh("f")
        _append(p, {"ts": NOW - 9999, "job": "j", "status": "started", "pid": os.getpid()})
        assert any("HUNG" in a for a in check(p, now=NOW, slas=S1, risk={})), "HUNG"

        # UNREGISTERED
        p = fresh("g")
        _append(p, {"ts": NOW, "job": "stranger", "status": "OK", "exit": 0})
        assert any("UNREGISTERED" in a for a in check(p, now=NOW, slas={}, risk={})), "UNREGISTERED"

        # QUIET: a healthy daemon must produce NO alert (a monitor that always fires is noise)
        p = fresh("h")
        _append(p, {"ts": NOW - 120, "job": "j", "status": "started", "pid": os.getpid()})
        assert check(p, now=NOW, slas=S, risk={}) == [], check(p, now=NOW, slas=S, risk={})

        # a torn line must not blind it
        with p.open("a") as fh:
            fh.write("{not json\n")
        assert check(p, now=NOW, slas=S, risk={}) == []
        # ── risk branches (nodes/risk/health) ────────────────────────────
        import sqlite3
        kill = Path(d) / "kill"; kill.mkdir()
        brk = kill / "breaker.json"; db = Path(d) / "t.sqlite"
        R = dict(kill_root=kill, breaker_path=brk, db_path=db, max_unreconciled_s=60, in_season=False)
        assert check(fresh("q"), now=NOW, slas={}, risk=R) == [], "quiet risk state must be silent"
        (kill / "venue-kalshi").write_text("{}")
        assert any("KILL_FILE_PRESENT" in a for a in check(fresh("q"), now=NOW, slas={}, risk=R)), "KILL_FILE"
        (kill / "venue-kalshi").unlink()
        brk.write_text(json.dumps({"latched": True, "reason": "test"}))
        assert any("BREAKER_LATCHED" in a for a in check(fresh("q"), now=NOW, slas={}, risk=R)), "BREAKER"
        brk.unlink()
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE capital_reservations(reservation_id TEXT, event_id TEXT, league TEXT, "
                    "per_venue_json TEXT, opportunity_id TEXT, created_utc REAL, released_utc REAL, release_reason TEXT)")
        con.execute("INSERT INTO capital_reservations VALUES('r','e','mlb','{}',NULL,?,NULL,NULL)", (NOW - 3600,))
        con.commit(); con.close()
        assert any("UNRECONCILED_TOO_LONG" in a for a in check(fresh("q"), now=NOW, slas={}, risk=R)), "UNRECONCILED"
        con = sqlite3.connect(db); con.execute("DELETE FROM capital_reservations"); con.commit(); con.close()
        # NO_CO_LISTED_GAMES: discovery has written for a day in season without one co-listed game.
        # (A fresh, empty registry is silent -- that fired falsely on the lane's first boot.)
        assert not any("registry" in a for a in check(fresh("q"), now=NOW, slas={}, risk={**R, "in_season": True}))
        from nodes.discovery.discovery import EVENTS_DDL
        con = sqlite3.connect(db); con.executescript(EVENTS_DDL)
        con.execute("INSERT INTO events(event_id, league, phase, first_seen_ts, last_seen_ts) VALUES('e','mlb','pre',?,?)",
                    (NOW - 2 * 86400, NOW - 3600))
        con.commit(); con.close()
        assert any("NO_CO_LISTED_GAMES" in a for a in check(fresh("q"), now=NOW, slas={}, risk={**R, "in_season": True})), "REGISTRY"
        assert not any("registry" in a for a in check(fresh("q"), now=NOW, slas={}, risk={**R, "in_season": False}))
        # ── sockets (socket_health, written by the lane's report tick) ───
        from nodes.store_tuples.store import TupleStore as _TS
        con = sqlite3.connect(db); con.executescript(_TS.SOCKET_HEALTH_DDL)

        def health(venue, i, connected, errors, last):
            con.execute("INSERT INTO socket_health VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (NOW - (15 - i) * 60, venue, connected, 10, 100 * i, 0, 0, 0, 0, 0.99, errors, 0.0, 1, 1.0, last, 0.0))
        for i in range(15):                                          # a quiet, connected socket
            health("kalshi", i, 1, 0, None)
        con.commit()
        assert not any("socket" in a for a in check(fresh("q"), now=NOW, slas={}, risk=R)), "quiet socket must be silent"
        # the 2026-09-03 signature: connected flips every row, errors climb, last_error is ours
        for i in range(15):
            health("polymarket", i, i % 2, i, "IllegalTransition: espn:cfb:1:moneyline:v1:5: BLOCKED_MATCH -> BLOCKED_STALE")
        con.commit()
        got = check(fresh("q"), now=NOW, slas={}, risk=R)
        assert any("polymarket: SOCKET_FLAPPING" in a for a in got), got
        assert any("polymarket: SOCKET_ERROR" in a for a in got), got
        assert not any("kalshi: SOCKET" in a for a in got), "the healthy venue must not be dragged in"
        # a venue that hung up (transport error, few reconnects) is neither
        con.execute("DELETE FROM socket_health WHERE venue='polymarket'")
        for i in range(15):
            health("polymarket", i, 1, 1 if i > 7 else 0, "ConnectionClosedError: no close frame received or sent")
        con.commit()
        assert not any("socket" in a for a in check(fresh("q"), now=NOW, slas={}, risk=R)), "one venue hang-up is not an alert"
        # LANE_SILENT: the lane is up but its report tick stopped writing (only when asked to watch for it)
        from ops.watchdog import socket_alerts as _sa
        assert any("LANE_SILENT" in a for a in _sa(db, now=NOW + 1000, max_silence_s=900.0)), "LANE_SILENT"
        assert not any("LANE_SILENT" in a for a in _sa(db, now=NOW + 1000)), "silence is only judged when the lane is up"
        assert not any("LANE_SILENT" in a for a in _sa(db, now=NOW + 100, max_silence_s=900.0)), "fresh rows are quiet"
        # rows older than an hour belong to a stopped lane: the daemon check owns that
        con.execute("DELETE FROM socket_health WHERE venue='polymarket'")
        for i in range(15):
            health("polymarket", i, i % 2, i, "TypeError: x")
        con.execute("UPDATE socket_health SET seen_ts = seen_ts - 7200 WHERE venue='polymarket'"); con.commit()
        assert not any("socket" in a for a in check(fresh("q"), now=NOW, slas={}, risk=R)), "stale health rows are silent"
        con.close()
    print("watchdog selftest OK — 7 job branches, 3 risk branches, the registry branch and 3 socket branches fired; healthy cases stayed quiet")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", type=Path, default=INDEX)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return 0
    alerts = check(a.index)
    for job, why in sorted(DISABLED.items()):
        print(f"info   {job}: DISABLED — {why}")
    for x in alerts:
        print(f"ALERT  {x}")
    if not alerts:
        print("ok — all registered jobs healthy")
    return 1 if alerts else 0


if __name__ == "__main__":
    raise SystemExit(main())
