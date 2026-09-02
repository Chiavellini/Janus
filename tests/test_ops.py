#!/usr/bin/env python3
"""Tests for the run index and the watchdog — the failure-localization substrate.

These exist because the failure they guard against was invisible for thirteen days:
com.janus.convergence restarted every 30 seconds from 2026-08-20 to 2026-09-02, wrote 15,207
identical tracebacks into 11.9 MB of unrotated stderr, and no surface reported it.

GATE_TO_LIVE.md:29-32 is explicit that "every alarm [must be] demonstrated firing against a fake
target — a monitor that has never emitted is untested (Kilos found three silent monitor bugs this
way)". test_watchdog_fires_on_the_real_convergence_signature is that demonstration.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


import ops.run_index as ri  # noqa: E402
import ops.watchdog as wd  # noqa: E402

NOW = 1_800_000_000.0
DEAD_PID = 999_999


@pytest.fixture
def index(tmp_path):
    return tmp_path / "index.jsonl"


def test_run_index_selftest():
    ri.selftest()


def test_watchdog_selftest_drives_every_alert_branch():
    """selftest() asserts each of the 7 branches fires and that the healthy case is silent."""
    wd.selftest()


def test_index_is_append_only(index):
    rid = ri.start("j", index=index)
    ri.finish("j", rid, exit_code=0, index=index)
    ri.finish("j", rid, exit_code=1, index=index)
    assert len(index.read_text().splitlines()) == 3, "rows must never be rewritten in place"
    assert ri.last_per_job(index)["j"]["status"] == "FAILED", "newest row wins"


def test_start_row_precedes_the_outcome(index):
    """The start row is the whole point: a crash at import still leaves a trace.

    The row must exist, name a real pid, and carry argv — everything the watchdog needs to tell
    a live daemon from a process that died before it could record anything.
    """
    import os
    ri.start("j", index=index, argv=["--once"])
    row = ri.last_per_job(index)["j"]
    assert row["status"] == "started"
    assert row["pid"] == os.getpid()
    assert row["argv"] == ["--once"]
    # a live pid with a start row and no outcome is a healthy daemon, not an alert
    assert wd.check(index, now=NOW, slas={"j": wd.Sla("daemon", 3600)}) == []


def test_watchdog_fires_on_the_real_convergence_signature(index):
    """40 restarts in 20 minutes, pid gone, no completions — exactly what convergence did."""
    for i in range(40):
        ri._append(index, {"ts": NOW - i * 30, "job": "j", "status": "started", "pid": DEAD_PID})
    alerts = wd.check(index, now=NOW, slas={"j": wd.Sla("daemon", 3600)})
    assert any("CRASH_LOOP" in a for a in alerts), alerts


def test_watchdog_is_quiet_for_a_healthy_daemon(index):
    """A monitor that always fires trains the operator to ignore it."""
    ri._append(index, {"ts": NOW - 60, "job": "j", "status": "started", "pid": os.getpid()})
    assert wd.check(index, now=NOW, slas={"j": wd.Sla("daemon", 3600)}) == []


def test_watchdog_survives_a_torn_line(index):
    """launchd can kill a job mid-write. A watchdog blinded by bad input is worse than none."""
    ri._append(index, {"ts": NOW - 60, "job": "j", "status": "FAILED", "exit": 1})
    with index.open("a") as fh:
        fh.write("{truncated json\n")
    assert any("FAILED" in a for a in wd.check(index, now=NOW, slas={"j": wd.Sla("daemon", 3600)}))


def test_disabled_jobs_never_alert():
    """convergence is deliberately unloaded; alerting on it forever is the noise that got us here."""
    assert "convergence" in wd.DISABLED
    assert "convergence" not in wd.SLAS


def test_every_registered_sla_job_is_not_also_disabled():
    assert not (set(wd.SLAS) & set(wd.DISABLED)), "a job cannot be both monitored and disabled"


def test_watchdog_reports_unregistered_jobs_rather_than_ignoring_them(index):
    ri._append(index, {"ts": NOW, "job": "stranger", "status": "OK", "exit": 0})
    assert any("UNREGISTERED" in a for a in wd.check(index, now=NOW, slas={}))
