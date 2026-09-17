#!/usr/bin/env bash
# F24: arm the plain taker profitability test. OPERATOR-RUN. Prints the remote payload by default.
#
#   bash arm_f24.sh "<your verbatim statement>"          # dry run: shows exactly what would run
#   bash arm_f24.sh "<your verbatim statement>" --send   # does it, on the box, through ops/box/run.sh
#
# Requires a dated GATE_TO_LIVE amendment carrying the SAME verbatim statement first.
#
# In one remote pass it refuses unless the lane is active in LIMITED_LIVE, the kill is exactly the
# F22 STOP, and the account is quiet with no unresolved material flag. Then, in this order:
#   1. writes an override with NO experiment block, at the unchanged caps ($30 / 25 / $500, 168 h);
#   2. waits for the lane to report "[f22] disabled" and no "[arm] STALE" -- if it does not, it stops
#      and LEAVES THE KILL IN PLACE;
#   3. archives (never deletes) the exact F22 kill.
# The order matters: clearing the kill under the current F22 override would resume F22.
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
LOG=/srv/janus/logs/live_stream.stdout.log
fail() { echo "F24_ARM_ABORTED: $*"; exit 2; }

[ "$(systemctl is-active janus-live-stream)" = active ] || fail "lane is not active"
PID=$(systemctl show -p MainPID --value janus-live-stream)
tr '\0' ' ' < "/proc/$PID/cmdline" | grep -q -- '--mode LIMITED_LIVE' || fail "lane is not in LIMITED_LIVE"

[ -f "$KILL" ] || fail "no kill/live present; nothing to clear and no reason to arm"
[ "$(sha256sum "$KILL" | cut -d' ' -f1)" = "$EXPECTED_KILL_SHA" ] || fail "kill/live is not the exact F22 STOP"

sudo -u janus env JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box "$PY" - <<'PYQ' || fail "account is not quiet"
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

printf %s '@@B64@@' | base64 -d > /tmp/f24-statement.txt
chmod 644 /tmp/f24-statement.txt
sudo -u janus bash -c 'set -a; . /run/janus/janus.env; set +a; cd /opt/janus; JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box .venv/bin/python3 ops/arming_override.py --mode LIMITED_LIVE --signed-by "@@SIGNER@@" --stake-usd 30 --max-contracts 25 --day-notional-usd 500 --expires-hours 168 --force --statement "$(cat /tmp/f24-statement.txt)"'
RC=$?
rm -f /tmp/f24-statement.txt
[ "$RC" = 0 ] || fail "override write failed; the F22 override and the kill are unchanged"
sudo -u janus "$PY" -c 'import json,sys; d=json.load(open("/srv/janus/kill/arming_override.json")); sys.exit(1 if d.get("experiment") else 0)' \
  || fail "the new override still carries an experiment block; kill left in place"

MARK=$(wc -l < "$LOG")
SEEN=no
for _ in $(seq 1 30); do
  sleep 5
  NEW=$(tail -n +"$((MARK + 1))" "$LOG")
  if printf %s "$NEW" | grep -q '\[arm\] STALE'; then
    fail "the lane reports the new override STALE; kill left in place"
  fi
  if printf %s "$NEW" | grep -q '\[f22\] disabled'; then SEEN=yes; break; fi
done
[ "$SEEN" = yes ] || fail "the lane never reported F22 disabled within 150 s; kill left in place"

[ "$(sha256sum "$KILL" | cut -d' ' -f1)" = "$EXPECTED_KILL_SHA" ] || fail "kill/live changed before archive; left in place"
AUDIT=$(sudo -u janus mktemp -d "$AUDIT_ROOT/.F24.XXXXXX") || fail "could not create the audit directory"
sudo -u janus mv "$KILL" "$AUDIT/kill-live-f22-stop-$EXPECTED_KILL_SHA.json" || fail "archive failed; kill left in place"
echo "F24_ARMED: override without experiment written; F22 kill archived to $AUDIT"
echo "start_utc=$(date +%s.%N)"
EOS

shopt -u patsub_replacement 2>/dev/null || true   # bash >= 5.2 would read '&' in a replacement
REMOTE=${TEMPLATE//@@B64@@/$B64}
REMOTE=${REMOTE//@@SIGNER@@/$SIGNED_BY}

if [ "$MODE" != "--send" ]; then
  echo "=== DRY RUN: nothing was sent. This is the exact payload --send would run on the box. ==="
  printf '%s\n' "$REMOTE"
  exit 0
fi
bash "$RUNNER" "$REMOTE"
