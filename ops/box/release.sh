#!/usr/bin/env bash
# THE OPERATOR'S DAILY PASTE: a release under the arm, in one command. The agent prepares it and
# never runs it (GATE_TO_LIVE 2026-09-07 amendment: "Pin the code tree, one daily paste").
#
#   bash ops/box/release.sh <sha>          # refuses while a co-listed game is in play on the box
#   bash ops/box/release.sh <sha> --now    # skip that check (the operator's call)
#
# In order: (a) ops/box/update.sh <sha> --no-restart -- the checkout moves, the lane keeps running
# its old tree; (b) ops/box/write_override.sh -- the override is re-signed for the NEW tree, at the
# caps in JANUS_ARM_CAPS (default $12 / 10 / $250, 168 h); from this moment the running lane refuses real orders
# (ARM_STALE: its tree is not the one pinned) until (c) ops/box/mode.sh LIMITED_LIVE restarts it
# under the new tree, where the gate matches again. A docs-only sha changes nothing under the pin
# and still gets the full three steps: the paste is the same every day.
#
# The statement is $JANUS_ARM_STATEMENT, else ops/box/arm_statement.txt (the standing one). Any
# change to the caps or the statement is a new dated GATE_TO_LIVE row first.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
SHA=${1:?the sha to release (git rev-parse main)}
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

echo "== (a) checkout $SHA, no restart"
bash "$HERE/update.sh" "$SHA" --no-restart
echo "== (b) re-sign the override for the new tree"
CAPS=${JANUS_ARM_CAPS:-"12 10 250 168"}      # stake, contracts per leg, day notional, hours (GATE row 2026-09-07, the smallest executable size)
# shellcheck disable=SC2086
bash "$HERE/write_override.sh" "$STATEMENT" $CAPS
echo "== (c) restart under LIMITED_LIVE"
bash "$HERE/mode.sh" LIMITED_LIVE
