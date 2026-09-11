#!/usr/bin/env bash
# THE OPERATOR'S DAILY PASTE: a release under the arm, in one command. The agent prepares it and
# never runs it (GATE_TO_LIVE 2026-09-07 amendment: "Pin the code tree, one daily paste").
#
#   bash ops/box/release.sh <sha>          # refuses while a co-listed game is in play on the box
#   bash ops/box/release.sh <sha> --now    # skip that check (the operator's call)
#
# In order: provision the PM redemption key if absent; checkout without restart; sync the pinned
# redemption runtime and units; re-sign the override at JANUS_ARM_CAPS (default $12 / 10 / $250,
# 168 h); restart LIMITED_LIVE; clear only the exact maker false-latch captured at paste start after
# stopped-lane terminal-zero/global-idle proof; verify post-start streams; run redemption now.
# A different or changed kill is never cleared. A docs-only sha still gets the same full sequence.
#
# The statement is $JANUS_ARM_STATEMENT, else ops/box/arm_statement.txt (the standing one). Any
# change to the caps or the statement is a new dated GATE_TO_LIVE row first.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
SHA=${1:?the sha to release (git rev-parse main)}
REGION=${JANUS_BOX_REGION:-mx-central-1}
NOW=0; [ "${2:-}" = "--now" ] && NOW=1
STATEMENT=${JANUS_ARM_STATEMENT:-$(cat "$HERE/arm_statement.txt")}
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

echo "== (0) provision idempotent PM redemption authority"
python3 "$HERE/provision_redemption.py" --region "$REGION"

echo "== (a) checkout $SHA, no restart"
bash "$HERE/update.sh" "$SHA" --no-restart
echo "== (b) sync pinned redemption runtime and systemd units"
bash "$HERE/sync_runtime.sh"
echo "== (c) re-sign the override for the new tree"
CAPS=${JANUS_ARM_CAPS:-"12 10 250 168"}      # stake, contracts per leg, day notional, hours (GATE row 2026-09-07, the smallest executable size)
# shellcheck disable=SC2086
bash "$HERE/write_override.sh" "$STATEMENT" $CAPS
echo "== (d) restart under LIMITED_LIVE"
bash "$HERE/mode.sh" LIMITED_LIVE
if [ "$LIVE_KILL_SHA" != none ]; then
  echo "== (e) exact recovery of reviewed false maker latch"
  bash "$HERE/clear_false_maker_latch.sh" "$SHA" "$LIVE_KILL_SHA"
else
  echo "== (e) no live kill present at release start"
fi
echo "== (f) run automatic redemption now"
bash "$HERE/run.sh" "set -e; systemctl start janus-pm-redeem.service || { tail -n 30 /srv/janus/logs/pm_redeem.stderr.log >&2; journalctl -u janus-pm-redeem.service -n 12 --no-pager >&2; exit 1; }; systemctl is-active janus-pm-redeem.timer; tail -1 /srv/janus/logs/pm_redeem.stdout.log"
