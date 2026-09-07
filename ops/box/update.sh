#!/usr/bin/env bash
# Move the box's checkout to a sha (default: the local main) and restart the lane.
#   bash ops/box/update.sh [sha] [--no-restart]
# Re-points /janus/repo/sha (what a relaunch checks out), fetches on the box through the same
# token URL cloud-init used (the token never leaves SSM or the box), checks the sha out and
# restarts janus-live-stream unless told not to. Restart only when no game is in play: a poller's
# state does not survive it. The arming override, if any, pins the runner sha and stops matching.
set -euo pipefail
ID=${JANUS_BOX_ID:-i-0c86891ee306de0b8}
REGION=us-east-1
SHA=${1:-$(git rev-parse main)}
RESTART=1; [ "${2:-}" = "--no-restart" ] && RESTART=0
aws ssm put-parameter --region $REGION --overwrite --name /janus/repo/sha --type String --value "$SHA" >/dev/null
read -r -d '' SCRIPT <<EOSS || true
set -e
P() { aws ssm get-parameter --region $REGION --name "\$1" --with-decryption --query Parameter.Value --output text; }
URL=\$(P /janus/repo/url); TOKEN=\$(P /janus/repo/token)
CLONE="\${URL/https:\/\//https://x-access-token:\${TOKEN}@}"
# git as the checkout's owner: SSM runs as root, and git refuses a repository owned by another user
sudo -u janus git -C /opt/janus fetch -q "\$CLONE" "+refs/heads/*:refs/remotes/origin/*"
sudo -u janus git -C /opt/janus checkout -q $SHA
echo "checkout: \$(sudo -u janus git -C /opt/janus rev-parse --short HEAD) \$(sudo -u janus git -C /opt/janus log -1 --format=%s | cut -c1-80)"
if [ $RESTART = 1 ]; then systemctl restart janus-live-stream; sleep 8; echo "lane=\$(systemctl is-active janus-live-stream)"; tail -3 /srv/janus/logs/live_stream.stdout.log | cut -c1-140; fi
EOSS
# SSM runs the command under sh; the script needs bash (the token-URL substitution), so it is
# written to a file on the box and run with bash from there.
WRAPPED=$(printf "cat > /tmp/janus-update.sh <<'JANUS_EOF'\n%s\nJANUS_EOF\nbash /tmp/janus-update.sh; rc=\$?; rm -f /tmp/janus-update.sh; exit \$rc" "$SCRIPT")
PARAMS=$(python3 -c 'import json,sys; print(json.dumps({"commands": [sys.stdin.read()]}))' <<<"$WRAPPED")
CMD=$(aws ssm send-command --region $REGION --instance-ids "$ID" --document-name AWS-RunShellScript \
  --parameters "$PARAMS" --query Command.CommandId --output text)
for _ in $(seq 1 40); do
  st=$(aws ssm get-command-invocation --region $REGION --command-id "$CMD" --instance-id "$ID" --query Status --output text 2>/dev/null || echo Pending)
  case $st in Success|Failed|Cancelled|TimedOut) break;; esac; sleep 3
done
echo "status=$st"
aws ssm get-command-invocation --region $REGION --command-id "$CMD" --instance-id "$ID" --query 'StandardOutputContent' --output text
aws ssm get-command-invocation --region $REGION --command-id "$CMD" --instance-id "$ID" --query 'StandardErrorContent' --output text | tail -5
