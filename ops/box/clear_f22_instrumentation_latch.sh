#!/usr/bin/env bash
# Operator-only exact recovery for the L140 F22 instrumentation STOP.
# bash ops/box/clear_f22_instrumentation_latch.sh <full-release-git-sha> <full-kill-sha256>
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
RELEASE_SHA=${1:?full deployed Git SHA required}
KILL_SHA=${2:?full retained kill SHA256 required}
[[ "$RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo 'full 40-hex release SHA required' >&2; exit 2; }
[[ "$KILL_SHA" == d81bbfc267a235ca7f268e7317d77ee7e83c65f5263117590e4e86d1552b1636 ]] || {
  echo 'L140 exact F22 instrumentation digest required' >&2; exit 2;
}
DB=/srv/janus/tuples/tuples.sqlite
KILL=/srv/janus/kill/live
PY=/opt/janus/.venv/bin/python3
AUDIT_ROOT=/srv/janus/release-audit
AUDIT=""
ARCHIVE=""
stop_lane_verified() {
  systemctl stop janus-live-stream || true
  local state main_pid control_pid
  state=$(systemctl is-active janus-live-stream || true)
  main_pid=$(systemctl show janus-live-stream --property=MainPID --value 2>/dev/null || true)
  control_pid=$(systemctl show janus-live-stream --property=ControlPID --value 2>/dev/null || true)
  [ "$main_pid:$control_pid" = 0:0 ] || return 1
  case "$state" in
    inactive) return 0 ;;
    failed) systemctl reset-failed janus-live-stream || return 1
      [ "$(systemctl is-active janus-live-stream || true)" = inactive ] || return 1
      [ "$(systemctl show janus-live-stream --property=MainPID --value 2>/dev/null || true)" = 0 ] || return 1
      [ "$(systemctl show janus-live-stream --property=ControlPID --value 2>/dev/null || true)" = 0 ] || return 1 ;;
    *) return 1 ;;
  esac
}
cleanup() {
  local rc=$?
  trap - EXIT
  if [ "$rc" != 0 ]; then
    # Kill first: a failed proof/warmup must leave entry blocked. Restore only the exact archived
    # bytes, then prove the lane is stopped; never restart on a mismatch.
    if [ ! -e "$KILL" ] && [ -n "$ARCHIVE" ] && [ -e "$ARCHIVE" ]; then
      "$PY" /opt/janus/ops/box/clear_f22_instrumentation_latch.py restore \
        --archive "$ARCHIVE" --kill "$KILL" --expected-kill-sha "$KILL_SHA" || {
        echo F22_INSTRUMENTATION_ROLLBACK_RESTORE_FAILED >&2; rc=97;
      }
    fi
    if ! stop_lane_verified; then echo F22_INSTRUMENTATION_ROLLBACK_STOP_FAILED >&2; rc=97; fi
    [ -e "$KILL" ] || { echo F22_INSTRUMENTATION_ROLLBACK_KILL_ABSENT >&2; rc=97; }
    if [ -n "$AUDIT" ] && [ ! -e "$ARCHIVE" ]; then rmdir "$AUDIT" >/dev/null 2>&1 || true; fi
  fi
  exit "$rc"
}
trap cleanup EXIT
AUDIT=$(mktemp -d "$AUDIT_ROOT/.L140.XXXXXX")
chown janus:janus "$AUDIT"
chmod 700 "$AUDIT"
ARCHIVE="$AUDIT/f22-instrumentation-$RELEASE_SHA-$KILL_SHA.json"

# Freeze all writers before proving rows 1 and 3, their NULL-fee terminal maker orders, F23
# absence and zero flight/unhedged/unreleased capital. This helper never updates those rows.
stop_lane_verified
sudo -u janus env JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box "$PY" \
  /opt/janus/ops/box/clear_f22_instrumentation_latch.py prove --db "$DB" --kill "$KILL" \
  --expected-kill-sha "$KILL_SHA" --release-sha "$RELEASE_SHA" --repo /opt/janus
echo STOPPED_EXACT_F22_INSTRUMENTATION_PROOF_OK
sudo -u janus /usr/bin/zsh -c 'set -a; source /etc/janus.env; source /run/janus/janus.env; exec /opt/janus/.venv/bin/python3 /opt/janus/ops/guard_once.py --db /srv/janus/tuples/tuples.sqlite --require-complete-quiet'
echo STOPPED_GUARD_PASS_1_OK

# Warm streams under the retained kill. F23 authority was written by release.sh before this route;
# no F22 override is accepted. Stop and re-run every guard before touching the kill.
STARTED=$(date +%s.%N)
systemctl start janus-live-stream
green=0
for _ in $(seq 1 25); do
  sleep 3
  if systemctl is-active --quiet janus-live-stream && sudo -u janus "$PY" -c "import sqlite3,time; c=sqlite3.connect('file:$DB?mode=ro',uri=True); s=float('$STARTED'); now=time.time(); rows=c.execute('SELECT venue,connected,seen_ts FROM socket_health WHERE rowid IN (SELECT max(rowid) FROM socket_health GROUP BY venue)').fetchall(); d={v:(bool(ok),float(ts)) for v,ok,ts in rows}; need=('kalshi','polymarket','polymarket_user'); raise SystemExit(0 if all(v in d and d[v][0] and s <= d[v][1] <= now for v in need) else 1)"; then
    green=1; break
  fi
done
[ "$green" = 1 ] || { echo POST_START_F22_INSTRUMENTATION_STREAMS_FAILED >&2; exit 1; }
echo RETAINED_KILL_STREAM_WARMUP_OK
stop_lane_verified
sudo -u janus /usr/bin/zsh -c 'set -a; source /etc/janus.env; source /run/janus/janus.env; exec /opt/janus/.venv/bin/python3 /opt/janus/ops/guard_once.py --db /srv/janus/tuples/tuples.sqlite --require-complete-quiet'
echo STOPPED_GUARD_PASS_2_OK

# Archive/remove only the exact registered kill, then restart under the exact F23 override.
sudo -u janus env JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box "$PY" \
  /opt/janus/ops/box/clear_f22_instrumentation_latch.py activate --db "$DB" --kill "$KILL" \
  --archive-dir "$AUDIT" --expected-kill-sha "$KILL_SHA" --release-sha "$RELEASE_SHA" --repo /opt/janus
echo F22_INSTRUMENTATION_CLEAR_COMPLETE archive="$ARCHIVE" F23_AUTHORITY_REQUIRED
systemctl start janus-live-stream
systemctl is-active --quiet janus-live-stream
echo F23_LANE_RESTARTED
trap - EXIT
