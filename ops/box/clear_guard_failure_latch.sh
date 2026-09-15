#!/usr/bin/env bash
# Operator-only L133 command. Never run this from an agent or unattended release job.
# bash ops/box/clear_guard_failure_latch.sh <full-release-git-sha> <full-kill-sha256>
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
RELEASE_SHA=${1:?full deployed Git SHA required}
KILL_SHA=${2:?full retained kill SHA256 required}
[[ "$RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo 'full 40-hex release SHA required' >&2; exit 2; }
[[ "$KILL_SHA" =~ ^[0-9a-f]{64}$ ]] || { echo 'full 64-hex kill SHA256 required' >&2; exit 2; }
[[ "$KILL_SHA" == dcc4c761ee8fb5f903475e0400b54a0ef57db8246cd7d378d4846cf181c96d83 ]] || {
  echo 'L133 exact guard-failure digest required' >&2; exit 2;
}
DB=/srv/janus/tuples/tuples.sqlite
KILL=/srv/janus/kill/live
PY=/opt/janus/.venv/bin/python3
read -r -d '' REMOTE <<EOS || true
set -euo pipefail
AUDIT_ROOT=/srv/janus/release-audit
AUDIT=""
ARCHIVE=""
stop_lane_verified() {
  systemctl stop janus-live-stream || true
  state=\$(systemctl is-active janus-live-stream || true)
  main_pid=\$(systemctl show janus-live-stream --property=MainPID --value 2>/dev/null || true)
  control_pid=\$(systemctl show janus-live-stream --property=ControlPID --value 2>/dev/null || true)
  case "\$main_pid:\$control_pid" in
    0:0) ;;
    *) return 1 ;;
  esac
  case "\$state" in
    inactive) return 0 ;;
    failed)
      systemctl reset-failed janus-live-stream || return 1
      [ "\$(systemctl is-active janus-live-stream || true)" = inactive ] || return 1
      [ "\$(systemctl show janus-live-stream --property=MainPID --value 2>/dev/null || true)" = 0 ] || return 1
      [ "\$(systemctl show janus-live-stream --property=ControlPID --value 2>/dev/null || true)" = 0 ] || return 1
      return 0
      ;;
    *) return 1 ;;
  esac
}
cleanup() {
  rc=\$?
  trap - EXIT
  if [ "\$rc" != 0 ]; then
    rollback_failed=0
    if [ ! -e '$KILL' ]; then
      if [ -n "\$ARCHIVE" ] && [ -e "\$ARCHIVE" ]; then
        if ! '$PY' /opt/janus/ops/box/clear_guard_failure_latch.py restore --archive "\$ARCHIVE" --kill '$KILL' --expected-kill-sha '$KILL_SHA'; then
          echo GUARD_1169_1170_ROLLBACK_RESTORE_FAILED >&2
          rollback_failed=1
        fi
      else
        echo GUARD_1169_1170_ROLLBACK_SOURCE_MISSING >&2
        rollback_failed=1
      fi
    fi
    stopped=0
    for _ in 1 2 3; do
      if stop_lane_verified; then stopped=1; break; fi
      sleep 1
    done
    if [ "\$stopped" != 1 ]; then
      echo GUARD_1169_1170_ROLLBACK_STOP_FAILED >&2
      rollback_failed=1
    fi
    if [ ! -e '$KILL' ]; then
      echo GUARD_1169_1170_ROLLBACK_KILL_ABSENT >&2
      rollback_failed=1
    fi
    if [ "\$rollback_failed" != 0 ]; then exit 97; fi
  fi
  if [ "\$rc" != 0 ] && [ -n "\$AUDIT" ] && [ ! -e "\$ARCHIVE" ]; then rmdir "\$AUDIT" >/dev/null 2>&1 || true; fi
  exit "\$rc"
}
trap cleanup EXIT
AUDIT=\$(mktemp -d "\$AUDIT_ROOT/.L133.XXXXXX")
chown janus:janus "\$AUDIT"
chmod 700 "\$AUDIT"
ARCHIVE="\$AUDIT/guard-failure-1169-1170-cleared-$RELEASE_SHA-$KILL_SHA.json"
# Freeze all writers before the exact incident-set proof. Even under a retained live kill the
# guard keeps running and could append a later GUARD_FAILED row, invalidating L133 between proof
# and activation.
stop_lane_verified
# L136: settle only the exact already-hedged cover that arrived after L133 was registered.  This
# uses the ordinary venue-result/apply_settlements path while the registered kill is retained;
# open or changed evidence fails before L133 can call the database quiet.
sudo -u janus env JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box '$PY' /opt/janus/ops/box/settle_held_cover.py \
  --db '$DB' --kill '$KILL' --expected-kill-sha '$KILL_SHA' \
  --release-sha '$RELEASE_SHA' --repo /opt/janus
echo STOPPED_EXACT_HELD_COVER_SETTLED
pre_proved=0
for _ in \$(seq 1 100); do
  if sudo -u janus env JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box '$PY' /opt/janus/ops/box/clear_guard_failure_latch.py prove --db '$DB' --kill '$KILL' --expected-kill-sha '$KILL_SHA' --release-sha '$RELEASE_SHA' --repo /opt/janus; then
    pre_proved=1; break
  fi
  sleep 3
done
if [ "\$pre_proved" != 1 ]; then echo STOPPED_PRE_GUARD_1169_1170_PROOF_FAILED >&2; exit 1; fi
echo STOPPED_PRE_GUARD_1169_1170_PROOF_OK
sudo -u janus /usr/bin/zsh -c 'set -a; source /etc/janus.env; source /run/janus/janus.env; exec /opt/janus/.venv/bin/python3 /opt/janus/ops/guard_once.py --db /srv/janus/tuples/tuples.sqlite --require-complete-quiet'
echo STOPPED_GUARD_PASS_1_OK
STARTED=\$(date +%s.%N)
systemctl start janus-live-stream
green=0
for _ in \$(seq 1 25); do
  sleep 3
  if systemctl is-active --quiet janus-live-stream && sudo -u janus '$PY' -c "import sqlite3,time; c=sqlite3.connect('file:$DB?mode=ro',uri=True); s=float('\$STARTED'); now=time.time(); rows=c.execute('SELECT venue,connected,seen_ts FROM socket_health WHERE rowid IN (SELECT max(rowid) FROM socket_health GROUP BY venue)').fetchall(); d={v:(bool(ok),float(ts)) for v,ok,ts in rows}; need=('kalshi','polymarket','polymarket_user'); raise SystemExit(0 if all(v in d and d[v][0] and s <= d[v][1] <= now for v in need) else 1)"; then
    green=1; break
  fi
done
if [ "\$green" != 1 ]; then echo POST_START_GUARD_1169_1170_STREAMS_FAILED >&2; exit 1; fi
echo RETAINED_KILL_STREAM_WARMUP_OK
stop_lane_verified
sudo -u janus /usr/bin/zsh -c 'set -a; source /etc/janus.env; source /run/janus/janus.env; exec /opt/janus/.venv/bin/python3 /opt/janus/ops/guard_once.py --db /srv/janus/tuples/tuples.sqlite --require-complete-quiet'
echo STOPPED_GUARD_PASS_2_OK
sudo -u janus env JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box '$PY' /opt/janus/ops/box/clear_guard_failure_latch.py activate --db '$DB' --kill '$KILL' --archive-dir "\$AUDIT" --expected-kill-sha '$KILL_SHA' --release-sha '$RELEASE_SHA' --repo /opt/janus
echo GUARD_FAILURE_1169_1170_CLEAR_COMPLETE archive=\$ARCHIVE
systemctl start janus-live-stream
systemctl is-active --quiet janus-live-stream
echo GUARD_FAILURE_1169_1170_LANE_RESTARTED
trap - EXIT
EOS
bash "$HERE/run.sh" "$REMOTE"
