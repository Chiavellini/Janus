#!/usr/bin/env bash
# F24 progress check. READ-ONLY: it reads the tuple store, the kill directory and the arming
# override, and changes nothing. It never writes /srv/janus/release-audit/f24_start_utc.
#
#   bash check_f24.sh <start_utc>              # the start_utc arm_f24.sh printed
#   bash check_f24.sh <start_utc> <end_utc>    # a fixed window (used to calibrate against L141)
#
# report.py REFUSES (exit 3) when <start_utc> disagrees by more than a second with the start
# arm_f24.sh persisted to /srv/janus/release-audit/f24_start_utc, and warns in the JSON when that
# file is absent. This script therefore does not pretty-print a refusal as if it were a report: it
# captures the reader's output, and on a non-zero exit passes it through untouched.
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
if [ "$#" -gt 2 ]; then
  echo "check_f24.sh takes a start and an optional end only. --include/--exclude change WHICH" >&2
  echo "covers are scored: run report.py directly on the box so the choice is a deliberate act." >&2
  exit 2
fi

# A FIXED staging path made two simultaneous read-only checks (a progress read while another is
# already running) overwrite and then delete each other's script -- exactly the failure ops/box/run.sh
# was changed for. Each run stages its own mktemp'd file, chmod 644 so the janus user can read the
# root-owned temp file, and a trap removes ONLY that file, on every exit path. The template ends in
# the X's with no `.py` suffix: a trailing suffix is a GNU extension that BSD mktemp copies
# VERBATIM, which would hand every run the same name again on any non-GNU host. Python does not
# need the extension.
REPORT=$(cat "$HERE/report.py")
PAYLOAD="F24_PY=\$(mktemp /tmp/f24_report.XXXXXX)
trap 'rm -f \"\$F24_PY\"' EXIT
chmod 644 \"\$F24_PY\"
cat > \"\$F24_PY\" <<'F24_REPORT_EOF'
$REPORT
F24_REPORT_EOF
PY=/opt/janus/.venv/bin/python3
OUT=\$(sudo -u janus \$PY \"\$F24_PY\" $START $END)
rc=\$?
if [ \$rc -ne 0 ]; then
  printf '%s\n' \"\$OUT\"
  echo \"check_f24: the reader exited \$rc and produced no report (see the message above).\" >&2
  exit \$rc
fi
printf '%s\n' \"\$OUT\" | sudo -u janus \$PY -m json.tool
exit \$?"

bash "$RUNNER" "$PAYLOAD"
