#!/usr/bin/env bash
# F24: arm the plain taker profitability test. Prints the remote payload by default.
#
#   bash arm_f24.sh "<verbatim operator statement>"          # dry run: shows exactly what would run
#   bash arm_f24.sh "<verbatim operator statement>" --send   # does it, on the box, through ops/box/run.sh
#
# Requires a dated GATE_TO_LIVE amendment carrying the SAME verbatim statement first.
#
# In one remote pass it refuses unless it holds the arming lock, no F24 start pin already exists, the
# lane is active in LIMITED_LIVE, the kill is exactly the F22 STOP, and the account is quiet with no
# unresolved material flag. Then, in this order:
#   1. copies the current F22 override into the audit directory (the deployed writer truncates in
#      place, so the copy is the only way back from a half-written file);
#   2. writes an override with NO experiment block, at the unchanged caps ($30 / 25 / $500, 168 h);
#   3. waits for the lane to re-read it and report F22 disabled, with no "[arm] STALE" -- if it does
#      not, it stops and LEAVES THE KILL IN PLACE;
#   4. repeats the quiet check, because the wait is long enough for a new alarm to appear;
#   5. archives (never deletes) the exact F22 kill, then pins the start time on the box.
# The order matters: clearing the kill under the current F22 override would resume F22.
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
KILL=/srv/janus/kill/live
OVERRIDE=/srv/janus/kill/arming_override.json
EXPECTED_KILL_SHA=d81bbfc267a235ca7f268e7317d77ee7e83c65f5263117590e4e86d1552b1636
AUDIT_ROOT=/srv/janus/release-audit
START_PIN=/srv/janus/release-audit/f24_start_utc
LOCK=/srv/janus/release-audit/.f24-arm.lock
LOG=/srv/janus/logs/live_stream.stdout.log
QUIET=
HELD=no
cleanup() {
  [ -n "$QUIET" ] && sudo -u janus rm -f "$QUIET"
  [ "$HELD" = yes ] && sudo -u janus rmdir "$LOCK" 2>/dev/null
  return 0
}
trap cleanup EXIT
fail() { echo "F24_ARM_ABORTED: $*"; exit 2; }

sudo -u janus mkdir -p "$AUDIT_ROOT" || fail "cannot create the audit directory"
sudo -u janus mkdir "$LOCK" 2>/dev/null || fail "another arming run holds $LOCK -- do not retry blindly; run verify_f24.sh"
HELD=yes
[ -e "$START_PIN" ] && fail "a start pin already exists ($START_PIN) -- F24 looks armed already; run verify_f24.sh"

[ "$(systemctl is-active janus-live-stream)" = active ] || fail "lane is not active"
PID=$(systemctl show -p MainPID --value janus-live-stream)
tr '\0' ' ' < "/proc/$PID/cmdline" | grep -q -- '--mode LIMITED_LIVE' || fail "lane is not in LIMITED_LIVE"

[ -f "$KILL" ] || fail "no kill/live present; nothing to clear and no reason to arm"
[ "$(sha256sum "$KILL" | cut -d' ' -f1)" = "$EXPECTED_KILL_SHA" ] || fail "kill/live is not the exact F22 STOP"
[ -f "$OVERRIDE" ] || fail "no arming override present; refusing to write one blind"

QUIET=$(sudo -u janus mktemp /tmp/f24-quiet.XXXXXX.py) || fail "cannot write the quiet check"
sudo -u janus tee "$QUIET" > /dev/null <<'PYQ'
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
PYQ
sudo -u janus env JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box "$PY" "$QUIET" || fail "account is not quiet"

BACKUP="$AUDIT_ROOT/f22-override-before-F24-$(date +%s).json"
sudo -u janus cp -p "$OVERRIDE" "$BACKUP" || fail "could not copy the current override aside"
echo "F24_OVERRIDE_BACKUP: $BACKUP"

printf %s '@@B64@@' | base64 -d > /tmp/f24-statement.txt
chmod 644 /tmp/f24-statement.txt
sudo -u janus bash -c 'set -a; . /run/janus/janus.env; set +a; cd /opt/janus; JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box .venv/bin/python3 ops/arming_override.py --mode LIMITED_LIVE --signed-by "@@SIGNER@@" --stake-usd 30 --max-contracts 25 --day-notional-usd 500 --expires-hours 168 --force --statement "$(cat /tmp/f24-statement.txt)"'
RC=$?
rm -f /tmp/f24-statement.txt
[ "$RC" = 0 ] || fail "override write failed; the kill is in place and $BACKUP holds the F22 override"
sudo -u janus "$PY" -c 'import json,sys; d=json.load(open("/srv/janus/kill/arming_override.json")); sys.exit(1 if d.get("experiment") else 0)' \
  || fail "the new override still carries an experiment block; kill left in place"

# The lane says "[f22] disabled" only when the authority CHANGES (grid.check_arm), so a re-run after
# a half-finished attempt would wait forever on a line that will never print again. Two report ticks
# prove the override was re-read; the last marker in the log then says what it was re-read as.
MARK=$(wc -l < "$LOG")
SEEN=no
for _ in $(seq 1 45); do
  sleep 5
  NEW=$(tail -n +"$((MARK + 1))" "$LOG")
  if printf %s "$NEW" | grep -q '\[arm\] STALE'; then
    fail "the lane reports the new override STALE; kill left in place"
  fi
  if printf %s "$NEW" | grep -q '\[f22\] disabled'; then SEEN=yes; break; fi
  TICKS=$(printf %s "$NEW" | grep -c '\] pollers=')
  LAST=$(grep -a '\[f22\] \(ENABLED\|disabled\)' "$LOG" | tail -1)
  case "$TICKS:$LAST" in
    [2-9]*:*"[f22] disabled"*|[1-9][0-9]*:*"[f22] disabled"*) SEEN=yes; break ;;
  esac
done
[ "$SEEN" = yes ] || fail "the lane never reported F22 disabled within 225 s; kill left in place"

sudo -u janus env JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box "$PY" "$QUIET" || fail "an alarm appeared while waiting; kill left in place"
[ "$(sha256sum "$KILL" | cut -d' ' -f1)" = "$EXPECTED_KILL_SHA" ] || fail "kill/live changed before archive; left in place"

AUDIT=$(sudo -u janus mktemp -d "$AUDIT_ROOT/.F24.XXXXXX") || fail "could not create the audit directory"
START=$(date +%s.%N)
sudo -u janus mv "$KILL" "$AUDIT/kill-live-f22-stop-$EXPECTED_KILL_SHA.json" || fail "archive failed; kill left in place"
printf '%s\n' "$START" | sudo -u janus tee "$START_PIN" > /dev/null \
  || echo "F24_WARNING: the start pin could not be written; record start_utc=$START yourself"
echo "F24_ARMED: override without experiment written; F22 kill archived to $AUDIT"
echo "start_utc=$START"
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
bash "$HERE/verify_f24.sh"
VERIFY_RC=$?
set -e
case "$VERIFY_RC" in
  0) echo "F24 IS ARMED (verified on the box). Record the start_utc above; check progress with check_f24.sh." ;;
  2) echo "F24 IS NOT ARMED (verified on the box): the F22 kill is in place and the F22 override is untouched." ;;
  *) echo "F24 STATE IS INDETERMINATE. Do not re-run this script. Read the evidence above, and stop the lane with 'bash ops/box/kill.sh live' if it may be trading." ;;
esac
exit "$VERIFY_RC"
