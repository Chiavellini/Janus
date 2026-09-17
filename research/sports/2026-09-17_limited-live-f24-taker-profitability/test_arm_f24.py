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


def two_call_stub(tmp_path, *, first_rc=0, second_out="", second_rc=0):
    """A runner that answers the arm send and the verify read differently, and records both."""
    stub = tmp_path / "runner.sh"
    stub.write_text(
        "#!/bin/bash\n"
        f'n=$(cat {tmp_path}/n 2>/dev/null || echo 0); n=$((n+1)); echo $n > {tmp_path}/n\n'
        f'printf "%s" "$1" > {tmp_path}/payload.$n.txt\n'
        f'if [ "$n" = 1 ]; then exit {first_rc}; fi\n'
        f'printf "%s\\n" {second_out!r}; exit {second_rc}\n')
    return stub


def test_send_hands_the_payload_to_the_ssm_runner(tmp_path):
    stub = two_call_stub(tmp_path)
    out = render(STATEMENT, "--send", env={"PATH": "/usr/bin:/bin", "F24_RUNNER": str(stub)})
    assert (tmp_path / "payload.1.txt").read_text() == payload()
    assert "F24_STATE" in (tmp_path / "payload.2.txt").read_text(), "the box is read afterwards"
    assert out.returncode == 3, "a runner that says nothing means INDETERMINATE, never success"


def test_a_silent_or_failed_send_is_never_reported_as_nothing_happened(tmp_path):
    """The blocker: run.sh gives up on its own poll budget while the remote arm runs on."""
    stub = two_call_stub(tmp_path, first_rc=1)
    out = render(STATEMENT, "--send", env={"PATH": "/usr/bin:/bin", "F24_RUNNER": str(stub)})
    assert (tmp_path / "payload.2.txt").exists(), "a failed send must still be verified"
    assert out.returncode == 3 and "INDETERMINATE" in out.stdout
    assert "kill.sh live" in out.stdout, "and it must say how to stop a lane that may be trading"


def test_the_verified_state_decides_the_exit_code_not_the_send(tmp_path):
    (tmp_path / "a").mkdir(exist_ok=True)
    armed = two_call_stub(tmp_path / "a", second_out="F24_STATE: ARMED\nstart_utc=1789600000.5", second_rc=0)
    out = render(STATEMENT, "--send", env={"PATH": "/usr/bin:/bin", "F24_RUNNER": str(armed)})
    assert out.returncode == 0 and "F24 IS ARMED" in out.stdout and "start_utc=1789600000.5" in out.stdout

    (tmp_path / "b").mkdir(exist_ok=True)
    not_armed = two_call_stub(tmp_path / "b", first_rc=1, second_out="F24_STATE: NOT_ARMED", second_rc=2)
    out = render(STATEMENT, "--send", env={"PATH": "/usr/bin:/bin", "F24_RUNNER": str(not_armed)})
    assert out.returncode == 2 and "F24 IS NOT ARMED" in out.stdout


def test_the_arm_is_locked_guarded_and_backed_up_before_anything_is_written():
    p = payload()
    lock = p.index('mkdir "$LOCK"')
    pin_guard = p.index('a start pin already exists')
    backup = p.index('cp -p "$OVERRIDE" "$BACKUP"')
    override = p.index("ops/arming_override.py")
    assert lock < pin_guard < backup < override
    assert 'rmdir "$LOCK"' in p and "trap cleanup EXIT" in p, "the lock is released however it exits"
    assert p.count("$QUIET") >= 4, "the quiet check is a file so it can be run again before the archive"


def test_the_quiet_check_is_repeated_after_the_wait_and_the_start_is_pinned():
    p = payload()
    first = p.index('fail "account is not quiet"')
    second = p.index('an alarm appeared while waiting')
    archive = p.index('mv "$KILL"')
    pin = p.index('tee "$START_PIN"')
    assert first < second < archive < pin, "re-checked before the archive; pinned after it"
    assert "F24_WARNING" in p, "a failed pin is announced, not swallowed"


def test_the_wait_also_accepts_a_lane_that_already_reported_f22_disabled():
    """grid.check_arm prints the marker only on CHANGE, so a re-run must not wait forever."""
    p = payload()
    assert "] pollers=" in p, "report ticks prove the override was re-read"
    assert "[f22] disabled" in p.replace("\\", "")
    assert 'fail "the lane never reported F22 disabled within 225 s; kill left in place"' in p


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
    assert 'mv "$KILL"' in p
    removals = [l for l in p.splitlines() if "rm -f" in l or "rm " in l]
    assert all(("$QUIET" in l or "/tmp/f24-statement.txt" in l or 'rmdir "$LOCK"' in l) for l in removals), \
        f"only the script's own temporaries are removed, never the kill or the override: {removals}"
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


# ── verify_f24.sh: the answer to "is it actually armed?", which a local failure cannot give ──────
VERIFY = Path(__file__).with_name("verify_f24.sh")


def _verify(tmp_path, *, out_text="", rc=0):
    stub = tmp_path / "runner.sh"
    stub.write_text(f'#!/bin/bash\nprintf "%s" "$1" > {tmp_path}/payload.txt\n'
                    f'printf "%s\\n" {out_text!r}\nexit {rc}\n')
    r = subprocess.run(["bash", str(VERIFY)], capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "F24_RUNNER": str(stub)})
    return r, (tmp_path / "payload.txt").read_text()


def test_verify_reads_the_box_and_never_writes_to_it(tmp_path):
    r, p = _verify(tmp_path, out_text="F24_STATE: NOT_ARMED", rc=2)
    assert r.returncode == 2
    for forbidden in ("mv ", "rm ", "tee ", "write_text", "arming_override.py", "> /srv"):
        assert forbidden not in p, f"the verify payload must not {forbidden!r}"
    assert subprocess.run(["bash", "-n"], input=p, capture_output=True, text=True).returncode == 0


def test_verify_maps_each_state_to_its_own_exit_code(tmp_path):
    for text, rc in (("F24_STATE: ARMED\nstart_utc=1", 0), ("F24_STATE: NOT_ARMED", 2),
                     ("F24_STATE: INDETERMINATE", 3)):
        d = tmp_path / str(rc)
        d.mkdir()
        r, _ = _verify(d, out_text=text, rc=rc)
        assert r.returncode == rc, text


def test_a_box_that_does_not_answer_is_unknown_not_unchanged(tmp_path):
    r, _ = _verify(tmp_path, out_text="", rc=1)
    assert r.returncode == 3
    assert "UNKNOWN, not unchanged" in r.stderr


def test_armed_requires_no_kill_no_experiment_and_the_registered_caps(tmp_path):
    _, p = _verify(tmp_path, out_text="F24_STATE: NOT_ARMED", rc=2)
    assert 'armed = (not ev["kill_present"]' in p
    assert 'not o.get("has_experiment")' in p and 'o.get("caps_are_the_registered_ones")' in p
    assert '"stake_usd": 30.0, "max_contracts": 25.0, "day_notional_usd": 500.0' in p
    assert "d81bbfc267a235ca7f268e7317d77ee7e83c65f5263117590e4e86d1552b1636" in p
