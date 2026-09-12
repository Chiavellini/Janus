#!/usr/bin/env bash
# The board, live: a private tunnel from this laptop to the box's loopback board service, and the
# page in the browser. Nothing is exposed on the internet; the tunnel is SSM (IAM), the service
# binds 127.0.0.1 on the box. Ctrl-C closes the tunnel.
#   bash ops/box/board.sh            # local port 8787
#   bash ops/box/board.sh 9001       # another local port
# Needs the AWS Session Manager plugin (session-manager-plugin) on this machine.
set -euo pipefail
ID=${JANUS_BOX_ID:-i-0a8c073c72dcdae11}
REGION=${JANUS_BOX_REGION:-mx-central-1}
LOCAL=${1:-8787}
command -v session-manager-plugin >/dev/null || { echo "session-manager-plugin is not installed (https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)"; exit 2; }
( sleep 2; open "http://localhost:$LOCAL/" 2>/dev/null || xdg-open "http://localhost:$LOCAL/" 2>/dev/null || true ) &
echo "tunnel: localhost:$LOCAL -> $ID:8787 ($REGION); Ctrl-C to close"
exec aws ssm start-session --region "$REGION" --target "$ID" --document-name AWS-StartPortForwardingSession \
  --parameters "{\"portNumber\":[\"8787\"],\"localPortNumber\":[\"$LOCAL\"]}"
