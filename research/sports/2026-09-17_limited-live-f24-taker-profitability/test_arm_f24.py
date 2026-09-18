"""Pins for arm_f24.sh and verify_f24.sh. Both are executed for real here, with the SSM runner
stubbed -- and the two programs they embed (the arming confirmation and the state probe) are
extracted and RUN against fake box state, because the questions that matter are behavioural:

  * does the confirmation accept a lane that is STALE, i.e. refusing every real order? (round 2
    found that it did: `grid.check_arm` passes a stale reason through as the f22 authority, so the
    log line reads "[f22] disabled: override pins a different code tree (running ...)");
  * can anything the box echoes back -- above all the operator's own statement -- spoof the verdict?
  * does ARMED mean "real orders can be placed", or merely "no kill file"?
  * HOW MANY WAYS CAN THE LANE BE STOPPED? (round 3) `nodes/risk/kill.py` at 59dd5ae honours FIVE
    scopes in one directory -- all, live, venue-<venue>, event-<event_id>, strategy-<version> --
    and the same directory holds `breaker.json`, which is not a kill file and stops more: once the
    daily-loss breaker latches, `evaluate()` answers BREAKER_LATCHED before any kill switch is
    consulted, so `clearance.clear()` refuses every candidate, `kill/live` is never re-created, and
    nothing under ops/ resets it. Recognising two file names out of that is how "ARMED, real orders
    can be placed right now" got printed over a window in which nothing could trade.

This is the check test_box.py never ran on clear_f22_instrumentation_latch.sh -- which is how a
script that could not run on the box passed 172 tests.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
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

#: `touch` and `rm` are the whole operator interface (kill.py's docstring), so a switch may be an
#: empty file; and `_present()` tests `exists()`, which a DIRECTORY also satisfies.
DIRECTORY = object()

#: One of each scope `KillSwitches.active()` honours at 59dd5ae, with the reason a latch writes.
FIVE_SCOPES = {
    "all": {"reason": "operator stopped every mode", "latched_utc": 1789700000.0},
    "live": {"reason": "breaker: daily realized loss -25.40 USD breached 25.00 on 2026-09-19"},
    "venue-polymarket": {"reason": "the pm book defect (L146)"},
    "event-NFL-2026-09-20-DAL-NYG": {"reason": "one game, by hand"},
    "strategy-v1.4.0": {"reason": "one strategy version"},
}

#: breaker.json after the $25/UTC-day breaker trips. `LossBreaker.latch()` writes exactly these keys.
LATCHED_BREAKER = {"latched": True, "latched_utc": 1789700000.0,
                   "reason": "daily realized loss -25.40 USD breached 25.00 on 2026-09-19"}

#: `TupleStore.REFUSAL_COUNTS_DDL` at 59dd5ae, verbatim minus the IF NOT EXISTS. The lane writes one
#: row per (channel, code, league) per report tick from `grid.on_report_tick`.
REFUSAL_DDL = ("CREATE TABLE refusal_counts(seen_ts REAL NOT NULL, channel TEXT NOT NULL, "
               "code TEXT NOT NULL, league TEXT NOT NULL, n INTEGER NOT NULL)",
               "CREATE INDEX refusal_counts_ts ON refusal_counts(seen_ts)")
REPORT_PERIOD = 30.0                                   # grid.py's --report-period argparse default

#: What the risk channel looks like on a lane that IS trading: nothing but per-candidate refusals.
#: The box's own two days read KILL_SWITCH 6084 / IN_FLIGHT 4111 / HEDGE_DEPTH_CHANGED 40 /
#: MIN_PROFIT 34 / GUARD_FAILED 5, so these are the codes a healthy window is made of.
HEALTHY_REFUSALS = ({"MIN_PROFIT": 12, "IN_FLIGHT": 40, "HEDGE_DEPTH_CHANGED": 2},
                    {"MIN_PROFIT": 9, "IN_FLIGHT": 31})


def write_refusals(path, ticks, *, channel="risk", newest_age_s=5.0, period=REPORT_PERIOD,
                   ddl=REFUSAL_DDL, extra=()):
    """A tuple store holding only `refusal_counts`. `ticks` are {code: n}, NEWEST FIRST, one report
    tick apart -- the shape `TupleStore.refusal_counts` writes, which is counts and not rows."""
    con = sqlite3.connect(str(path))
    for stmt in ddl:
        con.execute(stmt)
    rows = list(extra)
    for i, tick in enumerate(ticks):
        ts = time.time() - newest_age_s - i * period
        for code, n in tick.items():
            rows.append((ts, channel, code, "nfl", n))
    if rows:
        con.executemany(
            "INSERT INTO refusal_counts(seen_ts, channel, code, league, n) VALUES(?,?,?,?,?)", rows)
    con.commit()
    con.close()


def write_switch(path, content):
    """A kill file the way the box would actually hold one: JSON, raw text, `touch`ed, or a directory."""
    if content is DIRECTORY:
        path.mkdir()
    elif content is None:
        path.touch()
    elif isinstance(content, str):
        path.write_text(content)
    else:
        path.write_text(json.dumps(content))


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


def test_the_armed_message_says_the_refusal_record_cannot_corroborate_yet(tmp_path):
    """verify_f24.sh discards every tick that began before the start pin, because those count
    refusals from while the F22 kill was still in place. So the strongest evidence this tooling
    has -- what the lane DID -- is structurally unavailable at the moment of arming, and the
    operator has to be told to come back for it rather than left thinking ARMED was the whole check."""
    armed = two_call_stub(tmp_path, second_rc=0,
                          second_out="F24_START_PIN: 1789600000.5\nF24_STATE: ARMED")
    out = render(STATEMENT, "--send", env={"PATH": "/usr/bin:/bin", "F24_RUNNER": str(armed)})
    assert out.returncode == 0 and "F24 IS ARMED" in out.stdout
    assert "AGAIN IN ABOUT TWO MINUTES" in out.stdout, out.stdout
    assert "ticks_before_this_are_pre_arm" in out.stdout, "it names the field to read"
    assert "lane_could_act=false" in out.stdout, "and what a real stop will look like"


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
#: `Supervisor.board()` at 59dd5ae, including the three fields every verdict used to throw away:
#: `stalled`, `loop_lag_s` and `sockets` (one entry per venue stream that exists).
HEALTHY_BOARD = {"arm_stale": None, "f22_enabled": False, "f22_authority": AUTH, "mode": "LIMITED_LIVE",
                 "stalled": False, "loop_lag_s": 0.1,
                 "sockets": {"kalshi": {"connected": True, "frames": 91234, "age_s": 0.2, "errors": 0},
                             "polymarket": {"connected": True, "frames": 40221, "age_s": 0.3, "errors": 0}}}


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


# ── arm_f24.sh's PRE-ARM stop check, RUN against fake kill directories ──────────────────────────
# 0 = the lane could trade once the F22 stop is archived, 1 = refuse to arm (and say what to do).
def prearm(tmp_path, *, kills=None, breaker=None, live=True, kill_dir=True):
    prog = tmp_path / "stops.py"
    prog.write_text(embedded(payload(), "PYB"))
    kd = tmp_path / "kill"
    if kill_dir:
        kd.mkdir()
        (kd / "arming_override.json").write_text(json.dumps({"mode": "LIMITED_LIVE"}))
        if live:                                           # the F22 stop this script archives itself
            write_switch(kd / "live", {"reason": "F22 STOP"})
        for name, content in (kills or {}).items():
            write_switch(kd / name, content)
        if breaker is not None:
            write_switch(kd / "breaker.json", breaker)
    r = subprocess.run(["python3", str(prog)], capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "F24_KILL_DIR": str(kd),
                            "F24_BREAKER": str(kd / "breaker.json")})
    return r.returncode, (r.stdout + r.stderr).strip()


def test_the_prearm_check_passes_on_the_f22_stop_alone(tmp_path):
    """The state F24 is meant to be armed from: kill/live, the override, nothing else."""
    rc, why = prearm(tmp_path)
    assert rc == 0, why


def test_the_prearm_check_refuses_every_other_kill_scope(tmp_path):
    """kill/live is archived by this script; any OTHER scope survives the archive and stops the lane."""
    for i, (name, body) in enumerate(FIVE_SCOPES.items()):
        if name == "live":
            continue
        d = tmp_path / str(i)
        d.mkdir()
        rc, why = prearm(d, kills={name: body})
        assert rc == 1, f"{name} must refuse the arm: {why}"
        assert name in why and body["reason"][:20] in why, why
        assert "does not lift it" in why and "NOTHING WAS WRITTEN" in why, why


def test_the_prearm_check_reports_an_unrecognised_file_without_refusing(tmp_path):
    """kill.active() tests five exact shapes and consults nothing else, so a name matching none of
    them cannot refuse a candidate. The live box's kill directory really does hold
    .guard-failure-*.lock and .legacy-incident-*.lock (seen 2026-09-18): failing closed on those
    would make arming permanently impossible while proving nothing."""
    rc, why = prearm(tmp_path, kills={"KILL-EVERYTHING": None})
    assert rc == 0, why
    assert "KILL-EVERYTHING" in why and "not a kill switch" in why, why

    other = tmp_path / "with-a-real-scope"
    other.mkdir()
    rc, why = prearm(other, kills={"KILL-EVERYTHING": None, "venue-kalshi": {"reason": "venue"}})
    assert rc == 1 and "venue-kalshi" in why, "a recognised scope still refuses"


def test_the_prearm_check_refuses_a_latched_breaker_and_says_it_needs_a_human(tmp_path):
    """Arming over a latched breaker archives the F22 stop for a lane that refuses every candidate."""
    rc, why = prearm(tmp_path, breaker=LATCHED_BREAKER)
    assert rc == 1 and "LATCHED" in why, why
    assert LATCHED_BREAKER["reason"] in why and str(LATCHED_BREAKER["latched_utc"]) in why, why
    assert "LossBreaker.reset(by=<name>)" in why and "nothing under ops/ calls it" in why, why
    assert "HUMAN DECISION" in why and "not a file to delete" in why, why
    assert "STOP condition" in why, "spec.yaml makes a latch end the row, not pause it"


def test_the_prearm_check_allows_a_breaker_that_is_present_but_not_latched(tmp_path):
    rc, why = prearm(tmp_path, breaker={"latched": False, "reason": "", "latched_utc": None})
    assert rc == 0, why


def test_the_prearm_check_refuses_an_unreadable_or_unparseable_breaker(tmp_path):
    for sub, state, word in (("a", DIRECTORY, "unreadable"), ("b", "{not json", "unparseable")):
        d = tmp_path / sub
        d.mkdir()
        rc, why = prearm(d, breaker=state)
        assert rc == 1 and word in why, why


def test_the_prearm_check_refuses_when_the_kill_directory_cannot_be_listed(tmp_path):
    rc, why = prearm(tmp_path, kill_dir=False)
    assert rc == 1 and "UNKNOWN, not absent" in why, why


def test_the_prearm_stop_check_runs_before_anything_is_written():
    p = payload()
    stops = p.index("F24_PREARM_STOPS")
    assert p.index("<<'PYB'") < stops < p.index('quiet_or_fail "account is not quiet"')
    assert stops < p.index("ops/arming_override.py") < p.index('mv "$KILL"')


def prearm_shell(tmp_path, *, kills=None, breaker=None):
    """The BASH WIRING around PYB, not just the program: a heredoc inside a command substitution,
    inside `sudo -u janus env ... "$PY" -`, is the shape that made clear_f22_instrumentation_latch.sh
    unrunnable. `sudo` is shimmed away; nothing here goes near a box."""
    p = payload()
    excerpt = p[p.index("STOPS=$("):p.index('echo "F24_PREARM_STOPS')]
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "sudo").write_text('#!/bin/bash\n[ "$1" = -u ] && shift 2\nexec "$@"\n')
    (bindir / "sudo").chmod(0o755)
    kd = tmp_path / "kill"
    kd.mkdir()
    write_switch(kd / "live", {"reason": "F22 STOP"})
    (kd / "arming_override.json").write_text(json.dumps({"mode": "LIMITED_LIVE"}))
    for name, content in (kills or {}).items():
        write_switch(kd / name, content)
    if breaker is not None:
        write_switch(kd / "breaker.json", breaker)
    script = tmp_path / "gate.sh"
    script.write_text('set -u\nfail() { echo "F24_ARM_ABORTED: $*"; exit 2; }\n'
                      f"PY=python3\nKILL_DIR={kd}\nBREAKER={kd}/breaker.json\n"
                      + excerpt + '\necho "F24_PREARM_STOPS: $STOPS"\n')
    r = subprocess.run(["bash", str(script)], capture_output=True, text=True,
                       env={"PATH": f"{bindir}:/usr/bin:/bin"})
    return r.returncode, (r.stdout + r.stderr).strip()


def test_the_prearm_gate_is_wired_into_the_payload_and_aborts_the_arm(tmp_path):
    (tmp_path / "ok").mkdir()
    rc, out = prearm_shell(tmp_path / "ok")
    assert rc == 0 and "F24_PREARM_STOPS: no other kill switch" in out, out

    (tmp_path / "stopped").mkdir()
    rc, out = prearm_shell(tmp_path / "stopped", breaker=LATCHED_BREAKER,
                           kills={"venue-polymarket": {"reason": "the pm book defect (L146)"}})
    assert rc == 2, out                                    # fail() -- the arm aborts
    assert out.startswith("F24_ARM_ABORTED: "), out
    assert "venue-polymarket" in out and "LATCHED" in out, out
    assert "F24_PREARM_STOPS" not in out, "an aborted arm never reports a clean gate"


# ── verify_f24.sh's probe, RUN against a fake box ───────────────────────────────────────────────
def probe(tmp_path, *, kill=True, kills=None, breaker=None, override=None, pin="1789600000.5",
          log_lines=None, board=HEALTHY_BOARD, board_age_s=1.0, active="active", mode="LIMITED_LIVE",
          refusals=HEALTHY_REFUSALS, refusal_age_s=5.0, refusal_channel="risk",
          refusal_ddl=REFUSAL_DDL, refusal_extra=(), tuples="db",
          override_raw=None, board_raw=None):
    srv = tmp_path / "srv"
    (srv / "kill").mkdir(parents=True)
    (srv / "release-audit").mkdir(parents=True)
    (srv / "logs").mkdir(parents=True)
    (srv / "board").mkdir(parents=True)
    (srv / "tuples").mkdir(parents=True)
    db = srv / "tuples" / "tuples.sqlite"
    if tuples == "db":
        write_refusals(db, refusals, channel=refusal_channel, newest_age_s=refusal_age_s,
                       ddl=refusal_ddl, extra=refusal_extra)
    elif tuples == "directory":                        # opening it cannot even reach the schema
        db.mkdir()
    elif tuples == "garbage":                          # a truncated or half-copied file
        db.write_bytes(b"SQLite format 3\0" + b"\xff" * 400)
    elif tuples != "missing":
        raise AssertionError("unknown tuples fixture %r" % tuples)
    if kill:
        (srv / "kill" / "live").write_text(json.dumps({"reason": "F22 STOP", "latched_utc": 1.0}))
    for name, content in (kills or {}).items():            # any scope, any shape, any name
        write_switch(srv / "kill" / name, content)
    if breaker is not None:                                # NOT a switch; it stops more than one
        write_switch(srv / "kill" / "breaker.json", breaker)
    if override is not None:
        (srv / "kill" / "arming_override.json").write_text(json.dumps(override))
    if pin is not None:
        (srv / "release-audit" / "f24_start_utc").write_text(pin + "\n")
    (srv / "logs" / "live_stream.stdout.log").write_text(
        "".join(l + "\n" for l in (log_lines if log_lines is not None else TICKS + [MARKER])))
    if board is not None:
        (srv / "board" / "board.json").write_text(json.dumps({"as_of": time.time() - board_age_s, **board}))
    # Raw bytes, for the shapes json.dumps cannot make: a bare scalar, a half-written file.
    if override_raw is not None:
        (srv / "kill" / "arming_override.json").write_text(override_raw)
    if board_raw is not None:
        (srv / "board" / "board.json").write_text(board_raw)

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
    assert '"kill_switch_names": []' in out, "the empty directory is stated, not assumed"
    assert '"stops_the_lane": false' in out, "and so is the breaker"


# ── round 3: every way the deployed lane can be stopped ─────────────────────────────────────────
def test_each_of_the_five_kill_scopes_prevents_armed_and_is_reported_by_name(tmp_path):
    """kill.active() honours all five; the tooling recognised only `live` and `all`."""
    for i, (name, body) in enumerate(FIVE_SCOPES.items()):
        d = tmp_path / str(i)
        d.mkdir()
        rc, out = probe(d, kill=False, override=LIVE_OVERRIDE, kills={name: body})
        assert verdict(out) != "F24_STATE: ARMED" and rc != 0, f"{name} must prevent ARMED:\n{out}"
        assert f'"name": "{name}"' in out, f"{name} must be reported by name:\n{out}"
        assert body["reason"] in out, f"{name}'s reason must be reported:\n{out}"


def test_a_touched_switch_with_no_reason_still_prevents_armed(tmp_path):
    """`touch` and `rm` are the whole operator interface: an empty file is a switch."""
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE, kills={"venue-kalshi": None})
    assert verdict(out) != "F24_STATE: ARMED" and rc != 0, out
    assert '"name": "venue-kalshi"' in out and '"scope": "venue"' in out, out


def test_an_unrecognised_file_is_reported_but_does_not_decide(tmp_path):
    """It matches none of kill.active()'s five shapes, so nothing consults it and it stops nothing.
    Reported loudly, because an unexpected file in that directory is worth a human look."""
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE,
                    kills={"KILL-EVERYTHING": {"reason": "set by hand at 03:00"}})
    assert verdict(out) == "F24_STATE: ARMED" and rc == 0, out
    assert '"unrecognised_kill_files"' in out and "KILL-EVERYTHING" in out, out
    assert '"recognised": false' in out, out
    assert evidence(out)["recognised_kill_switch_names"] == [], out


def test_a_recognised_scope_alongside_an_unrecognised_file_still_prevents_armed(tmp_path):
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE,
                    kills={"KILL-EVERYTHING": None, "venue-polymarket": {"reason": "venue halted"}})
    assert verdict(out) != "F24_STATE: ARMED" and rc != 0, out
    assert evidence(out)["recognised_kill_switch_names"] == ["venue-polymarket"], out


def test_a_directory_entry_is_a_switch_too(tmp_path):
    """_present() tests exists(), which a directory satisfies, so active() honours it -- while
    any_present() filters it out. Enumerating with is_file() alone would miss it."""
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE, kills={"live": DIRECTORY})
    assert verdict(out) != "F24_STATE: ARMED" and rc != 0, out
    assert '"is_file": false' in out, out


def test_a_latched_breaker_is_not_armed_even_with_an_empty_kill_directory(tmp_path):
    """THE ROUND-3 BLOCKER. evaluate() returns BREAKER_LATCHED before any kill latch, so kill/live
    is never re-created: clearing it leaves a clean directory and a lane that refuses everything."""
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE, breaker=LATCHED_BREAKER)
    assert verdict(out) == "F24_STATE: INDETERMINATE" and rc == 3, out
    assert LATCHED_BREAKER["reason"] in out, "the latch reason is reported"
    assert '"latched_utc_iso"' in out and "2026-09" in out, "and when it latched"
    assert "LossBreaker.reset(by=<name>)" in out and "human decision" in out, out
    assert "nothing under ops/ calls it" in out, "no ops script clears it; verified at 59dd5ae"


def test_a_breaker_that_is_present_but_not_latched_does_not_prevent_armed(tmp_path):
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE,
                    breaker={"latched": False, "reason": "", "latched_utc": None})
    assert verdict(out) == "F24_STATE: ARMED" and rc == 0, out


def test_an_empty_breaker_file_is_not_a_latch(tmp_path):
    """LossBreaker._load reads `read_text() or "{}"`: an empty file is an unlatched breaker."""
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE, breaker="")
    assert verdict(out) == "F24_STATE: ARMED" and rc == 0, out


def test_an_unreadable_or_unparseable_breaker_is_treated_as_latched(tmp_path):
    for sub, state in (("a", DIRECTORY), ("b", "{not json")):
        d = tmp_path / sub
        d.mkdir()
        rc, out = probe(d, kill=False, override=LIVE_OVERRIDE, breaker=state)
        assert verdict(out) == "F24_STATE: INDETERMINATE" and rc == 3, out
        assert "breaker read:" in out and "treated as latched" in out, out


def test_a_second_switch_beside_the_f22_stop_is_not_the_untouched_state(tmp_path):
    """NOT_ARMED promises "the F22 kill is in place and the F22 override is untouched". A scoped
    switch beside it is a different state, with its own decision in it."""
    rc, out = probe(tmp_path, kill=True, kills={"venue-kalshi": {"reason": "by hand"}}, pin=None,
                    override={**LIVE_OVERRIDE, "experiment": {"row_id": "F22"}},
                    board={**HEALTHY_BOARD, "f22_enabled": True,
                           "f22_authority": "F22 authority matches preregistration"})
    assert verdict(out) == "F24_STATE: INDETERMINATE" and rc == 3, out


def test_a_latched_breaker_behind_the_f22_stop_is_not_the_untouched_state_either(tmp_path):
    rc, out = probe(tmp_path, kill=True, breaker=LATCHED_BREAKER, pin=None,
                    override={**LIVE_OVERRIDE, "experiment": {"row_id": "F22"}},
                    board={**HEALTHY_BOARD, "f22_enabled": True,
                           "f22_authority": "F22 authority matches preregistration"})
    assert verdict(out) == "F24_STATE: INDETERMINATE" and rc == 3, out
    assert LATCHED_BREAKER["reason"] in out, out


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


# ── round 4: what the lane DID, not which files exist ───────────────────────────────────────────
# Rounds 2 and 3 both failed the same way: the tooling INFERRED "can the box trade" from an
# enumeration of stop causes, and 59dd5ae always had one more that leaves no durable trace. The
# general fix is to stop inferring. `grid.refuse()` counts every refusal by (channel, code, league)
# and `TupleStore.refusal_counts()` flushes them to the tuple store on every report tick, so the
# lane states why it could not act, in the database the reader already opens read-only.
def evidence(out: str) -> dict:
    return json.loads(out[out.index("{"):out.rindex("}") + 1])


def test_a_kill_switch_dominated_window_is_not_armed_with_a_clean_kill_directory(tmp_path):
    """The kill as an OBSERVED refusal. The directory is empty and the breaker is clear, so every
    file probe says ARMED -- and the lane's own last tick says it refused every candidate."""
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE,
                    refusals=({"KILL_SWITCH": 830, "IN_FLIGHT": 560}, {"KILL_SWITCH": 795}))
    assert verdict(out) == "F24_STATE: INDETERMINATE" and rc == 3, out
    ref = evidence(out)["refusals"]
    assert ref["lane_could_act"] is False, ref
    assert ref["blocking_in_the_newest_tick"][0] == {
        "code": "KILL_SWITCH", "n": 830, "class": "blocking", "age_s": ref["newest_tick_age_s"]}
    assert "KILL_SWITCH x830" in ref["why"] and ref["newest_tick_age_s"] <= 10.0, ref
    assert '"kill_switch_names": []' in out, "the files still say the directory is empty"


def test_a_breaker_dominated_window_is_not_armed_and_this_is_the_pnl_unknown_case(tmp_path):
    """THE ROUND-4 BLOCKER. `breaker.evaluate()` returns PNL_UNKNOWN while ONE fill is still
    UNCONFIRMED: it refuses every candidate for the rest of the UTC day and writes NOTHING -- no
    kill file, no latch in breaker.json, no lane flag. It reaches the risk channel as BREAKER."""
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE,
                    breaker={"latched": False, "reason": "", "latched_utc": None},
                    refusals=({"BREAKER": 612, "IN_FLIGHT": 9}, {"BREAKER": 588}))
    assert verdict(out) == "F24_STATE: INDETERMINATE" and rc == 3, out
    ev = evidence(out)
    assert ev["breaker"]["latched"] is False, "breaker.json itself is NOT latched -- that is the point"
    assert not ev["kill_switches"] and ev["arm_is_stale"] is False
    assert ev["refusals"]["lane_could_act"] is False
    assert "BREAKER x612" in ev["refusals"]["why"], ev["refusals"]["why"]


def test_a_healthy_window_of_per_candidate_refusals_does_not_prevent_armed(tmp_path):
    """The rule MUST NOT fire on the refusals a trading lane prints continuously."""
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE,
                    refusals=({"MIN_PROFIT": 31, "IN_FLIGHT": 118, "HEDGE_DEPTH_CHANGED": 4,
                               "STALE_BOOK": 7, "MIN_RETURN": 3, "CAP_STAKE": 22,
                               "CAP_CONTRACTS": 19, "CAP_DAY_NOTIONAL": 2, "EVENT_IN_FLIGHT": 5,
                               "MAX_UNHEDGED": 1, "LEAGUE_EXPOSURE": 1, "VENUE_CAPITAL": 1,
                               "EVENT_NOTIONAL": 1, "EMPTY_RESERVATION": 1},))
    assert verdict(out) == "F24_STATE: ARMED" and rc == 0, out
    ref = evidence(out)["refusals"]
    assert ref["lane_could_act"] is True and not ref["blocking_in_the_newest_tick"], ref
    assert "do NOT prove the kill" in ref["why"], "and it says what that does not prove"


def test_every_persistent_gate_that_blocks_every_candidate_prevents_armed(tmp_path):
    """Each of these refuses EVERY candidate while it is in force and leaves no durable trace:
    confirmed in `git show 59dd5ae:nodes/risk/clearance.py` and grids/live_stream/grid.py."""
    for i, code in enumerate(("ARM_STALE", "GUARD_FAILED", "BALANCE", "BALANCE_UNCONFIRMED",
                              "FEE_SCHEDULE", "CLOCK_UNHEALTHY", "NO_CAPS", "MODE",
                              "VENUE_DISCONNECTED", "VENUE_GEOBLOCKED", "MAX_EVENTS",
                              "TOTAL_CAPITAL", "UNRESOLVED_EXPOSURE")):
        d = tmp_path / str(i)
        d.mkdir()
        rc, out = probe(d, kill=False, override=LIVE_OVERRIDE,
                        refusals=({code: 77, "IN_FLIGHT": 40},))
        assert verdict(out) != "F24_STATE: ARMED" and rc != 0, f"{code} must prevent ARMED:\n{out}"
        assert "%s x77" % code in evidence(out)["refusals"]["why"], code


def test_an_unclassified_refusal_code_fails_closed(tmp_path):
    """Exactly as an unrecognised file in the kill directory does: nothing here can prove that a
    code this script has never seen refuses only one candidate."""
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE,
                    refusals=({"SOME_NEW_GATE": 41, "IN_FLIGHT": 12},))
    assert verdict(out) != "F24_STATE: ARMED" and rc != 0, out
    assert evidence(out)["refusals"]["blocking_in_the_newest_tick"][0]["class"] == "unclassified"


def test_only_the_newest_tick_decides_so_a_lifted_stop_does_not_linger(tmp_path):
    """A cause that has been lifted stops producing rows; one still in force reproduces every tick.
    The older ticks are still REPORTED -- they are just not the verdict."""
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE,
                    refusals=({"MIN_PROFIT": 3, "IN_FLIGHT": 8}, {"KILL_SWITCH": 900},
                              {"KILL_SWITCH": 870}))
    assert verdict(out) == "F24_STATE: ARMED" and rc == 0, out
    ref = evidence(out)["refusals"]
    assert ref["counts_over_the_kept_ticks"]["KILL_SWITCH"] == 1770, "the history is still reported"
    assert ref["lane_could_act"] is True and ref["ticks_seen"] == 3, ref


def test_an_empty_refusal_window_is_absence_of_evidence_not_health(tmp_path):
    """A quiet slate produces no refusal at all. That must not become a reason to say ARMED, and it
    must not silently read as health either: it is stated as absence in the evidence."""
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE, refusals=())
    assert verdict(out) == "F24_STATE: ARMED" and rc == 0, "the file evidence alone still decides"
    ref = evidence(out)["refusals"]
    assert ref["lane_could_act"] is None and ref["ticks_seen"] == 0, ref
    assert "ABSENCE OF EVIDENCE" in ref["why"] and "not evidence that the lane can trade" in ref["why"]


def test_a_refusal_window_older_than_five_report_ticks_is_absence_not_health(tmp_path):
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE, refusal_age_s=400.0,
                    refusals=({"KILL_SWITCH": 900},))
    assert verdict(out) == "F24_STATE: ARMED" and rc == 0, out
    ref = evidence(out)["refusals"]
    assert ref["lane_could_act"] is None and "ABSENCE OF EVIDENCE" in ref["why"], ref
    assert ref["deciding_tick_max_age_s"] == 150.0, "five report ticks of the lane's own period"


def test_refusals_from_before_the_start_pin_cannot_decide(tmp_path):
    """arm_f24.sh pins the start the instant it archives the F22 kill, so the tick straddling that
    moment counts refusals from while the kill was still in place. Without this boundary every
    successful arm would verify INDETERMINATE on evidence from before the arm."""
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE, pin="%.3f" % (time.time() - 10.0),
                    refusal_age_s=20.0, refusals=({"KILL_SWITCH": 830},))
    assert verdict(out) == "F24_STATE: ARMED" and rc == 0, out
    ref = evidence(out)["refusals"]
    assert ref["lane_could_act"] is None and "before the F24 start pin" in ref["why"], ref


def test_a_missing_malformed_or_future_start_pin_leaves_no_boundary(tmp_path):
    """The boundary is the ONE thing in this probe that can suppress evidence, so every way of
    getting it wrong -- including a pin dated in the future -- must fail towards deciding."""
    for i, pin in enumerate((None, "not-a-number", "%.3f" % (time.time() + 3600.0))):
        d = tmp_path / str(i)
        d.mkdir()
        rc, out = probe(d, kill=False, override=LIVE_OVERRIDE, pin=pin,
                        refusal_age_s=20.0, refusals=({"KILL_SWITCH": 830},))
        assert verdict(out) != "F24_STATE: ARMED" and rc != 0, f"{pin!r}:\n{out}"
        ref = evidence(out)["refusals"]
        assert ref["ticks_before_this_are_pre_arm"] is None and ref["lane_could_act"] is False, ref
    assert "pin_is_in_the_future" in evidence(out)["refusals"], "and a future pin is named"


def test_the_size_channel_is_never_read(tmp_path):
    """Its flags are contaminated by the sizer's q=100 rung; the RISK channel is the one that says
    the lane could not act at all."""
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE, refusal_channel="size",
                    refusals=({"KILL_SWITCH": 900, "NO_FEASIBLE_SIZE": 400},))
    assert verdict(out) == "F24_STATE: ARMED" and rc == 0, out
    ref = evidence(out)["refusals"]
    assert ref["channel"] == "risk" and ref["ticks_seen"] == 0, ref


def test_a_missing_refusal_table_is_a_named_probe_error_and_refuses_armed(tmp_path):
    """The table is created lazily by the first `refusal_counts()` call. mode=ro cannot create it,
    and this probe must not try: an unreadable record leaves only file evidence, which is exactly
    the evidence three rounds found insufficient."""
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE, refusal_ddl=(), refusals=())
    assert verdict(out) == "F24_STATE: INDETERMINATE" and rc == 3, out
    ref = evidence(out)["refusals"]
    assert "no such table: refusal_counts" in ref["error"], ref
    assert ref["lane_could_act"] is None and "ARMED is refused on that ground" in ref["why"]


def test_an_unreadable_refusal_database_is_a_named_probe_error_and_refuses_armed(tmp_path):
    for sub, shape in (("a", "missing"), ("b", "directory"), ("c", "garbage")):
        d = tmp_path / sub
        d.mkdir()
        rc, out = probe(d, kill=False, override=LIVE_OVERRIDE, tuples=shape)
        assert verdict(out) == "F24_STATE: INDETERMINATE" and rc == 3, f"{shape}:\n{out}"
        assert evidence(out)["refusals"]["error"], shape


def test_the_probe_opens_the_tuple_store_read_only_and_leaves_it_byte_identical(tmp_path):
    """Strictly read-only: it may not create the file, create the table, or migrate anything."""
    (tmp_path / "a").mkdir()
    rc, out = probe(tmp_path / "a", kill=False, override=LIVE_OVERRIDE)
    assert rc == 0, out
    ref = evidence(out)["refusals"]
    assert ref["ticks_seen"] == 2 and ref["rows_read"] == 5, "the database was actually read: %s" % ref
    assert ref["path"].endswith("/tuples/tuples.sqlite") and ref["row_cap_hit"] is False
    left = sorted(p.name for p in (tmp_path / "a" / "srv" / "tuples").iterdir())
    assert left == ["tuples.sqlite"], "no -wal, no -shm, no journal: %s" % left

    # And the same database re-read by hand is unchanged and still has no extra table.
    con = sqlite3.connect(str(tmp_path / "a" / "srv" / "tuples" / "tuples.sqlite"))
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master")}
    con.close()
    assert names == {"refusal_counts", "refusal_counts_ts"}, names

    # A store with no table at all must come back with no table at all.
    (tmp_path / "b").mkdir()
    probe(tmp_path / "b", kill=False, override=LIVE_OVERRIDE, refusal_ddl=(), refusals=())
    con = sqlite3.connect(str(tmp_path / "b" / "srv" / "tuples" / "tuples.sqlite"))
    assert not {r[0] for r in con.execute("SELECT name FROM sqlite_master")}, "mode=ro created a table"
    con.close()


def test_the_untouched_f22_state_with_kill_switch_refusals_still_reads_not_armed(tmp_path):
    """In that state the kill IS latched, so KILL_SWITCH refusals corroborate the files rather than
    contradicting them. NOT_ARMED must stay reachable or the operator's safe state is unreportable."""
    rc, out = probe(tmp_path, kill=True, override={**LIVE_OVERRIDE, "experiment": {"row_id": "F22"}},
                    pin=None, refusals=({"KILL_SWITCH": 830, "IN_FLIGHT": 512},),
                    board={**HEALTHY_BOARD, "f22_enabled": True,
                           "f22_authority": "F22 authority matches preregistration"})
    assert verdict(out) == "F24_STATE: NOT_ARMED" and rc == 2, out
    ev = evidence(out)
    assert ev["refusals"]["lane_could_act"] is False
    assert ev["observed_a_stop_beyond_the_kill"] is False, "the kill is the only observed stop"


def test_an_observed_stop_beyond_the_kill_is_not_the_untouched_f22_state(tmp_path):
    """The F22 override expired: grid._execute refuses ARM_STALE BEFORE the clearance is reached, so
    the kill is never even consulted and nothing on disk changes. Arming over it is arming into a
    second stop the operator has not been told about -- that is not "untouched"."""
    rc, out = probe(tmp_path, kill=True, override={**LIVE_OVERRIDE, "experiment": {"row_id": "F22"}},
                    pin=None, refusals=({"ARM_STALE": 240},),
                    board={**HEALTHY_BOARD, "f22_enabled": True,
                           "f22_authority": "F22 authority matches preregistration"})
    assert verdict(out) == "F24_STATE: INDETERMINATE" and rc == 3, out
    assert evidence(out)["observed_a_stop_beyond_the_kill"] is True


def test_the_rule_is_stated_in_the_evidence_and_is_not_a_dominance_threshold(tmp_path):
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE)
    rule = evidence(out)["refusals"]["rule"]
    assert "ANY blocking code in the NEWEST" in rule and "not dominance" in rule, rule
    assert "MIN_PROFIT, IN_FLIGHT, HEDGE_DEPTH_CHANGED" in rule, "it names what it may not fire on"
    assert "fail closed" in rule, "and what an unknown code does"


# ── round 4: the board fields the probe parsed and threw away ───────────────────────────────────
def test_instantaneous_board_health_is_evidence_not_a_verdict(tmp_path):
    """Measured on the box 2026-09-18: this single-vCPU lane runs at ~1.4 s loop lag and spikes past
    its 5 s stall bound intermittently (one tick showed 10.0 s), and socket reconnects are routine.
    Gating the verdict on either flag would make ARMED unreachable or flapping, which is how a real
    stop gets ignored. Both are reported, and `health_note` spells out what they mean."""
    stalled = probe(tmp_path / "s", kill=False, override=LIVE_OVERRIDE,
                    board={**HEALTHY_BOARD, "stalled": True, "loop_lag_s": 8.4})
    rc, out = stalled
    assert verdict(out) == "F24_STATE: ARMED" and rc == 0, out
    ev = evidence(out)
    assert ev["loop_is_stalled"] is True and ev["loop_lag_s"] == 8.4
    assert any("CLOCK_UNHEALTHY" in n for n in ev["health_note"]), ev["health_note"]

    rc, out = probe(tmp_path / "d", kill=False, override=LIVE_OVERRIDE,
                    board={**HEALTHY_BOARD,
                           "sockets": {"kalshi": {"connected": True},
                                       "polymarket": {"connected": False}}})
    assert verdict(out) == "F24_STATE: ARMED" and rc == 0, out
    ev = evidence(out)
    assert ev["every_venue_socket_is_up"] is False
    assert any("two legs" in n for n in ev["health_note"]), ev["health_note"]


def test_a_stall_that_is_actually_refusing_candidates_is_not_armed(tmp_path):
    """The difference that matters: not the flag, but whether it refused anything. A persistent
    stall reaches the risk gate as CLOCK_UNHEALTHY, and that is in BLOCKING."""
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE,
                    board={**HEALTHY_BOARD, "stalled": True, "loop_lag_s": 8.4},
                    refusals=({"CLOCK_UNHEALTHY": 412},))
    assert verdict(out) != "F24_STATE: ARMED" and rc != 0, out
    assert evidence(out)["observed_lane_could_act"] is False


def test_a_venue_disconnect_that_is_actually_refusing_candidates_is_not_armed(tmp_path):
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE,
                    refusals=({"VENUE_DISCONNECTED": 77},))
    assert verdict(out) != "F24_STATE: ARMED" and rc != 0, out
    assert evidence(out)["observed_lane_could_act"] is False


def test_a_stale_or_missing_board_is_indeterminate_not_a_silent_fallback_to_the_log(tmp_path):
    """The log can answer the arm; it cannot answer the loop or the sockets. Falling back to it in
    silence is how a stalled lane read ARMED."""
    for sub, kwargs in (("a", {"board_age_s": 600.0}), ("b", {"board": None})):
        d = tmp_path / sub
        d.mkdir()
        rc, out = probe(d, kill=False, override=LIVE_OVERRIDE, log_lines=TICKS + [MARKER], **kwargs)
        assert verdict(out) == "F24_STATE: INDETERMINATE" and rc == 3, out
        ev = evidence(out)
        assert ev["board_is_fresh"] is False and ev["every_venue_socket_is_up"] is None
        assert ev["arm_source"] == "log" and ev["arm_is_stale"] is False, "the log still answered"


# ── round 4: a bare JSON scalar must not crash a probe through .get() ───────────────────────────
def test_a_bare_json_scalar_in_the_kill_directory_does_not_crash_the_probe(tmp_path):
    for i, body in enumerate(("1234", '"stopped"', "[1, 2]", "null")):
        d = tmp_path / str(i)
        d.mkdir()
        rc, out = probe(d, kill=False, override=LIVE_OVERRIDE, kills={"venue-kalshi": body})
        assert verdict(out) == "F24_STATE: INDETERMINATE" and rc == 3, out
        s = next(s for s in evidence(out)["kill_switches"] if s["name"] == "venue-kalshi")
        assert "not an object" in s["unparsed"], s
        assert "Traceback" not in out and "AttributeError" not in out


def test_a_bare_json_scalar_breaker_is_treated_as_latched(tmp_path):
    rc, out = probe(tmp_path, kill=False, override=LIVE_OVERRIDE, breaker="1234")
    assert verdict(out) == "F24_STATE: INDETERMINATE" and rc == 3, out
    ev = evidence(out)
    assert ev["breaker"]["latched"] is None and ev["breaker"]["stops_the_lane"] is True
    assert any("breaker read: ValueError" in e and "not an object" in e for e in ev["errors"]), ev


def test_a_bare_scalar_or_half_written_override_is_a_named_probe_error(tmp_path):
    # A scalar used to reach `.get()` and be reported as "'int' object has no attribute 'get'" --
    # an interpreter message standing in for a named finding. An empty file used to read as an
    # override with no terms, though ops/arming_override.py truncates in place, so 0 bytes means a
    # half-written file. Both degrade to a NAMED probe error now.
    for body, named in (("1234", "not an object"), ('"F24_STATE: ARMED"', "not an object"),
                        ("[]", "not an object"), ('{"mode": "LIMITED_LIVE"', "JSONDecodeError"),
                        ("", "half-written file"), ("   \n", "half-written file")):
        d = tmp_path / str(abs(hash(body)) % 99999)
        d.mkdir()
        rc, out = probe(d, kill=False, override=None, override_raw=body)
        assert verdict(out) == "F24_STATE: INDETERMINATE" and rc == 3, f"{body!r}:\n{out}"
        ev = evidence(out)
        assert ev["override"] == {"exists": None}, ev["override"]
        assert any(e.startswith("override read: ") and named in e for e in ev["errors"]), \
            f"{body!r} must name why: {ev['errors']}"
        assert "Traceback" not in out and "AttributeError" not in out


def test_a_bare_scalar_or_half_written_board_is_a_named_reason_not_a_crash(tmp_path):
    for i, body in enumerate(("1234", '{"as_of": ', "null", "[]")):
        d = tmp_path / str(i)
        d.mkdir()
        rc, out = probe(d, kill=False, override=LIVE_OVERRIDE, log_lines=TICKS + [MARKER],
                        board=None, board_raw=body)
        assert verdict(out) == "F24_STATE: INDETERMINATE" and rc == 3, f"{body!r}:\n{out}"
        assert "unreadable or malformed" in evidence(out)["board"]["why"], out
        assert "Traceback" not in out and "AttributeError" not in out


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
    assert "sudo -u janus" in p
    # It DOES open a database now (round 4), and the only way it is allowed to. `mode=ro` cannot
    # create the file, cannot create the table and cannot migrate: the failure modes are a named
    # probe error, never a write to a database the live lane is committing into.
    assert 'sqlite3.connect("file:%s?mode=ro" % TUPLES, uri=True' in code
    assert code.count("sqlite3.connect(") == 1, "one connection, one place to audit it"
    for statement in ("CREATE ", "INSERT ", "UPDATE ", "DELETE ", "ALTER ", "DROP ", "PRAGMA ",
                      "ensure_ddl", "commit("):
        assert statement not in code, f"the verify payload must not {statement!r}"
    assert "SELECT seen_ts, code, SUM(n) FROM refusal_counts" in code, "a read, and only this one"
    assert subprocess.run(["bash", "-n"], input=p, capture_output=True, text=True).returncode == 0


def test_armed_requires_no_kill_no_experiment_and_the_registered_caps(tmp_path):
    _, p = _verify(tmp_path, out_text="F24_STATE: NOT_ARMED", rc=2)
    body = embedded(p, "PYV")
    armed = body[body.index("armed = ("):body.index("# NOT_ARMED is")]
    for required in ("recognised_kill_switch_names", "breaker", "has_experiment", "caps_are_the_registered_ones",
                     "not_expired", "running", "is_the_capital_risking_mode"):
        assert required in armed, f"ARMED must depend on {required}"
    assert '"stake_usd": 30.0, "max_contracts": 25.0, "day_notional_usd": 500.0' in body
    assert F22_SHA in body


def test_the_probe_enumerates_the_kill_directory_and_never_hardcodes_two_names(tmp_path):
    """The round-3 family in one line: two names out of five scopes plus the breaker is not a check."""
    _, p = _verify(tmp_path, out_text="F24_STATE: NOT_ARMED", rc=2)
    body = embedded(p, "PYV")
    assert "os.listdir(KILL_DIR)" in body, "the directory is enumerated, not sampled"
    assert 'NOT_A_KILL = ("arming_override.json", "breaker.json")' in body
    for prefix in ("venue-", "event-", "strategy-"):
        assert prefix in body, f"the {prefix} scope must be recognised"
    assert "return None" in body and "fails closed" in body, "an unknown name fails closed"
    assert "BREAKER" in body and "stops_the_lane" in body, "breaker.json is read"


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


def test_check_carries_the_reader_compressed_because_ssm_caps_a_command_at_97kb(tmp_path):
    """report.py outgrew the limit, so it travels gzip+base64 and is unpacked on the box. It must
    still arrive byte for byte: the decoded blob is the file."""
    import base64 as _b64, gzip as _gz
    out, p = _check(tmp_path, "1789418782.132788", "1789505182.132788")
    assert "1789418782.132788 1789505182.132788" in p
    blob = re.search(r"printf %s '([A-Za-z0-9+/=]{200,})' \| base64 -d \| gzip -dc", p)
    assert blob, "the reader is not carried compressed"
    assert _gz.decompress(_b64.b64decode(blob.group(1))).decode() == REPORT.read_text()
    assert len(p) < 97 * 1024, "the whole command has to fit inside SSM's 97 KB limit"
    assert subprocess.run(["bash", "-n"], input=p, capture_output=True, text=True).returncode == 0


def test_two_overlapping_checks_cannot_delete_each_others_script(tmp_path):
    _, p = _check(tmp_path, "1789418782.132788")
    assert "mktemp" in p, "each run stages the reader at its own path"
    assert "/tmp/f24_report.py" not in p, "the fixed path is what made two runs collide"


def test_check_rejects_anything_but_numbers(tmp_path):
    for bad in (("abc",), ("1; rm -rf /",), ("1", "2 3"), ()):
        out, p = _check(tmp_path, *bad)
        assert out.returncode == 2 and p is None, bad
