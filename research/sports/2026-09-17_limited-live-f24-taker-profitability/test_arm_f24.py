"""Pins for arm_f24.sh. It is executed for real here, with the SSM runner stubbed.

This is the check test_box.py never ran on clear_f22_instrumentation_latch.sh -- which is how a script
that could not run on the box passed 172 tests.
"""
from __future__ import annotations

import base64
import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).with_name("arm_f24.sh")
STATEMENT = 'I approve F24: plain taker, current limits, 7 days or 30 covers; "quotes" & symbols.'


def render(*args, env=None):
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env)


def payload() -> str:
    """Exactly what --send passes to the runner: the dry run adds one display newline, dropped here."""
    out = render(STATEMENT)
    assert out.returncode == 0, out.stderr
    return out.stdout.split("\n", 1)[1].removesuffix("\n")


def test_dry_run_is_the_default_and_sends_nothing(tmp_path):
    marker = tmp_path / "sent"
    stub = tmp_path / "runner.sh"
    stub.write_text(f"#!/bin/bash\ntouch {marker}\n")
    out = render(STATEMENT, env={"PATH": "/usr/bin:/bin", "F24_RUNNER": str(stub)})
    assert out.returncode == 0 and "DRY RUN" in out.stdout
    assert not marker.exists(), "a dry run must never reach the runner"


def test_send_hands_the_payload_to_the_ssm_runner(tmp_path):
    received = tmp_path / "payload.txt"
    stub = tmp_path / "runner.sh"
    stub.write_text(f'#!/bin/bash\nprintf "%s" "$1" > {received}\n')
    out = render(STATEMENT, "--send", env={"PATH": "/usr/bin:/bin", "F24_RUNNER": str(stub)})
    assert out.returncode == 0, out.stderr
    assert received.read_text() == payload()


def test_refuses_an_empty_statement_or_an_unknown_option():
    assert render("   ").returncode == 2
    assert render(STATEMENT, "--force").returncode == 2


def test_refuses_a_signer_that_is_not_a_plain_name():
    out = render(STATEMENT, env={"PATH": "/usr/bin:/bin", "JANUS_SIGNED_BY": "x'; rm -rf /"})
    assert out.returncode == 2


def test_the_statement_survives_quoting_exactly():
    b64 = re.search(r"printf %s '([A-Za-z0-9+/=]+)' \| base64 -d", payload()).group(1)
    assert base64.b64decode(b64).decode() == STATEMENT


def test_the_override_carries_no_experiment_and_the_unchanged_caps():
    p = payload()
    line = next(l for l in p.splitlines() if "ops/arming_override.py" in l)
    assert "--experiment" not in line
    assert "--mode LIMITED_LIVE" in line
    assert "--stake-usd 30 --max-contracts 25 --day-notional-usd 500 --expires-hours 168" in line
    assert "--force" in line
    assert "sys.exit(1 if d.get(\"experiment\") else 0)" in p, "the written override is checked too"


def test_the_kill_is_pinned_to_the_exact_f22_stop():
    p = payload()
    assert "EXPECTED_KILL_SHA=d81bbfc267a235ca7f268e7317d77ee7e83c65f5263117590e4e86d1552b1636" in p
    assert p.count('sha256sum "$KILL"') == 2, "checked before arming and again immediately before the archive"


def test_the_order_is_quiet_check_then_override_then_confirmation_then_archive():
    p = payload()
    quiet = p.index("quiet check:")
    override = p.index("ops/arming_override.py")
    confirm = p.index(r"\[f22\] disabled")
    archive = p.index('mv "$KILL"')
    assert quiet < override < confirm < archive


def test_the_kill_is_archived_never_deleted_and_stays_on_any_failure():
    p = payload()
    assert 'mv "$KILL"' in p and "rm " not in p.replace("rm -f /tmp/f24-statement.txt", "")
    for reason in ("kill left in place",):
        assert p.count(reason) >= 4, "every post-override failure says the kill was not touched"


def test_the_lane_must_be_live_and_the_account_quiet_before_anything_is_written():
    p = payload()
    assert "--mode LIMITED_LIVE' || fail" in p
    assert "ORPHAN_FILL" in p and "ORDER_OVERFILL" in p and "UNHEDGED_POSITION" in p
    assert p.index('fail "account is not quiet"') < p.index("ops/arming_override.py")


def test_nothing_in_the_payload_is_left_for_local_expansion():
    p = payload()
    assert "@@" not in p, "every placeholder was substituted"
    assert 'KILL=/srv/janus/kill/live' in p and '"$KILL"' in p, "remote variables survive unexpanded"


def test_the_payload_is_valid_bash():
    out = subprocess.run(["bash", "-n"], input=payload(), capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


# ── check_f24.sh: the progress check must actually carry the report to the box ────────────────
CHECK = Path(__file__).with_name("check_f24.sh")
REPORT = Path(__file__).with_name("report.py")


def _check(tmp_path, *args):
    received = tmp_path / "payload.txt"
    stub = tmp_path / "runner.sh"
    stub.write_text(f'#!/bin/bash\nprintf "%s" "$1" > {received}\n')
    out = subprocess.run(["bash", str(CHECK), *args], capture_output=True, text=True,
                         env={"PATH": "/usr/bin:/bin", "F24_RUNNER": str(stub)})
    return out, (received.read_text() if received.exists() else None)


def test_check_embeds_the_report_verbatim_because_run_sh_ignores_stdin_with_an_argument(tmp_path):
    out, p = _check(tmp_path, "1789418782.132788", "1789505182.132788")
    assert out.returncode == 0, out.stderr
    assert REPORT.read_text().rstrip("\n") in p, "report.py travels inside the payload, unaltered"
    assert "/tmp/f24_report.py 1789418782.132788 1789505182.132788" in p
    assert subprocess.run(["bash", "-n"], input=p, capture_output=True, text=True).returncode == 0


def test_check_rejects_anything_but_numbers(tmp_path):
    for bad in (("abc",), ("1; rm -rf /",), ("1", "2 3"), ()):
        out, p = _check(tmp_path, *bad)
        assert out.returncode == 2 and p is None, bad
