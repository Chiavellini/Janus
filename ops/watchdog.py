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
    "newborn":         Sla("daemon", 3600),
    "shadow":          Sla("daemon", 3600),
    "track_b":         Sla("daemon", 3600),
    "wti_ladder":      Sla("daemon", 3600),
    "ibkr_archive":    Sla("daemon", 3600),
}


#: Deliberately not running. Reported as info, never as an alert -- an unloaded job that alerts
#: forever trains the operator to ignore the watchdog, which is how the convergence loop survived
#: thirteen days of a perfectly visible `launchctl list` exit status.
DISABLED: dict[str, str] = {
    "live_sports_arb": "not deployed — no launchd plist exists for the sports lane and the "
                       "Ashburn instance is stopped. Its SLA (oneshot, 300s) activates when the "
                       "lane is actually scheduled; registering it early is permanent noise.",
    "convergence": "unloaded 2026-09-02 after a 13-day crash loop; legacy crypto lane. "
                   "Restore: launchctl bootstrap gui/$(id -u) "
                   "~/Library/LaunchAgents/com.janus.convergence.plist",
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


def check(index: Path = INDEX, *, now: float | None = None,
          slas: dict[str, Sla] | None = None) -> list[str]:
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
        assert any("NEVER_RAN" in a for a in check(fresh("a"), now=NOW, slas=S)), "NEVER_RAN"

        # CRASH_LOOP — the convergence signature: a start row every 30s
        p = fresh("b")
        for i in range(20):
            _append(p, {"ts": NOW - i * 30, "job": "j", "status": "started", "pid": dead_pid})
        assert any("CRASH_LOOP" in a for a in check(p, now=NOW, slas=S)), "CRASH_LOOP"

        # CRASHED — started, pid gone, no outcome
        p = fresh("c")
        _append(p, {"ts": NOW - 60, "job": "j", "status": "started", "pid": dead_pid})
        assert any("CRASHED" in a for a in check(p, now=NOW, slas=S)), "CRASHED"

        # FAILED
        p = fresh("d")
        _append(p, {"ts": NOW - 100, "job": "j", "run_id": "r", "status": "started", "pid": dead_pid})
        _append(p, {"ts": NOW - 90, "job": "j", "run_id": "r", "status": "FAILED", "exit": 1})
        assert any("FAILED" in a for a in check(p, now=NOW, slas=S)), "FAILED"

        # STALE — oneshot completed too long ago
        p = fresh("e")
        _append(p, {"ts": NOW - 9999, "job": "j", "run_id": "r", "status": "OK", "exit": 0})
        assert any("STALE" in a for a in check(p, now=NOW, slas=S1)), "STALE"

        # HUNG — oneshot still running past SLA, pid alive
        p = fresh("f")
        _append(p, {"ts": NOW - 9999, "job": "j", "status": "started", "pid": os.getpid()})
        assert any("HUNG" in a for a in check(p, now=NOW, slas=S1)), "HUNG"

        # UNREGISTERED
        p = fresh("g")
        _append(p, {"ts": NOW, "job": "stranger", "status": "OK", "exit": 0})
        assert any("UNREGISTERED" in a for a in check(p, now=NOW, slas={})), "UNREGISTERED"

        # QUIET: a healthy daemon must produce NO alert (a monitor that always fires is noise)
        p = fresh("h")
        _append(p, {"ts": NOW - 120, "job": "j", "status": "started", "pid": os.getpid()})
        assert check(p, now=NOW, slas=S) == [], check(p, now=NOW, slas=S)

        # a torn line must not blind it
        with p.open("a") as fh:
            fh.write("{not json\n")
        assert check(p, now=NOW, slas=S) == []
    print("watchdog selftest OK — 7 alert branches fired, healthy case stayed quiet")


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
