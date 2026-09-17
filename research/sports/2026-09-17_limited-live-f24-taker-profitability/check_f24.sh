#!/usr/bin/env bash
# F24 progress check. READ-ONLY: it reads the tuple store and changes nothing.
#
#   bash check_f24.sh <start_utc>              # the start_utc arm_f24.sh printed
#   bash check_f24.sh <start_utc> <end_utc>    # a fixed window (used to calibrate against L141)
#
# ops/box/run.sh ignores stdin whenever it is given an argument, so report.py is embedded in the
# payload itself rather than piped alongside a command.
set -euo pipefail
START=${1:-}
END=${2:-}
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
RUNNER=${F24_RUNNER:-$REPO/ops/box/run.sh}
num='^[0-9]+(\.[0-9]+)?$'
if ! [[ "$START" =~ $num ]] || { [ -n "$END" ] && ! [[ "$END" =~ $num ]]; }; then
  echo "usage: bash check_f24.sh <start_utc> [end_utc]" >&2
  exit 2
fi

REPORT=$(cat "$HERE/report.py")
PAYLOAD="cat > /tmp/f24_report.py <<'F24_REPORT_EOF'
$REPORT
F24_REPORT_EOF
sudo -u janus /opt/janus/.venv/bin/python3 /tmp/f24_report.py $START $END | sudo -u janus /opt/janus/.venv/bin/python3 -m json.tool
rc=\${PIPESTATUS[0]}
rm -f /tmp/f24_report.py
exit \$rc"

bash "$RUNNER" "$PAYLOAD"
