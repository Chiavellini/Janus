#!/usr/bin/env bash
# Operator-invoked by release.sh only after it captured the exact live-kill digest.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
SHA=${1:?release sha}
DIGEST=${2:?expected live-kill sha256}
ARCHIVE=/srv/janus/release-audit/L64/live-cleared-$SHA-${DIGEST:0:12}.json

read -r -d '' REMOTE <<EOS || true
set -euo pipefail
cleanup() {
  rc=\$?
  if [ "\$rc" != 0 ]; then
    if [ ! -f /srv/janus/kill/live ] && [ -f '$ARCHIVE' ]; then
      /opt/janus/.venv/bin/python3 /opt/janus/ops/box/clear_false_maker_latch.py restore --archive '$ARCHIVE' || true
    fi
    systemctl start janus-live-stream || true
  fi
  exit "\$rc"
}
trap cleanup EXIT
# A restarted lane gets a bounded chance to close a now-fully-proved persistence incident while
# the old kill still blocks entry. Unknown or incomplete incidents remain unresolved and abort
# before the lane is stopped or the kill is touched.
risk_quiet=0
for _ in \$(seq 1 25); do
  if sudo -u janus /opt/janus/.venv/bin/python3 - <<'PY'
import sqlite3, sys
sys.path.insert(0, '/opt/janus')
from nodes.risk.flags import unresolved_flag_rows
flags = ('ORDER_PERSISTENCE_FAILED', 'POST_ONLY_PERSISTENCE_FAILED', 'ORPHAN_FILL',
         'POSITION_MISMATCH', 'PROTECT_FAILED', 'EXEC_CRASHED', 'ORDER_OVERFILL',
         'POST_ONLY_ROLE_VIOLATION', 'UNHEDGED_POSITION', 'RESERVATION_MISSING')
con = sqlite3.connect('file:/srv/janus/tuples/tuples.sqlite?mode=ro', uri=True)
active = {flag: [row[0] for row in unresolved_flag_rows(con, flag)] for flag in flags}
active = {flag: ids for flag, ids in active.items() if ids}
print('risk_flags=' + repr(active))
raise SystemExit(bool(active))
PY
  then risk_quiet=1; break; fi
  sleep 3
done
if [ "\$risk_quiet" != 1 ]; then
  echo PRE_CLEAR_RISK_FLAGS_NOT_QUIET >&2
  exit 1
fi
echo PRE_CLEAR_RISK_FLAGS_QUIET
systemctl stop janus-live-stream
test "\$(systemctl is-active janus-live-stream || true)" = inactive
/opt/janus/.venv/bin/python3 /opt/janus/ops/box/clear_false_maker_latch.py clear \
  --expected-digest '$DIGEST' --release-sha '$SHA' --retain
# A prior rollback may have recreated the kill as root. The lane must always be able to append a
# stronger incident while it warms under the retained entry block.
chown janus:janus /srv/janus/kill/live
chmod 600 /srv/janus/kill/live
export JANUS_CLEAR_STARTED=\$(date +%s)
systemctl start janus-live-stream
green=0
for _ in \$(seq 1 25); do
  sleep 3
  if systemctl is-active --quiet janus-live-stream && sudo -u janus env JANUS_CLEAR_STARTED="\$JANUS_CLEAR_STARTED" /opt/janus/.venv/bin/python3 - <<'PY'
import os, sqlite3, time
c=sqlite3.connect('file:/srv/janus/tuples/tuples.sqlite?mode=ro', uri=True)
rows=c.execute("SELECT venue,connected,seen_ts FROM socket_health s WHERE seen_ts=(SELECT MAX(seen_ts) FROM socket_health WHERE venue=s.venue)").fetchall()
latest={venue:(bool(connected),seen) for venue,connected,seen in rows}
need=('kalshi','polymarket','polymarket_user')
started=float(os.environ['JANUS_CLEAR_STARTED'])
raise SystemExit(0 if all(v in latest and latest[v][0] and started <= latest[v][1] <= time.time() for v in need) else 1)
PY
  then green=1; break; fi
done
if [ "\$green" != 1 ]; then
  echo 'POST_START_STREAMS_FAILED; original kill restored' >&2
  exit 1
fi
echo POST_START_STREAMS_GREEN
# Only now can entry become live. The digest is rechecked so a concurrent or stronger kill wins.
/opt/janus/.venv/bin/python3 /opt/janus/ops/box/clear_false_maker_latch.py activate \
  --archive '$ARCHIVE' --expected-digest '$DIGEST'
echo 'LIVE_CLEAR_COMPLETE sha=$SHA archive=$ARCHIVE'
trap - EXIT
EOS
bash "$HERE/run.sh" "$REMOTE"
