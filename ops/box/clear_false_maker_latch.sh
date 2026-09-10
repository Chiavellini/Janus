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
systemctl stop janus-live-stream
test "\$(systemctl is-active janus-live-stream || true)" = inactive
sudo -u janus /opt/janus/.venv/bin/python3 /opt/janus/ops/box/clear_false_maker_latch.py clear \
  --expected-digest '$DIGEST' --release-sha '$SHA'
export JANUS_CLEAR_STARTED=\$(date +%s)
systemctl start janus-live-stream
green=0
for _ in \$(seq 1 25); do
  sleep 3
  if systemctl is-active --quiet janus-live-stream && sudo -u janus /opt/janus/.venv/bin/python3 - <<'PY'
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
echo 'LIVE_CLEAR_COMPLETE sha=$SHA archive=$ARCHIVE'
trap - EXIT
EOS
bash "$HERE/run.sh" "$REMOTE"
