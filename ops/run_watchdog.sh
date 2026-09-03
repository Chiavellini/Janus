#!/bin/zsh
# Dead-man's switch runner. Invoked by com.janus.watchdog every 5 minutes (a systemd timer on the box).
#
# Writes one line per check to watchdog.log ALWAYS (so the watchdog's own silence is detectable --
# a monitor whose absence is invisible is not a monitor), and raises a desktop notification only
# when something is actually wrong and a desktop exists.
set -u
umask 077
ROOT="${JANUS_ROOT:-/Users/bernardodelrio/Code/Janus}"
PY="${JANUS_PYTHON:-/opt/homebrew/bin/python3}"
DATA="${JANUS_DATA_ROOT:-/Volumes/Kilos/janus}"
export JANUS_DATA_ROOT="$DATA"
LOGDIR="${JANUS_LOGDIR:-$DATA/logs}"
LOG="$LOGDIR/watchdog.log"
cd "$ROOT"
export PYTHONPATH="$ROOT"
mkdir -p "$LOGDIR"

# bounded: one line per 5 min is ~105 KB/year, but rotate anyway so no log in this system is
# unbounded ever again.
if [ -f "$LOG" ]; then
  size=$(stat -f%z "$LOG" 2>/dev/null || stat -c%s "$LOG" 2>/dev/null || echo 0)
  if [ "$size" -gt 8388608 ]; then mv -f "$LOG" "$LOG.1"; fi
fi

OUT=$("$PY" ops/watchdog.py 2>&1)
CODE=$?
print -r -- "$(date -u '+%Y-%m-%dT%H:%M:%SZ') exit=$CODE" >> "$LOG"
print -r -- "$OUT" | sed 's/^/  /' >> "$LOG"

if [ $CODE -ne 0 ] && [ -x /usr/bin/osascript ]; then
  N=$(print -r -- "$OUT" | grep -c '^ALERT')
  FIRST=$(print -r -- "$OUT" | grep '^ALERT' | head -1 | cut -c1-180)
  /usr/bin/osascript -e "display notification \"${FIRST//\"/}\" with title \"Janus: $N job alert(s)\"" 2>/dev/null || true
fi
exit 0    # never let the watchdog's own exit code make launchd restart-loop it
