#!/usr/bin/env bash
# THE OPERATOR'S SIGNATURE. Writes the arming override on the box (GATE_TO_LIVE step 9) from the
# operator's own statement, pinning the box's runner sha and its limits.toml sha. The agent
# prepares this file and never runs it.
#
#   bash ops/box/write_override.sh "I approve ..." [stake_usd] [max_contracts] [day_notional_usd] [expires_hours]
#
# Defaults are the GATE row of 2026-09-07 evening, the smallest executable size: $12 per order,
# 10 contracts per leg, $250 notional a day, 168 h (the morning's 12 / 25 / $60 row is superseded;
# ops/box/release.sh passes the same JANUS_ARM_CAPS). The lane reads the override only in
# LIMITED_LIVE (ops/box/mode.sh); a runner or limits change on the box invalidates it (rewrite).
set -euo pipefail
STATEMENT=${1:?the operator statement, verbatim}      # no apostrophe here: bash 3.2 reads it as a quote
STAKE=${2:-12}; CONTRACTS=${3:-10}; DAY=${4:-250}; HOURS=${5:-168}      # GATE row 2026-09-07 evening
SIGNED_BY=${JANUS_SIGNED_BY:-Bernardo}
# F22 remains available only to read historical evidence; new signing defaults to fresh F23.
# Set JANUS_EXPERIMENT=F22 only for an explicitly reviewed legacy read/recovery operation.
EXPERIMENT=${JANUS_EXPERIMENT:-F23}
case "$EXPERIMENT" in
  F22)
    # --experiment F22
    # --experiment-spec research/sports/2026-09-15_limited-live-f22-maker-vs-taker/spec.yaml
    # --assignment-algorithm janus:f22:entry-arm:v1
    EXPERIMENT_SPEC=research/sports/2026-09-15_limited-live-f22-maker-vs-taker/spec.yaml
    ASSIGNMENT_ALGORITHM=janus:f22:entry-arm:v1 ;;
  F23)
    # --experiment F23
    # --experiment-spec research/sports/2026-09-15_limited-live-f23-maker-vs-taker/spec.yaml
    # --assignment-algorithm janus:f23:entry-arm:v1
    EXPERIMENT_SPEC=research/sports/2026-09-15_limited-live-f23-maker-vs-taker/spec.yaml
    ASSIGNMENT_ALGORITHM=janus:f23:entry-arm:v1 ;;
  *) echo "unsupported JANUS_EXPERIMENT: $EXPERIMENT" >&2; exit 2 ;;
esac
# The statement travels base64-encoded so its own quotes need no escaping (and macOS bash 3.2
# cannot parse a heredoc nested in a heredoc).
B64=$(printf %s "$STATEMENT" | base64 | tr -d '\n')
read -r -d '' SCRIPT <<EOS || true
echo "$B64" | base64 -d > /tmp/janus-statement.txt
sudo -u janus bash -c 'set -a; . /run/janus/janus.env; set +a; cd /opt/janus; JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box .venv/bin/python3 ops/arming_override.py --mode LIMITED_LIVE --signed-by "$SIGNED_BY" --stake-usd $STAKE --max-contracts $CONTRACTS --day-notional-usd $DAY --expires-hours $HOURS --force --experiment "$EXPERIMENT" --experiment-spec "$EXPERIMENT_SPEC" --assignment-algorithm "$ASSIGNMENT_ALGORITHM" --statement "\$(cat /tmp/janus-statement.txt)"'
rm -f /tmp/janus-statement.txt
EOS
bash "$(dirname "$0")/run.sh" "$SCRIPT"
