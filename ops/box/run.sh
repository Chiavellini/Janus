#!/usr/bin/env bash
# Run a bash script on the box through SSM and print its output.
#   bash ops/box/run.sh 'echo hi; systemctl is-active janus-live-stream'
#   bash ops/box/run.sh < script.sh
# Root on the box; use `sudo -u janus` for anything that touches /opt/janus or /srv/janus as the
# lane does. SSM's document runs sh, so the script is written to a file and run with bash.
set -euo pipefail
ID=${JANUS_BOX_ID:-i-0c86891ee306de0b8}
REGION=us-east-1
if [ $# -ge 1 ]; then SCRIPT=$1; else SCRIPT=$(cat); fi
WRAPPED=$(printf "cat > /tmp/janus-run.sh <<'JANUS_EOF'\n%s\nJANUS_EOF\nbash /tmp/janus-run.sh; rc=\$?; rm -f /tmp/janus-run.sh; exit \$rc" "$SCRIPT")
PARAMS=$(python3 -c 'import json,sys; print(json.dumps({"commands": [sys.stdin.read()]}))' <<<"$WRAPPED")
CMD=$(aws ssm send-command --region $REGION --instance-ids "$ID" --document-name AWS-RunShellScript \
  --parameters "$PARAMS" --query Command.CommandId --output text)
for _ in $(seq 1 100); do
  st=$(aws ssm get-command-invocation --region $REGION --command-id "$CMD" --instance-id "$ID" --query Status --output text 2>/dev/null || echo Pending)
  case $st in Success|Failed|Cancelled|TimedOut) break;; esac; sleep 3
done
[ "$st" = Success ] || echo "status=$st"
aws ssm get-command-invocation --region $REGION --command-id "$CMD" --instance-id "$ID" --query 'StandardOutputContent' --output text
err=$(aws ssm get-command-invocation --region $REGION --command-id "$CMD" --instance-id "$ID" --query 'StandardErrorContent' --output text)
[ -z "$err" ] || { echo "--- stderr"; echo "$err" | tail -8; }
