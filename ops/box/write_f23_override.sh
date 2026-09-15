#!/usr/bin/env bash
# Prepare (but do not execute) an exact F23 LIMITED_LIVE override. The caller/operator still
# reviews and runs this route; the script never starts a service or submits an order.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
STATEMENT=$(cat "$HERE/f23_arm_statement.txt")
python3 "$ROOT/ops/arming_override.py" --root "$ROOT" --mode LIMITED_LIVE \
  --signed-by "${JANUS_SIGNED_BY:-Bernardo}" --stake-usd 30 --max-contracts 25 \
  --day-notional-usd 500 --expires-hours 168 --force \
  --experiment F23 \
  --experiment-spec research/sports/2026-09-15_limited-live-f23-maker-vs-taker/spec.yaml \
  --assignment-algorithm janus:f23:entry-arm:v1 --statement "$STATEMENT"
