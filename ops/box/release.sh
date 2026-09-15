#!/usr/bin/env bash
# One-command release under an exact dated GATE authority. The 2026-09-07 default was an operator
# paste; later experiment-specific amendments may explicitly authorize the agent to run it.
#
#   bash ops/box/release.sh <sha>          # refuses while a co-listed game is in play on the box
#   bash ops/box/release.sh <sha> --now    # skip that check (the operator's call)
#
# In order: provision the PM redemption key if absent; checkout without restart; sync the pinned
# redemption runtime and units; re-sign the override at JANUS_ARM_CAPS (default $30 / 25 / $500,
# 168 h); restart LIMITED_LIVE; clear only the exact reviewed latch captured at paste start after
# stopped-lane proof; verify post-start streams; run redemption now. L122's exact flag-211 latch and
# L133's exact guard-failure incident set are routed to separate helpers; the false-maker path is selected
# only by its reviewed reason signature. A malformed or unknown reason is a hard failure.
# A different or changed kill is never cleared. A docs-only sha still gets the same full sequence.
#
# The statement is $JANUS_ARM_STATEMENT, else ops/box/arm_statement.txt (the standing one). Any
# change to the caps or the statement is a new dated GATE_TO_LIVE row first.
set -euo pipefail
single_nonempty_line() {
  awk 'NF { n += 1; line = $0 } END { if (n == 1) print line; else exit 1 }'
}
HERE=$(cd "$(dirname "$0")" && pwd)
SHA=${1:?the sha to release (git rev-parse main)}
REGION=${JANUS_BOX_REGION:-mx-central-1}
NOW=0; [ "${2:-}" = "--now" ] && NOW=1
EXPERIMENT=${JANUS_EXPERIMENT:-F23}
case "$EXPERIMENT" in
  F22) DEFAULT_STATEMENT_FILE="$HERE/arm_statement.txt" ;;
  F23) DEFAULT_STATEMENT_FILE="$HERE/f23_arm_statement.txt" ;;
  *) echo "unsupported JANUS_EXPERIMENT: $EXPERIMENT" >&2; exit 2 ;;
esac
STATEMENT=${JANUS_ARM_STATEMENT:-$(cat "$DEFAULT_STATEMENT_FILE")}
if [ -z "${STATEMENT// }" ]; then echo "empty statement"; exit 2; fi

if [ $NOW = 0 ]; then
  # Refuse only on MONEY in motion: an execution in flight (a pre-hedge state touched in the last
  # two minutes) or an unhedged position the lane still holds. Games in play are a warning: a
  # restart drops their pollers' state, not money (2026-09-07: with ITF enabled the slate is
  # rarely empty, and "no game in play" would have meant "never"). --now skips both.
  read -r -d '' PROBE <<'EOS' || true
sudo -u janus /opt/janus/.venv/bin/python3 - <<'PY'
import sqlite3, sys, time
sys.path.insert(0, "/opt/janus")
from nodes.risk.limits import load_limits
c = sqlite3.connect('file:/srv/janus/tuples/tuples.sqlite?mode=ro', uri=True)
now = time.time()
games = c.execute("SELECT COUNT(*) FROM events WHERE phase='in:co_listed' AND last_seen_ts > ?", (now - 900,)).fetchone()[0]
try:
    flight = c.execute("SELECT COUNT(*) FROM executions WHERE last_utc > ? AND state IN ('DETECTED','VALIDATED','CAPITAL_RESERVED',"
                       "'LEG_A_SUBMITTED','LEG_A_FILLED','LEG_A_PARTIAL','LEG_B_SUBMITTED','LEG_B_PARTIAL')", (now - 120,)).fetchone()[0]
    dust = load_limits().protect.protect_dust_contracts
    unhedged = c.execute("SELECT COUNT(*) FROM executions WHERE ABS(unhedged) > ? AND released = 0", (dust,)).fetchone()[0]
except sqlite3.OperationalError:
    flight, unhedged = 0, 0
print(f"games={games} flight={flight} unhedged={unhedged}")
PY
EOS
  LINE=$(bash "$HERE/run.sh" "$PROBE" | grep -a "^games=" | tail -1)
  case $LINE in
    games=*) ;;
    *) echo "could not read the box's state (got: ${LINE:-nothing}); not releasing"; exit 2;;
  esac
  GAMES=${LINE#games=}; GAMES=${GAMES%% *}
  FLIGHT=${LINE#*flight=}; FLIGHT=${FLIGHT%% *}
  UNHEDGED=${LINE#*unhedged=}
  if [ "$FLIGHT" -gt 0 ] || [ "$UNHEDGED" -gt 0 ]; then
    echo "refused: $FLIGHT execution(s) in flight, $UNHEDGED unhedged position(s) on the box. Wait for them to settle, or pass --now knowingly."
    exit 3
  fi
  [ "$GAMES" -gt 0 ] && echo "note: $GAMES co-listed game(s) in play; nothing in flight, so the restart costs their pollers' state only"
  echo "money quiet (flight=0, unhedged=0); releasing $SHA"
fi

# Snapshot the exact current local live latch before moving the tree.  The release may clear it
# only if the new tree proves it is the reviewed false maker-terminality incident; any changed or
# human/other-risk latch remains a hard stop.
LIVE_KILL_SHA=$(bash "$HERE/run.sh" "if [ -f /srv/janus/kill/live ]; then sha256sum /srv/janus/kill/live | awk '{print \$1}'; else echo none; fi" | grep -E '^(none|[0-9a-f]{64})$' | tail -1)
[ -n "$LIVE_KILL_SHA" ] || { echo "could not snapshot live kill"; exit 2; }
if [ "$LIVE_KILL_SHA" != none ]; then
  LIVE_KILL_REASON=$(bash "$HERE/run.sh" "if [ -f /srv/janus/kill/live ]; then /usr/bin/python3 -c 'import json; print(json.load(open(\"/srv/janus/kill/live\")).get(\"reason\", \"__MALFORMED__\"))'; else echo none; fi" | single_nonempty_line || true)
  [ -n "$LIVE_KILL_REASON" ] || { echo "could not snapshot live kill reason" >&2; exit 2; }
else
  LIVE_KILL_REASON=none
fi
KILL_ROUTE=none
if [ "$LIVE_KILL_SHA" != none ]; then
  case "$LIVE_KILL_REASON" in
    'guard failed: RuntimeError: RuntimeError: incomplete guard snapshot: balance:polymarket: venue did not return a balance; fills:polymarket: PROJECTION_BATCH_INCOMPLETE: trade read: PolyApiExcepti')
      [ "$LIVE_KILL_SHA" = dcc4c761ee8fb5f903475e0400b54a0ef57db8246cd7d378d4846cf181c96d83 ] || { echo "guard-failure reason has an unreviewed digest; refusing clear" >&2; exit 2; }
      KILL_ROUTE=guard ;;
    'LEGACY_INCIDENT_ACK_INVALID flag=211: ValueError: acknowledged incident state changed')
      [ "$LIVE_KILL_SHA" = a9613b6dff2499e3da6fe4aa2b872fa02f955aaefb043e60725f289603c249f6 ] || { echo "flag-211 reason has an unreviewed digest; refusing clear" >&2; exit 2; }
      KILL_ROUTE=legacy ;;
    'unknown provider state:'*'post-only cancel/late-fill lifecycle unresolved:'*) KILL_ROUTE=false_maker ;;
    'F22 STOP: terminal maker zero-fill fee evidence is NULL; strict report classifies persistence_or_reconciliation_failure')
      [ "$LIVE_KILL_SHA" = d81bbfc267a235ca7f268e7317d77ee7e83c65f5263117590e4e86d1552b1636 ] || { echo "F22 instrumentation reason has an unreviewed digest; refusing clear" >&2; exit 2; }
      KILL_ROUTE=f22_instrumentation ;;
    *) echo "unknown or malformed live-kill reason; refusing generic clear" >&2; exit 2 ;;
  esac
fi

echo "== (0) provision idempotent PM redemption authority"
python3 "$HERE/provision_redemption.py" --region "$REGION"

echo "== (a) checkout $SHA, no restart"
bash "$HERE/update.sh" "$SHA" --no-restart
echo "== (b) sync pinned redemption runtime and systemd units"
bash "$HERE/sync_runtime.sh"
echo "== (b2) the fast JSON decoder for the lane venv (L81; idempotent; the lane falls back to the stdlib without it)"
bash "$HERE/run.sh" 'sudo -u janus /opt/janus/.venv/bin/pip install -q orjson 2>&1 | tail -1; /opt/janus/.venv/bin/python3 -c "import orjson; print(\"orjson\", orjson.__version__)"'
echo "== (c) re-sign the override for the new tree"
CAPS=${JANUS_ARM_CAPS:-"30 25 500 168"}      # stake, contracts per leg, day notional, hours (GATE row 2026-09-11, F21: one rung up from the smallest size)
# shellcheck disable=SC2086
JANUS_EXPERIMENT="$EXPERIMENT" bash "$HERE/write_override.sh" "$STATEMENT" $CAPS
if [ "$KILL_ROUTE" = guard ] || [ "$KILL_ROUTE" = f22_instrumentation ]; then
  # L133 owns the complete stopped-lane preproof, retained-kill warmup, second guard and final
  # restart. Starting here first could mint a third GUARD_FAILED row and invalidate exact recovery.
  echo "== (d) keep lane stopped; L133 recovery owns the guarded restart"
else
  echo "== (d) restart under LIMITED_LIVE"
  bash "$HERE/mode.sh" LIMITED_LIVE
fi
if [ "$LIVE_KILL_SHA" != none ]; then
  case "$LIVE_KILL_SHA" in
    dcc4c761ee8fb5f903475e0400b54a0ef57db8246cd7d378d4846cf181c96d83)
      [ "$KILL_ROUTE" = guard ] || { echo "guard-failure digest has an unexpected reason; refusing clear" >&2; exit 2; }
      echo "== (e) exact recovery of registered guard-failure flags 1169 and 1170"
      GUARD_DEPLOYED_SHA=$(bash "$HERE/run.sh" "sudo -u janus git -C /opt/janus rev-parse --verify HEAD" | grep -E '^[0-9a-f]{40}$' | tail -1 || true)
      [[ "$GUARD_DEPLOYED_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "could not resolve the box's full deployed Git SHA; guard clear remains blocked" >&2; exit 2; }
      bash "$HERE/clear_guard_failure_latch.sh" "$GUARD_DEPLOYED_SHA" "$LIVE_KILL_SHA"
      ;;
    a9613b6dff2499e3da6fe4aa2b872fa02f955aaefb043e60725f289603c249f6)
      [ "$KILL_ROUTE" = legacy ] || { echo "flag-211 digest has an unexpected reason; refusing clear" >&2; exit 2; }
      echo "== (e) exact recovery of reviewed flag-211 legacy incident latch"
      DEPLOYED_SHA=$(bash "$HERE/run.sh" "sudo -u janus git -C /opt/janus rev-parse --verify HEAD" | grep -E '^[0-9a-f]{40}$' | tail -1 || true)
      case "$DEPLOYED_SHA" in
        [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
        *) echo "could not resolve the box's full deployed Git SHA; legacy clear remains blocked" >&2; exit 2 ;;
      esac
      bash "$HERE/clear_legacy_incident_latch.sh" "$DEPLOYED_SHA" "$LIVE_KILL_SHA"
      ;;
    d81bbfc267a235ca7f268e7317d77ee7e83c65f5263117590e4e86d1552b1636)
      [ "$KILL_ROUTE" = f22_instrumentation ] || { echo "F22 instrumentation digest has an unexpected reason; refusing clear" >&2; exit 2; }
      echo "== (e) exact recovery of F22 terminal-zero-fill instrumentation STOP"
      DEPLOYED_SHA=$(bash "$HERE/run.sh" "sudo -u janus git -C /opt/janus rev-parse --verify HEAD" | grep -E '^[0-9a-f]{40}$' | tail -1 || true)
      [[ "$DEPLOYED_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "could not resolve the box's full deployed Git SHA; F22 clear remains blocked" >&2; exit 2; }
      bash "$HERE/clear_f22_instrumentation_latch.sh" "$DEPLOYED_SHA" "$LIVE_KILL_SHA"
      ;;
    *)
      [ "$KILL_ROUTE" = false_maker ] || { echo "unknown live-kill digest; refusing generic clear" >&2; exit 2; }
      echo "== (e) exact recovery of reviewed false maker latch"
      bash "$HERE/clear_false_maker_latch.sh" "$SHA" "$LIVE_KILL_SHA"
      ;;
  esac
else
  echo "== (e) no live kill present at release start"
fi
echo "== (f) run automatic redemption now"
bash "$HERE/run.sh" "set -e; systemctl start janus-pm-redeem.service || { tail -n 30 /srv/janus/logs/pm_redeem.stderr.log >&2; journalctl -u janus-pm-redeem.service -n 12 --no-pager >&2; exit 1; }; systemctl is-active janus-pm-redeem.timer; tail -1 /srv/janus/logs/pm_redeem.stdout.log"
