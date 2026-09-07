#!/bin/bash
# One read of the box through SSM: lane and creds state, memory, the last tick, what the lane did
# since the last check, and the box's watchdog. Read-only; nothing on the box changes.
#   ops/box/status.sh                # since the last call (a marker under $TMPDIR)
#   ops/box/status.sh --since 3600   # the last hour
set -euo pipefail
ID=${JANUS_BOX_ID:-i-0c86891ee306de0b8}
REGION=us-east-1
MARK=${TMPDIR:-/tmp}/janus-box-status.mark
SINCE=$(( $(date +%s) - 7200 ))
[ -f "$MARK" ] && SINCE=$(cat "$MARK")
[ "${1:-}" = "--since" ] && SINCE=$(( $(date +%s) - $2 ))
date +%s > "$MARK"
STAMP=$(date -u -r "$SINCE" +%H:%M 2>/dev/null || date -u -d "@$SINCE" +%H:%M)
read -r -d '' SCRIPT <<EOS || true
echo "lane=\$(systemctl is-active janus-live-stream) creds=\$(systemctl is-active janus-creds) \$(uptime -p)"
echo "mem_avail_mb=\$(free -m | awk 'NR==2{print \$7}') disk=\$(df -h /srv/janus | awk 'NR==2{print \$4}') free"
L=/srv/janus/logs/live_stream.stdout.log
echo "last: \$(tail -1 \$L | cut -c1-120)"
echo "since $STAMP UTC: spawns=\$(awk '/^\[[0-9:]+Z\]/{t=substr(\$1,2,8)} t>="$STAMP" && /\[spawn\]/' \$L | wc -l) execs=\$(awk '/^\[[0-9:]+Z\]/{t=substr(\$1,2,8)} t>="$STAMP" && /\[exec\]/' \$L | wc -l) settles=\$(awk '/^\[[0-9:]+Z\]/{t=substr(\$1,2,8)} t>="$STAMP" && /\[settle \] espn/' \$L | wc -l) refused=\$(awk '/^\[[0-9:]+Z\]/{t=substr(\$1,2,8)} t>="$STAMP" && /refused/' \$L | wc -l) blocked=\$(awk '/^\[[0-9:]+Z\]/{t=substr(\$1,2,8)} t>="$STAMP" && /spawn-blocked/' \$L | wc -l) reconnects=\$(awk '/^\[[0-9:]+Z\]/{t=substr(\$1,2,8)} t>="$STAMP" && /reconnect\]/' \$L | wc -l) halts=\$(awk '/^\[[0-9:]+Z\]/{t=substr(\$1,2,8)} t>="$STAMP" && /HALT/' \$L | wc -l)"
grep "\[exec\]\|\[settle \] espn\|spawn-blocked\|Traceback" \$L | tail -6 | cut -c1-160
echo "=== watchdog"
sudo -u janus JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box /opt/janus/.venv/bin/python3 /opt/janus/ops/watchdog.py | grep -v ^info || true
EOS
CMD=$(aws ssm send-command --region $REGION --instance-ids "$ID" --document-name AWS-RunShellScript \
      --parameters "$(python3 -c 'import json,sys; print(json.dumps({"commands":[sys.stdin.read()]}))' <<<"$SCRIPT")" \
      --query Command.CommandId --output text)
for _ in $(seq 1 20); do
  st=$(aws ssm get-command-invocation --region $REGION --command-id "$CMD" --instance-id "$ID" --query Status --output text 2>/dev/null || echo Pending)
  [ "$st" = "InProgress" ] || [ "$st" = "Pending" ] || break
  sleep 3
done
aws ssm get-command-invocation --region $REGION --command-id "$CMD" --instance-id "$ID" --query 'StandardOutputContent' --output text
