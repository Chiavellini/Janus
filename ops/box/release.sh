#!/usr/bin/env bash
# THE OPERATOR'S DAILY PASTE: a release under the arm, in one command. The agent prepares it and
# never runs it (GATE_TO_LIVE 2026-09-07 amendment: "Pin the code tree, one daily paste").
#
#   bash ops/box/release.sh <sha>          # refuses while a co-listed game is in play on the box
#   bash ops/box/release.sh <sha> --now    # skip that check (the operator's call)
#
# In order: (a) ops/box/update.sh <sha> --no-restart -- the checkout moves, the lane keeps running
# its old tree; (b) ops/box/write_override.sh -- the override is re-signed for the NEW tree, at the
# F8 caps ($12 / 25 / $60, 168 h); from this moment the running lane refuses real orders
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
  # Co-listed games in play, seen by the lane in the last 15 min. A restart mid-game loses the
  # pollers' state (update.sh's own rule); the operator passes --now to override.
  read -r -d '' PROBE <<'EOS' || true
sudo -u janus /opt/janus/.venv/bin/python3 -c "import sqlite3, time; c = sqlite3.connect('file:/srv/janus/tuples/tuples.sqlite?mode=ro', uri=True); print(c.execute(\"SELECT COUNT(*) FROM events WHERE phase='in:co_listed' AND last_seen_ts > ?\", (time.time() - 900,)).fetchone()[0])"
EOS
  IN_PLAY=$(bash "$HERE/run.sh" "$PROBE" | tail -1 | tr -d '[:space:]')
  case $IN_PLAY in
    ''|*[!0-9]*) echo "could not read the box's slate (got: ${IN_PLAY:-nothing}); not releasing"; exit 2;;
  esac
  if [ "$IN_PLAY" -gt 0 ]; then
    echo "refused: $IN_PLAY co-listed game(s) in play on the box; a restart now drops their pollers. Wait, or pass --now."
    exit 3
  fi
  echo "slate quiet (0 co-listed games in play); releasing $SHA"
fi

echo "== (a) checkout $SHA, no restart"
bash "$HERE/update.sh" "$SHA" --no-restart
echo "== (b) re-sign the override for the new tree"
bash "$HERE/write_override.sh" "$STATEMENT" 12 25 60 168
echo "== (c) restart under LIMITED_LIVE"
bash "$HERE/mode.sh" LIMITED_LIVE
