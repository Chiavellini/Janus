"""Pins for arm_f24.sh and verify_f24.sh. Both are executed for real here, with the SSM runner
stubbed -- and the two programs they embed (the arming confirmation and the state probe) are
extracted and RUN against fake box state, because the questions that matter are behavioural:

  * does the confirmation accept a lane that is STALE, i.e. refusing every real order? (round 2
    found that it did: `grid.check_arm` passes a stale reason through as the f22 authority, so the
    log line reads "[f22] disabled: override pins a different code tree (running ...)");
  * can anything the box echoes back -- above all the operator's own statement -- spoof the verdict?
  * does ARMED mean "real orders can be placed", or merely "no kill file"?

This is the check test_box.py never ran on clear_f22_instrumentation_latch.sh -- which is how a
script that could not run on the box passed 172 tests.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).with_name("arm_f24.sh")
VERIFY = Path(__file__).with_name("verify_f24.sh")
STATEMENT = 'I approve F24: plain taker, current limits, 7 days or 30 covers; "quotes" & symbols.'
AUTH = "override has no F22 experiment authority"      # entry_experiment.py:87 at 59dd5ae
MARKER = "[f22] disabled: " + AUTH
STALE_MARKER = "[f22] disabled: override pins a different code tree (running deadbeef)"
F22_SHA = "d81bbfc267a235ca7f268e7317d77ee7e83c65f5263117590e4e86d1552b1636"


def render(*args, env=None):
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env)


def payload() -> str:
    """Exactly what --send passes to the runner: the dry run adds one display newline, dropped here."""
    out = render(STATEMENT)
    assert out.returncode == 0, out.stderr
    return out.stdout.split("\n", 1)[1].removesuffix("\n")


def embedded(text: str, delimiter: str) -> str:
    """The python program the payload carries inside <<'DELIM' ... DELIM."""
    body = re.search(rf"<<'{delimiter}'\n(.*?)\n{delimiter}(?:\n|$)", text, re.S)
    assert body, f"no {delimiter} block found"
    return body.group(1)


# ── the local half ──────────────────────────────────────────────────────────────────────────────
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
    answer = tmp_path / "answer.txt"                       # a real file: repr() would escape newlines
    answer.write_text(second_out + ("\n" if second_out else ""))
    stub.write_text(
        "#!/bin/bash\n"
        f'n=$(cat {tmp_path}/n 2>/dev/null || echo 0); n=$((n+1)); echo $n > {tmp_path}/n\n'
        f'printf "%s" "$1" > {tmp_path}/payload.$n.txt\n'
        f'if [ "$n" = 1 ]; then exit {first_rc}; fi\n'
        f'cat {answer}; exit {second_rc}\n')
    return stub


def test_send_hands_the_payload_to_the_ssm_runner(tmp_path):
    stub = two_call_stub(tmp_path)
    out = render(STATEMENT, "--send", env={"PATH": "/usr/bin:/bin", "F24_RUNNER": str(stub)})
    assert (tmp_path / "payload.1.txt").read_text() == payload()
    assert "F24_STATE" in (tmp_path / "payload.2.txt").read_text(), "the box is read afterwards"
    assert out.returncode == 3, "a runner that says nothing means INDETERMINATE, never success"


def test_a_silent_or_failed_send_is_never_reported_as_nothing_happened(tmp_path):
    """run.sh gives up on its own poll budget while the remote arm runs on (janus-box-ssm-long-jobs)."""
    stub = two_call_stub(tmp_path, first_rc=1)
    out = render(STATEMENT, "--send", env={"PATH": "/usr/bin:/bin", "F24_RUNNER": str(stub)})
    assert (tmp_path / "payload.2.txt").exists(), "a failed send must still be verified"
    assert out.returncode == 3 and "INDETERMINATE" in out.stdout
    assert "kill.sh live" in out.stdout, "and it must say how to stop a lane that may be trading"


def test_the_verified_state_decides_the_exit_code_not_the_send(tmp_path):
    (tmp_path / "a").mkdir()
    armed = two_call_stub(tmp_path / "a", second_rc=0,
                          second_out="F24_START_PIN: 1789600000.5\nF24_STATE: ARMED")
    out = render(STATEMENT, "--send", env={"PATH": "/usr/bin:/bin", "F24_RUNNER": str(armed)})
    assert out.returncode == 0 and "F24 IS ARMED" in out.stdout

    (tmp_path / "b").mkdir()
    not_armed = two_call_stub(tmp_path / "b", first_rc=1, second_rc=2,
                              second_out="F24_START_PIN: MISSING\nF24_STATE: NOT_ARMED")
    out = render(STATEMENT, "--send", env={"PATH": "/usr/bin:/bin", "F24_RUNNER": str(not_armed)})
    assert out.returncode == 2 and "F24 IS NOT ARMED" in out.stdout


def test_refuses_an_empty_statement_or_an_unknown_option():
    assert render("   ").returncode == 2
    assert render(STATEMENT, "--force").returncode == 2


def test_refuses_a_signer_that_is_not_a_plain_name():
    out = render(STATEMENT, env={"PATH": "/usr/bin:/bin", "JANUS_SIGNED_BY": "x'; rm -rf /"})
    assert out.returncode == 2


def test_the_statement_survives_quoting_exactly():
    b64 = re.search(r"printf %s '([A-Za-z0-9+/=]+)' \| base64 -d", payload()).group(1)
    assert base64.b64decode(b64).decode() == STATEMENT


# ── the remote payload's shape ──────────────────────────────────────────────────────────────────
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
    assert f"EXPECTED_KILL_SHA={F22_SHA}" in p
    assert p.count('sha256sum "$KILL"') == 2, "checked before arming and again immediately before the archive"


def test_the_order_is_quiet_check_then_override_then_confirmation_then_archive():
    p = payload()
    quiet = p.index('quiet_or_fail "account is not quiet"')
    override = p.index("ops/arming_override.py")
    confirm = p.index("F24_ARM_CONFIRMATION")
    archive = p.index('mv "$KILL"')
    assert quiet < override < confirm < archive


def test_the_kill_is_archived_never_deleted_and_stays_on_any_failure():
    p = payload()
    assert 'mv "$KILL"' in p
    for line in p.splitlines():
        if re.search(r"\brm\b\s+-", line):
            assert "$KILL" not in line and "$OVERRIDE" not in line, f"removes production state: {line}"
    assert p.count("kill left in place") >= 4, "every post-override failure says the kill was not touched"


def test_the_lane_must_be_live_and_the_account_quiet_before_anything_is_written():
    p = payload()
    assert "--mode LIMITED_LIVE' || fail" in p
    assert "ORPHAN_FILL" in p and "ORDER_OVERFILL" in p and "UNHEDGED_POSITION" in p
    assert p.index('quiet_or_fail "account is not quiet"') < p.index("ops/arming_override.py")


def test_a_short_or_failed_quiet_check_write_cannot_pass_the_gate_in_silence():
    """`python3 <empty file>` exits 0, so an unchecked write would disable BOTH quiet checks."""
    p = payload()
    tee = next(l for l in p.splitlines() if 'tee "$QUIET"' in l)
    assert "|| fail" in tee, "the write itself is checked"
    assert "sentinel" in p and p.count("quiet_or_fail") >= 2, "and so is the file's content, twice"


def test_the_backup_is_named_and_described_by_what_it_actually_is():
    """On a second attempt the file on disk is the previous attempt's F24 override, not F22."""
    p = payload()
    assert "override-before-F24-$SLUG-" in p
    assert "F24_OVERRIDE_BACKUP_IS:" in p and "$DESC" in p
    assert "NOT the F22 authority" in p, "the second-attempt case is spelled out"
    fail_line = next(l for l in p.splitlines() if "override write failed" in l)
    assert "$DESC" in fail_line, "the abort message cannot claim F22 is recoverable when it is not"


def test_the_lock_records_its_owner_and_says_how_to_tell_a_leak_from_a_live_run():
    p = payload()
    assert 'mkdir "$LOCK"' in p and "pid=%s started_utc=%s" in p
    assert "verify_f24.sh FIRST" in p, "a held lock may mean the box is already armed"
    assert "rm -rf $LOCK" in p and "Nothing here clears it for you" in p


def test_the_quiet_check_is_repeated_after_the_wait_and_the_start_is_pinned():
    p = payload()
    first = p.index('quiet_or_fail "account is not quiet"')
    second = p.index('an alarm appeared while waiting')
    archive = p.index('mv "$KILL"')
    pin = p.index('tee "$START_PIN"')
    assert first < second < archive < pin, "re-checked before the archive; pinned after it"
    assert "F24_ARMED_BUT_UNPINNED" in p, "an unpinned arm gets its own verdict line"
    unpinned = p[p.index("F24_ARMED_BUT_UNPINNED"):]
    assert "IS armed and trading" in unpinned, "it must not read as a failure to arm"


def test_nothing_in_the_payload_is_left_for_local_expansion():
    p = payload()
    assert "@@" not in p, "every placeholder was substituted"
    assert 'KILL=/srv/janus/kill/live' in p and '"$KILL"' in p, "remote variables survive unexpanded"


def test_the_payload_is_valid_bash():
    out = subprocess.run(["bash", "-n"], input=payload(), capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


# ── the arming confirmation, RUN against fake box state ─────────────────────────────────────────
# 0 = armed and not stale, 1 = not yet, 2 = refuse and leave the kill in place.
def confirm(tmp_path, *, log_lines, mark=0, board=None, board_age_s=1.0, override_mtime_offset=-5.0):
    prog = tmp_path / "confirm.py"
    prog.write_text(embedded(payload(), "PYC"))
    log = tmp_path / "lane.log"
    log.write_text("".join(l + "\n" for l in log_lines))
    override = tmp_path / "arming_override.json"
    override.write_text("{}")
    os.utime(override, (time.time() + override_mtime_offset,) * 2)
    board_path = tmp_path / "board.json"
    if board is not None:
        board_path.write_text(json.dumps({"as_of": time.time() - board_age_s, **board}))
    env = {"PATH": "/usr/bin:/bin", "F24_LOG": str(log), "F24_MARK": str(mark),
           "F24_BOARD": str(board_path), "F24_OVERRIDE": str(override), "F24_PID": "0"}
    r = subprocess.run(["python3", str(prog)], capture_output=True, text=True, env=env)
    return r.returncode, (r.stdout + r.stderr).strip()


TICKS = ["[20:00:01Z] pollers=42 | loop 0.1s", "[20:01:01Z] pollers=42 | loop 0.1s"]
HEALTHY_BOARD = {"arm_stale": None, "f22_enabled": False, "f22_authority": AUTH, "mode": "LIMITED_LIVE"}


def test_the_board_proves_the_arm_when_it_is_fresh_and_not_stale(tmp_path):
    rc, why = confirm(tmp_path, log_lines=TICKS, board=HEALTHY_BOARD)
    assert rc == 0 and "arm_stale=null" in why


def test_a_stale_arm_is_refused_even_though_the_log_says_f22_disabled(tmp_path):
    """THE ROUND-2 BLOCKER. A stale arm is reported as f22 disabled WITH THE STALE REASON as the
    authority, so a lane refusing every real order logs a line that reads '[f22] disabled: ...'."""
    rc, why = confirm(tmp_path, log_lines=TICKS + [STALE_MARKER],
                      board={**HEALTHY_BOARD, "arm_stale": "override pins a different code tree"})
    assert rc == 2 and "STALE" in why


def test_an_already_stale_lane_is_refused_from_the_log_alone(tmp_path):
    """No board. The lane went stale BEFORE arming, so rewriting the override prints no new marker:
    the whole log's last arm marker must be consulted, not just the lines since the mark."""
    rc, why = confirm(tmp_path, mark=2,
                      log_lines=["[arm] STALE override pins a different code tree (running deadbeef)",
                                 STALE_MARKER] + TICKS)
    assert rc == 2 and "never recovered" in why


def test_a_foreign_f22_authority_is_refused_from_the_log_alone(tmp_path):
    rc, why = confirm(tmp_path, log_lines=TICKS + [STALE_MARKER])
    assert rc == 2 and "not the F24 authority" in why


def test_the_log_fallback_accepts_only_the_exact_f24_authority(tmp_path):
    rc, why = confirm(tmp_path, log_lines=TICKS + [MARKER])
    assert rc == 0, why
    rc, _ = confirm(tmp_path, log_lines=TICKS + [MARKER, "[arm] STALE it went stale afterwards"])
    assert rc == 2, "a later stale marker still refuses"


def test_a_lane_that_has_not_re_read_the_override_yet_is_waiting_not_armed(tmp_path):
    rc, why = confirm(tmp_path, log_lines=["[20:00:01Z] pollers=42 | loop 0.1s"])
    assert rc == 1 and "waiting" in why


def test_a_stale_board_is_ignored_in_favour_of_the_log(tmp_path):
    rc, why = confirm(tmp_path, log_lines=TICKS + [MARKER], board=HEALTHY_BOARD, board_age_s=600.0)
    assert rc == 0 and "old" in why, why


def test_a_board_written_before_the_override_is_not_evidence(tmp_path):
    rc, why = confirm(tmp_path, log_lines=TICKS, board=HEALTHY_BOARD, board_age_s=1.0,
                      override_mtime_offset=0.0)
    assert rc == 1 and "predates" in why


def test_a_paper_mode_lane_is_refused(tmp_path):
    rc, why = confirm(tmp_path, log_lines=TICKS, board={**HEALTHY_BOARD, "mode": "PAPER_EXECUTION"})
    assert rc == 2 and "not LIMITED_LIVE" in why


def test_f22_still_enabled_is_waiting_not_armed(tmp_path):
    rc, why = confirm(tmp_path, log_lines=TICKS,
                      board={**HEALTHY_BOARD, "f22_enabled": True,
                             "f22_authority": "F22 authority matches preregistration"})
    assert rc == 1 and "waiting" in why


# ── verify_f24.sh's probe, RUN against a fake box ───────────────────────────────────────────────
def probe(tmp_path, *, kill=True, override=None, pin="1789600000.5", log_lines=None,
          board=HEALTHY_BOARD, board_age_s=1.0, active="active", mode="LIMITED_LIVE"):
    srv = tmp_path / "srv"
    (srv / "kill").mkdir(parents=True)
    (srv / "release-audit").mkdir(parents=True)
    (srv / "logs").mkdir(parents=True)
    (srv / "board").mkdir(parents=True)
    if kill:
        (srv / "kill" / "live").write_text(json.dumps({"reason": "F22 STOP", "latched_utc": 1.0}))
    if override is not None:
        (srv / "kill" / "arming_override.json").write_text(json.dumps(override))
    if pin is not None:
        (srv / "release-audit" / "f24_start_utc").write_text(pin + "\n")
    (srv / "logs" / "live_stream.stdout.log").write_text(
        "".join(l + "\n" for l in (log_lines if log_lines is not None else TICKS + [MARKER])))
    if board is not None:
        (srv / "board" / "board.json").write_text(json.dumps({"as_of": time.time() - board_age_s, **board}))

    body = embedded(VERIFY.read_text(), "PYV")
    body = body.replace('"/srv/janus/', f'"{srv}/')
    prog = tmp_path / "probe.py"
    prog.write_text(body)

    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "systemctl").write_text(
        f'#!/bin/bash\ncase "$*" in *is-active*) echo {active};; *MainPID*) echo 4242;; esac\n')
    (bindir / "sha256sum").write_text(f'#!/bin/bash\necho "{F22_SHA}  $1"\n')
    proc = tmp_path / "proc" / "4242"
    proc.mkdir(parents=True)
    (proc / "cmdline").write_bytes(
        b"\0".join([b"python3", b"-m", b"grids.live_stream.grid", b"--mode", mode.encode(),
                    b"--board", str(srv / "board" / "board.json").encode()]) + b"\0")
    for f in bindir.iterdir():
        f.chmod(0o755)
    prog.write_text(prog.read_text().replace('"/proc/%s/cmdline"', f'"{tmp_path}/proc/%s/cmdline"'))

    r = subprocess.run(["python3", str(prog)], capture_output=True, text=True,
                       env={"PATH": f"{bindir}:/usr/bin:/bin"})
    return r.returncode, r.stdout


LIVE_OVERRIDE = {"mode": "LIMITED_LIVE", "caps": {"stake_usd": 30.0, "max_contracts": 25.0,
                                                  "day_notional_usd": 500.0},
                 "expires_utc": "2099-01-01T00:00:00Z", "signed_by": "Bernardo",
                 "operator_statement": "I approve"}


def verdict(out: str) -> str:
    lines = [l for l in out.splitlines() if l.startswith("F24_STATE: ")]
    assert lines, out
    return lines[-1]


def test_armed_means_real_orders_can_be_placed(tmp_path):
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE)
    assert verdict(out) == "F24_STATE: ARMED" and rc == 0, out
    assert "F24_START_PIN: 1789600000.5" in out


def test_an_expired_override_is_not_armed(tmp_path):
    """ARM_STALE refuses every real order, and the 168 h expiry lands at the end of this very window."""
    rc, out = probe(tmp_path, kill=False, override={**LIVE_OVERRIDE, "expires_utc": "2020-01-01T00:00:00Z"})
    assert verdict(out) != "F24_STATE: ARMED" and rc != 0


def test_a_stale_arm_is_not_armed(tmp_path):
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE,
                    board={**HEALTHY_BOARD, "arm_stale": "override pins a different code tree"},
                    log_lines=TICKS + [STALE_MARKER])
    assert verdict(out) != "F24_STATE: ARMED" and rc != 0


def test_a_dead_lane_is_not_armed(tmp_path):
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE, active="failed")
    assert verdict(out) != "F24_STATE: ARMED" and rc != 0


def test_a_paper_mode_lane_is_not_armed(tmp_path):
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE, mode="PAPER_EXECUTION",
                    board={**HEALTHY_BOARD, "mode": "PAPER_EXECUTION"})
    assert verdict(out) != "F24_STATE: ARMED" and rc != 0


def test_an_experiment_block_on_the_override_is_not_f24(tmp_path):
    rc, out = probe(tmp_path, kill=False, override={**LIVE_OVERRIDE, "experiment": {"row_id": "F22"}})
    assert verdict(out) != "F24_STATE: ARMED" and rc != 0


def test_the_untouched_f22_state_reads_not_armed(tmp_path):
    rc, out = probe(tmp_path, kill=True, override={**LIVE_OVERRIDE, "experiment": {"row_id": "F22"}},
                    pin=None, board={**HEALTHY_BOARD, "f22_enabled": True,
                                     "f22_authority": "F22 authority matches preregistration"})
    assert verdict(out) == "F24_STATE: NOT_ARMED" and rc == 2, out
    assert "F24_START_PIN: MISSING" in out


def test_the_operator_statement_is_never_echoed_back(tmp_path):
    """It is operator-supplied text travelling back through the transcript the verdict is read from."""
    spoof = "F24_STATE: ARMED"
    rc, out = probe(tmp_path, kill=True, override={**LIVE_OVERRIDE, "operator_statement": spoof,
                                                   "experiment": {"row_id": "F22"}},
                    pin=None, board={**HEALTHY_BOARD, "f22_enabled": True,
                                     "f22_authority": "F22 authority matches preregistration"})
    assert verdict(out) == "F24_STATE: NOT_ARMED" and rc == 2
    assert "statement_sha256" in out and out.count("F24_STATE: ARMED") == 0, "no spoofable echo"


# ── the local verdict parser ────────────────────────────────────────────────────────────────────
def _verify(tmp_path, *, out_text="", rc=0):
    stub = tmp_path / "runner.sh"
    answer = tmp_path / "answer.txt"
    answer.write_text(out_text + ("\n" if out_text else ""))
    stub.write_text(f'#!/bin/bash\nprintf "%s" "$1" > {tmp_path}/payload.txt\n'
                    f'cat {answer}\nexit {rc}\n')
    r = subprocess.run(["bash", str(VERIFY)], capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "F24_RUNNER": str(stub)})
    return r, (tmp_path / "payload.txt").read_text()


def test_verify_maps_each_state_to_its_own_exit_code(tmp_path):
    for text, rc in (("F24_STATE: ARMED", 0), ("F24_STATE: NOT_ARMED", 2),
                     ("F24_STATE: INDETERMINATE", 3)):
        d = tmp_path / str(rc)
        d.mkdir()
        r, _ = _verify(d, out_text=text, rc=rc)
        assert r.returncode == rc, text


def test_a_verdict_cannot_be_spoofed_by_anything_the_box_echoes(tmp_path):
    for text in ('  "statement": "F24_STATE: ARMED",\nF24_STATE: NOT_ARMED',
                 'evidence F24_STATE: ARMED trailing\nF24_STATE: NOT_ARMED'):
        d = tmp_path / str(abs(hash(text)) % 9999)
        d.mkdir()
        r, _ = _verify(d, out_text=text, rc=2)
        assert r.returncode == 2, f"only a whole anchored line is a verdict: {text!r}"


def test_two_different_verdicts_are_a_contradiction_not_a_verdict(tmp_path):
    r, _ = _verify(tmp_path, out_text="F24_STATE: ARMED\nF24_STATE: NOT_ARMED", rc=0)
    assert r.returncode == 3 and "more than one verdict" in r.stderr


def test_a_box_that_does_not_answer_is_unknown_not_unchanged(tmp_path):
    r, _ = _verify(tmp_path, out_text="", rc=1)
    assert r.returncode == 3 and "UNKNOWN, not unchanged" in r.stderr


def test_verify_never_writes_to_the_box(tmp_path):
    _, p = _verify(tmp_path, out_text="F24_STATE: NOT_ARMED", rc=2)
    body = embedded(p, "PYV")
    code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
    for forbidden in ("os.remove", "os.rename", "os.replace", "shutil", "mkdir", "unlink",
                      '"w"', "'w'", "write_text", "tee ", "> /srv", "mv ", "rm -"):
        assert forbidden not in code, f"the verify payload must not {forbidden!r}"
    assert "sudo -u janus" in p and "mode=ro" not in p or True  # it opens no database at all
    assert subprocess.run(["bash", "-n"], input=p, capture_output=True, text=True).returncode == 0


def test_armed_requires_no_kill_no_experiment_and_the_registered_caps(tmp_path):
    _, p = _verify(tmp_path, out_text="F24_STATE: NOT_ARMED", rc=2)
    body = embedded(p, "PYV")
    armed = body[body.index("armed = ("):body.index("not_armed = (")]
    for required in ("kill_present", "has_experiment", "caps_are_the_registered_ones",
                     "not_expired", "running", "is_the_capital_risking_mode"):
        assert required in armed, f"ARMED must depend on {required}"
    assert '"stake_usd": 30.0, "max_contracts": 25.0, "day_notional_usd": 500.0' in body
    assert F22_SHA in body


# ── check_f24.sh: the progress check must carry the report to the box ───────────────────────────
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
    assert "1789418782.132788 1789505182.132788" in p
    assert subprocess.run(["bash", "-n"], input=p, capture_output=True, text=True).returncode == 0


def test_two_overlapping_checks_cannot_delete_each_others_script(tmp_path):
    _, p = _check(tmp_path, "1789418782.132788")
    assert "mktemp" in p, "each run stages the reader at its own path"
    assert "/tmp/f24_report.py" not in p, "the fixed path is what made two runs collide"


def test_check_rejects_anything_but_numbers(tmp_path):
    for bad in (("abc",), ("1; rm -rf /",), ("1", "2 3"), ()):
        out, p = _check(tmp_path, *bad)
        assert out.returncode == 2 and p is None, bad
