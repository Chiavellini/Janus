#!/usr/bin/env bash
# Operator-only L122 command. Never run this from an agent or unattended release job.
# bash ops/box/clear_legacy_incident_latch.sh <full-release-git-sha> <full-kill-sha256>
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
RELEASE_SHA=${1:?full deployed Git SHA required}
KILL_SHA=${2:?full retained kill SHA256 required}
case "$RELEASE_SHA" in [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;; *) echo 'full 40-hex release SHA required' >&2; exit 2;; esac
case "$KILL_SHA" in [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;; *) echo 'full 64-hex kill SHA256 required' >&2; exit 2;; esac
DB=/srv/janus/tuples/tuples.sqlite
KILL=/srv/janus/kill/live
PY=/opt/janus/.venv/bin/python3
read -r -d '' REMOTE <<EOS || true
set -euo pipefail
AUDIT_ROOT=/srv/janus/release-audit
AUDIT=\"\"
ARCHIVE=\"\"
cleanup() {
  rc=\$?
  systemctl stop janus-live-stream >/dev/null 2>&1 || true
  if [ \"\$rc\" != 0 ] && [ -n \"\$ARCHIVE\" ] && [ ! -e '$KILL' ] && [ -e \"\$ARCHIVE\" ]; then
    '$PY' /opt/janus/ops/box/clear_legacy_incident_latch.py restore --archive \"\$ARCHIVE\" --kill '$KILL' --expected-kill-sha '$KILL_SHA' || true
  fi
  if [ \"\$rc\" != 0 ] && [ -n \"\$AUDIT\" ] && [ ! -e \"\$ARCHIVE\" ]; then rmdir \"\$AUDIT\" >/dev/null 2>&1 || true; fi
  exit \"\$rc\"
}
trap cleanup EXIT
AUDIT=\$(mktemp -d \"\$AUDIT_ROOT/.L122.XXXXXX\")
chown janus:janus \"\$AUDIT\"
chmod 700 \"\$AUDIT\"
ARCHIVE=\"\$AUDIT/legacy-incident-211-cleared-$RELEASE_SHA-$KILL_SHA.json\"
# Read-only proof before any stop or archive.
sudo -u janus env JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box '$PY' /opt/janus/ops/box/clear_legacy_incident_latch.py prove --db '$DB' --kill '$KILL' --expected-kill-sha '$KILL_SHA' --release-sha '$RELEASE_SHA' --repo /opt/janus
echo PRE_STOP_LEGACY_211_PROOF_OK
# Complete real two-venue guard pass while stopped with the exact retained kill present.
systemctl stop janus-live-stream
test \"\$(systemctl is-active janus-live-stream || true)\" = inactive
sudo -u janus /usr/bin/zsh -c 'set -a; source /etc/janus.env; source /run/janus/janus.env; exec /opt/janus/.venv/bin/python3 /opt/janus/ops/guard_once.py --db /srv/janus/tuples/tuples.sqlite --require-complete-quiet'
echo STOPPED_GUARD_PASS_1_OK
# Start once under the retained kill, requiring fresh connected three-socket health rows.
STARTED=\$(date +%s.%N)
systemctl start janus-live-stream
green=0
for _ in \$(seq 1 25); do
  sleep 3
  if systemctl is-active --quiet janus-live-stream && sudo -u janus '$PY' -c \"import sqlite3,time; c=sqlite3.connect('file:$DB?mode=ro',uri=True); s=float('$STARTED'); now=time.time(); rows=c.execute('SELECT venue,connected,seen_ts FROM socket_health WHERE rowid IN (SELECT max(rowid) FROM socket_health GROUP BY venue)').fetchall(); d={v:(bool(ok),float(ts)) for v,ok,ts in rows}; need=('kalshi','polymarket','polymarket_user'); raise SystemExit(0 if all(v in d and d[v][0] and s <= d[v][1] <= now for v in need) else 1)\"; then green=1; break; fi
done
if [ \"\$green\" != 1 ]; then echo POST_START_STREAMS_FAILED >&2; exit 1; fi
echo RETAINED_KILL_STREAM_WARMUP_OK
systemctl stop janus-live-stream
test \"\$(systemctl is-active janus-live-stream || true)\" = inactive
sudo -u janus /usr/bin/zsh -c 'set -a; source /etc/janus.env; source /run/janus/janus.env; exec /opt/janus/.venv/bin/python3 /opt/janus/ops/guard_once.py --db /srv/janus/tuples/tuples.sqlite --require-complete-quiet'
echo STOPPED_GUARD_PASS_2_OK
# activate repeats all proofs immediately before its exclusive exact-byte move.
sudo -u janus env JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box '$PY' /opt/janus/ops/box/clear_legacy_incident_latch.py activate --db '$DB' --kill '$KILL' --archive-dir '$AUDIT' --expected-kill-sha '$KILL_SHA' --release-sha '$RELEASE_SHA' --repo /opt/janus
echo LEGACY_211_CLEAR_COMPLETE archive=\$ARCHIVE
systemctl start janus-live-stream
systemctl is-active --quiet janus-live-stream
echo LEGACY_211_LANE_RESTARTED
trap - EXIT
EOS
bash "$HERE/run.sh" "$REMOTE"
