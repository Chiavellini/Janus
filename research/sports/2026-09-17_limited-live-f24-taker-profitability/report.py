#!/usr/bin/env python3
"""F24 progress and verdict report. Read-only.

    python3 report.py <start_utc> [end_utc] [--include EXEC_ID ...] [--exclude EXEC_ID ...]

Reads `executions` and `execution_settlements` for LIMITED_LIVE executions started in [start, end],
and prints one compact JSON object: the funnel, the two money figures below, the registered
event-clustered interval, the loss-making covers, what is still open, the row's live state (kill,
arming override, unresolved material flags) and the verdict F24's spec defines.

TWO MONEY FIGURES, AND THEY ARE NOT THE SAME NUMBER
---------------------------------------------------
`net.settled_covers_only.total_usd` is the VERDICT STATISTIC. spec.yaml's unit of observation is
"an execution in RECONCILED state whose both legs filled", so only those covers feed the total per
cover, the bootstrap interval and MAKES_MONEY_*. A PARTIAL row (the IOC hedge filled in part and
left naked contracts riding to settlement) and an UNWOUND row (the protection layer's cost) are not
covers and are not scored as covers.

`net.all_in_realised.total_usd` is the MONEY. It is every realised dollar in the window -- covers,
PARTIAL, UNWOUND, and any settlement row whose capital was not released -- because those dollars
are the operator's, the box's own daily breaker counts them (nodes/execute/guard.fills_today sums
`execution_settlements` by settled day with no filter on kind or release), and F24's $50 cumulative
end is about money lost, not about the unit of observation. THIS is the figure the $50 end is
decided on, the figure the daily read is about, and the figure `headline` leads with.

What it will NOT do, because spec.yaml says so:

  * score a settlement that is not a cover; those are counted, with their dollars, in
    `funnel.excluded_non_cover_settlements` AND in `net.all_in_realised`;
  * count PAPER_EXECUTION (or any non-LIMITED_LIVE) rows as F24 real money;
  * project a $/day figure beyond what was observed: the per-day figures are per COMPLETED UTC day,
    and the mean over completed days is null until at least one UTC day has completed;
  * end the row on an unsettled cover ("An unsettled cover is not scored until it settles; the row
    cannot end on an unsettled one"). When the 30-cover / 7-day / override-expiry end arrives with
    filled executions still unsettled, the row reports AWAITING_SETTLEMENT with the count and stake
    of what is outstanding and withholds the verdict. The $50 end and a real stop condition are the
    exceptions: both are about harm already done, so neither waits;
  * score covers the lane traded past the registered 30-cover end. Nothing in the lane stops at 30,
    so the scored set is truncated deterministically at the registered end (`registered_end`), and
    the excluded covers are listed with their dollars -- which stay in `net.all_in_realised`;
  * report IN_PROGRESS while a stop condition has actually ended the row. The kill file, the arming
    override and the thirteen material safety flags are probed on every run, read-only;
  * hide a `--include` / `--exclude`: both lists and every scored cover id are echoed in the output;
  * run against a start_utc that disagrees with the one arming persisted. It refuses instead;
  * describe the $25 daily breaker as a cap on a day's loss. It is not one: see
    `daily_loss_breaker.what_it_actually_bounds`.

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

#: spec.yaml `limits.max_daily_realized_loss_usd`. What it actually does is below; the report must
#: never imply more than this, because the operator's plan rests on the daily read, not on the box.
DAILY_BREAKER_USD = 25.0
DAILY_BREAKER_TRUTH = (
    "NOT a cap on a day's loss. nodes/risk/breaker.py at 59dd5ae latches only when the realised PnL "
    "of rows ALREADY SETTLED on the current UTC day reaches -25.00, and it is consulted at the "
    "PRE-TRADE gate: it refuses to start NEW entries and latches kill/live, and it never closes, "
    "caps or recalls a position already held. Contracts bought and not yet settled contribute "
    "nothing to it -- sports positions usually settle hours later and often on the NEXT UTC day -- "
    "so a day's LOSS is not bounded at 25.00; only that day's ALREADY-SETTLED loss is. A 7-day "
    "window touches EIGHT UTC days, so the arithmetic bound is eight daily allowances plus whatever "
    "is still open when it finally stops. The $50 end and the 30-cover end are enforced by nobody "
    "on the box: they are real only because a human reads this report and stops the test.")

#: spec.yaml `arm`: F24 is a LIMITED_LIVE row. Nothing else is F24's real money.
ROW_MODE = "LIMITED_LIVE"
#: nodes/reconcile/settle_executions._split writes COVER only when every first-leg contract was
#: hedged; PARTIAL otherwise. nodes/execute/records.write_unwind_settlement writes UNWOUND.
COVER_KIND = "COVER"
RECONCILED_STATE = "RECONCILED"
#: apply_settlements stamps ONE settled_ts per pass, so several covers routinely share it. The
#: scored set is truncated at the registered end, so the order must be total and stable.
COVER_ORDER = "settled_ts ascending, then execution_id ascending"

#: spec.yaml `limits`, as ops/arming_override.py records them.
REGISTERED_CAPS = {"stake_usd": 30.0, "max_contracts": 25.0, "day_notional_usd": 500.0}

#: The thirteen kinds arm_f24.sh's quiet check reads, in its order. Any unresolved row is
#: spec.yaml's "unresolved material safety flag" stop condition.
MATERIAL_FLAGS = (
    "ORDER_PERSISTENCE_FAILED", "POST_ONLY_PERSISTENCE_FAILED", "ORPHAN_FILL", "POSITION_MISMATCH",
    "PROTECT_FAILED", "EXEC_CRASHED", "ORDER_OVERFILL", "POST_ONLY_ROLE_VIOLATION", "UNHEDGED_POSITION",
    "RESERVATION_MISSING", "FEE_ABOVE_PIN", "F22_PERSISTENCE_FAILED", "GUARD_FAILED")

#: Columns the reader cannot work without, and columns it uses to price what is still open. The
#: optional ones arrived by ALTER (records._LATER_COLUMNS); a table without one is reported as a
#: named warning and an understated stake, never as a crash.
REQUIRED_EXEC_COLUMNS = ("execution_id", "event_id", "league", "mode", "state", "started_utc",
                         "first_filled", "hedge_filled")
OPTIONAL_EXEC_COLUMNS = ("first_avg_price", "hedge_avg_price", "first_unwound", "hedge_unwound")
#: (contracts bought, contracts sold back by the protection layer, average price paid).
_LEGS = (("first_filled", "first_unwound", "first_avg_price"),
         ("hedge_filled", "hedge_unwound", "hedge_avg_price"))

#: How many execution ids go into one `... IN (?,?,...)` lookup. `executions` has no index on
#: started_utc, so the window scan is forced and cannot be helped from a mode=ro connection -- but
#: the settlements lookup binds ONE variable per execution in the window, and a 7-day window holds
#: every attempt, not just the covers. SQLITE_MAX_VARIABLE_NUMBER is 999 on SQLite before 3.32, so
#: an unchunked list would turn the operator's daily read into `too many SQL variables` partway
#: through a live money test. Chunking changes no result; it only bounds the bind list.
_ID_CHUNK = 400


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
            *, loss_end: bool = False, all_in_total: float | None = None) -> tuple[str, str]:
    """spec.yaml `verdicts`. STOP is reserved for a real `stop_conditions` entry.

    `total` is the net over SCORED SETTLED COVERS -- the unit of observation, and the only thing the
    interval and MAKES_MONEY_* may rest on. `all_in_total` is every realised dollar in the window
    (covers plus PARTIAL, UNWOUND and unreleased settlements); it defaults to `total` for callers
    that have no non-cover money. The two are separated on purpose: the verdict statistic is about
    the mechanism, the all-in figure is about the operator's money, and a row whose covers made
    $2 while its partials lost $40 lost money and must say so.

    The $50 cumulative-loss rule is an `end`, not a stop condition, so a row that hits it reports
    the money it actually lost (LOSES_MONEY) -- and says so even under ten covers, because the
    dollars were real and INSUFFICIENT would read as "we learned nothing".
    """
    all_in = float(total if all_in_total is None else all_in_total)
    gap = (f" (settled covers alone: {total:+.5f})" if abs(all_in - total) > 5e-7 else "")
    if stopped:
        return "STOP", stopped
    if loss_end and all_in < 0:
        return "LOSES_MONEY", (f"all-in realised net {all_in:+.5f} reached the "
                               f"${CUMULATIVE_LOSS_STOP_USD:.0f} cumulative-loss end{gap}")
    if n < MIN_COVERS_FOR_VERDICT:
        return "INSUFFICIENT", (f"{n} settled covers < {MIN_COVERS_FOR_VERDICT}; all-in realised net "
                                f"so far {all_in:+.5f}{gap}")
    if total < 0:
        return "LOSES_MONEY", f"net over settled covers {total:+.5f} < 0 (all-in realised {all_in:+.5f})"
    if all_in <= 0:
        return "LOSES_MONEY", (f"settled covers total {total:+.5f}, but the all-in realised net is "
                               f"{all_in:+.5f}: the non-cover settlements took it back")
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
    """The kill files, by presence and recorded reason.

    The daily loss breaker latches `live` when it fires -- but see DAILY_BREAKER_TRUTH for what
    makes it fire: already-settled losses only, checked before a new entry.
    """
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

    Returns (is_cover, why_not). `why_not` is None only when there is no realised money at all to
    account for; every settlement row that exists gets a reason, so its dollars are always visible
    somewhere. `kind` is settle_executions' own verdict on the split: COVER only when every
    first-leg contract was hedged. A NULL kind is a row written before that column shipped (one
    production row, 2026-09-05); those fall back to the same test on the fills.
    """
    if s is None or s["realized_usd"] is None:
        return False, None
    if not s["released"]:
        # The venue's result is in (settle_executions writes the row only once every venue is
        # final) but the capital reservation was not released, so the execution never reached
        # RECONCILED. Real realised money; not a cover.
        return False, f"the settlement row is not released (execution state {row['state']})"
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


def holds_contracts(row: dict) -> bool:
    """Did this execution buy anything? Asked of the FILLS, never of the state name.

    A naked position rides to settlement in PARTIAL_FILL / HEDGE_UNAVAILABLE /
    HEDGE_SLIPPAGE_EXCEEDED / UNKNOWN_PROVIDER_STATE (kernel.schema._HOLDING_FAILURES) exactly as
    much as in HEDGED -- settle_executions.pending() polls all of them -- so a state whitelist
    would hide the most exposed rows in the row. Under F24's IOC hedge those are the common ones.
    """
    return float(row.get("first_filled") or 0.0) > 0.0 or float(row.get("hedge_filled") or 0.0) > 0.0


def open_stake(row: dict) -> dict:
    """Cash paid for contracts this execution still holds, and what could not be priced.

    Contracts the protection layer already sold back (`*_unwound`) are netted out. A leg whose
    average price the store does not carry is counted in `contracts_without_a_price` rather than
    valued at zero, so a missing price shows as a gap instead of a smaller number.
    """
    stake, unpriced = 0.0, 0.0
    for filled_c, unwound_c, price_c in _LEGS:
        held = max(0.0, float(row.get(filled_c) or 0.0) - float(row.get(unwound_c) or 0.0))
        if held <= 0.0:
            continue
        price = row.get(price_c)
        if price is None:
            unpriced += held
        else:
            stake += held * float(price)
    return {"stake_paid_usd": round(stake, 6), "contracts_without_a_price": round(unpriced, 6)}


def _utc_day(ts) -> str:
    if ts is None:
        return "unknown"
    return time.strftime("%Y-%m-%d", time.gmtime(float(ts)))


def _cover_order(c: dict) -> tuple[float, str]:
    ts = c.get("settled_ts")
    return (float(ts) if ts is not None else math.inf, str(c["execution_id"]))


def _completed_utc_days(start: float, stop_at: float) -> list[str]:
    """Every UTC calendar day lying WHOLLY inside the window. A partial day is not a day."""
    first, last = math.ceil(start / 86400.0), math.floor(stop_at / 86400.0)
    return [time.strftime("%Y-%m-%d", time.gmtime(d * 86400.0)) for d in range(first, max(first, last))]


def exec_columns(con) -> tuple[list[str], list[str]]:
    """The columns to SELECT, and the optional ones this database does not have."""
    have = {r[1] for r in con.execute("PRAGMA table_info(executions)")}
    missing = [c for c in OPTIONAL_EXEC_COLUMNS if c not in have]
    return list(REQUIRED_EXEC_COLUMNS) + [c for c in OPTIONAL_EXEC_COLUMNS if c in have], missing


def run(db: str, start: float, end: float | None = None, include=(), exclude=(), *,
        data_root: str = DATA_ROOT, code_root: str = CODE_ROOT, start_pin: str | None = None,
        now: float | None = None, flag_reader=None) -> dict:
    include, exclude = list(include), list(exclude)
    pin = check_start_pin(start, start_pin if start_pin is not None else start_pin_path(data_root))

    now = time.time() if now is None else float(now)
    stop_at = end if end is not None else now
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    columns, missing_columns = exec_columns(con)
    select = ", ".join(columns)
    rows = [dict(r) for r in con.execute(
        f"SELECT {select} FROM executions WHERE started_utc >= ? AND started_utc <= ?",
        (start, stop_at))]

    dropped_by_request = sorted({r["execution_id"] for r in rows} & set(exclude))
    rows = [r for r in rows if r["execution_id"] not in set(exclude)]
    have = {r["execution_id"] for r in rows}
    added_by_request = []
    for eid in include:
        if eid not in have:
            r = con.execute(f"SELECT {select} FROM executions WHERE execution_id=?", (eid,)).fetchone()
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
    for i in range(0, len(ids), _ID_CHUNK):
        chunk = ids[i:i + _ID_CHUNK]
        marks = ",".join("?" * len(chunk))
        for s in con.execute(
                "SELECT execution_id, realized_usd, released, kind, settled_ts FROM execution_settlements "
                f"WHERE execution_id IN ({marks})", chunk):
            settle[s["execution_id"]] = dict(s)

    covers_all, non_covers, open_rows, no_position = [], [], [], []
    for r in rows:
        s = settle.get(r["execution_id"])
        scored, why_not = is_settled_cover(r, s)
        if scored:
            covers_all.append({"execution_id": r["execution_id"], "event_id": r["event_id"],
                               "league": r["league"], "kind": s["kind"],
                               "realized_usd": float(s["realized_usd"]), "settled_ts": s["settled_ts"]})
        elif why_not is not None:
            non_covers.append({"execution_id": r["execution_id"], "event_id": r["event_id"],
                               "state": r["state"], "kind": s["kind"], "excluded_because": why_not,
                               "released": bool(s["released"]),
                               "realized_usd": float(s["realized_usd"]), "settled_ts": s["settled_ts"]})
        elif holds_contracts(r):
            open_rows.append({"execution_id": r["execution_id"], "event_id": r["event_id"],
                              "state": r["state"], **open_stake(r)})
        else:
            no_position.append(r["execution_id"])

    # spec.yaml `end`: "30 settled covers". Nothing in the lane stops at 30, so the SCORED set is
    # truncated at the registered end -- deterministically, by COVER_ORDER -- and the rest are
    # reported separately. Their dollars stay in the all-in figure: they were really spent.
    covers_all.sort(key=_cover_order)
    covers, post_end = covers_all[:END_COVERS], covers_all[END_COVERS:]

    cover_total = round(sum(c["realized_usd"] for c in covers), 6)
    # Every settlement row in the window, whatever its kind and whether or not capital was
    # released. This mirrors what the box's own breaker feed counts (guard.fills_today).
    realised_rows = covers_all + non_covers
    all_in_total = round(sum(r["realized_usd"] for r in realised_rows), 6)
    # Every scored cover is released by construction (is_settled_cover refuses an unreleased row),
    # so the unreleased ones are exactly the non-cover rows that said so. Counted separately
    # because `released_settlement_rows` must not quietly mean "all settlement rows": an
    # unreleased row is a settlement whose capital the lane never gave back, and the operator
    # reading this daily has to be able to see how many of those there are.
    unreleased_rows = [n for n in non_covers if not n["released"]]

    by_day: dict[str, float] = defaultdict(float)
    for c in covers:
        by_day[_utc_day(c["settled_ts"])] += c["realized_usd"]
    all_in_by_day: dict[str, float] = defaultdict(float)
    for r in realised_rows:
        all_in_by_day[_utc_day(r["settled_ts"])] += r["realized_usd"]
    by_kind: dict[str, float] = defaultdict(float)
    for r in realised_rows:
        by_kind[str(r["kind"])] += r["realized_usd"]
    ci = clustered_interval(covers)

    completed_days = _completed_utc_days(start, stop_at)
    net_by_completed = {d: round(by_day.get(d, 0.0), 6) for d in completed_days}
    elapsed_days = (stop_at - start) / 86400.0

    open_stake_total = round(sum(o["stake_paid_usd"] for o in open_rows), 6)
    open_unpriced = round(sum(o["contracts_without_a_price"] for o in open_rows), 6)

    state = row_state(con, now=now, data_root=data_root, code_root=code_root, flag_reader=flag_reader)
    # A live probe describes the lane NOW. Applying it to a closed historical window (the L141
    # calibration run) would brand that window STOP for something that happened afterwards, so the
    # findings are still printed but only bind a window that runs to the present.
    applied = end is None or end >= now
    stopped = "; ".join(state["stop_conditions"]) if (applied and state["stop_conditions"]) else None

    # The $50 end is decided on the ALL-IN realised figure: the dollars a PARTIAL left riding and
    # the dollars the protection layer spent are the operator's dollars, and the operator's plan is
    # to stop this test at $50 of them.
    loss_end = all_in_total <= -CUMULATIVE_LOSS_STOP_USD
    end_reasons: list[str] = []
    # `blocking` ends wait for outstanding settlements; the $50 end and a stop condition do not,
    # because both are about harm already done and delaying either would hide it.
    blocking: list[str] = []
    if len(covers_all) >= END_COVERS:
        r = f"{len(covers_all)} settled covers reached the registered {END_COVERS}"
        end_reasons.append(r)
        blocking.append(r)
    if elapsed_days >= END_DAYS:
        r = f"{elapsed_days:.3f} elapsed days reached the registered {END_DAYS}"
        end_reasons.append(r)
        blocking.append(r)
    if loss_end:
        end_reasons.append(f"all-in realised net {all_in_total:+.5f} reached the "
                           f"${CUMULATIVE_LOSS_STOP_USD:.0f} cumulative-loss end")
    if applied:
        end_reasons.extend(state["end_conditions"])
        blocking.extend(state["end_conditions"])

    # spec.yaml, unit_of_observation: "An unsettled cover is not scored until it settles; the row
    # cannot end on an unsettled one." On day 7 the window expires with covers filled on days 6-7
    # still open, so the honest report is AWAITING_SETTLEMENT over a complete set, not a verdict
    # over a truncated one.
    awaiting = bool(blocking) and bool(open_rows) and stopped is None and not loss_end
    ended = (bool(end_reasons) or stopped is not None) and not awaiting
    v, reason = verdict(cover_total, len(covers), ci, stopped,
                        loss_end=loss_end, all_in_total=all_in_total)

    if stopped is not None:
        row_status, verdict_field = "STOPPED", v
    elif ended:
        row_status, verdict_field = "ENDED", v
    elif awaiting:
        row_status = "AWAITING_SETTLEMENT"
        verdict_field = (f"AWAITING_SETTLEMENT (would be {v} once {len(open_rows)} filled "
                         f"execution(s) holding {open_stake_total:.5f} USD of stake settle)")
    else:
        row_status, verdict_field = "IN_PROGRESS", f"IN_PROGRESS (would be {v})"

    to_go = round(CUMULATIVE_LOSS_STOP_USD + all_in_total, 6)
    headline = (
        f"{row_status}: REALISED ALL-IN {all_in_total:+.5f} USD over {len(realised_rows)} settlement "
        f"row(s) | settled covers only (the verdict statistic) {cover_total:+.5f} over {len(covers)} "
        f"cover(s) | open and unsettled {len(open_rows)} execution(s), {open_stake_total:.5f} USD of "
        f"stake paid and counted in NO realised figure | the ${CUMULATIVE_LOSS_STOP_USD:.0f} end: "
        + ("REACHED -- stop the test" if loss_end
           else f"{max(0.0, to_go):.5f} USD of further realised loss away"))

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
    if abs(all_in_total - cover_total) > 5e-7:
        warnings.append(
            f"the two money figures differ: settled covers alone {cover_total:+.5f} USD, all-in "
            f"realised {all_in_total:+.5f} USD. The difference is PARTIAL/UNWOUND/unreleased "
            f"settlements -- real money, outside spec.yaml's unit of observation. The "
            f"${CUMULATIVE_LOSS_STOP_USD:.0f} end is decided on the all-in figure.")
    if unreleased_rows:
        warnings.append(
            f"{len(unreleased_rows)} settlement row(s) in this window were written WITHOUT releasing "
            f"their capital reservation ({round(sum(n['realized_usd'] for n in unreleased_rows), 6):+.5f} "
            f"USD, counted in net.all_in_realised and in no cover figure): "
            + ", ".join(sorted(n["execution_id"] for n in unreleased_rows))
            + ". The venue's result is in but the execution never reached RECONCILED.")
    if open_rows:
        warnings.append(
            f"{len(open_rows)} filled execution(s) have not settled: {open_stake_total:.5f} USD of "
            f"stake paid is in NO realised figure here and in NO daily breaker figure on the box. "
            f"Cumulative loss can therefore still be worse than every number above.")
    if open_unpriced:
        warnings.append(f"{open_unpriced:g} open contract(s) have no average price recorded, so the "
                        f"outstanding stake above is understated by whatever they cost")
    if awaiting:
        warnings.append(
            "the registered end was reached but the row is NOT ended: " + "; ".join(blocking)
            + f" -- and {len(open_rows)} filled execution(s) are still unsettled. spec.yaml: 'An "
            "unsettled cover is not scored until it settles; the row cannot end on an unsettled "
            "one.' The verdict is withheld until they settle; it is NOT issued over this "
            "truncated set. The lane must not start new entries in the meantime.")
    if post_end:
        warnings.append(
            f"the lane traded past the registered {END_COVERS}-cover end: {len(post_end)} further "
            f"settled cover(s) worth {round(sum(c['realized_usd'] for c in post_end), 6):+.5f} USD "
            f"are EXCLUDED from the verdict, the total per cover and the interval (they are in "
            f"registered_end.post_end_covers, and their dollars are in net.all_in_realised).")
    for c in missing_columns:
        warnings.append(f"the executions table has no `{c}` column, so the outstanding stake above "
                        f"is computed without it and may be overstated or unpriced")
    if not state["conclusive"] and stopped is None:
        reason += " (stop-condition probes were incomplete; see warnings)"

    return {
        "schema": SCHEMA,
        "headline": headline,
        "window": {"start_utc": start, "end_utc": stop_at, "elapsed_days": round(elapsed_days, 3),
                   "completed_utc_days": completed_days, "start_pin": pin},
        "row_status": row_status,
        "ended": ended,
        "end_reasons": end_reasons,
        "end_rule": {"covers": END_COVERS, "days": END_DAYS,
                     "cumulative_loss_end_usd": CUMULATIVE_LOSS_STOP_USD,
                     "cumulative_loss_end_is_decided_on": "net.all_in_realised.total_usd",
                     "ends_that_wait_for_outstanding_settlements": blocking,
                     "ends_that_do_not_wait": "the $50 cumulative-loss end and any stop condition"},
        "selection": {"mode": ROW_MODE,
                      "include": include, "exclude": exclude,
                      "included_out_of_window": sorted(added_by_request),
                      "excluded_by_request": dropped_by_request,
                      "scored_cover_execution_ids": sorted(c["execution_id"] for c in covers)},
        "registered_end": {
            "limit_covers": END_COVERS,
            "ordering": COVER_ORDER,
            "settled_covers_in_window": len(covers_all),
            "scored_covers": len(covers),
            "truncated": bool(post_end),
            "post_end_covers": {
                "count": len(post_end),
                "realized_usd": round(sum(c["realized_usd"] for c in post_end), 6),
                "execution_ids": [c["execution_id"] for c in post_end],
                "rows": post_end},
            "what_this_is": (
                "Nothing on the box stops the lane at the registered end, so any cover after the "
                f"{END_COVERS}th is not part of the registered row's answer and is excluded from the "
                "verdict, the total, the per-cover figure and the interval. Its dollars are real and "
                "remain in net.all_in_realised.total_usd.")},
        "funnel": {"executions": len(rows),
                   "by_state": dict(sorted(Counter(r["state"] for r in rows).items())),
                   "settled_covers": len(covers),
                   "settled_covers_in_window": len(covers_all),
                   "filled_not_yet_settled": len(open_rows),
                   "no_position": len(no_position),
                   "settlement_rows": len(realised_rows),
                   "released_settlement_rows": len(realised_rows) - len(unreleased_rows),
                   "unreleased_settlement_rows": len(unreleased_rows),
                   "excluded_non_cover_settlements": {
                       "count": len(non_covers),
                       "realized_usd": round(sum(n["realized_usd"] for n in non_covers), 6),
                       "by_kind": dict(sorted(Counter(str(n["kind"]) for n in non_covers).items())),
                       "rows": sorted(non_covers, key=lambda n: n["execution_id"])},
                   "excluded_wrong_mode": {
                       "count": len(wrong_mode),
                       "by_mode": dict(sorted(Counter(r["mode"] for r in wrong_mode).items())),
                       "execution_ids": sorted(r["execution_id"] for r in wrong_mode)}},
        "net": {
            "settled_covers_only": {
                "what_this_is": (
                    "THE VERDICT STATISTIC, not the money. spec.yaml's unit of observation: scored "
                    "RECONCILED covers with both legs filled, truncated at the registered "
                    f"{END_COVERS}. It excludes PARTIAL, UNWOUND and unreleased settlements, so it "
                    "is NOT what the row cost. Do not read it as the cumulative loss."),
                "covers": len(covers),
                "total_usd": cover_total,
                "per_settled_cover_usd": (round(cover_total / len(covers), 6) if covers else None),
                "by_settle_day_usd": {k: round(v, 6) for k, v in sorted(by_day.items())},
                "by_completed_utc_day_usd": net_by_completed,
                "observed_mean_usd_per_completed_utc_day":
                    (round(sum(net_by_completed.values()) / len(net_by_completed), 6)
                     if net_by_completed else None)},
            "all_in_realised": {
                "what_this_is": (
                    "THE MONEY. Every realised dollar on F24's LIMITED_LIVE rows in this window: "
                    "settled covers (including any past the registered end), PARTIAL rows whose IOC "
                    "hedge left contracts riding naked to settlement, UNWOUND rows the protection "
                    "layer paid for, and any settlement whose capital was not released. This is the "
                    f"figure the ${CUMULATIVE_LOSS_STOP_USD:.0f} cumulative-loss end is decided on "
                    "and the figure the daily read is about. It still excludes anything not yet "
                    "settled: see awaiting_settlement."),
                "total_usd": all_in_total,
                "settlement_rows": len(realised_rows),
                "by_kind_usd": {k: round(v, 6) for k, v in sorted(by_kind.items())},
                "by_settle_day_usd": {k: round(v, 6) for k, v in sorted(all_in_by_day.items())},
                "usd_of_further_realised_loss_before_the_50_end": max(0.0, to_go)}},
        "awaiting_settlement": {
            "count": len(open_rows),
            "stake_paid_usd": open_stake_total,
            "contracts_without_a_price": open_unpriced,
            "by_state": dict(sorted(Counter(o["state"] for o in open_rows).items())),
            "execution_ids": sorted(o["execution_id"] for o in open_rows),
            "rows": sorted(open_rows, key=lambda o: o["execution_id"]),
            "blocks_the_end": awaiting,
            "what_this_is": (
                "LIMITED_LIVE executions in the window that bought contracts and have no settlement "
                "row yet -- judged on the FILLS, so a naked PARTIAL_FILL or HEDGE_UNAVAILABLE row "
                "counts exactly like a HEDGED one. Their outcome is in no figure in this report and "
                "in no daily breaker figure on the box. `stake_paid_usd` is the cash already paid "
                "for the contracts still held, before fees: a scale of what is outstanding, not a "
                "prediction of what it will realise.")},
        "daily_loss_breaker": {
            "registered_usd": DAILY_BREAKER_USD,
            "what_it_actually_bounds": DAILY_BREAKER_TRUTH,
            "utc_days_a_7_day_window_touches": END_DAYS + 1,
            "realised_all_in_by_utc_settle_day_usd":
                {k: round(v, 6) for k, v in sorted(all_in_by_day.items())},
            "latest_utc_day_in_window": _utc_day(stop_at),
            "realised_all_in_on_that_day_usd": round(all_in_by_day.get(_utc_day(stop_at), 0.0), 6),
            "not_counted_by_the_breaker": {
                "open_unsettled_executions": len(open_rows),
                "stake_paid_usd": open_stake_total,
                "contracts_without_a_price": open_unpriced},
            "scope_note": (
                "these day figures are F24's own LIMITED_LIVE rows in this window, grouped by the "
                "settlement's own settled_ts. The deployed breaker sums EVERY real-mode settlement "
                "row stamped with the current UTC day, so its figure can differ if anything else "
                "settles on the box.")},
        "interval_net_per_cover": ci,
        "loss_making_covers": sorted(
            [c for c in covers if c["realized_usd"] < 0], key=lambda c: c["realized_usd"]),
        "row_state": {"stop_conditions_applied": applied,
                      "stop_conditions": state["stop_conditions"],
                      "end_conditions": state["end_conditions"],
                      "probe_errors": state["probe_errors"],
                      "conclusive": state["conclusive"],
                      "kill": state["kill"], "override": state["override"], "flags": state["flags"]},
        "verdict": verdict_field,
        "verdict_reason": reason,
        "warnings": warnings,
        "note": ("Only a verdict with ended=true is F24's result. net.settled_covers_only is the "
                 "verdict statistic over spec.yaml's unit of observation; net.all_in_realised is the "
                 "money, and it is what the $50 end and the daily read are about. Neither includes "
                 "anything still unsettled: awaiting_settlement counts that, and the row does not "
                 "end on it."),
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
