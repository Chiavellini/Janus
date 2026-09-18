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
# ARMED here means exactly one thing: REAL ORDERS CAN BE PLACED RIGHT NOW. That is not the same as
# "there is no kill file". The lane refuses every real order (ARM_STALE, nodes/risk/gate.stale_reason)
# when the override has expired -- the 168-hour expiry arm_f24.sh writes lands at the end of the very
# window this measures -- or when it no longer pins the running process's code tree or limits; and a
# lane that is dead, stopped, OOM-killed or running below LIMITED_LIVE places no orders either. All
# of those are checked. The lane's own board snapshot (Supervisor.write_board, one second old) states
# arm_stale / f22_enabled / mode outright and is the primary signal; the log is the fallback.
#
# Prints the evidence as JSON, then two fixed-form lines, LAST and anchored, so that nothing the box
# echoes back can spoof them (the operator's own statement is deliberately NOT echoed here at all):
#   F24_START_PIN: <start_utc> | MISSING | MALFORMED
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
import json, os, subprocess, sys, time
from datetime import datetime, timezone

KILL = "/srv/janus/kill/live"
KILL_ALL = "/srv/janus/kill/all"
OVERRIDE = "/srv/janus/kill/arming_override.json"
PIN = "/srv/janus/release-audit/f24_start_utc"
LOG = "/srv/janus/logs/live_stream.stdout.log"
BOARD_DEFAULT = "/srv/janus/board/board.json"
UNIT = "janus-live-stream"
F22_KILL_SHA = "d81bbfc267a235ca7f268e7317d77ee7e83c65f5263117590e4e86d1552b1636"
CAPS = {"stake_usd": 30.0, "max_contracts": 25.0, "day_notional_usd": 500.0}
LIVE_MODE = "LIMITED_LIVE"
AUTH = "override has no F22 experiment authority"      # entry_experiment.f22_activation, no experiment block
MARKER = "[f22] disabled: " + AUTH
BOARD_MAX_AGE_S = 120.0

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
    statement = str(d.get("operator_statement") or "")
    o = {
        "exists": True, "mode": d.get("mode"), "caps": caps,
        "has_experiment": bool(d.get("experiment")),
        "experiment_row": (d.get("experiment") or {}).get("row_id"),
        "expires_utc": d.get("expires_utc"), "signed_by": d.get("signed_by"),
        "written_utc": d.get("written_utc"), "runner_sha": d.get("runner_sha"),
        # The statement itself is NOT echoed: it is operator text that would travel back through this
        # transcript, and the verdict below is matched in it. Its digest identifies it without that.
        "statement_sha256": __import__("hashlib").sha256(statement.encode()).hexdigest(),
        "statement_length": len(statement),
        "caps_are_the_registered_ones": all(
            abs(float(caps.get(k, -1)) - v) < 1e-9 for k, v in CAPS.items()),
    }
    # The expiry, against the box's own clock. gate._expiry_ts parses it exactly this way, and
    # gate.stale_reason turns "seconds_left <= 0" into the ARM_STALE that refuses every real order.
    try:
        exp = datetime.fromisoformat(str(d["expires_utc"]).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
        o["seconds_left"] = round(exp - time.time(), 1)
        o["not_expired"] = o["seconds_left"] > 0.0
    except Exception as exc:                      # noqa: BLE001
        o["seconds_left"], o["not_expired"] = None, False
        o["expiry_error"] = "%s: %s" % (type(exc).__name__, exc)
    ev["override"] = o
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
    ev["start_pin"] = None
    errors.append("start pin read: %s" % exc)

# The lane process itself. `systemctl is-active` was already collected here before this version and
# then ignored by the verdict: a dead, stopped, OOM-killed or paper-mode lane read ARMED.
lane = {"active": None, "main_pid": None, "mode": None, "board_path": BOARD_DEFAULT}
try:
    lane["active"] = subprocess.run(["systemctl", "is-active", UNIT],
                                    capture_output=True, text=True).stdout.strip()
    lane["main_pid"] = subprocess.run(["systemctl", "show", "-p", "MainPID", "--value", UNIT],
                                      capture_output=True, text=True).stdout.strip()
except Exception as exc:                          # noqa: BLE001
    errors.append("systemctl: %s" % exc)
try:
    argv = open("/proc/%s/cmdline" % lane["main_pid"], "rb").read().decode("utf-8", "replace").split("\0")
    for i, a in enumerate(argv):
        for flag, key in (("--mode", "mode"), ("--board", "board_path")):
            if a == flag and i + 1 < len(argv):
                lane[key] = argv[i + 1]
            elif a.startswith(flag + "="):
                lane[key] = a.split("=", 1)[1]
except Exception as exc:                          # noqa: BLE001 -- a dead lane has no /proc entry; evidence, not an error
    lane["proc_error"] = "%s: %s" % (type(exc).__name__, exc)
lane["is_the_capital_risking_mode"] = lane["mode"] == LIVE_MODE
lane["running"] = lane["active"] == "active"
ev["lane"] = lane

# The authoritative artifact: the lane's own one-second snapshot. arm_stale / f22_enabled / mode as
# the running process sees them, with its own timestamp -- unambiguous where the log is not, because
# grid.check_arm prints its markers only on CHANGE and passes a stale reason through as the f22
# authority string ("[f22] disabled: override pins a different code tree (running ...)").
board = {"path": lane["board_path"], "present": False}
snap = None
try:
    b = json.load(open(lane["board_path"]))
    board["present"] = True
    board["age_s"] = round(time.time() - float(b["as_of"]), 1)
    board["fresh"] = -5.0 <= board["age_s"] <= BOARD_MAX_AGE_S
    board["arm_stale"] = b.get("arm_stale")
    board["f22_enabled"] = b.get("f22_enabled")
    board["f22_authority"] = b.get("f22_authority")
    board["mode"] = b.get("mode")
    if board["fresh"]:
        snap = b
except FileNotFoundError:
    board["why"] = "no board file"
except Exception as exc:                          # noqa: BLE001
    board["why"] = "unreadable: %s" % type(exc).__name__
ev["board"] = board

log = {}
try:
    lines = open(LOG, "rb").read().decode("utf-8", "replace").splitlines()
    f22 = [l for l in lines if "[f22] ENABLED" in l or "[f22] disabled" in l]
    log["last_f22_markers"] = [l[:160] for l in f22[-3:]]
    log["f22_last_is_the_f24_authority"] = bool(f22) and f22[-1].strip() == MARKER
    marks = [l for l in lines if "[arm] " in l]
    log["last_arm_markers"] = [l[:160] for l in marks[-2:]]
    # A healthy lane prints no "[arm] " line at all until it goes stale, and prints "override matches
    # again; real orders resume" when it recovers: no markers means not stale, not unknown.
    log["last_arm_marker_is_stale"] = bool(marks) and "[arm] STALE" in marks[-1]
except Exception as exc:                          # noqa: BLE001
    errors.append("log read: %s" % exc)
ev["log"] = log

if snap is not None:
    ev["arm_source"] = "board"
    ev["arm_is_stale"] = bool(snap.get("arm_stale"))
    ev["f22_is_disabled_on_the_f24_authority"] = (
        snap.get("f22_enabled") is False and str(snap.get("f22_authority")) == AUTH)
    ev["board_mode_is_the_capital_risking_mode"] = str(snap.get("mode")) == LIVE_MODE
elif "last_arm_marker_is_stale" in log:
    ev["arm_source"] = "log"
    ev["arm_is_stale"] = log["last_arm_marker_is_stale"]
    ev["f22_is_disabled_on_the_f24_authority"] = log["f22_last_is_the_f24_authority"]
    ev["board_mode_is_the_capital_risking_mode"] = None      # only /proc can say, and it does, above
else:
    ev["arm_source"] = "none"
    ev["arm_is_stale"] = None
    ev["f22_is_disabled_on_the_f24_authority"] = None
    ev["board_mode_is_the_capital_risking_mode"] = None

ev["errors"] = errors
o = ev.get("override") or {}
armed = (not ev["kill_present"] and not ev["kill_all_present"] and o.get("exists") is True
         and not o.get("has_experiment") and o.get("mode") == LIVE_MODE
         and o.get("caps_are_the_registered_ones") and o.get("not_expired") is True
         and lane["running"] and lane["is_the_capital_risking_mode"] is True
         and ev["board_mode_is_the_capital_risking_mode"] is not False
         and ev["arm_is_stale"] is False
         and ev["f22_is_disabled_on_the_f24_authority"] is True
         and not errors)
not_armed = (ev["kill_present"] and ev.get("kill_is_the_f22_stop") is True
             and o.get("exists") is True and o.get("has_experiment") is True and not errors)

state = "ARMED" if armed else ("NOT_ARMED" if not_armed else "INDETERMINATE")
print(json.dumps(ev, indent=2, sort_keys=True))
pin = ev.get("start_pin")
if pin is None:
    pin_line = "MISSING"
elif pin.replace(".", "", 1).isdigit():
    pin_line = pin
else:
    pin_line = "MALFORMED"
# Both verdict lines come LAST, whole, and in a fixed form. Everything above is evidence, and some of
# it is operator-supplied; only these two lines are read by a caller.
print("F24_START_PIN: %s" % pin_line)
print("F24_STATE: %s" % state)
sys.exit({"ARMED": 0, "NOT_ARMED": 2}.get(state, 3))
PYV
EOS

set +e
OUT=$(bash "$RUNNER" "$PAYLOAD" 2>&1)
RC=$?
set -e
printf '%s\n' "$OUT"
# Anchored, whole-line, and the LAST one the box printed -- never a substring of the transcript. If
# the box prints more than one distinct verdict, that is not a verdict, it is a contradiction.
VERDICTS=$(printf '%s\n' "$OUT" | grep -E '^F24_STATE: (ARMED|NOT_ARMED|INDETERMINATE)$' | sort -u || true)
case "$VERDICTS" in
  "F24_STATE: ARMED")           exit 0 ;;
  "F24_STATE: NOT_ARMED")       exit 2 ;;
  "F24_STATE: INDETERMINATE")   exit 3 ;;
esac
if [ -n "$VERDICTS" ]; then
  echo "F24_STATE: INDETERMINATE (the box returned more than one verdict line: $(printf '%s' "$VERDICTS" | tr '\n' ' ')-- the state is UNKNOWN, not unchanged)" >&2
else
  echo "F24_STATE: INDETERMINATE (the box did not answer; runner exit $RC -- the state is UNKNOWN, not unchanged)" >&2
fi
exit 3
