#!/usr/bin/env bash
# What state is the box ACTUALLY in? READ-ONLY: it changes nothing, and it is safe to run any time.
#
#   bash verify_f24.sh
#
# Written because `ops/box/run.sh` gives up after its own poll budget while the remote command keeps
# running (memory: janus-box-ssm-long-jobs). A failed arm_f24.sh therefore does NOT prove the box is
# unchanged -- the arming may have completed after the local end stopped listening. Never conclude
# "nothing happened" from a local failure; run this, which reads the box itself.
#
# Prints one line, then the evidence as JSON:
#   F24_STATE: ARMED          exit 0   real orders can be placed under the F24 override
#   F24_STATE: NOT_ARMED      exit 2   the F22 kill is in place and the F22 override is untouched
#   F24_STATE: INDETERMINATE  exit 3   neither -- read the evidence before doing anything else
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
RUNNER=${F24_RUNNER:-$REPO/ops/box/run.sh}

read -r -d '' PAYLOAD <<'EOS' || true
set -u
sudo -u janus /opt/janus/.venv/bin/python3 - <<'PYV'
import json, os, subprocess, sys

KILL = "/srv/janus/kill/live"
KILL_ALL = "/srv/janus/kill/all"
OVERRIDE = "/srv/janus/kill/arming_override.json"
PIN = "/srv/janus/release-audit/f24_start_utc"
LOG = "/srv/janus/logs/live_stream.stdout.log"
F22_KILL_SHA = "d81bbfc267a235ca7f268e7317d77ee7e83c65f5263117590e4e86d1552b1636"
CAPS = {"stake_usd": 30.0, "max_contracts": 25.0, "day_notional_usd": 500.0}

ev = {"kill_present": os.path.exists(KILL), "kill_all_present": os.path.exists(KILL_ALL)}
errors = []

if ev["kill_present"]:
    try:
        ev["kill_sha256"] = subprocess.run(["sha256sum", KILL], capture_output=True, text=True,
                                           check=True).stdout.split()[0]
        ev["kill_is_the_f22_stop"] = ev["kill_sha256"] == F22_KILL_SHA
        ev["kill_reason"] = json.load(open(KILL)).get("reason")
    except Exception as exc:                      # noqa: BLE001 -- evidence, never a crash
        errors.append("kill read: %s" % exc)

try:
    d = json.load(open(OVERRIDE))
    caps = d.get("caps") or {}
    ev["override"] = {
        "exists": True, "mode": d.get("mode"), "caps": caps,
        "has_experiment": bool(d.get("experiment")),
        "experiment_row": (d.get("experiment") or {}).get("row_id"),
        "expires_utc": d.get("expires_utc"), "signed_by": d.get("signed_by"),
        "written_utc": d.get("written_utc"), "runner_sha": d.get("runner_sha"),
        "statement": (d.get("operator_statement") or "")[:120],
        "caps_are_the_registered_ones": all(
            abs(float(caps.get(k, -1)) - v) < 1e-9 for k, v in CAPS.items()),
    }
except FileNotFoundError:
    ev["override"] = {"exists": False}
except Exception as exc:                          # noqa: BLE001
    ev["override"] = {"exists": None}
    errors.append("override read: %s" % exc)

try:
    ev["start_pin"] = open(PIN).read().strip()
except FileNotFoundError:
    ev["start_pin"] = None
except Exception as exc:                          # noqa: BLE001
    errors.append("start pin read: %s" % exc)

try:
    out = subprocess.run(["bash", "-c",
                          "grep -a '\\[f22\\] \\(ENABLED\\|disabled\\)' %s | tail -3" % LOG],
                         capture_output=True, text=True).stdout.strip().splitlines()
    ev["last_f22_markers"] = [line[:160] for line in out]
    ev["f22_last_says_disabled"] = bool(out) and "disabled" in out[-1]
    stale = subprocess.run(["bash", "-c", "grep -a '\\[arm\\] ' %s | tail -2" % LOG],
                           capture_output=True, text=True).stdout.strip().splitlines()
    ev["last_arm_markers"] = [line[:160] for line in stale]
except Exception as exc:                          # noqa: BLE001
    errors.append("log read: %s" % exc)

try:
    ev["lane_active"] = subprocess.run(["systemctl", "is-active", "janus-live-stream"],
                                       capture_output=True, text=True).stdout.strip()
except Exception as exc:                          # noqa: BLE001
    errors.append("systemctl: %s" % exc)

ev["errors"] = errors
o = ev.get("override") or {}
armed = (not ev["kill_present"] and not ev["kill_all_present"] and o.get("exists") is True
         and not o.get("has_experiment") and o.get("mode") == "LIMITED_LIVE"
         and o.get("caps_are_the_registered_ones") and ev.get("f22_last_says_disabled") is True
         and not errors)
not_armed = (ev["kill_present"] and ev.get("kill_is_the_f22_stop") is True
             and o.get("exists") is True and o.get("has_experiment") is True and not errors)

state = "ARMED" if armed else ("NOT_ARMED" if not_armed else "INDETERMINATE")
print("F24_STATE: %s" % state)
if state == "ARMED":
    print("start_utc=%s" % (ev.get("start_pin") or "UNKNOWN -- the pin is missing; use the override's written_utc"))
print(json.dumps(ev, indent=2, sort_keys=True))
sys.exit({"ARMED": 0, "NOT_ARMED": 2}.get(state, 3))
PYV
EOS

set +e
OUT=$(bash "$RUNNER" "$PAYLOAD" 2>&1)
RC=$?
set -e
printf '%s\n' "$OUT"
case "$OUT" in
  *"F24_STATE: ARMED"*)     exit 0 ;;
  *"F24_STATE: NOT_ARMED"*) exit 2 ;;
  *"F24_STATE: INDETERMINATE"*) exit 3 ;;
esac
echo "F24_STATE: INDETERMINATE (the box did not answer; runner exit $RC -- the state is UNKNOWN, not unchanged)" >&2
exit 3
