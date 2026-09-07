#!/usr/bin/env python3
"""Tests about the test suite itself.

WHY
───
tests/test_cover.py and tests/test_spine.py used a homemade `@check(name)` harness that ran at
IMPORT time and caught every exception into a list. Under pytest they collected ZERO items and
reported ZERO failures, so 28 assertions covering nodes/cover/cover.py -- the module that decides
whether money is on the table -- and the entire schedule/entity spine were invisible. The
"156 passed" figure quoted in HANDOFF_LIVE_SPORTS_CLOUDBET_2026-09-02.md excluded both files.
Every one of those 28 assertions passed once made visible; the defect was never a broken test, it
was that a broken one could not have been noticed.

These tests make that class of failure impossible to reintroduce quietly.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: Every test file in the tree -- the repo-root suite AND each node/kernel/ops `tests/` dir.
#: Scoping this to `tests/` alone left the 16 node-level files outside the collect-check.
TEST_FILES = sorted(p for p in ROOT.glob("**/tests/test_*.py") if ".venv" not in p.parts and "site-packages" not in p.parts
                    if "data" not in p.parts and ".git" not in p.parts and ".claude" not in p.parts)
#: This file names the forbidden patterns in order to search for them, so it matches itself.
SCANNED = [p for p in TEST_FILES if p.name != "test_meta.py"]


def test_no_module_swallows_its_own_failures():
    """A harness that catches assertions and appends them to a list is invisible to pytest."""
    for p in SCANNED:
        src = p.read_text()
        assert "PASS, FAIL" not in src, f"{p.name} uses the swallowing PASS/FAIL harness"
        assert "def check(name)" not in src, f"{p.name} defines the swallowing @check factory"


def test_every_test_file_collects_at_least_one_test():
    """A file that collects nothing drops silently out of the pass count. This is the check that
    would have caught the 156-vs-184 discrepancy the day it appeared."""
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        capture_output=True, text=True, cwd=ROOT).stdout
    missing = [str(p.relative_to(ROOT)) for p in TEST_FILES
               if str(p.relative_to(ROOT)) not in out]
    assert not missing, f"these files collect ZERO tests: {missing}"


def test_suite_runs_from_any_working_directory():
    """ops/ASHBURN_SPORTS_RUNBOOK.md prescribes `python3 -m pytest -q` on a fresh host. Before the
    repo-root conftest.py, two files lacking the sys.path prologue collection-errored under a bare
    pytest, so the documented verification step was already broken."""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(ROOT / "tests")],
        capture_output=True, text=True, cwd="/")
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]


def test_conftest_lives_at_the_repo_root():
    assert (ROOT / "conftest.py").exists(), "the sys.path fix must cover every file, not tests/ only"
