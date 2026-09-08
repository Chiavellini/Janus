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
  SIGNAL_EXIT   a daemon's run ended with exit >= 128 (a signal) inside `signal_window_s`, even
                though launchd has already started it again. On 2026-09-05 the lane died of a
                SIGBUS (exit 138; the host was paging) after 24 h and restarted 1 s later: one
                start in the hour is under CRASH_LOOP, and the FAILED check only reads the LAST
                row, which was the new start. A forward row's window has a hole nobody saw.
  UNHEDGED_POSITION  (nodes/risk/health) an execution whose first leg filled and whose hedge
                did not, still holding capital: the paper row's STOP condition, alarmed at once.
  OVERRIDE_STALE  (nodes/risk/health) the box's drop-in says LIMITED_LIVE but the arming override
                has expired, is missing, or pins another code tree or other limits: the lane
                refuses real orders (ARM_STALE) and a restart would crash-loop. Only where a
                drop-in exists (the Mac has none, so the Mac's watchdog never says this).
  OVERRIDE_EXPIRING  under 24 h left on the override while the drop-in says LIMITED_LIVE: the
                day's release paste (ops/box/release.sh) is due.
  CAP_BINDS_SMALLEST  (nodes/risk/health) the override's cap refused the smallest quantity the
                lane prices: nothing the lane can send would clear it. A GATE row (raise the cap
                or lower QUANTITIES), not a restart.
  COVERAGE_GAP  the census says both venues list an event in the window and the lane did not pair
                it: a market the lane should be covering and is not.
  EXECUTION_STUCK  (nodes/risk/health) a non-terminal execution that stopped moving for 120 s,
                excluding HEDGED and SETTLED (a cover held to the game's settlement is not stuck).
                Reconcile by hand: ops/reconcile_stuck_execution.py.

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
    signal_window_s: float = 24 * 3600   # daemon: a signal exit this recent is reported even after a restart


def _signal_name(exit_code: int) -> str:
    import signal as _sig
    try:
        return _sig.Signals(exit_code - 128).name
    except (ValueError, AttributeError):
        return f"signal {exit_code - 128}"


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
    "watch_fd": "built 2026-09-05 (nodes/watch_fd, ledger F6); awaits the operator's football-data.org token (FD_TOKEN). "
                "Bootstrap ops/com.janus.watch-fd.plist, then move this entry to SLAS as Sla(kind='oneshot', max_age_s=26 * 3600).",
}


#: The box runs the lane, the watchdog and the census; the daily resolver and the football-data job
#: are Mac launchd plists. A job registered here with no rows on this host alarms NEVER_RAN forever,
#: so each host gets its own set (JANUS_HOST from /etc/janus.env on the box; unset = the Mac).
SLAS_BY_HOST: dict[str, dict[str, Sla]] = {
    "box": {k: v for k, v in SLAS.items() if k in ("live_stream", "census")},
    # The Mac stopped running a lane on 2026-09-08 (see DISABLED_BY_HOST); it still runs the census
    # and the daily resolver.
    "": {k: v for k, v in SLAS.items() if k in ("census", "watch_settle")},
}


#: Deliberately not running ON A PARTICULAR HOST, layered over DISABLED. The lane is the case that
#: forces this to exist: it is the box's whole job and must keep its SLA there, while on the Mac it
#: is retired. Dropping a job from that host's SLAS alone is not enough -- a job with rows in the
#: index and no SLA alarms UNREGISTERED instead, which is the same permanent noise under a new name.
DISABLED_BY_HOST: dict[str, dict[str, str]] = {
    "": {"live_stream": "the Mac's lane, retired 2026-09-08. Its store corrupted under memory pressure at "
                        "2026-09-07 22:57 (the header claimed 17 pages more than the file held) and launchd "
                        "restarted it against the malformed file roughly seven hundred times, each run dying in "
                        "half a second at `PRAGMA journal_mode=WAL`, before it was booted out and the store "
                        "recovered. The box has been the only lane since 2026-09-07 and the retirement was "
                        "already on the list. Restore with `launchctl bootstrap` of "
                        "ops/com.janus.live-stream.plist, then move this entry back to SLAS_BY_HOST[\"\"]."},
}


def disabled_for_host(host: str | None = None) -> dict[str, str]:
    """DISABLED plus whatever this host retires on its own. Same host convention as slas_for_host."""
    h = host if host is not None else os.environ.get("JANUS_HOST", "")
    return {**DISABLED, **DISABLED_BY_HOST.get(h, {})}


def slas_for_host(host: str | None = None) -> dict[str, Sla]:
    h = host if host is not None else os.environ.get("JANUS_HOST", "")
    return SLAS_BY_HOST.get(h, SLAS)


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
    slas = slas_for_host() if slas is None else slas
    rows = _rows(index)

    by_job: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("job"):
            by_job.setdefault(r["job"], []).append(r)
    for v in by_job.values():
        v.sort(key=lambda r: r.get("ts", 0))

    alerts: list[str] = []

    for job in sorted(set(by_job) - set(slas) - set(disabled_for_host())):
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

        if sla.kind == "daemon":
            # A signal death followed by launchd's restart leaves the FAILED row second-to-last,
            # where the checks below never look. Report it once per window, without `continue`.
            for r in hist:
                code = r.get("exit")
                if r.get("status") == "FAILED" and isinstance(code, int) and code >= 128 and now - r.get("ts", 0) <= sla.signal_window_s:
                    restarted = any(x.get("status") == "started" and x.get("ts", 0) > r.get("ts", 0) for x in hist)
                    alerts.append(f"{job}: SIGNAL_EXIT — exited {code} ({_signal_name(code)}) {int(now - r.get('ts', 0))}s ago"
                                  + ("; restarted since (a gap in any forward row's window)" if restarted else "; not restarted"))

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
                    try:
                        from ops.coverage_report import coverage_alerts, newest_census
                        alerts.extend(coverage_alerts(path, newest_census(), now=now))
                    except Exception as exc:  # noqa: BLE001 -- coverage must report, never crash the watchdog
                        alerts.append(f"coverage: UNREADABLE — {type(exc).__name__}")
                    # A host that has retired its lane cannot be "silent": there is nothing to hear.
                    # Without this, a crash-looped start row whose pid the OS has since recycled
                    # keeps LANE_SILENT firing forever on a host with no lane at all.
                    lane_up = "live_stream" not in disabled_for_host() and \
                              any(r.get("job") == "live_stream" and r.get("status") == "started" and _pid_alive(r.get("pid"))
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

        # CAP_BINDS_SMALLEST — the override's cap refused the smallest quantity the lane prices
        from nodes.risk.flags import raise_flag, recent_flags
        from nodes.risk.health import risk_alerts as _ra
        from nodes.store_tuples.store import TupleStore as _TS2
        fdb = Path(d) / "flags.sqlite"
        fst = _TS2(fdb, enforce_volume=False)
        assert not any("CAP_BINDS_SMALLEST" in a for a in _ra(kill_root=Path(d) / "k0", breaker_path=Path(d) / "k0" / "b.json", db_path=fdb, now=NOW)), "no flag: quiet"
        raise_flag(fst, "CAP_BINDS_SMALLEST", "LAA @ BOS CAP_STAKE 23.25 > 12.00 q=5", now=NOW - 60)
        fst.close()
        assert recent_flags(fdb, "CAP_BINDS_SMALLEST", now=NOW) and any(
            "CAP_BINDS_SMALLEST" in a and "LAA @ BOS" in a for a in _ra(kill_root=Path(d) / "k0", breaker_path=Path(d) / "k0" / "b.json", db_path=fdb, now=NOW)), "CAP_BINDS_SMALLEST"
        assert not any("CAP_BINDS_SMALLEST" in a for a in _ra(kill_root=Path(d) / "k0", breaker_path=Path(d) / "k0" / "b.json", db_path=fdb, now=NOW + 2 * 86400)), "a day later it is history"

        # ORPHAN_FILL / POSITION_MISMATCH / PROTECT_FAILED / EXEC_CRASHED — the guard's and the protection layer's flags (2026-09-08)
        fst = _TS2(fdb, enforce_volume=False)
        raise_flag(fst, "ORPHAN_FILL", "kalshi KXMLBGAME-X buy_yes 5 @ 0.4 order k-777", now=NOW - 30)
        raise_flag(fst, "PROTECT_FAILED", "789ad9b2 pm:atp:974082 unhedged 10.175 after 12 attempts", now=NOW - 20)
        fst.close()
        got = _ra(kill_root=Path(d) / "k0", breaker_path=Path(d) / "k0" / "b.json", db_path=fdb, now=NOW)
        assert any("ORPHAN_FILL" in a and "k-777" in a for a in got) and any("PROTECT_FAILED" in a and "789ad9b2" in a for a in got), got
        assert not any("POSITION_MISMATCH" in a for a in got), "a flag never raised stays quiet"

        # COVERAGE_GAP — the census says both venues list it inside the lane's window, the lane did not pair it
        from ops.coverage_report import coverage_alerts
        from nodes.store_tuples.store import TupleStore as _TS
        cdb = Path(d) / "cov.sqlite"
        cst = _TS(cdb, enforce_volume=False)
        from nodes.discovery.discovery import EVENTS_DDL
        cst.ensure_ddl(EVENTS_DDL)
        cst.con.execute("INSERT INTO events(event_id, league, start_utc, participants, short_name, phase, kalshi_event, first_seen_ts, last_seen_ts, block_reason) "
                        "VALUES('espn:mlb:1','mlb',?,'[]','NYY @ BOS','pre',NULL,?,?,'UNPAIRED:kalshi=missing,polymarket=found')", (NOW + 600, NOW, NOW))
        cst.con.execute("INSERT INTO events(event_id, league, start_utc, participants, short_name, phase, kalshi_event, first_seen_ts, last_seen_ts) "
                        "VALUES('espn:mlb:2','mlb',?,'[]','SEA @ LAD','pre:co_listed','KXMLBGAME-SEALAD',?,?)", (NOW + 600, NOW, NOW))
        cst.con.commit(); cst.close()
        census = Path(d) / "results_x.json"
        census.write_text(json.dumps({"run": "x", "co_listed_pairs_48h": [
            {"kalshi_event": "KXMLBGAME-NYYBOS", "pm_event": "mlb-nyy-bos", "kalshi_series": "KXMLBGAME", "pm_sport": "mlb",
             "date": "2027-01-15", "start_utc": NOW + 600, "participants": ["New York Yankees", "Boston Red Sox"]},
            {"kalshi_event": "KXMLBGAME-SEALAD", "pm_event": "mlb-sea-lad", "kalshi_series": "KXMLBGAME", "pm_sport": "mlb",
             "date": "2027-01-15", "start_utc": NOW + 600, "participants": ["Seattle Mariners", "Los Angeles Dodgers"]},
            {"kalshi_event": "KXMLBGAME-FAR", "pm_event": "mlb-far", "kalshi_series": "KXMLBGAME", "pm_sport": "mlb",
             "date": "2027-01-20", "start_utc": NOW + 5 * 86400, "participants": ["A", "B"]}]}))
        cov = coverage_alerts(cdb, census, now=NOW)
        assert len(cov) == 1 and "COVERAGE_GAP" in cov[0] and "KXMLBGAME-NYYBOS" in cov[0] and "polymarket=found" in cov[0], cov
        assert coverage_alerts(cdb, None, now=NOW) == [], "no census: silent"

        # the box's SLA set drops the Mac-only daily jobs (JANUS_HOST=box); the Mac keeps them
        assert set(slas_for_host("box")) == {"live_stream", "census"} and "watch_settle" in slas_for_host("")
        _append(fresh("bx"), {"ts": NOW - 120, "job": "live_stream", "status": "started", "pid": os.getpid()})
        _append(fresh("bx"), {"ts": NOW - 3600, "job": "census", "run_id": "c", "status": "OK", "exit": 0})
        assert check(fresh("bx"), now=NOW, slas=slas_for_host("box"), risk={}) == [], "a fresh box with its two jobs is quiet"
        assert any("watch_settle: NEVER_RAN" in a for a in check(fresh("bx"), now=NOW, slas=slas_for_host(""), risk={})), "the Mac set would alarm"

        # UNREGISTERED
        p = fresh("g")
        _append(p, {"ts": NOW, "job": "stranger", "status": "OK", "exit": 0})
        assert any("UNREGISTERED" in a for a in check(p, now=NOW, slas={}, risk={})), "UNREGISTERED"

        # SIGNAL_EXIT — the 2026-09-05 signature: a FAILED 138 row, then launchd's new start row.
        # Neither CRASH_LOOP (one start) nor FAILED (last row is a start) sees it.
        p = fresh("d2")
        _append(p, {"ts": NOW - 90000, "job": "j", "run_id": "r0", "status": "started", "pid": dead_pid})
        _append(p, {"ts": NOW - 7200, "job": "j", "run_id": "r0", "status": "FAILED", "exit": 138})
        _append(p, {"ts": NOW - 7199, "job": "j", "run_id": "r1", "status": "started", "pid": os.getpid()})
        got = check(p, now=NOW, slas=S, risk={})
        assert any("SIGNAL_EXIT" in a and "138" in a and "restarted since" in a for a in got), got
        assert not any("FAILED —" in a or "CRASH_LOOP" in a for a in got), got
        # a plain non-zero exit before a restart is not a signal; a signal exit older than the window is quiet
        p = fresh("d3")
        _append(p, {"ts": NOW - 7200, "job": "j", "run_id": "r0", "status": "FAILED", "exit": 1})
        _append(p, {"ts": NOW - 90000, "job": "j", "run_id": "rz", "status": "FAILED", "exit": 138})
        _append(p, {"ts": NOW - 7199, "job": "j", "run_id": "r1", "status": "started", "pid": os.getpid()})
        assert not any("SIGNAL_EXIT" in a for a in check(p, now=NOW, slas=S, risk={})), "exit 1 / stale 138 are quiet"

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
        conf = Path(d) / "mode.conf"                         # the box's drop-in; absent on the Mac
        R = dict(kill_root=kill, breaker_path=brk, db_path=db, max_unreconciled_s=60, in_season=False,
                 mode_conf=conf, code_sha="c0detree", limits_sha="11m1t5")
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
        # UNHEDGED_POSITION: leg A filled, hedge short, capital held -- the paper row's STOP condition.
        # A HEDGED execution and a released PARTIAL_FILL are both quiet.
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE executions(execution_id TEXT, opportunity_id TEXT, event_id TEXT, league TEXT, mode TEXT, state TEXT, "
                    "started_utc REAL, last_utc REAL, quantity REAL, first_filled REAL, hedge_filled REAL, unhedged REAL, "
                    "reservation_id TEXT, released INTEGER)")
        con.execute("INSERT INTO executions VALUES('hedgedok','o','e','mlb','PAPER_EXECUTION','HEDGED',?,?,100,100,100,0,'r1',0)", (NOW - 100, NOW - 100))
        con.execute("INSERT INTO executions VALUES('oldpart','o','e','mlb','PAPER_EXECUTION','PARTIAL_FILL',?,?,100,100,64,36,'r2',1)", (NOW - 100, NOW - 100))
        con.commit()
        assert not any("UNHEDGED_POSITION" in a for a in check(fresh("q"), now=NOW, slas={}, risk=R)), "hedged / released are quiet"
        con.execute("INSERT INTO executions VALUES('69852b86x','o','espn:mlb:401816802','mlb','PAPER_EXECUTION','PARTIAL_FILL',?,?,100,100,64.18,35.82,'r3',0)", (NOW - 3600, NOW - 3600))
        con.commit()
        got = check(fresh("q"), now=NOW, slas={}, risk=R)
        assert any("UNHEDGED_POSITION" in a and "69852b86" in a and "35.82/100" in a for a in got), got
        assert not any("UNRECONCILED_TOO_LONG" in a for a in got), "a holding failure is the UNHEDGED alarm's business, not a late reconcile"
        # EXECUTION_STUCK: a machine that stopped moving before a terminal state. HEDGED and SETTLED
        # are not terminal (RECONCILED comes after the game) and released stays 0 until then, so a
        # ten-minute-old cover is quiet; a ten-minute-old LEG_A_SUBMITTED is the alarm.
        con.execute("INSERT INTO executions VALUES('hedgedold','o','e','mlb','LIMITED_LIVE','HEDGED',?,?,10,10,10,0,'r4',0)", (NOW - 600, NOW - 600))
        con.execute("INSERT INTO executions VALUES('settledold','o','e','mlb','LIMITED_LIVE','SETTLED',?,?,10,10,10,0,'r5',0)", (NOW - 600, NOW - 600))
        con.commit()
        got = check(fresh("q"), now=NOW, slas={}, risk=R)
        assert not any("EXECUTION_STUCK" in a and ("hedgedol" in a or "settledo" in a) for a in got), got
        con.execute("INSERT INTO executions VALUES('stucklega','o','e','mlb','LIMITED_LIVE','LEG_A_SUBMITTED',?,?,10,0,0,0,'r6',0)", (NOW - 600, NOW - 600))
        con.commit()
        got = check(fresh("q"), now=NOW, slas={}, risk=R)
        assert any("EXECUTION_STUCK" in a and "stuckleg" in a and "600s" in a for a in got), got
        assert not any("EXECUTION_STUCK" in a and ("hedgedol" in a or "settledo" in a) for a in got), got
        con.execute("DROP TABLE executions"); con.commit(); con.close()
        # OVERRIDE_STALE / OVERRIDE_EXPIRING: judged only where a drop-in says LIMITED_LIVE (the box).
        # The Mac has no drop-in and must never say either; a paper drop-in is quiet too.
        from datetime import datetime as _dt, timezone as _tz
        ov = kill / "arming_override.json"

        def stamp(offset_s):
            return _dt.fromtimestamp(NOW + offset_s, tz=_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        good_ov = {"operator_statement": "I approve.", "signed_by": "operator", "mode": "LIMITED_LIVE", "runner_sha": "head",
                   "code_sha": "c0detree", "limits_sha": "11m1t5", "caps": {"stake_usd": 12.0}, "expires_utc": stamp(48 * 3600)}
        ov.write_text(json.dumps({**good_ov, "expires_utc": stamp(-60)}))
        assert not any("OVERRIDE" in a for a in check(fresh("q"), now=NOW, slas={}, risk=R)), "no drop-in (the Mac): quiet"
        exec_line = "[Service]\nExecStart=\nExecStart=/usr/bin/zsh /opt/janus/ops/run_node.sh live_stream -m grids.live_stream.grid --mode {}\n"
        conf.write_text(exec_line.format("PAPER_EXECUTION"))
        assert not any("OVERRIDE" in a for a in check(fresh("q"), now=NOW, slas={}, risk=R)), "a paper drop-in: quiet"
        conf.write_text(exec_line.format("LIMITED_LIVE"))
        ov.write_text(json.dumps(good_ov))
        assert not any("OVERRIDE" in a for a in check(fresh("q"), now=NOW, slas={}, risk=R)), "48 h left and matching: quiet"
        ov.write_text(json.dumps({**good_ov, "expires_utc": stamp(6 * 3600)}))
        got = check(fresh("q"), now=NOW, slas={}, risk=R)
        assert any("OVERRIDE_EXPIRING" in a and "6.0 h left" in a for a in got) and not any("OVERRIDE_STALE" in a for a in got), got
        ov.write_text(json.dumps({**good_ov, "expires_utc": stamp(-60)}))
        got = check(fresh("q"), now=NOW, slas={}, risk=R)
        assert any("OVERRIDE_STALE" in a and "expired" in a for a in got) and not any("EXPIRING" in a for a in got), got
        ov.write_text(json.dumps({**good_ov, "code_sha": "another"}))
        assert any("OVERRIDE_STALE" in a and "code tree" in a for a in check(fresh("q"), now=NOW, slas={}, risk=R)), "a deploy moved the tree"
        ov.write_text(json.dumps({**good_ov, "limits_sha": "other"}))
        assert any("OVERRIDE_STALE" in a and "limits" in a for a in check(fresh("q"), now=NOW, slas={}, risk=R)), "limits changed"
        ov.write_text(json.dumps({k: v for k, v in good_ov.items() if k != "code_sha"}))
        assert any("OVERRIDE_STALE" in a and "missing or incomplete" in a for a in check(fresh("q"), now=NOW, slas={}, risk=R)), "an old file"
        ov.unlink()
        assert any("OVERRIDE_STALE" in a for a in check(fresh("q"), now=NOW, slas={}, risk=R)), "no override under a live drop-in"
        conf.unlink()
        assert not any("OVERRIDE" in a for a in check(fresh("q"), now=NOW, slas={}, risk=R)), "drop-in gone: quiet again"
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
    print("watchdog selftest OK — 8 job branches, 7 risk branches (the two override alarms and EXECUTION_STUCK among them), the registry branch "
          "and 3 socket branches fired; healthy cases stayed quiet")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", type=Path, default=INDEX)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return 0
    alerts = check(a.index)
    for job, why in sorted(disabled_for_host().items()):
        print(f"info   {job}: DISABLED — {why}")
    for x in alerts:
        print(f"ALERT  {x}")
    if not alerts:
        print("ok — all registered jobs healthy")
    return 1 if alerts else 0


if __name__ == "__main__":
    raise SystemExit(main())
