#!/bin/zsh
# Generic Janus job wrapper: start row -> run -> finish row, with log rotation.
#
#   ops/run_node.sh <job> <python-module-or-script> [args...]
#
# THE START ROW IS WRITTEN BEFORE THE INTERPRETER IS INVOKED. That is the whole point: a crash at
# import, argparse or config time -- which is exactly what com.janus.convergence did every 30
# seconds for thirteen days -- still leaves a durable trace for ops/watchdog.py to alert on.
#
# The old collectors/run_*.sh wrappers `exec` into python, which replaces the shell and makes it
# structurally impossible to record an outcome. This one deliberately does NOT exec.
set -u                       # NOT -e: a job failure must reach the finish row, not abort the script
umask 077

ROOT=/Users/bernardodelrio/Code/Janus
JOB="$1"; shift
LOGDIR=/Volumes/Kilos/janus/logs
LOG="$LOGDIR/${JOB}.stderr.log"
MAXBYTES=33554432            # 32 MB. convergence reached 11.9 MB unrotated and nobody noticed.

cd "$ROOT"
export PYTHONPATH="$ROOT"
mkdir -p "$LOGDIR"

# Rotate on start. No sudo, no newsyslog, no logrotate -- one generation is enough to debug a
# crash and bounded enough that a loop cannot fill the volume.
if [ -f "$LOG" ] && [ "$(stat -f%z "$LOG")" -gt "$MAXBYTES" ]; then
  mv -f "$LOG" "$LOG.1"
fi

RUN_ID=$(/opt/homebrew/bin/python3 ops/run_index.py start "$JOB" "$@")
export JANUS_RUN_ID="$RUN_ID"

/opt/homebrew/bin/python3 "$@" >>"$LOGDIR/${JOB}.stdout.log" 2>>"$LOG"
CODE=$?

/opt/homebrew/bin/python3 ops/run_index.py finish "$JOB" "$RUN_ID" --exit "$CODE" >/dev/null
exit $CODE
