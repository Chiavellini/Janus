#!/usr/bin/env bash
# F24: arm the plain taker profitability test. Prints the remote payload by default.
#
#   bash arm_f24.sh "<verbatim operator statement>"          # dry run: shows exactly what would run
#   bash arm_f24.sh "<verbatim operator statement>" --send   # does it, on the box, through ops/box/run.sh
#
# Requires a dated GATE_TO_LIVE amendment carrying the SAME verbatim statement first.
#
# In one remote pass it refuses unless it holds the arming lock, no F24 start pin already exists, the
# lane is active in LIMITED_LIVE, the kill is exactly the F22 STOP, NOTHING ELSE IN THE KILL
# DIRECTORY STOPS THE LANE, and the account is quiet with no unresolved material flag. Then, in this
# order:
#   1. copies whatever override is currently on disk into the audit directory, NAMED AND DESCRIBED BY
#      WHAT IT ACTUALLY IS (the deployed writer truncates in place, so the copy is the only way back
#      from a half-written file -- but on a second attempt it is the previous attempt's F24 override,
#      not the F22 authority, and the abort message says so);
#   2. writes an override with NO experiment block, at the unchanged caps ($30 / 25 / $500, 168 h);
#   3. waits for the lane to re-read it and prove it is armed AND NOT STALE -- if it does not, it
#      stops and LEAVES THE KILL IN PLACE;
#   4. repeats the quiet check, because the wait is long enough for a new alarm to appear;
#   5. archives (never deletes) the exact F22 kill, then pins the start time on the box.
# The order matters: clearing the kill under the current F22 override would resume F22.
#
# ARCHIVING kill/live IS NOT THE SAME AS LETTING THE LANE TRADE. nodes/risk/kill.py (59dd5ae) keeps
# FIVE scopes in that one directory -- all, live, venue-<venue>, event-<event_id>,
# strategy-<version> -- and clearance.clear() refuses every candidate any of them applies to; an
# unrecognised name is REPORTED but does not refuse: active() consults five exact shapes and nothing
# same directory holds breaker.json, which is not a kill file and stops more: once the $25/UTC-day
# breaker latches, evaluate() answers BREAKER_LATCHED from that file BEFORE any kill switch, so
# kill/live is never re-created and every candidate is refused for the rest of the window. Only
# LossBreaker.reset(by=<name>) clears it and nothing under ops/ calls it. Arming into either state
# would write a live override, archive the F22 stop, and leave a lane that places no orders at all
# while every report calls the row IN_PROGRESS -- so the pre-arm pass refuses both, by name.
#
# STEP 3 IS NOT A GREP FOR "[f22] disabled". `grid.check_arm` prints its markers only when they
# CHANGE, and when the arm is stale it forces F22 disabled WITH THE STALE REASON AS THE AUTHORITY
# STRING -- so a lane that was already refusing every order logs a line that reads, literally,
# "[f22] disabled: override pins a different code tree (running ...)". A rule that accepts any
# "[f22] disabled" therefore arms on a dead lane. This script instead prefers the lane's own
# authoritative artifact, /srv/janus/board/board.json (Supervisor.write_board, one second old),
# which states arm_stale / f22_enabled / mode directly with its own timestamp; the log is only the
# fallback, and there the WHOLE log's last "[arm] " marker must not be a STALE one and the last
# "[f22] disabled" must carry the F24 authority itself, never a stale reason.
#
# NEITHER IS THE PRE-ARM PASS BELOW A PROOF THAT THE LANE WILL TRADE. It enumerates stop causes, and
# at 59dd5ae there is always one more that leaves no file: `breaker.evaluate()` answers PNL_UNKNOWN
# while a single fill is still UNCONFIRMED and refuses every candidate for the rest of the UTC day
# without latching breaker.json, and BALANCE, BALANCE_UNCONFIRMED, FEE_SCHEDULE and the ledger's
# reservation refusals do the same. verify_f24.sh, which decides this script's exit code, therefore
# also reads what the lane ACTUALLY DID -- the risk-channel rows of `refusal_counts` in the tuple
# store. In the F22 state that record only ever says KILL_SWITCH (clear() checks the kill before the
# breaker), so it corroborates here rather than adding a gate; it becomes the real evidence a minute
# or two AFTER the archive, which is why the ARMED message below says to read the box again.
#
# WHATEVER THIS PRINTS LOCALLY, THE BOX IS THE AUTHORITY. `ops/box/run.sh` stops listening after its
# own poll budget while the remote command runs on (memory: janus-box-ssm-long-jobs), and Ctrl-C or a
# dropped connection does the same, so a local failure does NOT mean the box is unchanged. This
# script therefore always ends by running verify_f24.sh, which reads the box itself, and its exit
# code reports THAT verdict -- never the send's.
#
# Every remote value is baked in here; the body is a quoted heredoc so nothing in it is expanded
# locally. That is the class of bug that made clear_f22_instrumentation_latch.sh non-executable.
set -euo pipefail
STATEMENT=${1:-}
MODE=${2:-}
SIGNED_BY=${JANUS_SIGNED_BY:-Bernardo}
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
RUNNER=${F24_RUNNER:-$REPO/ops/box/run.sh}

if [ -z "${STATEMENT// }" ]; then
  echo "usage: bash arm_f24.sh \"<your verbatim statement>\" [--send]" >&2
  exit 2
fi
if [ -n "$MODE" ] && [ "$MODE" != "--send" ]; then
  echo "unknown option $MODE (only --send)" >&2
  exit 2
fi
if ! printf %s "$SIGNED_BY" | grep -Eq '^[A-Za-z][A-Za-z .-]{0,40}$'; then
  echo "JANUS_SIGNED_BY must be a plain name" >&2
  exit 2
fi
B64=$(printf %s "$STATEMENT" | base64 | tr -d '\n')

read -r -d '' TEMPLATE <<'EOS' || true
set -u
PY=/opt/janus/.venv/bin/python3
KILL_DIR=/srv/janus/kill
KILL=/srv/janus/kill/live
BREAKER=/srv/janus/kill/breaker.json
OVERRIDE=/srv/janus/kill/arming_override.json
EXPECTED_KILL_SHA=d81bbfc267a235ca7f268e7317d77ee7e83c65f5263117590e4e86d1552b1636
AUDIT_ROOT=/srv/janus/release-audit
START_PIN=/srv/janus/release-audit/f24_start_utc
LOCK=/srv/janus/release-audit/.f24-arm.lock
LOG=/srv/janus/logs/live_stream.stdout.log
BOARD=/srv/janus/board/board.json
QUIET=
HELD=no
cleanup() {
  [ -n "$QUIET" ] && sudo -u janus rm -f "$QUIET"
  [ "$HELD" = yes ] && { sudo -u janus rm -f "$LOCK/owner"; sudo -u janus rmdir "$LOCK" 2>/dev/null; }
  return 0
}
trap cleanup EXIT
fail() { echo "F24_ARM_ABORTED: $*"; exit 2; }

sudo -u janus mkdir -p "$AUDIT_ROOT" || fail "cannot create the audit directory"
if ! sudo -u janus mkdir "$LOCK" 2>/dev/null; then
  OWNER=$(sudo -u janus cat "$LOCK/owner" 2>/dev/null) || OWNER=
  fail "the arming lock $LOCK is held.
  It says: ${OWNER:-(no owner file -- it predates this version, or the writer died between mkdir and the record)}
  This is EITHER a live concurrent arming run OR a leaked lock: a kill that skips the EXIT trap
  (OOM, an SSM restart, a reboot) leaves the directory behind. The two look identical from here.
  RUN verify_f24.sh FIRST: the box may already be armed, in which case do nothing else.
  To tell them apart:  ps -p <the pid above>    (gone => the run that made it is over)
                       ls -ld $LOCK ; sudo -u janus cat $LOCK/owner
  Clear it ONLY when that pid is gone and the recorded time is older than one arming pass (~5 min):
                       sudo -u janus rm -rf $LOCK
  Nothing here clears it for you, and re-running this script blindly is not a way to find out."
fi
HELD=yes
printf 'pid=%s started_utc=%s host=%s ssm_command=%s\n' "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(hostname)" "${AWS_SSM_COMMAND_ID:-unknown}" \
  | sudo -u janus tee "$LOCK/owner" > /dev/null \
  || fail "held $LOCK but could not record who holds it; clear it by hand (see verify_f24.sh first)"
[ -e "$START_PIN" ] && fail "a start pin already exists ($START_PIN) -- F24 looks armed already; run verify_f24.sh"

[ "$(systemctl is-active janus-live-stream)" = active ] || fail "lane is not active"
PID=$(systemctl show -p MainPID --value janus-live-stream)
tr '\0' ' ' < "/proc/$PID/cmdline" | grep -q -- '--mode LIMITED_LIVE' || fail "lane is not in LIMITED_LIVE"

[ -f "$KILL" ] || fail "no kill/live present; nothing to clear and no reason to arm"
[ "$(sha256sum "$KILL" | cut -d' ' -f1)" = "$EXPECTED_KILL_SHA" ] || fail "kill/live is not the exact F22 STOP"
[ -f "$OVERRIDE" ] || fail "no arming override present; refusing to write one blind"

# Archiving kill/live is not the same as letting the lane trade. nodes/risk/kill.py holds FIVE
# scopes in this one directory and clearance.clear() refuses on any of them; breaker.json, in the
# same directory, refuses everything by itself and is not lifted by removing a kill file. Arming
# into either state writes a live override, archives the F22 stop, and produces a lane that places
# no orders for the whole window -- while every report calls the row IN_PROGRESS.
STOPS=$(sudo -u janus env F24_KILL_DIR="$KILL_DIR" F24_BREAKER="$BREAKER" "$PY" - <<'PYB'
"""Could the lane trade once kill/live is archived? 0 yes (one summary line), 1 no (why, and what to do).

Read-only. Everything under kernel/paths.KILL_ROOT except arming_override.json and breaker.json is a
kill switch: `all`, `live`, `venue-<venue>`, `event-<event_id>`, `strategy-<version>`. A name outside
those five is UNRECOGNISED and refuses anyway -- nothing here can prove an unknown file is harmless.
"""
import json, os

KILL_DIR, BREAKER = os.environ["F24_KILL_DIR"], os.environ["F24_BREAKER"]
NOT_A_KILL = ("arming_override.json", "breaker.json")
SCOPED = ("venue-", "event-", "strategy-")


def scope(name):
    if name in ("all", "live"):
        return name
    for prefix in SCOPED:
        if name.startswith(prefix) and len(name) > len(prefix):
            return prefix[:-1]
    return None


def reason_of(path):
    try:
        d = json.loads(open(path).read() or "{}")
        return str(d.get("reason") or "") if isinstance(d, dict) else ""
    except Exception:                                     # noqa: BLE001 -- a touched switch is empty
        return ""


problems, notes = [], []
try:
    names = sorted(n for n in os.listdir(KILL_DIR) if n not in NOT_A_KILL and n != "live")
except OSError as exc:
    print("the kill directory %s could not be listed (%s), so the switches are UNKNOWN, not absent."
          "\n  Nothing was written. Read it by hand before arming." % (KILL_DIR, exc))
    raise SystemExit(1)

for n in names:
    s, why = scope(n), reason_of(os.path.join(KILL_DIR, n))
    tail = (": %s" % why[:120]) if why else ""
    if s is None:
        # NOT a refusal. kill.active() tests exactly "all", "live", "venue-<v>", "event-<id>" and
        # "strategy-<version>"; a name matching none of them is never consulted, so it CANNOT refuse
        # a candidate. Verified on the box 2026-09-18: the directory holds .guard-failure-*.lock and
        # .legacy-incident-*.lock left by the guard tooling, and failing closed on those would make
        # arming permanently impossible while proving nothing.
        notes.append(
            "  %s -- not a kill switch%s: it matches none of kill.active()'s five scopes, so nothing\n"
            "    consults it. Reported because an unexpected file in this directory is worth a look." % (n, tail))
    else:
        how = ("ops/box/kill.sh %s --clear lifts an ssm-latched one within five minutes; a file the\n"
               "    breaker or a human latched stays until it is removed on the box, deliberately." % n
               ) if n in ("all", "live") else (
               "kill_sync.py mirrors only all/live, so this one was set on the box itself: find out\n"
               "    who set it and why before removing it there.")
        problems.append(
            "  %s -- a %s-scope kill switch%s. clearance.clear() refuses every candidate it applies\n"
            "    to, and archiving kill/live does not lift it. %s" % (n, s, tail, how))

try:
    raw = open(BREAKER).read()
except FileNotFoundError:
    raw = None
except OSError as exc:
    raw = None
    problems.append("  breaker.json -- unreadable (%s). LossBreaker._load() reads this file at every\n"
                    "    start; an unreadable daily-loss state is treated as latched here." % exc)
if raw is not None:
    try:
        d = json.loads(raw or "{}")
    except ValueError as exc:
        d = None
        problems.append("  breaker.json -- unparseable (%s); fail closed, it may be a latch." % exc)
    if isinstance(d, dict) and d.get("latched"):
        problems.append(
            "  breaker.json -- the daily realised-loss breaker is LATCHED: %s (latched_utc=%s).\n"
            "    breaker.evaluate() returns BREAKER_LATCHED from this file BEFORE any kill switch is\n"
            "    consulted, so clearance.clear() refuses EVERY candidate and kill/live is never\n"
            "    re-created: the directory would look clean and the lane would still place no order.\n"
            "    Only LossBreaker.reset(by=<name>) clears it, and nothing under ops/ calls it (at\n"
            "    59dd5ae only nodes/risk/tests/test_risk.py does), so this is a HUMAN DECISION about\n"
            "    a day that already lost money -- not a file to delete. F24 spec.yaml also makes a\n"
            "    latch a STOP condition that ENDS the row." % (d.get("reason"), d.get("latched_utc")))

if problems:
    print("the lane could not place an order even with the F22 kill archived:\n" + "\n".join(problems)
          + "\n  NOTHING WAS WRITTEN and the kill is in place. Resolve each of these, then re-run.")
    raise SystemExit(1)
print("no other kill switch in %s and the breaker is not latched%s"
      % (KILL_DIR, ("\n  other files there, none of them switches:\n" + "\n".join(notes)) if notes else ""))
PYB
) || fail "$STOPS"
echo "F24_PREARM_STOPS: $STOPS"

# The quiet check is a FILE so it can be run again before the archive. A short or failed write leaves
# a 0-byte file, and `python3 <empty file>` exits 0 -- which would pass this gate and the post-wait
# re-check in silence. ENOSPC is this box's documented failure mode (memory: janus-disk-full), so the
# file's own last line is a sentinel and every run checks for it before believing the exit status.
QUIET=$(sudo -u janus mktemp /tmp/f24-quiet.XXXXXX.py) || fail "cannot create the quiet check"
sudo -u janus tee "$QUIET" > /dev/null <<'PYQ' || fail "the quiet check could not be written (tee failed -- the disk may be full); nothing was written"
import sqlite3, sys
sys.path.insert(0, "/opt/janus")
from nodes.risk.flags import unresolved_flag_rows
con = sqlite3.connect("file:/srv/janus/tuples/tuples.sqlite?mode=ro", uri=True)
q = lambda s: con.execute(s).fetchone()[0]
counts = {
    "unreleased": q("SELECT COUNT(*) FROM executions WHERE released IS NOT 1"),
    "unhedged": q("SELECT COUNT(*) FROM executions WHERE released IS NOT 1 AND ABS(COALESCE(unhedged,0))>0.01"),
    "open_orders": q("SELECT COUNT(*) FROM orders WHERE open IS NOT 0 OR settlement_pending IS NOT 0 OR state='UNCONFIRMED'"),
    "open_reservations": q("SELECT COUNT(*) FROM capital_reservations WHERE released_utc IS NULL"),
}
flags = {f: len(unresolved_flag_rows(con, f)) for f in (
    "ORDER_PERSISTENCE_FAILED", "POST_ONLY_PERSISTENCE_FAILED", "ORPHAN_FILL", "POSITION_MISMATCH",
    "PROTECT_FAILED", "EXEC_CRASHED", "ORDER_OVERFILL", "POST_ONLY_ROLE_VIOLATION", "UNHEDGED_POSITION",
    "RESERVATION_MISSING", "FEE_ABOVE_PIN", "F22_PERSISTENCE_FAILED", "GUARD_FAILED")}
bad = {k: v for k, v in {**counts, **flags}.items() if v}
print("quiet check:", "OK" if not bad else bad)
sys.exit(1 if bad else 0)
# F24_QUIET_SENTINEL
PYQ
quiet_or_fail() {
  grep -q '^# F24_QUIET_SENTINEL$' "$QUIET" \
    || fail "the quiet check at $QUIET is empty or truncated: its sentinel is gone, so the write was
  short or failed (ENOSPC is this box's documented failure mode) and an empty file would have exited
  0 and passed this gate in silence. $2"
  sudo -u janus env JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box "$PY" "$QUIET" || fail "$1"
}
quiet_or_fail "account is not quiet" "Nothing was written."

# The backup is a copy of WHATEVER IS ON DISK NOW. On a first attempt that is the F22 authority; on a
# second attempt it is the previous attempt's F24 override and the F22 authority is NOT in it. Name
# and describe it by what it is, so the abort message below cannot lie either way.
WHAT=$(sudo -u janus "$PY" - <<'PYD'
import json
try:
    d = json.load(open("/srv/janus/kill/arming_override.json"))
except Exception as exc:
    print("unreadable|UNREADABLE (%s): the copy is a byte-for-byte snapshot; inspect it by hand" % type(exc).__name__)
    raise SystemExit(0)
e = d.get("experiment") if isinstance(d.get("experiment"), dict) else None
row = str((e or {}).get("row_id") or "")
slug = "".join(c if (c.isalnum() or c in "-_") else "-" for c in (row or "no-experiment"))[:32]
what = ("the %s authority" % row) if row else (
    "an override with NO experiment block, i.e. an F24-shaped one and NOT the F22 authority -- a "
    "previous attempt already replaced it; the F22 authority, if you still need it, is in the "
    "earliest override-before-F24-*.json under /srv/janus/release-audit")
print("%s|%s: mode=%s signed_by=%s written_utc=%s expires_utc=%s" % (
    slug, what, d.get("mode"), d.get("signed_by"), d.get("written_utc"), d.get("expires_utc")))
PYD
)
[ -n "$WHAT" ] || fail "could not read $OVERRIDE to describe what is about to be copied aside"
SLUG=${WHAT%%|*}
DESC=${WHAT#*|}
BACKUP="$AUDIT_ROOT/override-before-F24-$SLUG-$(date +%s).json"
sudo -u janus cp -p "$OVERRIDE" "$BACKUP" || fail "could not copy the current override aside"
echo "F24_OVERRIDE_BACKUP: $BACKUP"
echo "F24_OVERRIDE_BACKUP_IS: a byte-for-byte copy of $OVERRIDE as it was one moment ago -- $DESC"

printf %s '@@B64@@' | base64 -d > /tmp/f24-statement.txt
chmod 644 /tmp/f24-statement.txt
sudo -u janus bash -c 'set -a; . /run/janus/janus.env; set +a; cd /opt/janus; JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box .venv/bin/python3 ops/arming_override.py --mode LIMITED_LIVE --signed-by "@@SIGNER@@" --stake-usd 30 --max-contracts 25 --day-notional-usd 500 --expires-hours 168 --force --statement "$(cat /tmp/f24-statement.txt)"'
RC=$?
rm -f /tmp/f24-statement.txt
[ "$RC" = 0 ] || fail "override write failed; the kill is in place and $BACKUP holds what was on disk before this attempt -- $DESC"
sudo -u janus "$PY" -c 'import json,sys; d=json.load(open("/srv/janus/kill/arming_override.json")); sys.exit(1 if d.get("experiment") else 0)' \
  || fail "the new override still carries an experiment block; kill left in place"

# MARK is taken AFTER the override is written, so any report tick past it proves check_arm() re-read
# the new file: grid.py calls sup.check_arm() immediately before printing the "] pollers=" line.
MARK=$(wc -l < "$LOG")
SEEN=no
for _ in $(seq 1 45); do
  sleep 5
  set +e
  WHY=$(sudo -u janus env F24_MARK="$MARK" F24_LOG="$LOG" F24_BOARD="$BOARD" F24_OVERRIDE="$OVERRIDE" F24_PID="$PID" "$PY" - <<'PYC'
"""Is the lane ARMED AND NOT STALE under the override we just wrote? 0 yes, 1 not yet, 2 refuse.

Read-only. grid.check_arm prints "[arm] STALE <reason>" / "[f22] ..." ONLY when they CHANGE, and a
stale arm is reported as f22 disabled WITH THE STALE REASON AS THE AUTHORITY STRING. So "[f22]
disabled" alone proves nothing: a lane that has been refusing every order for hours prints exactly
that. Supervisor.write_board's snapshot states arm_stale / f22_enabled / mode outright and is one
second old, so it is the primary signal; the log is the fallback.
"""
import json, os, sys, time

LOG, OVERRIDE = os.environ["F24_LOG"], os.environ["F24_OVERRIDE"]
MARK = int(os.environ["F24_MARK"])
AUTH = "override has no F22 experiment authority"     # entry_experiment.f22_activation, no experiment block
MARKER = "[f22] disabled: " + AUTH


def say(code, msg):
    print(msg)
    sys.exit(code)


def board_path():
    """Whatever --board the running lane was given; its argparse default otherwise."""
    try:
        argv = open("/proc/%s/cmdline" % os.environ["F24_PID"], "rb").read().decode().split("\0")
    except OSError:
        argv = []
    for i, a in enumerate(argv):
        if a.startswith("--board="):
            return a[len("--board="):]
        if a == "--board" and i + 1 < len(argv):
            return argv[i + 1]
    return os.environ["F24_BOARD"]


try:
    lines = open(LOG, "rb").read().decode("utf-8", "replace").splitlines()
except OSError as exc:
    say(1, "cannot read the lane log: %s" % exc)
new = lines[MARK:]

for ln in new:
    if "[arm] STALE" in ln:
        say(2, "the lane reports the new override STALE: %s" % ln.strip()[:160])

# The whole log, not just since the mark: a lane that was ALREADY stale says nothing when the new
# override is stale for the same reason. A healthy lane prints no "[arm] " line at all until it goes
# stale, and prints "override matches again; real orders resume" when it recovers.
arms = [l for l in lines if "[arm] " in l]
if arms and "[arm] STALE" in arms[-1]:
    say(2, "the lane's last arm marker is STALE and it never recovered: %s" % arms[-1].strip()[:160])

ticks = sum(1 for l in new if "] pollers=" in l)
if ticks < 2 and not any(l.strip() == MARKER for l in new):
    say(1, "waiting: %d report tick(s) since the override was written" % ticks)

board, why = None, "no board"
try:
    b = json.load(open(board_path()))
    age = time.time() - float(b["as_of"])
    if not -5.0 <= age <= 120.0:
        why = "the board is %.0fs old" % age
    elif float(b["as_of"]) < os.path.getmtime(OVERRIDE):
        why = "the board predates the override"
    else:
        board, why = b, "board %.0fs old" % age
except Exception as exc:                              # noqa: BLE001 -- a missing board is a fallback, not a crash
    why = "the board is unreadable (%s)" % type(exc).__name__

if board is not None:
    if board.get("arm_stale"):
        say(2, "the board says the arm is STALE: %s" % str(board["arm_stale"])[:160])
    if str(board.get("mode")) != "LIMITED_LIVE":
        say(2, "the board says the lane is in %s, not LIMITED_LIVE" % str(board.get("mode"))[:60])
    if board.get("f22_enabled") or str(board.get("f22_authority")) != AUTH:
        say(1, "waiting: the board still reports f22 authority %s" % str(board.get("f22_authority"))[:120])
    say(0, "the board reports arm_stale=null, f22 disabled on '%s', as_of=%s" % (AUTH, board.get("as_of")))

f22 = [l for l in lines if "[f22] ENABLED" in l or "[f22] disabled" in l]
if not f22:
    say(1, "waiting: no [f22] marker in the log yet (%s)" % why)
last = f22[-1].strip()
if last != MARKER:
    say(2, "the last [f22] marker is not the F24 authority, so the lane is not armed under the new "
           "override (%s): %s" % (why, last[:160]))
say(0, "the log's last marker is exactly '%s' and no arm marker is STALE (%s)" % (MARKER, why))
PYC
)
  RC=$?
  set -e
  case "$RC" in
    0) SEEN=yes; echo "F24_ARM_CONFIRMATION: $WHY"; break ;;
    2) fail "the lane is not armed under the new override: $WHY; kill left in place" ;;
  esac
done
[ "$SEEN" = yes ] || fail "the lane never proved F22 disabled with a live, non-stale arm within 225 s; kill left in place"

quiet_or_fail "an alarm appeared while waiting; kill left in place" "The kill was left in place."
[ "$(sha256sum "$KILL" | cut -d' ' -f1)" = "$EXPECTED_KILL_SHA" ] || fail "kill/live changed before archive; left in place"

AUDIT=$(sudo -u janus mktemp -d "$AUDIT_ROOT/.F24.XXXXXX") || fail "could not create the audit directory"
START=$(date +%s.%N)
sudo -u janus mv "$KILL" "$AUDIT/kill-live-f22-stop-$EXPECTED_KILL_SHA.json" || fail "archive failed; kill left in place"
# The pin is what makes report.py refuse a mistyped start. It is written LAST and can fail, so it
# decides which verdict line this prints: an unpinned arm is still a LIVE, TRADING lane, and the
# runbook's promise that a mistyped start cannot produce a fake verdict does not hold without it.
if printf '%s\n' "$START" | sudo -u janus tee "$START_PIN" > /dev/null \
   && [ "$(sudo -u janus cat "$START_PIN" 2>/dev/null)" = "$START" ]; then
  echo "start_utc=$START"
  echo "F24_ARMED: override without experiment written; F22 kill archived to $AUDIT; start pinned at $START_PIN"
else
  echo "start_utc=$START"
  echo "F24_ARMED_BUT_UNPINNED: the lane IS armed and trading -- the kill is archived to $AUDIT -- but"
  echo "  $START_PIN could NOT be written. report.py can then only WARN about a start_utc that"
  echo "  disagrees with it instead of refusing, so the runbook's 'a mistyped start cannot produce a"
  echo "  fake verdict' does NOT hold for this run. Write down start_utc=$START now, and either fix"
  echo "  the pin by hand or treat every check_f24.sh verdict as unverified."
fi
EOS

shopt -u patsub_replacement 2>/dev/null || true   # bash >= 5.2 would read '&' in a replacement
REMOTE=${TEMPLATE//@@B64@@/$B64}
REMOTE=${REMOTE//@@SIGNER@@/$SIGNED_BY}

if [ "$MODE" != "--send" ]; then
  echo "=== DRY RUN: nothing was sent. This is the exact payload --send would run on the box. ==="
  printf '%s\n' "$REMOTE"
  exit 0
fi

set +e
bash "$RUNNER" "$REMOTE"
SEND_RC=$?
set -e
echo
echo "=== the send returned $SEND_RC. That is NOT the answer. Reading the box's own state. ==="
set +e
VERIFY_OUT=$(bash "$HERE/verify_f24.sh" 2>&1)
VERIFY_RC=$?
set -e
printf '%s\n' "$VERIFY_OUT"
# Anchored whole-line match, like verify_f24.sh's own verdict: nothing the box echoes back mid-line
# can turn a missing pin into a pinned one.
PIN_LINE=$(printf '%s\n' "$VERIFY_OUT" | grep -E '^F24_START_PIN: ' | tail -1 || true)
case "$VERIFY_RC" in
  0) if [ "$PIN_LINE" = "F24_START_PIN: MISSING" ]; then
       echo "F24 IS ARMED BUT THE START PIN IS MISSING (verified on the box). The lane is LIVE and"
       echo "trading. Nothing on the box records when it started, so report.py cannot refuse a"
       echo "mistyped start_utc -- it can only warn. Record the start_utc printed by the send above"
       echo "(or the override's written_utc from the evidence) before running check_f24.sh, and treat"
       echo "its verdict as unverified until the pin exists."
     else
       echo "F24 IS ARMED (verified on the box). Record the start_utc above; check progress with check_f24.sh."
     fi
     echo "RUN 'bash verify_f24.sh' AGAIN IN ABOUT TWO MINUTES. This verdict rests on the box's state"
     echo "files plus the lane's own record of why it refused -- and that record cannot corroborate"
     echo "yet: every report tick up to the archive counts refusals from while the F22 kill was still"
     echo "in place, so verify_f24.sh discards them (refusals.ticks_before_this_are_pre_arm). Once a"
     echo "whole tick has elapsed under the new override, a stop that leaves no file -- a PNL_UNKNOWN"
     echo "breaker, BALANCE_UNCONFIRMED, a failed guard -- shows up as refusals.lane_could_act=false." ;;
  2) echo "F24 IS NOT ARMED (verified on the box): the F22 kill is in place and the F22 override is untouched." ;;
  *) echo "F24 STATE IS INDETERMINATE. Do not re-run this script. Read the evidence above, and stop the lane with 'bash ops/box/kill.sh live' if it may be trading." ;;
esac
exit "$VERIFY_RC"
