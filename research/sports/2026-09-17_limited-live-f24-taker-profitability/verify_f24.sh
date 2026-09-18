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
# "there is no kill/live". The lane refuses every real order (ARM_STALE, nodes/risk/gate.stale_reason)
# when the override has expired -- the 168-hour expiry arm_f24.sh writes lands at the end of the very
# window this measures -- or when it no longer pins the running process's code tree or limits; and a
# lane that is dead, stopped, OOM-killed or running below LIMITED_LIVE places no orders either. All
# of those are checked. The lane's own board snapshot (Supervisor.write_board, one second old) states
# arm_stale / f22_enabled / mode outright and is the primary signal; the log is the fallback.
#
# THERE ARE MORE WAYS TO BE STOPPED THAN kill/live AND kill/all. nodes/risk/kill.py (59dd5ae) keeps
# FIVE scopes in ONE directory -- all, live, venue-<venue>, event-<event_id>, strategy-<version> --
# `active()` honours every one of them and `clearance.clear()` refuses each candidate they apply to.
# So this ENUMERATES /srv/janus/kill instead of testing two names: every file there that is not
# arming_override.json and not breaker.json is a kill switch, is reported by name with its reason,
# and prevents ARMED. A name that matches none of the five scopes is reported as UNRECOGNISED and
# still prevents ARMED -- fail closed; nothing in this directory is assumed harmless. (A directory
# entry that is not a regular file counts too: `_present()` tests `exists()`, so `active()` would
# honour it even though `any_present()` filters it out.)
#
# THE SAME DIRECTORY HOLDS breaker.json, WHICH IS NOT A KILL FILE AND STOPS MORE. Once the daily
# realised-loss breaker latches (nodes/risk/breaker.py) it stays latched across restarts, and
# `evaluate()` returns BREAKER_LATCHED straight from that file BEFORE any kill is latched -- so
# kill/live is never re-created, and `clearance.clear()` refuses every candidate for the rest of the
# window. Clearing kill/live does not lift it. It is read here, and a latch prevents ARMED.
#
# AND ENUMERATING STOP CAUSES IS STILL NOT ENOUGH, BECAUSE THE DEPLOYED CODE ALWAYS HAS ONE MORE
# THAT LEAVES NO FILE BEHIND. `breaker.evaluate()` also answers PNL_UNKNOWN while a single fill is
# still UNCONFIRMED: that refuses EVERY candidate for the rest of the UTC day, and writes nothing to
# the kill directory, nothing to breaker.json and no lane flag. Six more persistent gates in
# nodes/risk/clearance.py (BALANCE, BALANCE_UNCONFIRMED, FEE_SCHEDULE, the ledger's reservation
# refusals, GUARD_FAILED, ARM_STALE) are invisible in exactly the same way. Every round of this
# audit has found one more, so the enumeration itself is the defect.
#
# SO THE VERDICT NO LONGER RESTS ON FILES ALONE: IT ALSO RESTS ON WHAT THE LANE DID. `grid.refuse()`
# counts every refusal by (channel, code, league) and `TupleStore.refusal_counts()` flushes them to
# /srv/janus/tuples/tuples.sqlite on every report tick (both at 59dd5ae). The kill is then an
# OBSERVED refusal, not an inferred one, and so is PNL_UNKNOWN -- which arrives on the risk channel
# as code BREAKER. This reads the recent risk-channel rows, strictly read-only, and a blocking code
# in the newest tick prevents ARMED whatever the files say. The '[size] refused' channel is NOT
# read: its flags are contaminated by its q=100 rung, and it is not the channel that says the lane
# could not act at all.
#
# Prints the evidence as JSON, then two fixed-form lines, LAST and anchored, so that nothing the box
# echoes back can spoof them (the operator's own statement is deliberately NOT echoed here at all):
#   F24_START_PIN: <start_utc> | MISSING | MALFORMED
#   F24_STATE: ARMED          exit 0   real orders can be placed under the F24 override
#   F24_STATE: NOT_ARMED      exit 2   kill/live is the F22 stop and the ONLY switch, the breaker is
#                                      not latched, and the F22 override is untouched
#   F24_STATE: INDETERMINATE  exit 3   neither -- read the evidence before doing anything else
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
RUNNER=${F24_RUNNER:-$REPO/ops/box/run.sh}

read -r -d '' PAYLOAD <<'EOS' || true
set -u
sudo -u janus /opt/janus/.venv/bin/python3 - <<'PYV'
import json, os, sqlite3, subprocess, sys, time
from datetime import datetime, timezone

KILL_DIR = "/srv/janus/kill"
BREAKER = "/srv/janus/kill/breaker.json"
OVERRIDE = "/srv/janus/kill/arming_override.json"
NOT_A_KILL = ("arming_override.json", "breaker.json")   # kernel/paths: both live in KILL_ROOT
PIN = "/srv/janus/release-audit/f24_start_utc"
LOG = "/srv/janus/logs/live_stream.stdout.log"
BOARD_DEFAULT = "/srv/janus/board/board.json"
TUPLES = "/srv/janus/tuples/tuples.sqlite"              # kernel/paths.DB; opened ?mode=ro only
UNIT = "janus-live-stream"
F22_KILL_SHA = "d81bbfc267a235ca7f268e7317d77ee7e83c65f5263117590e4e86d1552b1636"
CAPS = {"stake_usd": 30.0, "max_contracts": 25.0, "day_notional_usd": 500.0}
LIVE_MODE = "LIMITED_LIVE"
AUTH = "override has no F22 experiment authority"      # entry_experiment.f22_activation, no experiment block
MARKER = "[f22] disabled: " + AUTH
BOARD_MAX_AGE_S = 120.0
REPORT_PERIOD_DEFAULT_S = 30.0                          # grid.py's --report-period argparse default
REFUSAL_WINDOW_S = 1200.0                               # ~20 min of risk-channel rows, REPORTED
REFUSAL_TICKS = 8                                       # at most this many report ticks of them
REFUSAL_ROW_CAP = 4000                                  # a bound for a SINGLE vCPU, never a filter

#: Codes that refuse EVERY candidate while they are in force, not one. Confirmed in
#: `git show 59dd5ae:nodes/risk/clearance.py` (clear(), in order), in grids/live_stream/grid.py's
#: own risk-channel refusals, and in nodes/risk/ledger.py's assess()/reserve().
#:   MODE, NO_CAPS, CLOCK_UNHEALTHY, FEE_SCHEDULE, VENUE_DISCONNECTED  -- clear(), lane-wide state
#:   KILL_SWITCH                                                       -- kill.active(), any scope
#:   BREAKER                     -- breaker.evaluate(): BREAKER_LATCHED *and* PNL_UNKNOWN, which is
#:                                  the traceless refusal this round exists for
#:   BALANCE, BALANCE_UNCONFIRMED                       -- clear(), only when sends_real_orders
#:   ARM_STALE, GUARD_FAILED, VENUE_GEOBLOCKED          -- grid._execute, before any plan
#:   MAX_EVENTS, TOTAL_CAPITAL, UNRESOLVED_EXPOSURE     -- ledger.assess(): the whole book, not this
#:                                  candidate; a stuck open reservation holds them shut
BLOCKING = ("ARM_STALE", "BALANCE", "BALANCE_UNCONFIRMED", "BREAKER", "CLOCK_UNHEALTHY",
            "FEE_SCHEDULE", "GUARD_FAILED", "KILL_SWITCH", "MAX_EVENTS", "MODE", "NO_CAPS",
            "TOTAL_CAPITAL", "UNRESOLVED_EXPOSURE", "VENUE_DISCONNECTED", "VENUE_GEOBLOCKED")

#: Ordinary per-candidate refusals. A healthy, trading lane prints these continuously, so NONE of
#: them may ever prevent ARMED. Each is a property of THIS candidate (its price, its quantity, its
#: event, this instant), and a different candidate in the same tick can still clear.
#:   MIN_PROFIT, MIN_RETURN, STALE_BOOK       -- this cover's price and this book's age
#:   CAP_STAKE, CAP_CONTRACTS, MAX_UNHEDGED   -- this quantity; the size ladder walks several
#:   CAP_DAY_NOTIONAL     -- spent + THIS stake; a smaller cover in the same tick still fits, so it
#:                           is quantity-dependent even though it tightens over a UTC day
#:   IN_FLIGHT, EVENT_IN_FLIGHT               -- single-flight, by design, while a cover executes
#:   HEDGE_DEPTH_CHANGED                      -- this hedge book, re-read before entry
#:   EVENT_NOTIONAL, LEAGUE_EXPOSURE, VENUE_CAPITAL, EMPTY_RESERVATION  -- scoped ledger limits
PER_CANDIDATE = ("CAP_CONTRACTS", "CAP_DAY_NOTIONAL", "CAP_STAKE", "EMPTY_RESERVATION",
                 "EVENT_IN_FLIGHT", "EVENT_NOTIONAL", "HEDGE_DEPTH_CHANGED", "IN_FLIGHT",
                 "LEAGUE_EXPOSURE", "MAX_UNHEDGED", "MIN_PROFIT", "MIN_RETURN", "STALE_BOOK",
                 "VENUE_CAPITAL")

#: THE RULE, AND WHY IT IS THIS ONE. It is emitted into the evidence as well as written here, so the
#: operator reads the rule they are being judged by rather than trusting a boolean.
#:   * Not "dominance". A share threshold would be a number nobody can defend, and the box's own
#:     figures show why: with the kill latched it recorded KILL_SWITCH 6084 against IN_FLIGHT 4111
#:     over two days, because a refused flight still briefly sets in_flight and every other candidate
#:     in that instant is counted IN_FLIGHT. The code that halted everything was 59% of the channel.
#:   * Not "any occurrence in the last N ticks" either. That is what would make this unusable: for
#:     the first minutes after an arm the recent ticks are full of the kill that was just archived.
#:   * ONE tick, the NEWEST. A cause that has been lifted stops producing rows on the next tick; one
#:     still in force reproduces on every tick. That is the whole discriminator, and it is why the
#:     older ticks are reported as history and decide nothing.
#:   * ONE occurrence in that tick is enough, because a blocking code refuses EVERY candidate while
#:     it is in force -- there is no such thing as one candidate refused KILL_SWITCH or BREAKER.
#:   * Bounded by freshness (5 report ticks) and by the start pin, so absence and pre-arm evidence
#:     are handled as absence rather than as either health or a stop.
THE_RULE = (
    "ANY blocking code in the NEWEST risk-channel report tick, not dominance. A blocking code "
    "refuses EVERY candidate while it is in force, so one occurrence already says the lane could "
    "not act -- and a share threshold could not be defended anyway: with the kill latched the box "
    "itself recorded KILL_SWITCH 6084 against IN_FLIGHT 4111 over two days, so the stop that halted "
    "everything was 59% of the channel. ONE tick, the newest, because a cause that has been lifted "
    "stops producing rows on the next tick while one still in force reproduces on every tick; older "
    "ticks are reported but decide nothing, which is what makes this safe to run seconds after the "
    "F22 kill is archived. It cannot fire on MIN_PROFIT, IN_FLIGHT, HEDGE_DEPTH_CHANGED, STALE_BOOK "
    "or the CAP_ family: those are per-candidate and a healthy lane prints them continuously. A "
    "code in neither list is UNCLASSIFIED and counts as blocking -- fail closed, exactly as an "
    "unrecognised file in the kill directory does.")


def refusal_class(code):
    """blocking / per_candidate / unclassified -- and unclassified fails closed."""
    if code in BLOCKING:
        return "blocking"
    if code in PER_CANDIDATE:
        return "per_candidate"
    return "unclassified"


def as_object(raw, what):
    """json.loads, but a bare scalar or a list is a NAMED probe error, never an AttributeError two
    lines later when something calls .get() on it. `touch`ed files are empty and mean {}."""
    d = json.loads(raw or "{}")
    if not isinstance(d, dict):
        raise ValueError("%s is JSON %s, not an object" % (what, type(d).__name__))
    return d

CLEARING_A_LATCHED_BREAKER = (
    "a latched breaker is cleared ONLY by LossBreaker.reset(by=<name>), and at 59dd5ae nothing "
    "under ops/ calls it -- only nodes/risk/tests/test_risk.py does. Deleting kill/live does not "
    "lift it either: evaluate() returns BREAKER_LATCHED from breaker.json before any kill latch, so "
    "the kill directory can look perfectly clean while every candidate is refused. This is a human "
    "decision, not a file to delete; F24 spec.yaml also makes a latch a STOP condition that ends "
    "the row rather than pausing it.")


def kill_scope(name):
    """Which of kill.py's five scopes this name is, or None -- and None fails closed."""
    if name in ("all", "live"):
        return name
    for prefix in ("venue-", "event-", "strategy-"):
        if name.startswith(prefix) and len(name) > len(prefix):
            return prefix[:-1]
    return None


ev = {}
errors = []

# EVERY switch in the directory, by name -- not two hardcoded ones. kill.active() honours all five
# scopes; anything else here is UNRECOGNISED and counts anyway, because nothing on this box can say
# what does or does not honour it.
switches = []
try:
    names = sorted(n for n in os.listdir(KILL_DIR) if n not in NOT_A_KILL)
except FileNotFoundError:
    names = []
except Exception as exc:                          # noqa: BLE001
    names = []
    errors.append("kill directory read: %s -- the switches are UNKNOWN, not absent" % exc)
for n in names:
    p = os.path.join(KILL_DIR, n)
    s = {"name": n, "scope": kill_scope(n), "is_file": os.path.isfile(p)}
    s["recognised"] = s["scope"] is not None
    if s["is_file"]:
        try:
            s["sha256"] = subprocess.run(["sha256sum", p], capture_output=True, text=True,
                                         check=True).stdout.split()[0]
        except Exception as exc:                  # noqa: BLE001 -- evidence, never a crash
            errors.append("kill switch %s sha: %s" % (n, exc))
        try:                                      # a `touch`ed switch is empty and still a switch
            d = as_object(open(p).read(), "kill switch %s" % n)
            s["reason"] = d.get("reason")
            s["latched_utc"] = d.get("latched_utc")
        except Exception as exc:                  # noqa: BLE001 -- no reason is not an error
            s["reason"] = None
            s["unparsed"] = "%s: %s" % (type(exc).__name__, exc)
    else:
        s["note"] = ("not a regular file: any_present() would not list it, but _present() tests "
                     "exists(), so active() honours it")
    switches.append(s)

ev["kill_switches"] = switches
ev["kill_switch_names"] = [s["name"] for s in switches]
ev["unrecognised_kill_files"] = [s["name"] for s in switches if not s["recognised"]]
# Only a RECOGNISED name can stop a trade: kill.active() tests "all", "live", "venue-<v>",
# "event-<id>" and "strategy-<version>" and consults nothing else. The live box's kill directory
# holds .guard-failure-*.lock and .legacy-incident-*.lock from the guard tooling (seen 2026-09-18),
# so gating on unrecognised names would pin this tool at INDETERMINATE for ever while proving
# nothing. They are reported above, and named in `why`, but they do not decide.
ev["recognised_kill_switch_names"] = [s["name"] for s in switches if s["recognised"]]
ev["kill_present"] = "live" in ev["kill_switch_names"]
ev["kill_all_present"] = "all" in ev["kill_switch_names"]
_live = None
for s in switches:
    if s["name"] == "live":
        _live = s
if _live is not None:
    ev["kill_sha256"] = _live.get("sha256")
    ev["kill_is_the_f22_stop"] = _live.get("sha256") == F22_KILL_SHA
    ev["kill_reason"] = _live.get("reason")

# breaker.json is not a kill file and it stops more than one. LossBreaker._load reads it exactly
# this way, and evaluate() answers BREAKER_LATCHED from it before any kill switch is consulted.
br = {"path": BREAKER, "present": os.path.exists(BREAKER)}
if br["present"]:
    try:
        d = as_object(open(BREAKER).read(), "breaker.json")
        br["latched"] = bool(d.get("latched"))
        br["reason"] = d.get("reason")
        br["latched_utc"] = d.get("latched_utc")
        if br["latched_utc"] is not None:         # its own try: a bad stamp must not flip the latch
            try:
                br["latched_utc_iso"] = datetime.fromtimestamp(
                    float(br["latched_utc"]), timezone.utc).isoformat()
            except Exception as exc:              # noqa: BLE001
                br["latched_utc_iso"] = "unreadable (%s)" % type(exc).__name__
    except Exception as exc:                      # noqa: BLE001
        br["latched"] = None
        errors.append("breaker read: %s: %s -- an unreadable, half-written or malformed breaker "
                      "state is treated as latched" % (type(exc).__name__, exc))
else:
    br["latched"] = False
br["stops_the_lane"] = br["latched"] is not False
if br["stops_the_lane"]:
    br["how_to_clear"] = CLEARING_A_LATCHED_BREAKER
ev["breaker"] = br

try:
    raw = open(OVERRIDE).read()
    if not raw.strip():
        # ops/arming_override.py truncates in place (arm_f24.sh copies the file aside for exactly
        # this reason), so a 0-byte override is a half-written one, not an override with no terms.
        raise ValueError("arming_override.json is empty: the writer truncates in place, so this is "
                         "a half-written file and not an override")
    d = as_object(raw, "arming_override.json")
    caps = d.get("caps")
    caps = caps if isinstance(caps, dict) else {}
    statement = str(d.get("operator_statement") or "")
    o = {
        "exists": True, "mode": d.get("mode"), "caps": caps,
        "has_experiment": bool(d.get("experiment")),
        "experiment_row": (d.get("experiment") or {}).get("row_id") if isinstance(d.get("experiment"), dict) else None,
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
    errors.append("override read: %s: %s -- an unreadable, half-written or malformed override "
                  "proves nothing about what authorises the lane" % (type(exc).__name__, exc))

try:
    ev["start_pin"] = open(PIN).read().strip()
except FileNotFoundError:
    ev["start_pin"] = None
except Exception as exc:                          # noqa: BLE001
    ev["start_pin"] = None
    errors.append("start pin read: %s" % exc)

# The lane process itself. `systemctl is-active` was already collected here before this version and
# then ignored by the verdict: a dead, stopped, OOM-killed or paper-mode lane read ARMED.
lane = {"active": None, "main_pid": None, "mode": None, "board_path": BOARD_DEFAULT,
        "report_period_s": REPORT_PERIOD_DEFAULT_S}
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
        # --report-period is read for the same reason --board is: every bound below is measured in
        # report ticks, and the lane's own period is the only honest unit for them.
        for flag, key in (("--mode", "mode"), ("--board", "board_path"),
                          ("--report-period", "report_period_s")):
            if a == flag and i + 1 < len(argv):
                lane[key] = argv[i + 1]
            elif a.startswith(flag + "="):
                lane[key] = a.split("=", 1)[1]
except Exception as exc:                          # noqa: BLE001 -- a dead lane has no /proc entry; evidence, not an error
    lane["proc_error"] = "%s: %s" % (type(exc).__name__, exc)
try:
    lane["report_period_s"] = float(lane["report_period_s"])
except Exception:                                 # noqa: BLE001 -- an unparsable period is the default
    lane["report_period_s"] = REPORT_PERIOD_DEFAULT_S
PERIOD = lane["report_period_s"] if 1.0 <= lane["report_period_s"] <= 600.0 else REPORT_PERIOD_DEFAULT_S
#: How old the DECIDING tick may be: five report ticks. Older than that it describes an earlier
#: state of the box, not this one, and absence is handled as absence rather than as health.
REFUSAL_FRESH_S = 5.0 * PERIOD
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
    b = as_object(open(lane["board_path"]).read(), "board.json")
    board["present"] = True
    board["age_s"] = round(time.time() - float(b["as_of"]), 1)
    board["fresh"] = -5.0 <= board["age_s"] <= BOARD_MAX_AGE_S
    board["arm_stale"] = b.get("arm_stale")
    board["f22_enabled"] = b.get("f22_enabled")
    board["f22_authority"] = b.get("f22_authority")
    board["mode"] = b.get("mode")
    # Collected since the first version and thrown away by every verdict until now. A STALLED loop
    # means on_report_tick's probe overshot max_loop_lag_s: every poller is halted LOOP_STALLED and
    # the frames read during it carry the lane's own delay as the venue's skew (L111), so nothing is
    # priced and nothing can be entered. Both venue sockets down is the same answer by another
    # route: clear() refuses VENUE_DISCONNECTED and every cover needs a leg on each venue.
    board["stalled"] = b.get("stalled")
    board["loop_lag_s"] = b.get("loop_lag_s")
    board["sockets"] = b.get("sockets") if isinstance(b.get("sockets"), dict) else None
    if board["fresh"]:
        snap = b
except FileNotFoundError:
    board["why"] = "no board file"
except Exception as exc:                          # noqa: BLE001
    board["why"] = "unreadable or malformed: %s: %s" % (type(exc).__name__, exc)
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

ev["board_is_fresh"] = snap is not None
if snap is not None:
    ev["arm_source"] = "board"
    ev["arm_is_stale"] = bool(snap.get("arm_stale"))
    ev["f22_is_disabled_on_the_f24_authority"] = (
        snap.get("f22_enabled") is False and str(snap.get("f22_authority")) == AUTH)
    ev["board_mode_is_the_capital_risking_mode"] = str(snap.get("mode")) == LIVE_MODE
    ev["loop_is_stalled"] = bool(snap.get("stalled"))
    ev["loop_lag_s"] = snap.get("loop_lag_s")
    socks = snap.get("sockets") if isinstance(snap.get("sockets"), dict) else {}
    ev["venue_sockets"] = {str(k): bool(v.get("connected")) if isinstance(v, dict) else None
                           for k, v in socks.items()}
    # NOT "both connected": a single venue's reconnect is routine on this lane (HEARTBEAT_LOST
    # dominates its flapping), and demanding both would read INDETERMINATE several times an hour on
    # a box that is trading. No socket up at all -- or a board carrying no socket block, which is a
    # lane with neither stream -- is the state in which nothing can be priced or hedged.
    # EVERY venue socket, not any: a cover is two legs, so one venue down means no cover can
    # clear at all. Usually transient (reconnects are routine), which is why this reads
    # INDETERMINATE -- "look again in a minute" -- and never NOT_ARMED.
    ev["every_venue_socket_is_up"] = bool(ev["venue_sockets"]) and all(ev["venue_sockets"].values())
elif "last_arm_marker_is_stale" in log:
    ev["arm_source"] = "log"
    ev["arm_is_stale"] = log["last_arm_marker_is_stale"]
    ev["f22_is_disabled_on_the_f24_authority"] = log["f22_last_is_the_f24_authority"]
    ev["board_mode_is_the_capital_risking_mode"] = None      # only /proc can say, and it does, above
    # The log fallback still answers the arm question, and NOT_ARMED never depended on the board.
    # But it cannot answer the loop or the sockets at all, and a silent fall back to it is how a
    # stalled lane would read ARMED: these stay None, and ARMED below requires a FRESH board.
    ev["loop_is_stalled"] = None
    ev["venue_sockets"] = None
    ev["every_venue_socket_is_up"] = None
else:
    ev["arm_source"] = "none"
    ev["arm_is_stale"] = None
    ev["f22_is_disabled_on_the_f24_authority"] = None
    ev["board_mode_is_the_capital_risking_mode"] = None
    ev["loop_is_stalled"] = None
    ev["venue_sockets"] = None
    ev["every_venue_socket_is_up"] = None

# ── WHAT THE LANE DID, not which files exist ────────────────────────────────────────────────────
# One row per (channel, code, league) per report tick, written by TupleStore.refusal_counts() from
# grid.on_report_tick(). Strictly read-only: ?mode=ro cannot create the file, cannot create the
# table and cannot migrate anything, so a database that is absent or has never held a refusal is a
# named probe error here and never a write. The index refusal_counts_ts makes the seen_ts bound the
# scan; the GROUP BY collapses ~20 codes x 14 leagues per tick into one row per code per tick, and
# the LIMIT bounds the worst case for a SINGLE vCPU that is also running the live lane.
#
# The open itself is already proven on this box: arm_f24.sh's own quiet check opens this same file
# with this same URI, as this same `sudo -u janus` user, and it gated the 2026-09-17 pre-flight
# read. That matters because the lane holds the file in WAL mode, where a read-only connection still
# needs the -shm wal-index -- which the janus user owns. A different user would fail here, and would
# fail as a NAMED probe error that refuses ARMED rather than as a silent fall back to file evidence.
ref = {"path": TUPLES, "channel": "risk", "window_s": REFUSAL_WINDOW_S, "ticks_kept": REFUSAL_TICKS,
       "deciding_tick_max_age_s": REFUSAL_FRESH_S, "report_period_s": PERIOD, "rule": THE_RULE}
rows, con, blocking, t_now = [], None, [], time.time()
try:
    con = sqlite3.connect("file:%s?mode=ro" % TUPLES, uri=True, timeout=5.0)
    rows = con.execute(
        "SELECT seen_ts, code, SUM(n) FROM refusal_counts "
        "WHERE seen_ts >= ? AND seen_ts <= ? AND channel = ? "
        "GROUP BY seen_ts, code ORDER BY seen_ts DESC LIMIT ?",
        (t_now - REFUSAL_WINDOW_S, t_now + 5.0, "risk", REFUSAL_ROW_CAP)).fetchall()
except Exception as exc:                          # noqa: BLE001 -- a named probe error, never a crash
    ref["error"] = "%s: %s" % (type(exc).__name__, exc)
if con is not None:
    try:
        con.close()
    except Exception:                             # noqa: BLE001
        pass

if "error" not in ref:
    ticks = sorted({float(r[0]) for r in rows}, reverse=True)[:REFUSAL_TICKS]
    kept = set(ticks)
    counts, newest = {}, {}
    for ts, code, n in rows:
        if float(ts) in kept:
            counts[str(code)] = counts.get(str(code), 0) + int(n)
        if ticks and float(ts) == ticks[0]:
            newest[str(code)] = newest.get(str(code), 0) + int(n)
    ref["rows_read"] = len(rows)
    ref["row_cap_hit"] = len(rows) >= REFUSAL_ROW_CAP
    ref["ticks_seen"] = len(ticks)
    ref["counts_over_the_kept_ticks"] = counts
    ref["newest_tick_utc"] = ticks[0] if ticks else None
    ref["newest_tick_age_s"] = round(t_now - ticks[0], 1) if ticks else None
    ref["newest_tick_counts"] = newest
    blocking = sorted(((c, n) for c, n in newest.items() if refusal_class(c) != "per_candidate"),
                      key=lambda cn: (-cn[1], cn[0]))
    ref["blocking_in_the_newest_tick"] = [
        {"code": c, "n": n, "class": refusal_class(c), "age_s": ref["newest_tick_age_s"]}
        for c, n in blocking]

    # A tick whose report period of counting began BEFORE the F24 start pin covers the window in
    # which the F22 kill was still in place, so its KILL_SWITCH rows describe the state F24 was
    # armed OUT OF. arm_f24.sh persists the pin immediately after it archives the kill, which is why
    # it is the boundary: without this, verify_f24.sh would read INDETERMINATE for the first two
    # minutes of every successful arm, on evidence from before the arm. A missing, malformed or
    # future-dated pin leaves no boundary and every fresh tick decides -- this boundary is the ONE
    # thing here that can suppress evidence, so it fails closed in every direction.
    floor = None
    try:
        floor = float(ev["start_pin"]) + PERIOD
        if floor > t_now + PERIOD:
            ref["pin_is_in_the_future"] = ev["start_pin"]
            floor = None
    except Exception:                             # noqa: BLE001 -- no pin, or not a number
        floor = None
    ref["ticks_before_this_are_pre_arm"] = floor

    if not ticks:
        ref["lane_could_act"] = None
        ref["why"] = ("no risk-channel refusal at all in the last %.0f s. A quiet slate, or a lane "
                      "with no live poller, produces none: this is ABSENCE OF EVIDENCE and it is "
                      "not evidence that the lane can trade. Nothing here can raise ARMED on its "
                      "own; the file probes above are the only evidence in this case."
                      % REFUSAL_WINDOW_S)
    elif ref["newest_tick_age_s"] > REFUSAL_FRESH_S:
        ref["lane_could_act"] = None
        ref["why"] = ("the newest risk-channel refusal is %.0fs old (bound %.0fs = 5 report ticks). "
                      "It describes an earlier state of the box, not this one. ABSENCE OF EVIDENCE, "
                      "not health." % (ref["newest_tick_age_s"], REFUSAL_FRESH_S))
    elif floor is not None and ticks[0] < floor:
        ref["lane_could_act"] = None
        ref["why"] = ("the newest risk-channel tick (%.0fs old) began before the F24 start pin at "
                      "%s, so it counts refusals from while the F22 kill was still in place. It "
                      "says nothing about the armed lane. ABSENCE OF EVIDENCE, not health."
                      % (ref["newest_tick_age_s"], ev["start_pin"]))
    elif blocking:
        ref["lane_could_act"] = False
        ref["why"] = ("the lane's newest report tick, %.0fs ago, refused with %s -- a code that "
                      "blocks EVERY candidate, not one. The lane was not trading %.0fs ago, "
                      "whatever the files above say."
                      % (ref["newest_tick_age_s"],
                         ", ".join("%s x%d (%s)" % (c, n, refusal_class(c)) for c, n in blocking),
                         ref["newest_tick_age_s"]))
    else:
        ref["lane_could_act"] = True
        ref["why"] = ("the lane's newest report tick, %.0fs ago, refused only per-candidate: %s. "
                      "NOTE WHAT THIS DOES AND DOES NOT PROVE: MIN_PROFIT, the CAP_ family and "
                      "IN_FLIGHT are decided in grid._execute BEFORE nodes/risk.clear() is called, "
                      "so they prove only that GUARD_FAILED and ARM_STALE were not in force. They "
                      "do NOT prove the kill, the breaker or the balances were clear. Only the "
                      "False value of this field decides anything below."
                      % (ref["newest_tick_age_s"],
                         ", ".join("%s x%d" % (c, n) for c, n in sorted(newest.items()))))
else:
    ref["lane_could_act"] = None
    ref["why"] = ("the lane's own refusal record could not be read, so the ONLY evidence left is "
                  "which files exist -- which is exactly the evidence three rounds of this audit "
                  "found insufficient. ARMED is refused on that ground alone.")
ev["refusals"] = ref
ev["observed_lane_could_act"] = ref["lane_could_act"]
#: For NOT_ARMED only. In the untouched F22 state the kill IS latched, so KILL_SWITCH refusals are
#: expected and corroborate the files. ANY OTHER blocking code there is a second stop the operator
#: has not been told about -- a latched or PNL_UNKNOWN breaker, a failed guard, unconfirmed
#: balances -- and that is a different state with its own decision in it, not "untouched".
ev["observed_a_stop_beyond_the_kill"] = (
    None if ref["lane_could_act"] is not False else
    any(c != "KILL_SWITCH" for c, _n in blocking))

ev["errors"] = errors
o = ev.get("override") or {}
# ARMED is the header's promise and nothing weaker: NO switch of any scope in the kill directory,
# the breaker not latched, the override live and unexpired at the registered caps, the lane itself
# alive, in the capital-risking mode, and not stale -- AND THE LANE'S OWN RECORD OF WHY IT REFUSED
# NOT SAYING OTHERWISE. The last four conjuncts are the ones this round adds: an observed blocking
# refusal, an unreadable refusal record, a stalled loop and no venue socket each refuse ARMED, and
# the board must be FRESH rather than silently falling back to the log, because a stale board can
# answer neither the loop nor the sockets.
notes = []
if ev.get("loop_is_stalled") is True:
    notes.append("the board reports the supervisor loop STALLED at its last tick (lag %s s, bound "
                 "5 s): while that holds, clear() refuses every candidate CLOCK_UNHEALTHY. This box "
                 "runs at ~1.4 s and spikes past the bound intermittently, so it is usually a blip -- "
                 "but if it persists the newest refusal tick says CLOCK_UNHEALTHY and the verdict "
                 "below is not ARMED." % ev.get("loop_lag_s"))
if ev.get("every_venue_socket_is_up") is False:
    notes.append("a venue socket is down right now (%s): a cover is two legs, so none can clear "
                 "while that lasts. Reconnects are routine; a disconnect that persists shows up as "
                 "VENUE_DISCONNECTED in the refusal record and is decided there."
                 % ev.get("venue_sockets"))
ev["health_note"] = notes or None

armed = (not ev["recognised_kill_switch_names"] and ev["breaker"]["stops_the_lane"] is False
         and o.get("exists") is True
         and not o.get("has_experiment") and o.get("mode") == LIVE_MODE
         and o.get("caps_are_the_registered_ones") and o.get("not_expired") is True
         and lane["running"] and lane["is_the_capital_risking_mode"] is True
         and ev["board_is_fresh"] is True
         and ev["board_mode_is_the_capital_risking_mode"] is not False
         and ev["arm_is_stale"] is False
         and ev["f22_is_disabled_on_the_f24_authority"] is True
         # NOT gated on the board's INSTANTANEOUS health -- `stalled`, `loop_lag_s`, a socket
         # mid-reconnect. Measured on the box 2026-09-18: this single-vCPU lane runs at ~1.4 s loop
         # lag and spikes past its 5 s stall bound intermittently (one tick showed 10.0 s), so a
         # verdict gated on that flag would be unreachable or flapping, which is how a real stop
         # gets ignored. What decides instead is whether those conditions actually REFUSED anything:
         # CLOCK_UNHEALTHY and VENUE_DISCONNECTED are both in BLOCKING, so a stall or a disconnect
         # that is really shutting the lane out appears in the newest tick and fails the next line.
         # The raw flags stay in the evidence, and `health_note` names them for a human deciding.
         and ev["observed_lane_could_act"] is not False
         and "error" not in ev["refusals"]
         and not errors)
# NOT_ARMED is the untouched pre-F24 state and nothing else: kill/live is the F22 stop AND THE ONLY
# SWITCH in the directory, the breaker is clear, and the F22 override is still on disk. A second
# switch, an unrecognised file or a latched breaker is a different state with its own decision in
# it, so it reads INDETERMINATE -- "read the evidence" -- and never "the F22 stop, untouched".
# An OBSERVED stop that is not the kill belongs in that same list. It does not demand a readable
# refusal record: a missing observation cannot contradict "untouched", and in this state the kill
# is latched anyway, so clear() answers KILL_SWITCH before it ever reaches the breaker.
not_armed = (ev["recognised_kill_switch_names"] == ["live"] and ev.get("kill_is_the_f22_stop") is True
             and ev["breaker"]["stops_the_lane"] is False
             and ev["observed_a_stop_beyond_the_kill"] is not True
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
