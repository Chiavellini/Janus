#!/usr/bin/env bash
# The two unwind proofs (hedge protection R4), on the box, real and tiny: buy a venue's minimum
# and sell it straight back through the adapter and clearance the protection layer uses.
#   JANUS_BOX_REGION=mx-central-1 JANUS_BOX_ID=i-0a8c073c72dcdae11 bash ops/box/unwind_proofs.sh <kalshi ticker> <polymarket slug> <polymarket token>
# The kill file is lifted for the minute the proofs take and re-latched on exit whatever happens
# (the running lane cannot use the window: its override pins the staged tree, ARM_STALE). Prints
# each proof's verdict; the proof files land in /srv/janus/proofs/. The operator runs this: the
# --arm is inside, and only a human arms a real order in this project.
set -euo pipefail
TICKER=${1:?the Kalshi ticker (a live market with a two-sided touch)}
SLUG=${2:?the Polymarket slug}
TOKEN=${3:?the Polymarket token id of the outcome}
HERE=$(cd "$(dirname "$0")" && pwd)
SCRIPT=$(cat <<EOS
set -a; for f in /run/janus/*.env /etc/janus.env; do [ -f "\$f" ] && . "\$f"; done; set +a
cd /opt/janus
trap 'sudo -u janus touch /srv/janus/kill/live; echo "kill/live re-latched"' EXIT
sudo -u janus rm -f /srv/janus/kill/live; echo "kill/live lifted for the proofs"
echo "=== kalshi"; sudo -u janus -E JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box /opt/janus/.venv/bin/python3 ops/unwind_proof.py --venue kalshi --ticker '$TICKER' --arm 2>&1 | grep -v api-key | cut -c1-220
echo "=== polymarket"; sudo -u janus -E JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box /opt/janus/.venv/bin/python3 ops/unwind_proof.py --venue polymarket --slug '$SLUG' --token '$TOKEN' --arm 2>&1 | grep -v api-key | cut -c1-220
ls -t /srv/janus/proofs/unwind_* 2>/dev/null | head -2
EOS
)
bash "$HERE/run.sh" "$SCRIPT"
