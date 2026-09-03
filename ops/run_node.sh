#!/bin/zsh
# Generic Janus job wrapper: start row -> run -> finish row, with log rotation.
#
#   ops/run_node.sh <job> <python-module-or-script> [args...]
#
# THE START ROW IS WRITTEN BEFORE THE INTERPRETER IS INVOKED. That is the whole point: a crash at
# import, argparse or config time -- which is exactly what com.janus.convergence did every 30
# seconds for thirteen days -- still leaves a durable trace for ops/watchdog.py to alert on.
#
# The old collectors/run_*.sh wrappers `exec`'d into python, which replaces the shell and makes it
# structurally impossible to record an outcome. This one deliberately does NOT exec.
#
# Portable since 2026-09-03: JANUS_ROOT (the checkout), JANUS_PYTHON (the interpreter) and
# JANUS_DATA_ROOT (the data volume; logs live under it) default to the Mac's values, and the box
# sets them in its systemd unit. Both volumes are checked for free space before anything runs.
set -u                       # NOT -e: a job failure must reach the finish row, not abort the script
umask 077

ROOT="${JANUS_ROOT:-/Users/bernardodelrio/Code/Janus}"
PY="${JANUS_PYTHON:-/opt/homebrew/bin/python3}"
DATA="${JANUS_DATA_ROOT:-/Volumes/Kilos/janus}"
export JANUS_DATA_ROOT="$DATA"
JOB="$1"; shift
LOGDIR="${JANUS_LOGDIR:-$DATA/logs}"
LOG="$LOGDIR/${JOB}.stderr.log"
MAXBYTES=33554432            # 32 MB. convergence reached 11.9 MB unrotated and nobody noticed.
MINFREE_KB=2097152           # 2 GB on each of the root disk and the data volume, else abort loudly.

cd "$ROOT"
export PYTHONPATH="$ROOT"
mkdir -p "$LOGDIR"

# Credentials are sourced here, never written into a plist, a command line or a log. Kalshi
# authenticates every socket -- even for public market data -- so a lane that needs them cannot
# start without them, and failing loudly here beats a confusing auth error 30 frames in.
if [ -n "${JANUS_CREDS:-}" ] && [ -f "$JANUS_CREDS" ]; then
  set -a; . "$JANUS_CREDS"; set +a
fi

# The df guard the Ashburn runbook always prescribed and nothing enforced: a full disk is a
# silent data loss on a lane whose whole output is what it writes.
for vol in / "$DATA"; do
  free_kb=$(df -Pk "$vol" 2>/dev/null | awk 'NR==2 {print $4}')
  if [ -n "$free_kb" ] && [ "$free_kb" -lt "$MINFREE_KB" ]; then
    echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $JOB: ABORT -- $vol has ${free_kb} KB free, below 2 GB" >> "$LOG"
    exit 75
  fi
done

# Rotate on start. No sudo, no newsyslog, no logrotate -- one generation is enough to debug a
# crash and bounded enough that a loop cannot fill the volume.
if [ -f "$LOG" ]; then
  size=$(stat -f%z "$LOG" 2>/dev/null || stat -c%s "$LOG" 2>/dev/null || echo 0)
  if [ "$size" -gt "$MAXBYTES" ]; then mv -f "$LOG" "$LOG.1"; fi
fi

RUN_ID=$("$PY" ops/run_index.py start --pid $$ "$JOB" "$@")   # $$ = this wrapper, alive for the whole job; the option precedes the job because the rest is REMAINDER
if [ -z "$RUN_ID" ]; then
  echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $JOB: ABORT -- no run row was written (ops/run_index.py start failed); a job the watchdog cannot see does not run" >> "$LOG"
  exit 70
fi
export JANUS_RUN_ID="$RUN_ID"

"$PY" "$@" >>"$LOGDIR/${JOB}.stdout.log" 2>>"$LOG"
CODE=$?

"$PY" ops/run_index.py finish "$JOB" "$RUN_ID" --exit "$CODE" >/dev/null
exit $CODE
