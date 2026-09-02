#!/bin/zsh
# Dead-man's switch runner. Invoked by com.janus.watchdog every 5 minutes.
#
# Writes one line per check to watchdog.log ALWAYS (so the watchdog's own silence is detectable --
# a monitor whose absence is invisible is not a monitor), and raises a desktop notification only
# when something is actually wrong.
set -u
umask 077
ROOT=/Users/bernardodelrio/Code/Janus
LOGDIR=/Volumes/Kilos/janus/logs
LOG="$LOGDIR/watchdog.log"
cd "$ROOT"
export PYTHONPATH="$ROOT"
mkdir -p "$LOGDIR"

# bounded: one line per 5 min is ~105 KB/year, but rotate anyway so no log in this system is
# unbounded ever again.
if [ -f "$LOG" ] && [ "$(stat -f%z "$LOG")" -gt 8388608 ]; then mv -f "$LOG" "$LOG.1"; fi

OUT=$(/opt/homebrew/bin/python3 ops/watchdog.py 2>&1)
CODE=$?
print -r -- "$(date -u '+%Y-%m-%dT%H:%M:%SZ') exit=$CODE" >> "$LOG"
print -r -- "$OUT" | sed 's/^/  /' >> "$LOG"

if [ $CODE -ne 0 ]; then
  N=$(print -r -- "$OUT" | grep -c '^ALERT')
  FIRST=$(print -r -- "$OUT" | grep '^ALERT' | head -1 | cut -c1-180)
  /usr/bin/osascript -e "display notification \"${FIRST//\"/}\" with title \"Janus: $N job alert(s)\"" 2>/dev/null || true
fi
exit 0    # never let the watchdog's own exit code make launchd restart-loop it
