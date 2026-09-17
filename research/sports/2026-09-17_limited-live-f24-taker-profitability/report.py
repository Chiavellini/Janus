#!/usr/bin/env python3
"""F24 progress and verdict report. Read-only.

    python3 report.py <start_utc> [end_utc] [--include EXEC_ID ...] [--exclude EXEC_ID ...]

Reads `executions` and `execution_settlements` for LIMITED_LIVE executions started in [start, end],
and prints one compact JSON object: the funnel, realised net per settled cover and per COMPLETED UTC
day, the registered event-clustered interval, the loss-making covers, the row's live state (kill,
arming override, unresolved material flags) and the verdict F24's spec defines.

What it will NOT do, because spec.yaml says so:

  * score a settlement that is not a cover. The unit of observation is "an execution in RECONCILED
    state whose both legs filled" -- so a PARTIAL row (the hedge left naked contracts, a directional
    gamble) and an UNWOUND row (the protection layer's cost, nothing held) are counted and reported
    in `funnel.excluded_non_cover_settlements`, never in the realised net per cover;
  * count PAPER_EXECUTION (or any non-LIMITED_LIVE) rows as F24 real money;
  * project a $/day figure beyond what was observed: `net` reports realised net per completed UTC
    day, and the mean over completed days is null until at least one UTC day has completed;
  * report IN_PROGRESS while a stop condition has actually ended the row. The kill file, the arming
    override and the thirteen material safety flags are probed on every run, read-only;
  * hide a `--include` / `--exclude`: both lists and every scored cover id are echoed in the output;
  * run against a start_utc that disagrees with the one arming persisted. It refuses instead.

The $50 cumulative-loss rule is one of spec.yaml's `end` conditions, NOT a `stop_condition`: it ends
the row with the honest verdict LOSES_MONEY, not with "a safety condition fired".

Run it with an L141-window start/end first: it must reproduce L141's known totals before its F24
numbers are trusted.
"""
from __future__ import annotations

import json
import math
import os
import random
import sqlite3
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

#: The box's roots. Overridable for a test harness only; the deployed reader uses the defaults.
DATA_ROOT = os.environ.get("JANUS_DATA_ROOT", "/srv/janus")
CODE_ROOT = os.environ.get("JANUS_CODE_ROOT", "/opt/janus")
DB = f"{DATA_ROOT}/tuples/tuples.sqlite"
SCHEMA = "janus.f24.taker_profitability_report.v1"

# Registered in spec.yaml.
END_COVERS = 30
END_DAYS = 7
CUMULATIVE_LOSS_STOP_USD = 50.0
MIN_COVERS_FOR_VERDICT = 10
RESAMPLES = 10000
SEED = 170924

#: spec.yaml `arm`: F24 is a LIMITED_LIVE row. Nothing else is F24's real money.
ROW_MODE = "LIMITED_LIVE"
#: nodes/reconcile/settle_executions._split writes COVER only when every first-leg contract was
#: hedged; PARTIAL otherwise. nodes/execute/records.write_unwind_settlement writes UNWOUND.
COVER_KIND = "COVER"
RECONCILED_STATE = "RECONCILED"
#: States that mean contracts were bought, so an unsettled row here is a fill awaiting settlement.
FILLED_STATES = ("HEDGED", "SETTLED", "RECONCILED")

#: spec.yaml `limits`, as ops/arming_override.py records them.
REGISTERED_CAPS = {"stake_usd": 30.0, "max_contracts": 25.0, "day_notional_usd": 500.0}

#: The thirteen kinds arm_f24.sh's quiet check reads, in its order. Any unresolved row is
#: spec.yaml's "unresolved material safety flag" stop condition.
MATERIAL_FLAGS = (
    "ORDER_PERSISTENCE_FAILED", "POST_ONLY_PERSISTENCE_FAILED", "ORPHAN_FILL", "POSITION_MISMATCH",
    "PROTECT_FAILED", "EXEC_CRASHED", "ORDER_OVERFILL", "POST_ONLY_ROLE_VIOLATION", "UNHEDGED_POSITION",
    "RESERVATION_MISSING", "FEE_ABOVE_PIN", "F22_PERSISTENCE_FAILED", "GUARD_FAILED")

#: arm_f24.sh persists the start it printed here. A start_utc that disagrees is a typo or a stale
#: paste, and a verdict computed over the wrong window is worse than no verdict. This reader only
#: ever READS it: it does not create it, and its absence is a warning, not a failure.
def start_pin_path(data_root: str = DATA_ROOT) -> str:
    return os.path.join(data_root, "release-audit", "f24_start_utc")


START_PIN = start_pin_path()
START_PIN_TOLERANCE_S = 1.0


class StartMismatch(Exception):
    """The start_utc given disagrees with the one arming persisted. Refuse; do not report."""


# --------------------------------------------------------------------------------------- statistics


def clustered_interval(covers: list[dict]) -> dict | None:
    """Event-clustered percentile bootstrap of mean net per settled cover."""
    by_event: dict[str, list[float]] = defaultdict(list)
    for c in covers:
        by_event[c["event_id"]].append(c["realized_usd"])
    keys = sorted(by_event)
    if len(keys) < 2:
        return None
    rng = random.Random(SEED)
    means = []
    for _ in range(RESAMPLES):
        vals = [v for k in (rng.choice(keys) for _ in keys) for v in by_event[k]]
        means.append(statistics.fmean(vals))
    means.sort()

    def pct(p: float) -> float:
        return means[max(0, min(len(means) - 1, math.ceil(p * len(means)) - 1))]

    return {"events": len(keys), "resamples": RESAMPLES, "seed": SEED,
            "lower_95": round(pct(0.025), 6), "upper_95": round(pct(0.975), 6)}


def verdict(total: float, n: int, ci: dict | None, stopped: str | None,
            *, loss_end: bool = False) -> tuple[str, str]:
    """spec.yaml `verdicts`. STOP is reserved for a real `stop_conditions` entry.

    The $50 cumulative-loss rule is an `end`, not a stop condition, so a row that hits it reports
    the money it actually lost (LOSES_MONEY) -- and says so even under ten covers, because the
    dollars were real and INSUFFICIENT would read as "we learned nothing".
    """
    if stopped:
        return "STOP", stopped
    if loss_end and total < 0:
        return "LOSES_MONEY", (f"total realised net {total:+.5f} reached the "
                               f"${CUMULATIVE_LOSS_STOP_USD:.0f} cumulative-loss end")
    if n < MIN_COVERS_FOR_VERDICT:
        return "INSUFFICIENT", f"{n} settled covers < {MIN_COVERS_FOR_VERDICT}"
    if total < 0:
        return "LOSES_MONEY", f"total realised net {total:+.5f} < 0"
    if total > 0 and ci is not None and ci["lower_95"] > 0:
        return "MAKES_MONEY_PROVEN", f"total {total:+.5f} and 95% interval lower bound {ci['lower_95']:+.5f} > 0"
    if total > 0:
        return "MAKES_MONEY_NOT_PROVEN", f"total {total:+.5f} > 0 but the 95% interval includes zero"
    return "LOSES_MONEY", f"total realised net {total:+.5f} is not above zero"


# ------------------------------------------------------------------------------------ the start pin


def read_start_pin(path: str) -> dict:
    """What arming persisted, if anything. Reads; never writes and never creates the file."""
    out: dict = {"path": path, "present": False, "value": None, "error": None}
    try:
        if not os.path.exists(path):
            return out
        out["present"] = True
        out["value"] = float(open(path).read().strip())
    except (OSError, ValueError) as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["value"] = None
    return out


def check_start_pin(start: float, path: str) -> dict:
    """Refuse a start_utc that disagrees with the pinned one; warn loudly when it is absent."""
    pin = read_start_pin(path)
    if pin["value"] is not None and abs(float(start) - pin["value"]) > START_PIN_TOLERANCE_S:
        raise StartMismatch(
            f"start_utc {start!r} disagrees with the start arming persisted at {path} "
            f"({pin['value']!r}) by {abs(float(start) - pin['value']):.3f} s, more than "
            f"{START_PIN_TOLERANCE_S:g} s. Refusing: a verdict computed over the wrong window is "
            f"worse than no verdict. Use the pinned value, or correct the file by hand if IT is wrong.")
    if pin["present"] and pin["error"]:
        pin["warning"] = (f"the start pin {path} exists but could not be read ({pin['error']}); "
                          f"start_utc {start!r} was NOT verified against it")
    elif not pin["present"]:
        pin["warning"] = (f"NO start pin at {path}: start_utc {start!r} is UNVERIFIED. A mistyped or "
                          f"stale start silently moves the window; check it against the start_utc "
                          f"arming printed.")
    else:
        pin["warning"] = None
    return pin


# ------------------------------------------------------------------------------------- the row state


def _read_json_file(path: str) -> dict:
    text = open(path).read()
    return json.loads(text) if text.strip() else {}


def _parse_utc(text) -> float | None:
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


def probe_kill(kill_dir: str) -> dict:
    """The kill files, by presence and recorded reason. The loss breaker latches `live`."""
    out: dict = {"dir": kill_dir, "live_present": None, "all_present": None, "reasons": {}, "error": None}
    try:
        for name in ("live", "all"):
            path = os.path.join(kill_dir, name)
            present = os.path.exists(path)
            out[f"{name}_present"] = present
            if not present:
                continue
            try:
                out["reasons"][name] = _read_json_file(path).get("reason") or "no reason recorded"
            except (OSError, ValueError) as exc:
                out["reasons"][name] = f"unreadable ({type(exc).__name__})"
    except OSError as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def probe_override(path: str, *, now: float) -> dict:
    """The arming override: is it there, has it expired, and has anything about it changed."""
    out: dict = {"path": path, "present": None, "readable": None, "mode": None, "caps": None,
                 "caps_match_registered": None, "experiment": None, "expires_utc": None,
                 "expired": None, "error": None}
    try:
        out["present"] = os.path.exists(path)
    except OSError as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    if not out["present"]:
        return out
    try:
        d = _read_json_file(path)
    except (OSError, ValueError) as exc:
        out["readable"], out["error"] = False, f"{type(exc).__name__}: {exc}"
        return out
    out["readable"] = True
    out["mode"] = d.get("mode")
    out["caps"] = d.get("caps")
    out["experiment"] = d.get("experiment") or None
    out["expires_utc"] = d.get("expires_utc")
    expires = _parse_utc(d.get("expires_utc"))
    if expires is None:
        out["error"] = f"unparseable expires_utc {d.get('expires_utc')!r}"
    else:
        out["expired"] = expires <= now
    caps = d.get("caps") if isinstance(d.get("caps"), dict) else {}
    try:
        out["caps_match_registered"] = all(
            abs(float(caps[k]) - v) < 1e-9 for k, v in REGISTERED_CAPS.items() if k in caps
        ) and set(REGISTERED_CAPS) <= set(caps)
    except (TypeError, ValueError):
        out["caps_match_registered"] = False
    return out


def probe_flags(con, *, code_root: str, reader=None) -> dict:
    """Unresolved material safety flags, through the box's OWN reader.

    The resolution semantics (legacy boundary markers vs exact per-id acknowledgements) live in
    nodes/risk/flags.unresolved_flag_rows and must not be reimplemented here. Imported from
    `code_root` the way arm_f24.sh's quiet check does it.
    """
    out: dict = {"ok": False, "checked": list(MATERIAL_FLAGS), "unresolved": {}, "error": None}
    if reader is None:
        try:
            if os.path.isdir(code_root) and code_root not in sys.path:
                sys.path.insert(0, code_root)
            from nodes.risk.flags import unresolved_flag_rows as reader  # noqa: PLC0415
        except Exception as exc:                                        # noqa: BLE001 - degrade, never crash
            out["error"] = f"could not import nodes.risk.flags from {code_root}: {type(exc).__name__}: {exc}"
            return out
    try:
        counts = {f: len(reader(con, f)) for f in MATERIAL_FLAGS}
    except Exception as exc:                                            # noqa: BLE001 - degrade, never crash
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    out["unresolved"] = {k: v for k, v in counts.items() if v}
    out["ok"] = True
    return out


def row_state(con, *, now: float, data_root: str, code_root: str, flag_reader=None) -> dict:
    """Every stop/end condition the reader can observe, plus what it failed to observe.

    A probe that fails names itself in `probe_errors` and sets `conclusive` false. It never
    invents a stop, and it never lets the report claim a clean IN_PROGRESS in silence.
    """
    kill_dir = os.path.join(data_root, "kill")
    kill = probe_kill(kill_dir)
    override = probe_override(os.path.join(kill_dir, "arming_override.json"), now=now)
    flags = probe_flags(con, code_root=code_root, reader=flag_reader)

    stops: list[str] = []
    ends: list[str] = []
    errors: list[str] = []

    if kill["error"]:
        errors.append(f"kill: {kill['error']}")
    else:
        for name in ("live", "all"):
            if kill[f"{name}_present"]:
                stops.append(f"kill/{name} is present: {kill['reasons'].get(name)}")

    if override["present"] is None:
        errors.append(f"override: {override['error']}")
    elif override["present"] is False:
        stops.append(f"the arming override {override['path']} is gone")
    elif not override["readable"]:
        errors.append(f"override: {override['error']}")
    else:
        if override["experiment"]:
            stops.append("the arming override carries an experiment block; F24's arm is 'no experiment'")
        if override["mode"] != ROW_MODE:
            stops.append(f"the arming override's mode is {override['mode']!r}, not {ROW_MODE}")
        if override["caps_match_registered"] is False:
            stops.append(f"the arming override's caps {override['caps']!r} are not "
                         f"the registered {REGISTERED_CAPS}")
        if override["expired"]:
            # spec.yaml lists override expiry under `end`, and stop_conditions exempt it explicitly
            # ("any change to ... the override other than its expiry"). So it ends, it does not STOP.
            ends.append(f"the arming override expired at {override['expires_utc']}")
        elif override["expired"] is None:
            errors.append(f"override: {override['error']}")

    if not flags["ok"]:
        errors.append(f"flags: {flags['error']}")
    elif flags["unresolved"]:
        stops.append("unresolved material safety flag(s): "
                     + ", ".join(f"{k}x{v}" for k, v in sorted(flags["unresolved"].items())))

    return {"kill": kill, "override": override, "flags": flags, "stop_conditions": stops,
            "end_conditions": ends, "probe_errors": errors, "conclusive": not errors}


# ------------------------------------------------------------------------------------------- scoring


def _both_legs_filled(row) -> bool:
    return float(row["first_filled"] or 0.0) > 0.0 and float(row["hedge_filled"] or 0.0) > 0.0


def is_settled_cover(row: dict, s: dict | None) -> tuple[bool, str | None]:
    """spec.yaml's unit of observation: a RECONCILED execution whose BOTH legs filled, settled.

    Returns (is_cover, why_not). `kind` is settle_executions' own verdict on the split: COVER only
    when every first-leg contract was hedged. A NULL kind is a row written before that column
    shipped (one production row, 2026-09-05); those fall back to the same test on the fills.
    """
    if s is None or not s["released"] or s["realized_usd"] is None:
        return False, None
    if row["state"] != RECONCILED_STATE:
        return False, f"state {row['state']}, not {RECONCILED_STATE}"
    if not _both_legs_filled(row):
        return False, "a leg did not fill"
    kind = s["kind"]
    if kind is None:
        unhedged = float(row["first_filled"] or 0.0) - float(row["hedge_filled"] or 0.0)
        return (True, None) if unhedged <= 1e-9 else (False, "NULL kind and the hedge left naked contracts")
    if kind != COVER_KIND:
        return False, f"settlement kind {kind}"
    return True, None


def _completed_utc_days(start: float, stop_at: float) -> list[str]:
    """Every UTC calendar day lying WHOLLY inside the window. A partial day is not a day."""
    first, last = math.ceil(start / 86400.0), math.floor(stop_at / 86400.0)
    return [time.strftime("%Y-%m-%d", time.gmtime(d * 86400.0)) for d in range(first, max(first, last))]


_EXEC_COLUMNS = "execution_id, event_id, league, mode, state, started_utc, first_filled, hedge_filled"


def run(db: str, start: float, end: float | None = None, include=(), exclude=(), *,
        data_root: str = DATA_ROOT, code_root: str = CODE_ROOT, start_pin: str | None = None,
        now: float | None = None, flag_reader=None) -> dict:
    include, exclude = list(include), list(exclude)
    pin = check_start_pin(start, start_pin if start_pin is not None else start_pin_path(data_root))

    now = time.time() if now is None else float(now)
    stop_at = end if end is not None else now
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        f"SELECT {_EXEC_COLUMNS} FROM executions WHERE started_utc >= ? AND started_utc <= ?",
        (start, stop_at))]

    dropped_by_request = sorted({r["execution_id"] for r in rows} & set(exclude))
    rows = [r for r in rows if r["execution_id"] not in set(exclude)]
    have = {r["execution_id"] for r in rows}
    added_by_request = []
    for eid in include:
        if eid not in have:
            r = con.execute(f"SELECT {_EXEC_COLUMNS} FROM executions WHERE execution_id=?", (eid,)).fetchone()
            if r:
                rows.append(dict(r))
                added_by_request.append(eid)

    # F24 is a LIMITED_LIVE row. PAPER_EXECUTION lives in the same database -- and switching the
    # lane to PAPER_EXECUTION is the documented way back when the override expires -- so a paper
    # fill sitting inside the window must never be counted as the operator's real money.
    wrong_mode = [r for r in rows if r["mode"] != ROW_MODE]
    rows = [r for r in rows if r["mode"] == ROW_MODE]

    settle: dict[str, dict] = {}
    ids = [r["execution_id"] for r in rows]
    if ids:
        marks = ",".join("?" * len(ids))
        for s in con.execute(
                "SELECT execution_id, realized_usd, released, kind, settled_ts FROM execution_settlements "
                f"WHERE execution_id IN ({marks})", ids):
            settle[s["execution_id"]] = dict(s)

    covers, non_covers, unsettled_fills = [], [], []
    for r in rows:
        s = settle.get(r["execution_id"])
        scored, why_not = is_settled_cover(r, s)
        if scored:
            covers.append({"execution_id": r["execution_id"], "event_id": r["event_id"],
                           "league": r["league"], "kind": s["kind"],
                           "realized_usd": float(s["realized_usd"]), "settled_ts": s["settled_ts"]})
        elif why_not is not None:
            non_covers.append({"execution_id": r["execution_id"], "event_id": r["event_id"],
                               "state": r["state"], "kind": s["kind"], "excluded_because": why_not,
                               "realized_usd": float(s["realized_usd"])})
        elif r["state"] in FILLED_STATES:
            unsettled_fills.append(r["execution_id"])

    total = round(sum(c["realized_usd"] for c in covers), 6)
    by_day: dict[str, float] = defaultdict(float)
    for c in covers:
        by_day[time.strftime("%Y-%m-%d", time.gmtime(c["settled_ts"]))] += c["realized_usd"]
    ci = clustered_interval(covers)

    completed_days = _completed_utc_days(start, stop_at)
    net_by_completed = {d: round(by_day.get(d, 0.0), 6) for d in completed_days}
    elapsed_days = (stop_at - start) / 86400.0

    state = row_state(con, now=now, data_root=data_root, code_root=code_root, flag_reader=flag_reader)
    # A live probe describes the lane NOW. Applying it to a closed historical window (the L141
    # calibration run) would brand that window STOP for something that happened afterwards, so the
    # findings are still printed but only bind a window that runs to the present.
    applied = end is None or end >= now
    stopped = "; ".join(state["stop_conditions"]) if (applied and state["stop_conditions"]) else None

    loss_end = total <= -CUMULATIVE_LOSS_STOP_USD
    end_reasons = []
    if len(covers) >= END_COVERS:
        end_reasons.append(f"{len(covers)} settled covers reached the registered {END_COVERS}")
    if elapsed_days >= END_DAYS:
        end_reasons.append(f"{elapsed_days:.3f} elapsed days reached the registered {END_DAYS}")
    if loss_end:
        end_reasons.append(f"cumulative realised net {total:+.5f} reached the "
                           f"${CUMULATIVE_LOSS_STOP_USD:.0f} cumulative-loss end")
    if applied:
        end_reasons.extend(state["end_conditions"])
    ended = bool(end_reasons) or stopped is not None
    v, reason = verdict(total, len(covers), ci, stopped, loss_end=loss_end)

    warnings = []
    if pin.get("warning"):
        warnings.append(pin["warning"])
    for e in state["probe_errors"]:
        warnings.append(f"stop-condition probe incomplete -- {e}: this report CANNOT say no stop "
                        f"condition fired, only that it could not look")
    if state["stop_conditions"] and not applied:
        warnings.append("stop conditions are live on the box RIGHT NOW but were not applied to this "
                        "verdict, because an explicit end_utc in the past was given: "
                        + "; ".join(state["stop_conditions"]))
    if state["end_conditions"] and not applied:
        warnings.append("end conditions detected but not applied to this fixed-end window: "
                        + "; ".join(state["end_conditions"]))
    if not state["conclusive"] and stopped is None:
        reason += " (stop-condition probes were incomplete; see warnings)"

    return {
        "schema": SCHEMA,
        "window": {"start_utc": start, "end_utc": stop_at, "elapsed_days": round(elapsed_days, 3),
                   "completed_utc_days": completed_days, "start_pin": pin},
        "ended": ended,
        "end_reasons": end_reasons,
        "end_rule": {"covers": END_COVERS, "days": END_DAYS,
                     "cumulative_loss_end_usd": CUMULATIVE_LOSS_STOP_USD},
        "selection": {"mode": ROW_MODE,
                      "include": include, "exclude": exclude,
                      "included_out_of_window": sorted(added_by_request),
                      "excluded_by_request": dropped_by_request,
                      "scored_cover_execution_ids": sorted(c["execution_id"] for c in covers)},
        "funnel": {"executions": len(rows),
                   "by_state": dict(sorted(Counter(r["state"] for r in rows).items())),
                   "settled_covers": len(covers),
                   "filled_not_yet_settled": len(unsettled_fills),
                   "released_settlement_rows": len(covers) + len(non_covers),
                   "excluded_non_cover_settlements": {
                       "count": len(non_covers),
                       "realized_usd": round(sum(n["realized_usd"] for n in non_covers), 6),
                       "by_kind": dict(sorted(Counter(str(n["kind"]) for n in non_covers).items())),
                       "rows": sorted(non_covers, key=lambda n: n["execution_id"])},
                   "excluded_wrong_mode": {
                       "count": len(wrong_mode),
                       "by_mode": dict(sorted(Counter(r["mode"] for r in wrong_mode).items())),
                       "execution_ids": sorted(r["execution_id"] for r in wrong_mode)}},
        "net": {"total_usd": total,
                "per_settled_cover_usd": (round(total / len(covers), 6) if covers else None),
                "by_settle_day_usd": {k: round(v, 6) for k, v in sorted(by_day.items())},
                "by_completed_utc_day_usd": net_by_completed,
                "observed_mean_usd_per_completed_utc_day":
                    (round(sum(net_by_completed.values()) / len(net_by_completed), 6)
                     if net_by_completed else None)},
        "interval_net_per_cover": ci,
        "loss_making_covers": sorted(
            [c for c in covers if c["realized_usd"] < 0], key=lambda c: c["realized_usd"]),
        "row_state": {"stop_conditions_applied": applied,
                      "stop_conditions": state["stop_conditions"],
                      "end_conditions": state["end_conditions"],
                      "probe_errors": state["probe_errors"],
                      "conclusive": state["conclusive"],
                      "kill": state["kill"], "override": state["override"], "flags": state["flags"]},
        "verdict": v if ended else f"IN_PROGRESS (would be {v})",
        "verdict_reason": reason,
        "warnings": warnings,
        "note": ("Only a verdict with ended=true is F24's result. An unsettled fill is not scored, and "
                 "neither is a PARTIAL or UNWOUND settlement: those are in "
                 "funnel.excluded_non_cover_settlements with their dollars."),
    }


def _parse_argv(args: list[str]) -> tuple[list[str], list[str], list[str]]:
    inc, exc, pos = [], [], []
    i = 0
    while i < len(args):
        if args[i] in ("--include", "--exclude"):
            if i + 1 >= len(args):
                raise SystemExit(f"{args[i]} needs an execution id")
            (inc if args[i] == "--include" else exc).append(args[i + 1])
            i += 2
        elif args[i].startswith("-"):
            raise SystemExit(f"unknown option {args[i]} "
                             "(usage: report.py <start_utc> [end_utc] [--include ID ...] [--exclude ID ...])")
        else:
            pos.append(args[i])
            i += 1
    return inc, exc, pos


if __name__ == "__main__":
    inc, exc, pos = _parse_argv(sys.argv[1:])
    if not pos or len(pos) > 2:
        raise SystemExit("usage: report.py <start_utc> [end_utc] [--include ID ...] [--exclude ID ...]")
    start = float(pos[0])
    end = float(pos[1]) if len(pos) > 1 else None
    try:
        out = run(DB, start, end, inc, exc)
    except StartMismatch as exc_:
        print(f"F24_REPORT_REFUSED: {exc_}", file=sys.stderr)
        raise SystemExit(3)
    print(json.dumps(out, sort_keys=True, separators=(",", ":")))
