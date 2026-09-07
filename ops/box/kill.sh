#!/usr/bin/env bash
# The cross-host kill, from the Mac. Sets (or clears) an SSM parameter the box's watchdog job
# mirrors into its local kill files within five minutes (ops/box/kill_sync.py):
#   bash ops/box/kill.sh all            # every mode that sends or simulates an order
#   bash ops/box/kill.sh live           # LIMITED_LIVE and PRODUCTION only
#   bash ops/box/kill.sh live --clear   # lift it; a file the breaker or a human latched on the box stays
# For an immediate stop use `bash ops/box/run.sh 'systemctl stop janus-live-stream'` as well: the
# parameter is the durable switch, the stop is the fast one. Nothing here reads a secret.
set -euo pipefail
NAME=${1:?all or live}
case $NAME in all|live) ;; *) echo "unknown switch $NAME (all|live)"; exit 2;; esac
REGION=${JANUS_BOX_REGION:-us-east-1}      # the Mexico box: export JANUS_BOX_REGION=mx-central-1 JANUS_BOX_ID=i-…
PARAM=/janus/kill/$NAME
if [ "${2:-}" = "--clear" ]; then
  if aws ssm delete-parameter --region $REGION --name "$PARAM" 2>/dev/null; then
    echo "cleared $PARAM; the box releases its ssm-latched kill/$NAME within 5 min (a breaker's or a human's file stays)"
  else
    echo "$PARAM was not set"
  fi
else
  STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ) $(whoami)@$(hostname -s)"
  aws ssm put-parameter --region $REGION --overwrite --name "$PARAM" --type String --value "$STAMP" >/dev/null
  echo "set $PARAM = $STAMP; the box latches kill/$NAME within 5 min (janus-watchdog.timer); ops/box/status.sh shows KILL_FILE_PRESENT"
fi
