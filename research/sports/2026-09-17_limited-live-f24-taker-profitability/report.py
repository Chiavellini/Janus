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
  * report IN_PROGRESS while a stop condition has actually ended the row. EVERY file-visible way
    the deployed lane can be stopped is probed, read-only: the WHOLE kill directory (all five
    scopes `nodes/risk/kill.active()` honours at 59dd5ae, not two names), the LATCHING daily-loss
    breaker (`nodes/risk/breaker.py`: it survives a restart AND the clearing of kill/live, and only
    a human `LossBreaker.reset(by=...)` -- which nothing in ops/ calls -- clears it), the lane's
    own one-second board snapshot (ARM_STALE, mode, the caps the RUNNING process loaded, F22, and
    the loop/socket health), the arming override, and the thirteen material safety flags;
  * call a row ENDED, or issue one of spec.yaml's five verdicts, on evidence it could not gather.
    A probe that fails or a signal that is unavailable makes `row_state.conclusive` false and the
    row INCONCLUSIVE: no verdict, no ENDED, and no seventh day running out in silence;
  * hide a `--include` / `--exclude`: both lists and every scored cover id are echoed in the output;
  * run against a start_utc that disagrees with the one arming persisted. It refuses instead;
  * describe the $25 daily breaker as a cap on a day's loss. It is not one: see
    `daily_loss_breaker.what_it_actually_bounds`.

NUMBERS PER UTC DAY, AND NO STORY ABOUT THEM
--------------------------------------------
The lane records why it refused, aggregated once per report tick, in the same database this reader
already opens read-only:

    CREATE TABLE refusal_counts(seen_ts REAL NOT NULL, channel TEXT NOT NULL, code TEXT NOT NULL,
                                league TEXT NOT NULL, n INTEGER NOT NULL);
    CREATE INDEX refusal_counts_ts ON refusal_counts(seen_ts);

(`nodes/store_tuples/store.py` REFUSAL_COUNTS_DDL / `refusal_counts()`, written from
`grids/live_stream/grid.py`'s report tick.) The RISK channel is `nodes/risk.clear` -- the
authoritative gate that owns the reservation -- plus grid.py's own pre-gate refusals. The `size`
channel is a read-only sizing mirror whose flags are contaminated by its q=100 rung; it is summed
into one line and its codes are never read for meaning.

An earlier reader turned those rows into a per-day VERDICT -- ATTEMPTED / BLOCKED / QUIET, and a
STOP built on it -- and an adversarial prover broke it in both directions, each reproduced end to
end. One cleared candidate at 00:10 made a day "ATTEMPTED" and printed MAKES_MONEY_PROVEN,
ended=true, over a row whose own risk channel recorded KILL_SWITCH x241,500. A single tick with
n=1 of a transient code on a quiet day printed "THE LANE COULD NOT TRADE ... EVERY candidate was
refused", which was false. Both defects have the same cause: a row of counters cannot support a
claim about what the lane COULD have done. A tick is one report pass; the table says in how many
passes a code was counted, never for how long it held, never what happened between two passes,
and never whether it applied to the candidates the lane actually saw.

So the classification is gone. `daily_record` reports, per completed UTC day: executions started,
covers settled, every risk-channel code with its count and the number of that day's ticks it
appeared in, the number of ticks recorded that day, and the size channel in one line. Numbers, and
nothing else.

WHAT MAY END THE ROW, AND WHAT MERELY WITHHOLDS THE VERDICT
----------------------------------------------------------
Only the unambiguous and durable may STOP or END a row: a kill switch present by the DEPLOYED
semantics of `nodes/risk/kill.py` (`all`, `live`, `venue-`, `event-`, `strategy-`; every other
name in that directory stops nothing on the box and is listed as evidence, never as a stop -- the
real box holds stray `.guard-failure-*.lock` files, and calling those unknown kills would make
every read indeterminate forever), a latched breaker, the arming override missing / expired /
carrying an experiment / with changed caps, an ARM_STALE lane or a lane not in LIMITED_LIVE, an
unresolved material safety flag, or a probe that failed.

Everything else WITHHOLDS instead of asserting. When a completed UTC day's numbers are consistent
with the lane having been unable to trade -- a candidate-independent code in that day's ticks, an
unrecognised code, or no LIMITED_LIVE execution started at all -- the day is NAMED with its
counts, the final verdict is withheld pending a human's eye, and the report states in its own
words what that evidence does and does not establish. It is not called BLOCKED, the row is not
called STOPPED, and nothing claims "every candidate was refused". The asymmetry is deliberate: a
withheld verdict costs the operator one glance, a wrong one costs them the answer they paid for.
The rule is applied PER DAY, so one cleared candidate can never speak for the other 23 hours.

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

#: nodes/risk/kill.py at 59dd5ae: FIVE scopes in ONE directory, and `active()` honours all five.
#: A reader that probes two names reports "no kill" while a venue-, event- or strategy- file sits
#: in the directory refusing entries. `any_present()` already enumerates the directory; so does
#: this. The scope prefixes carry a value (`venue-<venue>`), so a bare "venue-" matches nothing.
KILL_EXACT_SCOPES = ("all", "live")
KILL_PREFIX_SCOPES = ("venue-", "event-", "strategy-")
#: What each scope stops, in kill.py's and gate.py's own terms.
KILL_SCOPE_EFFECT = {
    "all": "every mode that sends or simulates an order",
    "live": "every new LIMITED_LIVE/PRODUCTION entry (clear() refuses; only clear_protect() mints)",
    "venue": "every entry needing that venue -- and an F24 cover needs BOTH Polymarket and Kalshi",
    "event": "every entry on that event; the row's registered surface is no longer what it was",
    "strategy": "every entry from that strategy version -- the lane runs one",
}
#: kernel/paths.py puts these two in KILL_ROOT as well, and they are NOT kill switches: the
#: breaker is read by probe_breaker and the override by probe_override. nodes/risk/health.py's
#: risk_alerts skips exactly these two names and calls every other file KILL_FILE_PRESENT.
KILL_DIR_NON_KILL_FILES = ("breaker.json", "arming_override.json")

#: nodes/store_tuples/store.py REFUSAL_COUNTS_DDL: the lane's own COUNTERS, flushed once per
#: report tick. Counts, per tick, per code, per league -- no duration, no candidate, no mode.
REFUSAL_TABLE = "refusal_counts"
#: grid.refuse(): `risk` is nodes/risk.clear -- the authoritative gate that owns the reservation --
#: and grid.py's own pre-gate refusals. `size` is the read-only sizing mirror, whose flags are
#: contaminated by its q=100 rung; its rows are summed to one line and its codes are never read.
RISK_CHANNEL = "risk"
#: nodes/store_tuples/store.RETENTION_TABLES holds ("refusal_counts", "seen_ts") and
#: grid.Supervisor.retain_days is 7, so a 7-day row's FIRST day can age out of this table while
#: the row is still running. The oldest retained row is reported, so a day before it is visibly
#: a day with nothing left to read rather than a day with nothing to report.
REFUSAL_RETENTION_DAYS = 7

#: CANDIDATE-INDEPENDENT: when the deployed code returns one of these it has not looked at the
#: candidate. Each is confirmed in `nodes/risk/clearance.py` or `grids/live_stream/grid.py` at
#: 59dd5ae; the value is what the deployed code does, quoted, not what this reader concludes.
#:
#: THIS LIST DRIVES NO VERDICT. Its only effect is that a completed UTC day carrying one of these
#: codes is NAMED, with its counts, as a day a human should look at before the row is given a
#: verdict. It never produces a STOP and it never becomes the claim "the lane could not trade":
#: the table records a count per report tick, so it cannot say for how long the condition held,
#: what happened between two ticks, or whether it applied to the candidates the lane saw.
CANDIDATE_INDEPENDENT_RISK_CODES = {
    "KILL_SWITCH": ("clearance.clear: kill.active() matched one of nodes/risk/kill.py's five "
                    "scopes, before any other check"),
    "BREAKER": ("clearance.clear: breaker.evaluate() refused -- either BREAKER_LATCHED (the "
                "latching daily-loss breaker) or PNL_UNKNOWN, which a SINGLE fill still "
                "UNCONFIRMED produces and which refuses every candidate for the rest of the UTC "
                "day while writing NOTHING to the kill directory, to breaker.json or to a lane flag"),
    "ARM_STALE": ("grid._execute: check_arm found the override no longer authorises this process "
                  "(code tree, limits or expiry), and _execute refuses every real order while it is set"),
    "GUARD_FAILED": ("grid._guard_entry_refused: the position guard's health proof is invalid, so "
                     "no new capital entry is allowed until a complete pass restores it"),
    "BALANCE": "clearance.clear: a venue's balance was below the stake the candidate needed",
    "BALANCE_UNCONFIRMED": ("clearance.clear: venue balances could not be confirmed at all, which "
                            "refuses every order that sends real money"),
    "FEE_SCHEDULE": "clearance.clear: a venue's fee schedule is missing or unverified",
    "CLOCK_UNHEALTHY": ("clearance.clear: grid.clock_ok() is false -- a venue's stamps are outside "
                        "the bound, or the loop stalled -- and the gate refuses every candidate"),
    "VENUE_DISCONNECTED": ("clearance.clear: a venue is not connected and synced, and an F24 cover "
                           "needs BOTH Polymarket and Kalshi"),
    "VENUE_GEOBLOCKED": ("grid._execute: this host cannot place Polymarket orders; the lane says it "
                         "refused EVERY cover"),
    "MODE": "clearance.clear: the lane's mode does not execute, so there is nothing to clear",
    "NO_CAPS": "clearance.clear: a capital-risking mode with no arming override caps",
    "CAP_DAY_NOTIONAL": ("clearance.clear: the override's day notional cap is spent, which refuses "
                         "every further candidate for the rest of the UTC day"),
    "MAX_EVENTS": "ledger.assess: every simultaneous-event reservation slot is already taken",
    "TOTAL_CAPITAL": "ledger.assess: open capital is at limits.max_total_usd",
    "UNRESOLVED_EXPOSURE": "ledger.assess: unresolved exposure is at limits.max_unresolved_usd",
}
#: PER-CANDIDATE: the deployed code returned this after looking at THIS candidate at THIS size (or
#: at the ceiling its scope -- a league, a venue, an event, a quantity -- had already reached).
#: Listed for the same reason as the other list: so a code in NEITHER can be recognised as one
#: this reader does not know. A day of these is not called "a working lane that found nothing
#: worth trading" anywhere in this report; that is a story, and the counters do not carry it.
PER_CANDIDATE_RISK_CODES = {
    "MIN_PROFIT": "the candidate's net profit was under the hurdle",
    "MIN_RETURN": "the candidate's locked return was under the hurdle",
    "STALE_BOOK": "the candidate was priced from a book older than the bound",
    "IN_FLIGHT": "another execution was already on the wire (one flight at a time)",
    "HEDGE_DEPTH_CHANGED": "the hedge book moved between the plan and the entry",
    "CAP_STAKE": "this candidate's stake was over the override's cap",
    "CAP_CONTRACTS": "this candidate's quantity was over the override's cap",
    "MAX_UNHEDGED": "this candidate's first leg was over limits.max_unhedged_contracts",
    "EVENT_IN_FLIGHT": "that event already had an open reservation (single-flight)",
    "EVENT_NOTIONAL": "that event was at its per-event notional",
    "LEAGUE_EXPOSURE": "that league was at its exposure cap",
    "VENUE_CAPITAL": "that venue was at its capital cap",
    "EMPTY_RESERVATION": "the candidate asked to reserve nothing",
}

#: What one row of `refusal_counts` is, and therefore the exact limit of every number below it.
#: Printed in the report, in the report's own words, beside the days it withholds a verdict over.
WHAT_A_TICK_IS = (
    "A tick is ONE report pass in which grids/live_stream/grid.py flushed its refusal counters. "
    "`n` is how many refusals that code accumulated; `ticks` is in how many of that day's recorded "
    "passes it appeared. Neither says for how long the condition held, what happened between two "
    "passes, or whether it applied to the candidates the lane actually saw. `refusal_counts` has "
    "no mode column and no candidate column, so no count here can be attributed to a candidate, "
    "to a minute, or to a mode.")

#: Why a completed UTC day is handed to a human instead of being given a label. Each is a FACT
#: about the numbers; none of them is a finding about the lane.
LOOK_CANDIDATE_INDEPENDENT = "CANDIDATE_INDEPENDENT_CODE_PRESENT"
LOOK_UNRECOGNISED_CODE = "UNRECOGNISED_CODE_PRESENT"
LOOK_NO_EXECUTION_STARTED = "NO_LIMITED_LIVE_EXECUTION_STARTED"
#: What a day carrying any of the above does and does not establish, said outright in the output.
WHAT_A_WITHHELD_DAY_ESTABLISHES = (
    "ESTABLISHES: these codes were counted in this many of the day's recorded report ticks, and "
    "this many LIMITED_LIVE executions started that day. DOES NOT ESTABLISH: that the lane was "
    "unable to act, that no candidate could have cleared, that the condition held for the whole "
    "day, or that it held for any moment between two ticks. This report does not claim any of "
    "those and cannot rule them out either -- which is why the verdict waits for a human rather "
    "than being issued or being turned into a STOP.")
#: The mode hole, stated in the output rather than papered over with an invented signal.
MODE_LIMITATION = (
    "`refusal_counts` carries NO mode column, so a paper-mode lane's refusals are indistinguishable "
    "here from a LIMITED_LIVE lane's. This report does not guess: `row_state.board.mode` is the "
    "lane's mode NOW, at the moment of this read, and nothing more. What a paper period does leave "
    "is days with zero LIMITED_LIVE executions started -- executions are filtered to "
    f"{ROW_MODE} -- and every such completed day is named and withholds the final verdict, which "
    "is how a half-paper row stops passing silently.")

#: grids/live_stream/grid.py: `loop_stalled()` is `stalled or loop_lag_max_s > max_loop_lag_s`, and
#: `clock_ok()` -- what the risk gate is handed as `clock_healthy` -- is false while it holds. The
#: board states both outright. 5.0 s is grid.Supervisor.max_loop_lag_s at 59dd5ae.
BOARD_MAX_LOOP_LAG_S = 5.0
#: An F24 cover needs BOTH venues; a socket the board reports as not connected is a lane that
#: cannot complete one, whatever the kill directory says.
REQUIRED_VENUES = ("kalshi", "polymarket")

#: grids/live_stream/grid.py Supervisor.write_board writes this snapshot every loop pass (one a
#: second) to the --board path, whose argparse default is DATA_ROOT/board/board.json. It states
#: arm_stale, mode, the caps the RUNNING process loaded and the F22 authority OUTRIGHT, which no
#: file in the kill directory does. verify_f24.sh reads the running lane's own --board out of
#: /proc; this reader uses the default path and treats a board it cannot find as a probe failure,
#: never as a pass. The tolerances are verify_f24.sh's, for one answer from both tools.
BOARD_MAX_AGE_S = 120.0
BOARD_CLOCK_SKEW_S = 5.0

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


def board_path(data_root: str = DATA_ROOT) -> str:
    """The lane's one-second snapshot: grid.py's `--board` argparse default under the data root."""
    return os.path.join(data_root, "board", "board.json")


def breaker_path(data_root: str = DATA_ROOT) -> str:
    """kernel/paths.BREAKER_PATH: the latching daily-loss breaker's state, inside the kill root."""
    return os.path.join(data_root, "kill", "breaker.json")


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
    """The JSON OBJECT a state file holds, or ValueError.

    `json.loads` happily returns a bare scalar: `null`, `5`, `"latched"`, `[]` are all valid JSON
    documents. Every caller here then asks it for `.get(...)` or `[...]` and dies with
    AttributeError or TypeError -- which is not caught anywhere, so a one-byte kill file or a
    truncated board crashes the whole daily read and the operator sees a traceback instead of a
    report. A crashed probe is worse than a failed one: it reads as no probe at all. A non-object
    is therefore raised as ValueError, which is exactly what every caller's `except ... ValueError`
    branch already handles by naming the file and failing closed.
    """
    text = open(path).read()
    if not text.strip():
        return {}
    d = json.loads(text)
    if not isinstance(d, dict):
        raise ValueError(f"holds a bare JSON {type(d).__name__}, not an object: {text.strip()[:80]!r}")
    return d


def _utc_iso(ts) -> str | None:
    """A UTC timestamp as the operator reads it in the report; None when it is not a number."""
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(ts)))
    except (TypeError, ValueError, OSError):
        return None


def _parse_utc(text) -> float | None:
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


def kill_scope(name: str) -> str | None:
    """Which of nodes/risk/kill.py's five scopes this file name is, or None if it is not one.

    `active()` matches `all`, `live`, and the three prefixed families by the exact name it builds
    (`venue-{v}`, `event-{id}`, `strategy-{version}`), so a bare prefix with no value -- "venue-"
    -- matches no action and is NOT a kill. It is listed in `kill.other_files` as evidence.
    """
    if name in KILL_EXACT_SCOPES:
        return name
    for prefix in KILL_PREFIX_SCOPES:
        if name.startswith(prefix) and len(name) > len(prefix):
            return prefix[:-1]
    return None


def probe_kill(kill_dir: str) -> dict:
    """EVERY kill file in the directory, by name, scope and recorded reason.

    Probing two names ("live", "all") is how a reader reports a quiet row while a
    `venue-polymarket`, `event-<id>` or `strategy-<version>` file in the same directory is
    refusing entries: `KillSwitches.active()` honours all five scopes, and `any_present()`
    enumerates the whole directory. This enumerates it too.

    AND NOTHING ELSE IS A KILL SWITCH. `active()` matches only the five names it builds, so a file
    with any other name stops NOTHING on the box -- verified on the real box, whose kill directory
    holds stray `.guard-failure-*.lock` and `.legacy-incident-*.lock` files. Treating those as
    kills this reader "cannot classify" would withhold every verdict forever, which is not caution
    but noise. They are listed by name in `other_files`, as evidence a human may want, and they
    are neither a stop nor a probe failure. (nodes/risk/health.risk_alerts is more alarmed than
    this: it calls every non-breaker, non-override file KILL_FILE_PRESENT.)

    The daily loss breaker latches `live` when it fires -- but see DAILY_BREAKER_TRUTH for what
    makes it fire, and probe_breaker for the latch that OUTLIVES the file.
    """
    out: dict = {"dir": kill_dir, "listed": False, "live_present": None, "all_present": None,
                 "present": [], "names": [], "scopes": [], "other_files": [], "non_kill_files": [],
                 "reasons": {}, "error": None,
                 "other_files_note": (
                     "files in the kill directory that are none of nodes/risk/kill.py's five "
                     "scopes. active() never builds their names, so they stop nothing on the box: "
                     "they are reported as evidence and are never treated as a kill, as an unknown "
                     "kill, or as a reason to withhold anything.")}
    try:
        entries = sorted(os.listdir(kill_dir))
    except OSError as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    out["listed"] = True
    out["live_present"], out["all_present"] = False, False
    for name in entries:
        if name in KILL_DIR_NON_KILL_FILES:
            out["non_kill_files"].append(name)
            continue
        scope = kill_scope(name)
        if scope is None:
            out["other_files"].append(name)
            continue
        try:
            reason = _read_json_file(os.path.join(kill_dir, name)).get("reason") or "no reason recorded"
        except (OSError, ValueError) as exc:
            reason = f"unreadable ({type(exc).__name__})"
        out["names"].append(name)
        out["reasons"][name] = reason
        out["present"].append({"name": name, "scope": scope, "reason": reason,
                               "stops": KILL_SCOPE_EFFECT[scope]})
        if name in KILL_EXACT_SCOPES:
            out[f"{name}_present"] = True
    out["scopes"] = sorted({k["scope"] for k in out["present"]})
    return out


def probe_breaker(path: str) -> dict:
    """The LATCHING daily realised-loss breaker (nodes/risk/breaker.py at 59dd5ae).

    spec.yaml names this a stop condition in its own words: "the daily realised-loss breaker
    latching (it latches kill/live and needs a human to clear, so one latch ends the row rather
    than pausing it)". The file is the latch, not the kill file it also creates:

      * `_load` reads `latched` from this file at every construction, so the latch survives a
        restart;
      * `evaluate()` returns BREAKER_LATCHED from that flag BEFORE it can latch anything, so
        kill/live is never re-created after someone deletes it -- and `nodes/risk/clearance.py`
        refuses every candidate for as long as the flag is set;
      * only `LossBreaker.reset(by=...)` clears it, and nothing in ops/ calls reset.

    So a latched breaker with NO kill file is a lane that looks armed and places no order for the
    rest of the row. A missing file is a definite reading (`_load` leaves `latched` False); an
    unreadable one is not: the deployed `_load` would raise on it, and health.risk_alerts treats
    it as latched. This reports it as a failed probe and lets the caller fail closed.
    """
    out: dict = {"path": path, "present": None, "latched": None, "reason": None, "latched_utc": None,
                 "error": None,
                 "what_clears_it": ("a human, by name: LossBreaker.reset(by=...). Nothing in ops/ "
                                    "calls it, and deleting kill/live does NOT clear it.")}
    try:
        out["present"] = os.path.exists(path)
    except OSError as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    if not out["present"]:
        out["latched"] = False          # breaker._load: no state file means it has never latched
        return out
    try:
        d = _read_json_file(path)
    except (OSError, ValueError) as exc:
        out["error"] = (f"{type(exc).__name__}: {exc} -- the deployed LossBreaker._load would raise "
                        f"on this file, and nodes/risk/health.risk_alerts treats an unreadable "
                        f"breaker state as LATCHED")
        return out
    out["latched"] = bool(d.get("latched"))
    out["reason"] = d.get("reason") or None
    out["latched_utc"] = d.get("latched_utc")
    return out


def probe_board(path: str, *, now: float) -> dict:
    """The lane's own one-second snapshot: is the RUNNING process able to place a real order?

    `Supervisor.check_arm` sets `arm_stale` from `nodes/risk/gate.stale_reason` on every report
    tick, and `_execute` refuses every real order while it is set: an ARM_STALE lane keeps
    evaluating, keeps logging, keeps looking healthy, and trades nothing. Nothing in the kill
    directory says so, and the log says it only when it CHANGES. `write_board` states it outright,
    with the mode, the caps this process loaded at start and the F22 authority, stamped `as_of`.

    A board that is missing, unreadable or stale is a NAMED probe failure -- the lane may be dead,
    stopped, OOM-killed or running below LIMITED_LIVE -- never a quiet pass. The fields of a stale
    board are still reported, and a stale board that says ARM_STALE is still believed: only a new
    override or a restart clears that, so the age is named rather than used to dismiss it.

    `stalled`, `loop_lag_s` and `sockets` are read too, and they are not decoration. `clock_ok()`
    -- what the risk gate is handed as `clock_healthy` -- is `not loop_stalled()` AND both venues'
    stamps inside the bound, and `loop_stalled()` is exactly `stalled or loop_lag_s >
    max_loop_lag_s`. A cover needs BOTH venues, so a socket the board reports as not connected is
    a cover that cannot complete. Neither is one of spec.yaml's stop conditions -- a stall
    self-clears in two ticks -- so both are reported as what the board says AT THIS MOMENT, in a
    note. They are never applied backwards to a day: this snapshot is one second old, and the day
    it describes is today.
    """
    out: dict = {"path": path, "present": None, "readable": None, "as_of": None, "age_s": None,
                 "fresh": None, "max_age_s": BOARD_MAX_AGE_S, "mode": None, "caps": None,
                 "caps_match_registered": None, "arm_stale": None, "f22_enabled": None,
                 "f22_authority": None, "stalled": None, "loop_lag_s": None,
                 "max_loop_lag_s": BOARD_MAX_LOOP_LAG_S, "loop_gate_open": None, "sockets": None,
                 "venues_not_connected": None, "not_trading_evidence": [], "error": None}
    try:
        out["present"] = os.path.exists(path)
    except OSError as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    if not out["present"]:
        out["error"] = (f"no board at {path}: the lane writes one every second "
                        f"(grid.Supervisor.write_board). Without it this reader cannot tell an "
                        f"armed lane from a dead one or from one refusing every order (ARM_STALE)")
        return out
    try:
        d = _read_json_file(path)
    except (OSError, ValueError) as exc:
        out["readable"] = False
        out["error"] = f"the board at {path} is unreadable: {type(exc).__name__}: {exc}"
        return out
    out["readable"] = True
    try:
        out["as_of"] = float(d["as_of"])
    except (KeyError, TypeError, ValueError):
        out["error"] = f"the board at {path} carries no usable `as_of`: {d.get('as_of')!r}"
        return out
    out["age_s"] = round(now - out["as_of"], 1)
    out["fresh"] = -BOARD_CLOCK_SKEW_S <= out["age_s"] <= BOARD_MAX_AGE_S
    out["mode"] = d.get("mode")
    out["arm_stale"] = d.get("arm_stale") or None
    out["f22_enabled"] = d.get("f22_enabled")
    out["f22_authority"] = d.get("f22_authority")

    # The loop and the sockets: what the risk gate is actually handed. Parsed and USED, not
    # discarded -- these are the two board fields that say "this lane is not placing orders"
    # without anything appearing in the kill directory.
    out["stalled"] = bool(d["stalled"]) if isinstance(d.get("stalled"), bool) else d.get("stalled")
    try:
        out["loop_lag_s"] = None if d.get("loop_lag_s") is None else float(d["loop_lag_s"])
    except (TypeError, ValueError):
        out["loop_lag_s"] = None
    lagged = out["loop_lag_s"] is not None and out["loop_lag_s"] > BOARD_MAX_LOOP_LAG_S
    out["loop_gate_open"] = not (bool(out["stalled"]) or lagged)
    if out["stalled"]:
        out["not_trading_evidence"].append(
            "the board reports the supervisor loop STALLED at its last tick: grid.loop_stalled() "
            "is true, so clock_ok() is false and nodes/risk.clear refuses every candidate "
            "CLOCK_UNHEALTHY until two clean ticks have passed")
    if lagged:
        out["not_trading_evidence"].append(
            f"the board reports loop_lag_s {out['loop_lag_s']:g} over grid.max_loop_lag_s "
            f"{BOARD_MAX_LOOP_LAG_S:g}: loop_stalled() is true on that alone, so the gate refuses "
            f"every candidate CLOCK_UNHEALTHY")
    socks = d.get("sockets") if isinstance(d.get("sockets"), dict) else None
    out["sockets"] = socks
    if socks is None:
        out["venues_not_connected"] = list(REQUIRED_VENUES)
        out["not_trading_evidence"].append(
            "the board carries no `sockets` object, so neither venue's stream can be confirmed "
            "connected; an F24 cover needs BOTH")
    else:
        down = [v for v in REQUIRED_VENUES
                if v not in socks or not (isinstance(socks[v], dict) and socks[v].get("connected"))]
        out["venues_not_connected"] = down
        if down:
            out["not_trading_evidence"].append(
                f"the board reports {', '.join(down)} NOT connected: an F24 cover needs both "
                f"Polymarket and Kalshi, so no cover can complete while that holds "
                f"(nodes/risk.clear refuses VENUE_DISCONNECTED)")

    caps = d.get("caps") if isinstance(d.get("caps"), dict) else None
    out["caps"] = caps
    if caps is not None and str(out["mode"]) == ROW_MODE:
        try:
            out["caps_match_registered"] = all(
                abs(float(caps[k]) - v) < 1e-9 for k, v in REGISTERED_CAPS.items() if k in caps
            ) and set(REGISTERED_CAPS) <= set(caps)
        except (TypeError, ValueError):
            out["caps_match_registered"] = False
    if not out["fresh"]:
        out["error"] = (f"the board at {path} is {out['age_s']}s old (a live lane rewrites it every "
                        f"second; more than {BOARD_MAX_AGE_S:g}s means the lane is dead, stopped, "
                        f"starved or writing somewhere else). Its last reading is reported, but it "
                        f"does NOT say the lane is trading now")
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


def _utc_day_start(day: str) -> float | None:
    """The epoch second a `YYYY-MM-DD` UTC day begins, or None if it is not one."""
    try:
        return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


#: The whole refusal read, in TWO statements. `seen_ts` is the indexed column (refusal_counts_ts),
#: so both are bounded by the row's own window instead of scanning the table: the box is a SINGLE
#: vCPU that is also running the live lane, and this runs every day. Both channels come back; the
#: second statement counts the DISTINCT report ticks each (day, channel) recorded, which is the
#: denominator every per-code tick count is read against.
#:
#: COUNT(DISTINCT seen_ts), not COUNT(*): one report tick writes one row per (code, league), so
#: counting rows would report four ticks for one tick that refused across four leagues.
_REFUSAL_SQL = (f"SELECT CAST(seen_ts/86400.0 AS INTEGER) AS utc_day, channel, code, SUM(n), "
                f"COUNT(DISTINCT seen_ts) FROM {REFUSAL_TABLE} WHERE seen_ts >= ? AND seen_ts <= ? "
                f"GROUP BY 1, 2, 3")
_REFUSAL_TICKS_SQL = (f"SELECT CAST(seen_ts/86400.0 AS INTEGER) AS utc_day, channel, "
                      f"COUNT(DISTINCT seen_ts) FROM {REFUSAL_TABLE} "
                      f"WHERE seen_ts >= ? AND seen_ts <= ? GROUP BY 1, 2")
_REFUSAL_SPAN_SQL = f"SELECT MIN(seen_ts), MAX(seen_ts) FROM {REFUSAL_TABLE}"


def probe_refusals(con, *, start: float, stop_at: float, channel: str = RISK_CHANNEL) -> dict:
    """What the lane ITSELF counted, per UTC day, per code, over the row's window.

    Counters, and nothing more. `breaker.evaluate()` returning PNL_UNKNOWN, a BALANCE that could
    not be confirmed, a FEE_SCHEDULE that went unverified and an ARM_STALE a later override
    cleared all leave nothing on disk -- and all of them are counted here, once per report tick,
    for as long as the rows are retained. What the counts do NOT carry is duration, candidate or
    mode: see WHAT_A_TICK_IS, which is printed in the report beside them.

    Cheap by construction: the aggregation happens in SQLite over an indexed `seen_ts` range, so
    the daily read returns one row per (UTC day, channel, code) plus one per (UTC day, channel)
    instead of the window's tens of thousands of tick rows. `MIN`/`MAX` over the indexed column
    are index lookups and give the retention horizon, which is what separates "no row was recorded
    that day" from "that day is older than anything this table still holds" (store.RETENTION_TABLES
    ages this table at grid.retain_days = 7).

    A missing or unreadable table is reported as an error and fails closed upstream: this reader
    says what it could not read, and issues no verdict over a window it could not read.
    """
    out: dict = {"table": REFUSAL_TABLE, "channel": channel, "present": None, "error": None,
                 "window": {"start_utc": start, "end_utc": stop_at},
                 "ticks_in_window": 0, "refusals_in_window": 0,
                 "retained_from_utc": None, "retained_to_utc": None,
                 "by_code": {}, "candidate_independent_by_code": {}, "per_candidate_by_code": {},
                 "unrecognised_by_code": {},
                 "by_utc_day": {}, "ticks_by_utc_day": {},
                 "other_channels_by_utc_day": {}, "other_channels_over_the_row": {},
                 "by_channel": {}, "sql": [_REFUSAL_SQL, _REFUSAL_TICKS_SQL],
                 "what_a_tick_is": WHAT_A_TICK_IS,
                 "other_channel_note": (
                     "`other_channels_*` sums the NON-risk channels (today: `size`, "
                     "nodes/execute/sizing's read-only mirror) to ONE count and ONE tick count per "
                     "day. Its codes are not reported per code and are never read for meaning: the "
                     "size ladder unions CAP_CONTRACTS in unconditionally and its flags are "
                     "contaminated by its q=100 rung."),
                 "cost_note": (
                     "two indexed range scans over refusal_counts_ts, aggregated in SQLite: the "
                     "result is one row per (UTC day, channel, code) and one per (UTC day, "
                     "channel), not per tick. The box writes roughly 9,000 rows a day across both "
                     "channels, so a 7-day window touches tens of thousands of rows once a day -- "
                     "bounded, and it never reads outside the row's window. MIN/MAX are index "
                     "lookups."),
                 "what_this_is": (
                     "grids/live_stream/grid.py counts every refusal by (channel, code, league) "
                     "and flushes it to nodes/store_tuples/store.refusal_counts once per report "
                     "tick. The `risk` channel is nodes/risk.clear -- the gate that owns the "
                     "reservation -- plus grid.py's own pre-gate refusals. The `size` channel is a "
                     "read-only sizing mirror contaminated by its q=100 rung."),
                 "retention_note": (
                     f"store.RETENTION_TABLES ages `{REFUSAL_TABLE}` out at grid.retain_days = "
                     f"{REFUSAL_RETENTION_DAYS} days, which is exactly F24's registered length: "
                     f"the row's first day can lose its rows while the row is still running. "
                     f"`retained_from_utc` is the oldest row the table still holds, so a day "
                     f"entirely before it has no evidence left either way.")}
    try:
        present = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (REFUSAL_TABLE,)).fetchone()
    except sqlite3.Error as exc:
        out["error"] = f"could not look for {REFUSAL_TABLE}: {type(exc).__name__}: {exc}"
        return out
    if not present:
        out["present"] = False
        out["error"] = (
            f"this database has no `{REFUSAL_TABLE}` table, so the lane's own count of why it "
            f"refused cannot be read. It is written by grids/live_stream/grid.py on every report "
            f"tick at 59dd5ae (store.REFUSAL_COUNTS_DDL creates it on the first flush), so its "
            f"absence means the lane has not ticked since L113 was deployed, or this is not the "
            f"lane's database. No verdict is issued over a window whose record could not be read")
        return out
    out["present"] = True
    try:
        lo, hi = con.execute(_REFUSAL_SPAN_SQL).fetchone()
        out["retained_from_utc"], out["retained_to_utc"] = lo, hi
        rows = con.execute(_REFUSAL_SQL, (start, stop_at)).fetchall()
        tick_rows = con.execute(_REFUSAL_TICKS_SQL, (start, stop_at)).fetchall()
    except sqlite3.Error as exc:
        out["error"] = f"reading {REFUSAL_TABLE}: {type(exc).__name__}: {exc}"
        return out

    by_day: dict[str, dict[str, dict]] = defaultdict(dict)
    other_by_day: dict[str, dict[str, dict]] = defaultdict(dict)
    totals: dict[str, dict] = defaultdict(lambda: {"n": 0, "ticks": 0})
    other_totals: dict[str, dict] = defaultdict(lambda: {"n": 0, "ticks": 0})
    by_channel: dict[str, int] = defaultdict(int)
    for day_i, chan, code, n, ticks in rows:
        day = _day_name(day_i)
        chan, code, n, ticks = str(chan), str(code), int(n or 0), int(ticks or 0)
        by_channel[chan] += n
        if chan != channel:
            slot = other_by_day[day].setdefault(chan, {"n": 0, "ticks": 0})
            slot["n"] += n
            other_totals[chan]["n"] += n
            continue
        cell = by_day[day].setdefault(code, {"n": 0, "ticks": 0})
        cell["n"] += n
        cell["ticks"] += ticks
        totals[code]["n"] += n
        totals[code]["ticks"] += ticks
    # The DENOMINATOR: how many report ticks that (day, channel) recorded at all. A code seen in 1
    # of 240 ticks and a code seen in 240 of 240 are different numbers and must read differently.
    ticks_by_day: dict[str, int] = {}
    for day_i, chan, ticks in tick_rows:
        day, chan, ticks = _day_name(day_i), str(chan), int(ticks or 0)
        if chan == channel:
            ticks_by_day[day] = ticks_by_day.get(day, 0) + ticks
        else:
            other_by_day[day].setdefault(chan, {"n": 0, "ticks": 0})["ticks"] += ticks
            other_totals[chan]["ticks"] += ticks

    out["ticks_in_window"] = sum(ticks_by_day.values())
    out["refusals_in_window"] = sum(c["n"] for c in totals.values())
    out["by_channel"] = dict(sorted(by_channel.items()))
    out["other_channels_by_utc_day"] = {d: dict(sorted(c.items())) for d, c in sorted(other_by_day.items())}
    out["other_channels_over_the_row"] = dict(sorted(other_totals.items()))
    out["by_code"] = dict(sorted(totals.items()))
    out["candidate_independent_by_code"] = {k: v for k, v in sorted(totals.items())
                                            if k in CANDIDATE_INDEPENDENT_RISK_CODES}
    out["per_candidate_by_code"] = {k: v for k, v in sorted(totals.items())
                                    if k in PER_CANDIDATE_RISK_CODES}
    out["unrecognised_by_code"] = {k: v for k, v in sorted(totals.items())
                                   if k not in CANDIDATE_INDEPENDENT_RISK_CODES
                                   and k not in PER_CANDIDATE_RISK_CODES}
    out["by_utc_day"] = {d: dict(sorted(c.items())) for d, c in sorted(by_day.items())}
    out["ticks_by_utc_day"] = dict(sorted(ticks_by_day.items()))
    return out


def _day_name(day_index) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(float(day_index) * 86400.0))


def _codes_line(codes: dict, ticks_seen: int) -> str:
    """One line of plain numbers: `CODE n=1234 in 4 of 4 tick(s)`, and nothing else."""
    if not codes:
        return f"no code recorded, in {ticks_seen} recorded tick(s)"
    return ", ".join(f"{k} n={v['n']} in {v['ticks']} of {ticks_seen} tick(s)"
                     for k, v in sorted(codes.items()))


def _other_channels_line(chans: dict) -> str:
    """The size channel (and any other), summed, in ONE line. Its codes are never read."""
    if not chans:
        return "no row on any other channel"
    return ", ".join(f"{c} n={v['n']} in {v['ticks']} tick(s)" for c, v in sorted(chans.items()))


def daily_record(*, completed_days: list[str], partial_day: str | None, attempts_by_day: dict,
                 covers_by_day: dict, refusals: dict, board: dict) -> dict:
    """Per UTC day: the numbers, and which days a human has to look at before a verdict is issued.

    There is no day classification here and no day label. An earlier version of this function
    decided ATTEMPTED / BLOCKED / QUIET per day and built a STOP out of it; a prover broke it in
    both directions from the same root cause -- counters cannot answer "could the lane have
    traded". What is reported instead, per completed UTC day:

      * how many LIMITED_LIVE executions STARTED, and how many covers SETTLED;
      * every risk-channel code, its count, and in how many of that day's ticks it appeared;
      * how many ticks that day recorded at all;
      * the other channels summed into one line.

    A day is then handed to a human -- never labelled, never turned into a STOP -- when its
    numbers are consistent with the lane having been unable to trade: a candidate-independent
    code appeared, a code this reader does not recognise appeared, or no LIMITED_LIVE execution
    started at all. The last one carries the paper-mode case (MODE_LIMITATION): `refusal_counts`
    has no mode column, but executions are filtered to LIMITED_LIVE, so a paper period is a run of
    days with zero of them and those days withhold the verdict.

    Days with attempts are judged by exactly the same rule: one cleared candidate at 00:10 does
    not speak for the other 23 hours, which is what the whitewash was made of.
    """
    days: list[dict] = []
    look_reasons: dict[str, list[str]] = {}
    evidence = list(board.get("not_trading_evidence") or [])
    horizon = refusals.get("retained_from_utc")
    by_day = refusals.get("by_utc_day", {}) or {}
    ticks_by_day = refusals.get("ticks_by_utc_day", {}) or {}
    other_by_day = refusals.get("other_channels_by_utc_day", {}) or {}

    def facts(day: str, *, complete: bool) -> dict:
        attempts = int(attempts_by_day.get(day, 0) or 0)
        codes = dict(by_day.get(day) or {})
        ticks_seen = int(ticks_by_day.get(day, 0) or 0)
        others = dict(other_by_day.get(day) or {})
        independent = {k: v for k, v in sorted(codes.items()) if k in CANDIDATE_INDEPENDENT_RISK_CODES}
        unrecognised = {k: v for k, v in sorted(codes.items())
                        if k not in CANDIDATE_INDEPENDENT_RISK_CODES
                        and k not in PER_CANDIDATE_RISK_CODES}
        entry = {
            "utc_day": day,
            "complete": complete,
            "executions_started": attempts,
            "covers_settled": int(covers_by_day.get(day, 0) or 0),
            "risk_channel": {"ticks_recorded": ticks_seen, "codes": dict(sorted(codes.items()))},
            "risk_line": f"risk: {_codes_line(codes, ticks_seen)}",
            "other_channels_line": _other_channels_line(others),
            "candidate_independent_codes": independent,
            "unrecognised_codes": unrecognised,
            "needs_a_human_look": False,
            #: The short tag(s) for why, so a reader that has room for one line per day (the
            #: check_f24.sh banner) can state it without reprinting the same paragraph per day.
            "look_tags": [],
            "why": [],
        }
        if not complete:
            return entry

        why: list[str] = []
        tags: list[str] = []
        if independent:
            tags.append(LOOK_CANDIDATE_INDEPENDENT)
            why.append(
                f"{LOOK_CANDIDATE_INDEPENDENT}: {_codes_line(independent, ticks_seen)}. When the "
                f"deployed code returns {' / '.join(sorted(independent))} it has not looked at the "
                f"candidate (" + "; ".join(CANDIDATE_INDEPENDENT_RISK_CODES[k] for k in sorted(independent))
                + ")")
        if unrecognised:
            tags.append(LOOK_UNRECOGNISED_CODE)
            why.append(
                f"{LOOK_UNRECOGNISED_CODE}: {_codes_line(unrecognised, ticks_seen)}. This reader "
                f"does not know {' / '.join(sorted(unrecognised))}; it is in neither of the two "
                f"reference lists, so whether it depends on the candidate is unknown here. Check it "
                f"against nodes/risk/clearance.py")
        if attempts == 0:
            tags.append(LOOK_NO_EXECUTION_STARTED)
            aged = ""
            start_ts = _utc_day_start(day)
            if (not codes and not others and horizon is not None and start_ts is not None
                    and start_ts + 86400.0 <= float(horizon)):
                aged = (f" This day is entirely before the oldest row the table still holds "
                        f"({_utc_iso(horizon)}), so its refusal rows have aged out at "
                        f"grid.retain_days = {REFUSAL_RETENTION_DAYS} and there is nothing to read "
                        f"either way.")
            why.append(
                f"{LOOK_NO_EXECUTION_STARTED}: 0 {ROW_MODE} executions started on this completed "
                f"UTC day. The risk channel recorded {ticks_seen} tick(s) and "
                f"{_codes_line(codes, ticks_seen)}; other channels: {_other_channels_line(others)}."
                + aged)
        if why:
            entry["needs_a_human_look"] = True
            entry["look_tags"] = tags
            entry["why"] = why
            entry["what_this_evidence_establishes"] = WHAT_A_WITHHELD_DAY_ESTABLISHES
            look_reasons[day] = why
        return entry

    for day in completed_days:
        days.append(facts(day, complete=True))
    current = facts(partial_day, complete=False) if partial_day else None

    needs_look = [d["utc_day"] for d in days if d["needs_a_human_look"]]
    notes: list[str] = []
    if evidence:
        notes.append("the lane's board reports, at the moment of this read: " + "; ".join(evidence)
                     + ". That is the board now; it says nothing about any earlier day.")
    return {
        "question": ("Per completed UTC day of the row: how many LIMITED_LIVE executions started, "
                     "how many covers settled, and what the lane counted in its refusal channels. "
                     "Numbers only -- this reader does not decide what they mean."),
        "days": days,
        "current_utc_day": current,
        "completed_days": len(days),
        "executions_started_by_utc_day": {d["utc_day"]: d["executions_started"] for d in days},
        "covers_settled_by_utc_day": {d["utc_day"]: d["covers_settled"] for d in days},
        "risk_refusals_over_the_row": refusals.get("by_code", {}),
        "risk_ticks_over_the_row": refusals.get("ticks_in_window", 0),
        "candidate_independent_over_the_row": refusals.get("candidate_independent_by_code", {}),
        "unrecognised_over_the_row": refusals.get("unrecognised_by_code", {}),
        "other_channels_over_the_row_line": _other_channels_line(
            refusals.get("other_channels_over_the_row", {}) or {}),
        "days_needing_a_human_look": needs_look,
        "why_each_day_needs_a_look": look_reasons,
        "board_evidence": evidence,
        "notes": notes,
        "what_a_tick_is": WHAT_A_TICK_IS,
        "what_a_withheld_day_establishes": WHAT_A_WITHHELD_DAY_ESTABLISHES,
        "mode_limitation": MODE_LIMITATION,
        "no_day_label_is_issued": (
            "This report labels no day, states nothing about what the lane was able to do, and "
            "states nothing about why any individual candidate was refused. It reports each day's "
            "numbers, and where those are consistent with the lane having been unable to act it "
            "withholds the verdict and names the day. Only the durable signals in row_state -- a "
            "kill file in one of the five deployed scopes, a latched breaker, the override, an "
            "ARM_STALE or non-LIMITED_LIVE lane, an unresolved material flag, a failed probe -- "
            "end a row."),
        "code_reference": {"candidate_independent": CANDIDATE_INDEPENDENT_RISK_CODES,
                           "per_candidate": PER_CANDIDATE_RISK_CODES},
        "refusals": refusals,
    }


def row_state(con, *, now: float, data_root: str, code_root: str, flag_reader=None,
              window: tuple[float, float] | None = None, completed_days: list[str] | None = None,
              partial_day: str | None = None, attempts_by_day: dict | None = None,
              covers_by_day: dict | None = None) -> dict:
    """The stop and end conditions this reader can OBSERVE, plus what it failed to observe.

    Every entry in `stop_conditions` is unambiguous and durable, and there is no other kind:

      1. a kill file present, by the DEPLOYED semantics of nodes/risk/kill.py at 59dd5ae -- the
         names `all` and `live` and the prefixed families `venue-`, `event-`, `strategy-`. Nothing
         else in that directory is a kill switch: `active()` never builds another name, so a
         stray lock file stops nothing. Those are listed in `kill.other_files` as evidence;
      2. the LATCHED daily-loss breaker, which outlives both a restart and the deletion of
         kill/live -- spec.yaml's own stop condition, and the one that ends the row rather than
         pausing it;
      3. the arming override gone, expired (an `end`, not a stop), carrying an experiment, or no
         longer at the registered caps;
      4. an ARM_STALE lane, or a lane the board reports is not in LIMITED_LIVE: `_execute` refuses
         every real order while either holds, and the lane still looks healthy;
      5. an unresolved material safety flag, through the box's own reader.

    A probe that fails names itself in `probe_errors` and sets `conclusive` false: no verdict is
    issued over a signal this reader could not read. It never invents a stop, and it never lets
    the report claim a clean IN_PROGRESS in silence.

    These file probes are POINT-IN-TIME -- they describe the box NOW -- so the caller applies them
    only to a window that runs to the present. What the lane counted inside the window is in
    `daily_record`, and it produces no stop of any kind: see `daily_record.no_day_label_is_issued`.
    """
    kill_dir = os.path.join(data_root, "kill")
    kill = probe_kill(kill_dir)
    breaker = probe_breaker(breaker_path(data_root))
    override = probe_override(os.path.join(kill_dir, "arming_override.json"), now=now)
    board = probe_board(board_path(data_root), now=now)
    flags = probe_flags(con, code_root=code_root, reader=flag_reader)

    stops: list[str] = []
    ends: list[str] = []
    errors: list[str] = []
    notes: list[str] = []

    if kill["error"]:
        errors.append(f"kill: {kill['error']}")
    else:
        for k in kill["present"]:
            stops.append(f"kill/{k['name']} is present ({k['scope']} scope -- it stops "
                         f"{k['stops']}): {k['reason']}")
        if kill["other_files"]:
            # Evidence, never a stop and never a withholding. nodes/risk/kill.active() builds only
            # the five names, so none of these stops anything on the box; the real box keeps stray
            # `.guard-failure-*.lock` and `.legacy-incident-*.lock` files here, and calling them
            # kills this reader "cannot classify" would withhold every verdict forever.
            notes.append(
                f"the kill directory also holds {', '.join(repr(n) for n in kill['other_files'])}, "
                f"which nodes/risk/kill.active() never matches (it builds only all, live, venue-*, "
                f"event-*, strategy-*), so they stop nothing on the box. Listed as evidence: "
                f"nodes/risk/health.risk_alerts would call each of them KILL_FILE_PRESENT, and a "
                f"mistyped kill file would look exactly like this")

    # The breaker, and the trap it sets: `evaluate()` returns BREAKER_LATCHED from the FILE before
    # it can latch anything, so once someone deletes kill/live nothing re-creates it. The row is
    # over and every other signal here looks clean.
    if breaker["error"] or breaker["latched"] is None:
        errors.append(f"breaker: {breaker['error'] or 'no reading from ' + breaker['path']}")
    elif breaker["latched"]:
        when = (f" at {_utc_iso(breaker['latched_utc'])}" if breaker["latched_utc"] else "")
        stops.append(
            f"the daily realised-loss breaker is LATCHED{when}: {breaker['reason'] or 'no reason recorded'}"
            f" -- nodes/risk/breaker.evaluate returns BREAKER_LATCHED before any new entry and "
            f"nodes/risk/clearance refuses every candidate. Only a human clears it, by name "
            f"(LossBreaker.reset(by=...)), nothing in ops/ calls that, and deleting kill/live does "
            f"NOT clear it. spec.yaml: one latch ENDS the row rather than pausing it")
        if kill["listed"] and not kill["live_present"]:
            notes.append(
                "THE BREAKER IS LATCHED AND THERE IS NO kill/live FILE. Deleting kill/live does "
                "not clear the breaker, and the breaker never re-creates it (evaluate() returns "
                "BREAKER_LATCHED before it can latch anything), so the lane runs, evaluates and "
                "places NO order while every kill-file check on the box -- verify_f24.sh included "
                "-- reads clean. The row ended when the breaker latched; nothing traded after it, "
                "whatever the elapsed days in this report say.")

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

    # The lane's own snapshot. An ARM_STALE lane is the blind spot every file check shares: the
    # override is present and valid-looking on disk, the kill directory is empty, and the running
    # process refuses every real order because the override no longer pins ITS code tree or limits.
    if board["error"]:
        errors.append(f"board: {board['error']}")
    if board["readable"] and board["as_of"] is not None:
        aged = "" if board["fresh"] else f" (that board is {board['age_s']}s old -- STALE)"
        stale = board["arm_stale"]
        if stale:
            text = str(stale)
            if text.lower().startswith("override expired"):
                # spec.yaml puts override expiry under `end` and exempts it from stop_conditions by
                # name, so the lane refusing orders BECAUSE of the expiry is that same end.
                ends.append(f"the lane reports ARM_STALE '{text}'{aged}: it has refused every real "
                            f"order since, so nothing traded after that moment")
            else:
                stops.append(
                    f"the lane reports ARM_STALE '{text}'{aged}: grid.check_arm set it from "
                    f"gate.stale_reason and _execute refuses EVERY real order while it is set. The "
                    f"lane still evaluates and still logs; it places nothing. spec.yaml stops on "
                    f"'any change to code, limits, hurdles, entry policy or the override other "
                    f"than its expiry'")
        if board["mode"] is not None and str(board["mode"]) != ROW_MODE:
            stops.append(f"the lane's board reports mode {board['mode']!r}, not {ROW_MODE}{aged}: "
                         f"no real F24 order can be placed in that mode")
        if board["f22_enabled"]:
            stops.append(f"the lane's board reports F22 ENABLED ({board['f22_authority']!r}){aged}; "
                         f"F24's registered arm is 'no experiment'")
        if board["caps_match_registered"] is False:
            stops.append(f"the RUNNING lane's caps {board['caps']!r} are not the registered "
                         f"{REGISTERED_CAPS}{aged} -- these are the caps the process loaded at "
                         f"start, which an override rewritten since does not change")

    if not flags["ok"]:
        errors.append(f"flags: {flags['error']}")
    elif flags["unresolved"]:
        stops.append("unresolved material safety flag(s): "
                     + ", ".join(f"{k}x{v}" for k, v in sorted(flags["unresolved"].items())))

    # What the lane counted, per UTC day. It produces NO stop and NO day label -- only numbers,
    # and a list of days whose numbers a human has to look at before a verdict is issued.
    w_start, w_end = window if window is not None else (now, now)
    refusals = probe_refusals(con, start=w_start, stop_at=w_end)
    if refusals["error"]:
        errors.append(f"refusals: {refusals['error']}")
    record = daily_record(completed_days=list(completed_days or []), partial_day=partial_day,
                          attempts_by_day=dict(attempts_by_day or {}),
                          covers_by_day=dict(covers_by_day or {}), refusals=refusals, board=board)
    notes.extend(record["notes"])

    return {"kill": kill, "breaker": breaker, "override": override, "board": board, "flags": flags,
            "refusals": refusals, "daily_record": record,
            "stop_conditions": stops, "end_conditions": ends, "probe_errors": errors,
            "notes": notes, "conclusive": not errors}


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

    # Every file probe below is POINT-IN-TIME: a kill file that was deleted, a breaker a human
    # reset (reset() wipes the reason) or an ARM_STALE the next override cleared leaves NO trace in
    # the kill directory, the breaker state or the board. What the database does hold is how many
    # LIMITED_LIVE executions started on each UTC day and how many covers settled. Those are
    # reported as the numbers they are; a day with none of the former is named for a human rather
    # than given a meaning.
    attempts_by_day: dict[str, int] = defaultdict(int)
    for r in rows:
        attempts_by_day[_utc_day(r["started_utc"])] += 1
    covers_by_day: dict[str, int] = defaultdict(int)
    for c in covers_all:
        covers_by_day[_utc_day(c["settled_ts"])] += 1
    silent_days = [d for d in completed_days if not attempts_by_day.get(d)]

    open_stake_total = round(sum(o["stake_paid_usd"] for o in open_rows), 6)
    open_unpriced = round(sum(o["contracts_without_a_price"] for o in open_rows), 6)

    # The still-running day is judged too, but only as information: it is not over, so it can
    # never be one of the row's stopped days.
    last_day = _utc_day(stop_at)
    partial_day = last_day if last_day not in set(completed_days) else None
    state = row_state(con, now=now, data_root=data_root, code_root=code_root, flag_reader=flag_reader,
                      window=(start, stop_at), completed_days=completed_days,
                      partial_day=partial_day, attempts_by_day=dict(attempts_by_day),
                      covers_by_day=dict(covers_by_day))
    record = state["daily_record"]
    # A live probe describes the lane NOW. Applying it to a closed historical window (the L141
    # calibration run) would brand that window STOP for something that happened afterwards, so the
    # findings are still printed but only bind a window that runs to the present.
    applied = end is None or end >= now
    # STOPPED is reserved for the unambiguous and durable, and there is no second source of stops:
    # nothing counted in refusal_counts stops a row, because a count per report tick cannot
    # establish that the lane was unable to trade. Days whose numbers are consistent with that
    # withhold the verdict instead, below.
    stop_lines = list(state["stop_conditions"]) if applied else []
    stopped = "; ".join(stop_lines) if stop_lines else None
    # WITHHOLD, NEVER ASSERT. A completed UTC day carrying a candidate-independent code, a code
    # this reader does not recognise, or no LIMITED_LIVE execution at all is named for a human --
    # not labelled, not called a stop. Per DAY, so one cleared candidate cannot speak for the
    # other 23 hours, which is exactly how the whitewash was produced.
    needs_look = list(record["days_needing_a_human_look"])
    # A probe that could not read its signal is NOT evidence of a quiet row. While the findings
    # bind (a window that runs to the present), an incomplete probe withholds the verdict outright:
    # spec.yaml's five verdicts are answers about a row that was able to trade, and this reader
    # cannot say that when it could not look. It is also what keeps day 7 from arriving quietly.
    #
    # The $50 end is decided on the ALL-IN realised figure: the dollars a PARTIAL left riding and
    # the dollars the protection layer spent are the operator's dollars, and the operator's plan is
    # to stop this test at $50 of them.
    loss_end = all_in_total <= -CUMULATIVE_LOSS_STOP_USD
    # ... and that end is the one thing a failed probe does NOT withhold: those dollars are gone
    # whatever the kill directory says, and LOSES_MONEY rests on the database, which WAS read.
    inconclusive = applied and stopped is None and not state["conclusive"] and not loss_end
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
    # A withheld day blocks the ending and the verdict, and it does so whether or not the $50 end
    # or the registered end has arrived -- with ONE exception, below: the $50 end is decided on
    # dollars that are in the database, so it is never withheld.
    withheld = bool(needs_look) and stopped is None and not loss_end
    ended = ((bool(end_reasons) or stopped is not None)
             and not awaiting and not inconclusive and not withheld)
    v, reason = verdict(cover_total, len(covers), ci, stopped,
                        loss_end=loss_end, all_in_total=all_in_total)
    look_days = ", ".join(needs_look)

    if stopped is not None:
        row_status, verdict_field = "STOPPED", v
    elif inconclusive:
        row_status = "INCONCLUSIVE"
        verdict_field = (
            f"INCONCLUSIVE: {len(state['probe_errors'])} stop-condition probe(s) could not read "
            f"their signal, so this report cannot say the row was able to trade over this window. "
            f"No verdict is issued (it would have read {v}); see warnings")
    elif withheld and (bool(end_reasons) or awaiting):
        row_status = "NEEDS_HUMAN_LOOK"
        verdict_field = (
            f"NEEDS_HUMAN_LOOK: the registered end was reached ({'; '.join(end_reasons)}) and "
            f"{len(needs_look)} completed UTC day(s) carry numbers this report will not interpret "
            f"({look_days}). No verdict is issued (it would have read {v}); read "
            f"daily_record.why_each_day_needs_a_look, then decide")
    elif awaiting:
        row_status = "AWAITING_SETTLEMENT"
        verdict_field = (f"AWAITING_SETTLEMENT (would be {v} once {len(open_rows)} filled "
                         f"execution(s) holding {open_stake_total:.5f} USD of stake settle)")
    elif ended:
        row_status, verdict_field = "ENDED", v
    else:
        row_status = "IN_PROGRESS"
        verdict_field = (f"IN_PROGRESS (would be {v})" if not needs_look else
                         f"IN_PROGRESS (would be {v}, but {len(needs_look)} completed UTC day(s) "
                         f"need a human look first: {look_days})")

    to_go = round(CUMULATIVE_LOSS_STOP_USD + all_in_total, 6)
    # The lane's numbers on the same line as the money, stated as numbers. No day is characterised
    # here; the only judgement on this line is whether a human still has to read a day's counts.
    lane = (f"{record['completed_days']} completed UTC day(s), "
            f"{sum(record['executions_started_by_utc_day'].values())} {ROW_MODE} execution(s) "
            f"started, {sum(record['covers_settled_by_utc_day'].values())} cover(s) settled, "
            f"{record['risk_ticks_over_the_row']} risk tick(s) recorded")
    lane += (f" | DAY(S) NEEDING A HUMAN LOOK: {look_days}" if needs_look
             else " | no completed day needs a human look")
    headline = (
        f"{row_status}: REALISED ALL-IN {all_in_total:+.5f} USD over {len(realised_rows)} settlement "
        f"row(s) | settled covers only (the verdict statistic) {cover_total:+.5f} over {len(covers)} "
        f"cover(s) | open and unsettled {len(open_rows)} execution(s), {open_stake_total:.5f} USD of "
        f"stake paid and counted in NO realised figure | lane: {lane} | the "
        f"${CUMULATIVE_LOSS_STOP_USD:.0f} end: "
        + ("REACHED -- stop the test" if loss_end
           else f"{max(0.0, to_go):.5f} USD of further realised loss away"))

    warnings = []
    if pin.get("warning"):
        warnings.append(pin["warning"])
    for n in state["notes"]:
        warnings.append(n)
    if inconclusive:
        warnings.append(
            "INCONCLUSIVE -- no verdict: " + "; ".join(state["probe_errors"])
            + (". The registered end HAS been reached (" + "; ".join(end_reasons) + ") and the row "
               "is still not ended: a window this reader could not prove was able to trade cannot "
               "produce one of spec.yaml's verdicts." if end_reasons else
               ". A row can be stopped in ways this run could not check.")
            + " Fix the probe (or stop the lane) and read again before acting on any figure above.")
    if needs_look:
        warnings.append(
            f"{len(needs_look)} COMPLETED UTC DAY(S) NEED A HUMAN LOOK BEFORE THIS ROW GETS A "
            f"VERDICT: " + "; ".join(f"{d} -- " + " | ".join(record["why_each_day_needs_a_look"][d])
                                     for d in needs_look)
            + f". {WHAT_A_WITHHELD_DAY_ESTABLISHES} No day above is labelled, nothing here says "
              f"what the lane was able to do, and the row is not reported STOPPED on any of it: "
              f"the only things that stop or end a row are in "
              f"row_state.what_may_stop_or_end_a_row.")
    for d in record["days"]:
        if d["needs_a_human_look"]:
            warnings.append(f"{d['utc_day']}: {d['executions_started']} execution(s) started, "
                            f"{d['covers_settled']} cover(s) settled, {d['risk_line']}; "
                            f"{d['other_channels_line']}.")
    if record["board_evidence"]:
        warnings.append("the lane's own board reports, at the moment of this read: "
                        + "; ".join(record["board_evidence"])
                        + ". That is the board now, not a finding about any earlier day, and it is "
                          "not a registered stop condition.")
    if silent_days:
        warnings.append(
            f"{len(silent_days)} completed UTC day(s) in this window started NO LIMITED_LIVE "
            f"execution ({', '.join(silent_days)}). {MODE_LIMITATION} Every FILE probe in "
            f"row_state is point-in-time: a kill file someone deleted, a breaker a human reset "
            f"(reset() wipes the reason) or an ARM_STALE a new override cleared leaves no trace in "
            f"them. Each of those days' counts is in daily_record.days.")
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
                   "attempts_by_started_utc_day": dict(sorted(attempts_by_day.items())),
                   "covers_settled_by_utc_day": dict(sorted(covers_by_day.items())),
                   "completed_utc_days_with_no_attempt": silent_days,
                   # spec.yaml `funnel`: "pre-wire declines by reason". This is the lane's own
                   # count of them, risk channel, over the window -- the stage that used to be
                   # readable only by grepping journald. Each code carries `n` (refusals counted)
                   # and `ticks` (report passes it appeared in); see refusal_record.what_a_tick_is.
                   "pre_wire_declines_by_risk_code": record["risk_refusals_over_the_row"],
                   "pre_wire_decline_risk_ticks": record["risk_ticks_over_the_row"],
                   "pre_wire_declines_on_other_channels": record["other_channels_over_the_row_line"],
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
            "state_file": state["breaker"]["path"],
            "latched_now": state["breaker"]["latched"],
            "latch_reason": state["breaker"]["reason"],
            "latched_utc": _utc_iso(state["breaker"]["latched_utc"]),
            "latching_is_a_registered_stop_condition": (
                "spec.yaml stop_conditions: 'the daily realised-loss breaker latching (it latches "
                "kill/live and needs a human to clear, so one latch ends the row rather than "
                "pausing it)'. The latch is this FILE, not the kill file it also writes: deleting "
                "kill/live leaves it latched, and the lane then places no order for the rest of "
                "the row while every kill-file check reads clean."),
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
        "daily_record": {k: v for k, v in record.items() if k not in ("refusals",)},
        "days_needing_a_human_look": needs_look,
        "verdict_withheld_pending_a_human_look": withheld,
        "refusal_record": state["refusals"],
        "row_state": {"stop_conditions_applied": applied,
                      "stop_conditions": state["stop_conditions"],
                      "what_may_stop_or_end_a_row": (
                          "ONLY the unambiguous and durable: a kill file present by the deployed "
                          "semantics of nodes/risk/kill.py (all, live, venue-*, event-*, "
                          "strategy-*, and nothing else in that directory); a latched breaker; the "
                          "arming override missing, expired, carrying an experiment or no longer "
                          "at the registered caps; an ARM_STALE lane or a lane not in "
                          f"{ROW_MODE}; an unresolved material safety flag; or a probe that "
                          "failed. Nothing counted in refusal_counts stops a row: those counts "
                          "withhold the verdict and name the day instead."),
                      "end_conditions": state["end_conditions"],
                      "probe_errors": state["probe_errors"],
                      "notes": state["notes"],
                      "conclusive": state["conclusive"],
                      "inconclusive_withholds_the_verdict": inconclusive,
                      "probed": ("the whole kill directory (the five deployed scopes, with every "
                                 "other file listed as evidence), the latching daily-loss breaker, "
                                 "the arming override, the lane's own board snapshot (ARM_STALE / "
                                 "mode / running caps / F22 / loop / sockets), and the thirteen "
                                 "material safety flags; plus, as NUMBERS only, what the lane "
                                 "counted in refusal_counts per UTC day"),
                      "what_this_cannot_see": (
                          "The FILE probes are POINT-IN-TIME. A kill file someone deleted, a "
                          "breaker a human reset (LossBreaker.reset wipes the reason), a "
                          "PNL_UNKNOWN that resolved and an ARM_STALE a new override cleared all "
                          "leave NO trace in them, so a stop that came and went between two daily "
                          "reads does not appear there. What the counters hold for each day is in "
                          "daily_record -- counts per report tick, which cannot establish "
                          "duration, candidate or mode -- and that record ages out at "
                          f"grid.retain_days = {REFUSAL_RETENTION_DAYS} days. Where those numbers "
                          "are consistent with the lane having been unable to trade, the day is "
                          "named and the verdict waits for a human; nothing here is asserted."),
                      "kill": state["kill"], "breaker": state["breaker"],
                      "override": state["override"], "board": state["board"],
                      "flags": state["flags"]},
        "verdict": verdict_field,
        "verdict_reason": reason,
        "warnings": warnings,
        "note": ("daily_record reports NUMBERS per completed UTC day -- executions started, covers "
                 "settled, each risk code with its count and the ticks it appeared in, the ticks "
                 "recorded that day, and the other channels in one line. It labels no day and "
                 "makes no claim about what the lane could have done. "
                 "Only a verdict with ended=true is F24's result. net.settled_covers_only is the "
                 "verdict statistic over spec.yaml's unit of observation; net.all_in_realised is the "
                 "money, and it is what the $50 end and the daily read are about. Neither includes "
                 "anything still unsettled: awaiting_settlement counts that, and the row does not "
                 "end on it. row_status INCONCLUSIVE means a stop probe could not read its signal, "
                 "so no verdict is issued at all -- not even on day 7; NEEDS_HUMAN_LOOK means the "
                 "end arrived over day(s) whose numbers this report will not interpret, so the "
                 "verdict waits for a person; STOPPED means one of the durable conditions in "
                 "row_state.what_may_stop_or_end_a_row was found, and no figure here covers the "
                 "time since."),
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
