#!/usr/bin/env bash
# The two unwind proofs (hedge protection R4), on the box, real and tiny: buy a venue's minimum
# and sell it straight back through the adapter and clearance the protection layer uses.
#   JANUS_BOX_REGION=mx-central-1 JANUS_BOX_ID=i-0a8c073c72dcdae11 bash ops/box/unwind_proofs.sh
#   ... unwind_proofs.sh <kalshi ticker> <polymarket slug> <polymarket token>     # a market of your choosing
# With no arguments the box picks a co-listed match IN PLAY right now whose books have a
# two-sided touch on both venues (it dry-runs each candidate first). The kill file is lifted for
# the minute the proofs take and re-latched on exit whatever happens (the running lane cannot use
# the window: its override pins the staged tree, ARM_STALE). Prints each proof's verdict; the
# proof files land in /srv/janus/proofs/. The operator runs this: the --arm is inside, and only a
# human arms a real order in this project.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
TICKER=${1:-}; SLUG=${2:-}; TOKEN=${3:-}
SCRIPT=$(cat <<EOS
set -a; for f in /run/janus/*.env /etc/janus.env; do [ -f "\$f" ] && . "\$f"; done; set +a
cd /opt/janus
PY=/opt/janus/.venv/bin/python3
run() { sudo -u janus -E JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box \$PY ops/unwind_proof.py "\$@" 2>&1 | grep -v api-key | cut -c1-220; }
TICKER='$TICKER'; SLUG='$SLUG'; TOKEN='$TOKEN'
trap 'sudo -u janus touch /srv/janus/kill/live; echo "kill/live re-latched"' EXIT
sudo -u janus rm -f /srv/janus/kill/live; echo "kill/live lifted for the proofs"
if [ -z "\$TICKER" ]; then
  # candidates: in-play co-listed events, newest kickoff first: "ticker slug token" per line
  CANDS=\$(sudo -u janus \$PY - <<'PYX'
import sqlite3, json
c = sqlite3.connect("file:/srv/janus/tuples/tuples.sqlite?mode=ro", uri=True)
for ev, slug, spec in c.execute("select event_id, pm_slug, spec_json from events where phase='in:co_listed' and pm_slug is not null order by start_utc desc limit 12"):
    outs = json.loads(spec or "{}").get("outcomes") or {}
    for v in outs.values():
        if isinstance(v, dict) and v.get("kalshi") and v.get("polymarket"):
            print(v["kalshi"], slug, v["polymarket"]); break
PYX
)
  while read -r T S K; do
    [ -n "\$T" ] || continue
    echo "=== candidate \$T \$S (dry runs)"
    if run --venue kalshi --ticker "\$T" | grep -q "dry run" && run --venue polymarket --slug "\$S" --token "\$K" | grep -q "dry run"; then
      TICKER=\$T; SLUG=\$S; TOKEN=\$K; break
    fi
  done <<< "\$CANDS"
  [ -n "\$TICKER" ] || { echo "no in-play co-listed match with a two-sided touch on both venues right now; try again later"; exit 3; }
fi
echo "=== kalshi \$TICKER"; run --venue kalshi --ticker "\$TICKER" --arm
echo "=== polymarket \$SLUG"; run --venue polymarket --slug "\$SLUG" --token "\$TOKEN" --arm
ls -t /srv/janus/proofs/unwind_* 2>/dev/null | head -2
EOS
)
bash "$HERE/run.sh" "$SCRIPT"
