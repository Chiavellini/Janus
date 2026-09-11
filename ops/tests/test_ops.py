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
    assert wd.check(index, now=NOW, slas={"j": wd.Sla("daemon", 3600)}, risk={}) == []


def test_watchdog_fires_on_the_real_convergence_signature(index):
    """40 restarts in 20 minutes, pid gone, no completions — exactly what convergence did."""
    for i in range(40):
        ri._append(index, {"ts": NOW - i * 30, "job": "j", "status": "started", "pid": DEAD_PID})
    alerts = wd.check(index, now=NOW, slas={"j": wd.Sla("daemon", 3600)})
    assert any("CRASH_LOOP" in a for a in alerts), alerts


def test_watchdog_is_quiet_for_a_healthy_daemon(index):
    """A monitor that always fires trains the operator to ignore it."""
    ri._append(index, {"ts": NOW - 60, "job": "j", "status": "started", "pid": os.getpid()})
    assert wd.check(index, now=NOW, slas={"j": wd.Sla("daemon", 3600)}, risk={}) == []


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


def test_secret_flag_values_never_reach_the_index(index):
    """The index is append-only and forever. No flag carries a secret today; this is what keeps
    the first `--api-key ...` anyone adds from being persisted verbatim."""
    ri.start("j", index=index, argv=["--api-key", "sk-live-123", "--once"])
    row = ri.last_per_job(index)["j"]
    assert row["argv"] == ["--api-key", "<redacted>", "--once"]
    assert "sk-live-123" not in index.read_text()


def test_watchdog_disk_alerts_fire_on_pressure_runway_and_the_critical_floor(tmp_path):
    """L72: the volume filled with nothing watching. PRESSURE at 80 % or under three days of
    projected runway, CRITICAL under 5 GiB, and the root disk gets only the critical floor."""
    from collections import namedtuple
    U = namedtuple("usage", "total used free")
    G = 2 ** 30
    samples = tmp_path / "disk_samples.jsonl"
    now = 1_800_000_000.0

    def usage_for(data, root=U(20 * G, 4 * G, 16 * G)):
        return lambda p: root if str(p) == "/" else data
    # Quiet: 40 % used, no history yet, root fine.
    assert wd.disk_alerts(data_root=tmp_path, now=now, samples=samples, usage=usage_for(U(200 * G, 80 * G, 120 * G))) == []
    # 12 hours later, 90 GB used: not yet 80 %, and 20 GB/day leaves 5.5 days -> quiet.
    assert wd.disk_alerts(data_root=tmp_path, now=now + 12 * 3600, samples=samples, usage=usage_for(U(200 * G, 90 * G, 110 * G))) == []
    # A day in, 150 GB used: 70 GB/day over the window -> 0.7 days of runway -> PRESSURE by runway.
    a = wd.disk_alerts(data_root=tmp_path, now=now + 24 * 3600, samples=samples, usage=usage_for(U(200 * G, 150 * G, 50 * G)))
    assert len(a) == 1 and a[0].startswith("disk: PRESSURE") and "full in 0.7 days" in a[0], a
    # 80 % used with no growth is PRESSURE by fraction alone.
    a = wd.disk_alerts(data_root=tmp_path, now=now, samples=None, usage=usage_for(U(100 * G, 80 * G, 20 * G)))
    assert len(a) == 1 and "PRESSURE" in a[0] and "80% used" in a[0]
    # Under 5 GiB free is CRITICAL, whatever the fraction says; the root disk too.
    a = wd.disk_alerts(data_root=tmp_path, now=now, samples=None, usage=usage_for(U(100 * G, 96 * G, 4 * G), root=U(20 * G, 17 * G, 3 * G)))
    assert [x.split(" — ")[0] for x in a] == ["disk: CRITICAL", "disk: CRITICAL"] and "/ has 3.0 GiB" in a[1]
    # An unreadable data volume is reported, never swallowed.
    def boom(p):
        raise OSError("no such volume")
    assert wd.disk_alerts(data_root=tmp_path, now=now, samples=None, usage=boom) == [f"disk: UNREADABLE — {tmp_path}: OSError"]
    # The sample file survives a failed write (the disk it measures may be the full one).
    assert wd.disk_growth_per_day(tmp_path / "nope" / "x" / "s.jsonl", now=now, used=1) is None


def test_watchdog_check_measures_no_real_disk_when_the_risk_branches_are_off(index):
    """`risk={}` is the job-branch-only mode every existing test uses; it must stay disk-free,
    and an explicit disk keyword set is honoured."""
    from collections import namedtuple
    U = namedtuple("usage", "total used free")
    ri.start("j", index=index)
    assert wd.check(index, now=NOW, slas={"j": wd.Sla("daemon", 3600)}, risk={}) == []
    a = wd.check(index, now=NOW, slas={"j": wd.Sla("daemon", 3600)}, risk={},
                 disk=dict(data_root="/x", root=None, samples=None, usage=lambda p: U(10 * 2 ** 30, 9 * 2 ** 30, 2 ** 30)))
    assert len(a) == 1 and a[0].startswith("disk: CRITICAL — /x")
