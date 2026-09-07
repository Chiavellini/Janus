#!/usr/bin/env bash
# Switch the box's lane between PAPER_EXECUTION and LIMITED_LIVE and restart it.
#   bash ops/box/mode.sh LIMITED_LIVE      # the operator's, after write_override.sh
#   bash ops/box/mode.sh PAPER_EXECUTION   # anyone's; the way back
# LIMITED_LIVE is refused by the lane itself (nodes/risk/gate.resolve_mode) unless an override on
# the box pins the running sha and limits sha; the unit then exits and systemd retries each minute,
# which the watchdog reports as CRASH_LOOP. Restart only when no game is in play.
set -euo pipefail
MODE=${1:?PAPER_EXECUTION or LIMITED_LIVE}
case $MODE in PAPER_EXECUTION|LIMITED_LIVE) ;; *) echo "unknown mode $MODE"; exit 2;; esac
bash "$(dirname "$0")/run.sh" "mkdir -p /etc/systemd/system/janus-live-stream.service.d
cat > /etc/systemd/system/janus-live-stream.service.d/mode.conf <<EOF
[Service]
ExecStart=
ExecStart=/usr/bin/zsh /opt/janus/ops/run_node.sh live_stream -m grids.live_stream.grid --leagues enabled --pre-hours 6 --discovery-period 300 --report-period 60 --mode $MODE
EOF
systemctl daemon-reload; systemctl restart janus-live-stream; sleep 12
echo lane=\$(systemctl is-active janus-live-stream) mode=$MODE
grep -a '\[mode\]\|refused\|Refused\|OVERRIDE' /srv/janus/logs/live_stream.stdout.log | tail -3 | cut -c1-160"
