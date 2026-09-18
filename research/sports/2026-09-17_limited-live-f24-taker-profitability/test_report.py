"""F24 report pins: the verdict follows the registered rule, and the interval is event-clustered.

The report was also calibrated on the box against L141's window: all four covers total -$0.16449
(-$0.041122 each) and, excluding the scalar cover, three total +$0.82908 ($0.27636 each). That
calibration is pinned below on L141's ACTUAL window (`test_the_l141_window_still_calibrates`).
Nothing here may change how an ORDINARY reconciled cover's realised net is summed, or that
calibration stops meaning anything.

TWO MONEY FIGURES. `net.settled_covers_only` is the verdict statistic -- spec.yaml's unit of
observation, RECONCILED covers with both legs filled, truncated at the registered 30. Every test
that used to read `net.total_usd` now reads it there, and reads `net.all_in_realised.total_usd`
for the money: every realised dollar in the window, PARTIAL and UNWOUND and unreleased included,
which is what the $50 cumulative-loss end is decided on.

The rest of this file is the 2026-09-17 audit's six defects, one test each, the start pin, the
two-figure separation with the registered-end truncation and the unsettled-cover rule beside it,
and -- at the bottom -- the round-5 pins: the report states each UTC day's NUMBERS and withholds
the verdict over a day it will not interpret, instead of labelling the day and stopping the row.
"""
from __future__ import annotations

import importlib.util
import base64
import gzip
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("f24_report", Path(__file__).with_name("report.py"))
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)

HERE = Path(__file__).parent
REPORT_PY = HERE / "report.py"
CHECK = HERE / "check_f24.sh"

#: The only fully measured window (spec.yaml `known_at_registration`), to the microsecond.
L141_START = 1789418782.132788
L141_END = 1789505182.132788

#: spec.yaml `verdicts`. Anything else in the `verdict` field is a status, not a result.
VERDICTS = {"LOSES_MONEY", "MAKES_MONEY_PROVEN", "MAKES_MONEY_NOT_PROVEN", "INSUFFICIENT", "STOP"}


# ----------------------------------------------------------------------------------------- fixtures


#: nodes/store_tuples/store.py REFUSAL_COUNTS_DDL at 59dd5ae, verbatim. The lane creates it on its
#: first flush and it is live on the box (26,947 rows on 2026-09-17), so every fixture carries it:
#: a database WITHOUT it is the exception, and `_drop_refusals` is how a test asks for that.
REFUSAL_DDL = ("CREATE TABLE refusal_counts(seen_ts REAL NOT NULL, channel TEXT NOT NULL, "
               "code TEXT NOT NULL, league TEXT NOT NULL, n INTEGER NOT NULL)")
REFUSAL_INDEX = "CREATE INDEX refusal_counts_ts ON refusal_counts(seen_ts)"


def _db(tmp_path):
    """The executions table as it shipped: no `*_avg_price` / `*_unwound` (records._LATER_COLUMNS)."""
    p = tmp_path / "t.sqlite"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE executions(execution_id TEXT, event_id TEXT, league TEXT, mode TEXT, "
                "state TEXT, started_utc REAL, first_filled REAL, hedge_filled REAL)")
    con.execute("CREATE TABLE execution_settlements(execution_id TEXT, realized_usd REAL, released INTEGER, "
                "kind TEXT, settled_ts REAL)")
    con.execute(REFUSAL_DDL)
    con.execute(REFUSAL_INDEX)
    return p, con


def _db_full(tmp_path):
    """The executions table after the 2026-09-08 ALTER: the protection and price columns are there."""
    p = tmp_path / "full.sqlite"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE executions(execution_id TEXT, event_id TEXT, league TEXT, mode TEXT, "
                "state TEXT, started_utc REAL, first_filled REAL, hedge_filled REAL, "
                "first_avg_price REAL, hedge_avg_price REAL, first_unwound REAL, hedge_unwound REAL)")
    con.execute("CREATE TABLE execution_settlements(execution_id TEXT, realized_usd REAL, released INTEGER, "
                "kind TEXT, settled_ts REAL)")
    con.execute(REFUSAL_DDL)
    con.execute(REFUSAL_INDEX)
    return p, con


def _refuse(con, ts, code, n=1, *, channel="risk", league="mlb"):
    """One report tick's worth of refusals, exactly as grid.py flushes them: COUNTS, not rows."""
    con.execute("INSERT INTO refusal_counts VALUES(?,?,?,?,?)", (ts, channel, code, league, n))


def _working_day(con, day_start, *, ticks=4):
    """What a day the lane WAS trading on looks like in its own record: per-candidate refusals
    only. MIN_PROFIT and IN_FLIGHT are verdicts on a candidate, not on the lane."""
    for i in range(ticks):
        t = day_start + 3600.0 * (i + 1)
        _refuse(con, t, "MIN_PROFIT", 37)
        _refuse(con, t, "IN_FLIGHT", 412)


def _blocked_day(con, day_start, code, *, ticks=4, n=1500):
    """What a day the lane could NOT trade on looks like: a blocking code, every tick."""
    for i in range(ticks):
        _refuse(con, day_start + 3600.0 * (i + 1), code, n)


def _drop_refusals(p):
    """A database whose lane has never ticked since L113 shipped -- no refusal record at all."""
    con = sqlite3.connect(p)
    con.execute("DROP TABLE refusal_counts")
    con.commit()
    con.close()


def _exec(con, eid, event, state, started, *, mode="LIMITED_LIVE", first=10.0, hedge=10.0, league="mlb"):
    con.execute("INSERT INTO executions VALUES(?,?,?,?,?,?,?,?)",
                (eid, event, league, mode, state, started, first, hedge))


def _exec_full(con, eid, event, state, started, *, mode="LIMITED_LIVE", first=10.0, hedge=10.0,
               league="mlb", first_price=None, hedge_price=None, first_unwound=0.0, hedge_unwound=0.0):
    con.execute("INSERT INTO executions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, event, league, mode, state, started, first, hedge,
                 first_price, hedge_price, first_unwound, hedge_unwound))


def _settle(con, eid, usd, *, released=1, kind="COVER", ts=200.0):
    con.execute("INSERT INTO execution_settlements VALUES(?,?,?,?,?)", (eid, usd, released, kind, ts))


def _override(**over):
    d = {"operator_statement": "I approve", "signed_by": "Bernardo", "mode": "LIMITED_LIVE",
         "caps": {"stake_usd": 30.0, "max_contracts": 25.0, "day_notional_usd": 500.0},
         "expires_utc": "2099-01-01T00:00:00Z"}
    d.update(over)
    return d


def _live(tmp_path, *, override="default", kill=(), start_pin=None, breaker=None):
    """A stand-in for the box's /srv/janus. Nothing here is ever written by the reader.

    `kill` names files in the kill directory -- any of nodes/risk/kill.py's five scopes, and
    anything else, which is what an unrecognised file looks like. `breaker` is the latching
    daily-loss breaker's state file (kernel/paths.BREAKER_PATH, inside the same directory): a dict
    is written as JSON, a string verbatim (for the unreadable case).
    """
    root = tmp_path / "srv"
    (root / "kill").mkdir(parents=True, exist_ok=True)
    (root / "release-audit").mkdir(parents=True, exist_ok=True)
    if override == "default":
        override = _override()
    if override is not None:
        (root / "kill" / "arming_override.json").write_text(json.dumps(override))
    for name in kill:
        (root / "kill" / name).write_text(json.dumps({"reason": f"{name} latched", "latched_utc": 1.0}))
    if breaker is not None:
        (root / "kill" / "breaker.json").write_text(
            breaker if isinstance(breaker, str) else json.dumps(breaker))
    if start_pin is not None:
        (root / "release-audit" / "f24_start_utc").write_text(f"{start_pin}\n")
    return root


def _latched(reason="daily realized loss -25.31 USD breached 25.00 on 2026-09-19", **over):
    """What nodes/risk/breaker.LossBreaker._save writes once it has latched."""
    d = {"latched": True, "reason": reason, "latched_utc": 1789500000.0}
    d.update(over)
    return d


def _board_doc(**over):
    """grid.Supervisor.board(), as write_board leaves it: here, a healthy armed LIMITED_LIVE lane.

    `as_of` is filled in by _kw with the same `now` the reader is given, so the default board is
    one second old exactly as the running lane's is.
    """
    d = {"mode": "LIMITED_LIVE",
         "caps": {"stake_usd": 30.0, "max_contracts": 25.0, "day_notional_usd": 500.0},
         "arm_stale": None, "f22_enabled": False,
         "f22_authority": "no experiment block in the override, so the historical taker entry stands",
         "loop_lag_s": 0.4, "stalled": False, "blocked": 0,
         # Both venues streaming: an F24 cover needs BOTH, and grid.board() reports each socket's
         # own `connected`. A board with no sockets is a lane that cannot complete a cover.
         "sockets": {"kalshi": {"connected": True, "frames": 91234, "age_s": 0.2, "errors": 0},
                     "polymarket": {"connected": True, "frames": 40311, "age_s": 0.3, "errors": 0}},
         "games": []}
    d.update(over)
    return d


def _quiet(_con, _flag):
    return []


def _kw(root, *, board="fresh", **extra):
    """Reader kwargs against the stand-in box, plus the lane's one-second board snapshot.

    `board`: "fresh" writes a healthy armed lane stamped at `now`; a dict writes that snapshot
    (`as_of` defaults to `now`); None writes no board at all, which is what a dead lane, a lane
    started with a different --board, or an unreadable data root looks like from here.
    """
    if board is not None:
        doc = _board_doc() if board == "fresh" else dict(board)
        doc.setdefault("as_of", extra.get("now"))
        (Path(root) / "board").mkdir(parents=True, exist_ok=True)
        (Path(root) / "board" / "board.json").write_text(json.dumps(doc))
    kw = {"data_root": str(root), "code_root": str(root / "no-such-checkout"), "flag_reader": _quiet}
    kw.update(extra)
    return kw


def _covers(out):
    """The verdict statistic: spec.yaml's unit of observation, and nothing else."""
    return out["net"]["settled_covers_only"]


def _money(out):
    """Every realised dollar in the window. What the $50 end is decided on."""
    return out["net"]["all_in_realised"]


# ------------------------------------------------------------------- the registered rule, unchanged


def test_registered_constants():
    assert (rp.END_COVERS, rp.END_DAYS, rp.CUMULATIVE_LOSS_STOP_USD) == (30, 7, 50.0)
    assert (rp.MIN_COVERS_FOR_VERDICT, rp.RESAMPLES, rp.SEED) == (10, 10000, 170924)
    assert rp.SCHEMA == "janus.f24.taker_profitability_report.v1"


def test_a_stop_overrides_every_other_verdict():
    assert rp.verdict(5.0, 40, {"lower_95": 0.1}, "breaker latched")[0] == "STOP"


def test_too_few_covers_is_insufficient_whatever_the_total():
    assert rp.verdict(9.0, 9, {"lower_95": 0.5}, None)[0] == "INSUFFICIENT"


def test_a_net_loss_loses_money():
    assert rp.verdict(-0.01, 30, {"lower_95": -0.2}, None)[0] == "LOSES_MONEY"


def test_proof_needs_the_interval_strictly_above_zero():
    assert rp.verdict(3.0, 30, {"lower_95": 0.01}, None)[0] == "MAKES_MONEY_PROVEN"
    assert rp.verdict(3.0, 30, {"lower_95": 0.0}, None)[0] == "MAKES_MONEY_NOT_PROVEN"
    assert rp.verdict(3.0, 30, {"lower_95": -0.4}, None)[0] == "MAKES_MONEY_NOT_PROVEN"
    assert rp.verdict(3.0, 30, None, None)[0] == "MAKES_MONEY_NOT_PROVEN"


def test_the_interval_resamples_events_not_covers():
    """Two covers on one event must move together; a per-cover bootstrap would understate spread."""
    covers = ([{"event_id": "big", "realized_usd": -1.0}] * 2
              + [{"event_id": f"e{i}", "realized_usd": 0.3} for i in range(8)])
    ci = rp.clustered_interval(covers)
    assert ci["events"] == 9 and ci["resamples"] == 10000 and ci["seed"] == 170924
    assert ci["lower_95"] < 0 < ci["upper_95"]
    assert rp.clustered_interval(covers) == ci, "deterministic"


def test_one_event_gives_no_interval():
    assert rp.clustered_interval([{"event_id": "a", "realized_usd": 1.0}] * 3) is None


def test_only_released_settlements_are_scored_and_unsettled_fills_are_counted(tmp_path):
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _exec(con, "b", "e2", "HEDGED", 101.0)          # filled, not yet settled
    _exec(con, "c", "e3", "BOOK_MOVED", 102.0, first=0.0, hedge=0.0)   # declined before the wire
    _exec(con, "d", "e4", "RECONCILED", 50.0)       # before the window
    _settle(con, "a", 0.4)
    _settle(con, "d", 9.0, ts=60.0)
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))
    assert out["funnel"]["executions"] == 3 and out["funnel"]["settled_covers"] == 1
    assert out["funnel"]["filled_not_yet_settled"] == 1
    assert out["funnel"]["no_position"] == 1, "the pre-wire decline held nothing"
    assert _covers(out)["total_usd"] == 0.4
    assert _money(out)["total_usd"] == 0.4, "no non-cover money here, so the two figures agree"


def test_the_l141_window_still_calibrates(tmp_path):
    """THE CALIBRATION. L141's real window, to the microsecond: four covers, -0.16449, -0.041122
    each, nothing excluded -- and the three non-scalar covers +0.82908, 0.27636 each."""
    p, con = _db(tmp_path)
    ids = ("L141a", "L141b", "L141c", "L141scalar")
    for i, (eid, usd) in enumerate(zip(ids, (0.27636, 0.27636, 0.27636, -0.99357))):
        _exec(con, eid, f"e{i}", "RECONCILED", L141_START + 60.0 * (i + 1))
        _settle(con, eid, usd, ts=L141_START + 3600.0 * (i + 1))
    con.commit()
    out = rp.run(str(p), L141_START, L141_END, **_kw(_live(tmp_path), now=L141_END + 86400.0))

    assert out["funnel"]["settled_covers"] == 4
    assert _covers(out)["covers"] == 4
    assert _covers(out)["total_usd"] == -0.16449
    assert _covers(out)["per_settled_cover_usd"] == -0.041122
    assert _money(out)["total_usd"] == -0.16449, "nothing wrongly excluded and nothing extra"
    assert out["funnel"]["excluded_non_cover_settlements"]["count"] == 0
    assert out["funnel"]["excluded_wrong_mode"]["count"] == 0
    assert out["funnel"]["filled_not_yet_settled"] == 0 and out["funnel"]["no_position"] == 0
    assert out["registered_end"]["truncated"] is False
    assert out["registered_end"]["settled_covers_in_window"] == 4
    assert out["selection"]["scored_cover_execution_ids"] == sorted(ids)
    assert out["window"]["elapsed_days"] == 1.0
    assert out["window"]["completed_utc_days"] == [], "24 h straddling midnight completes no UTC day"

    three = rp.run(str(p), L141_START, L141_END, (), ["L141scalar"],
                   **_kw(_live(tmp_path), now=L141_END + 86400.0))
    assert _covers(three)["covers"] == 3
    assert _covers(three)["total_usd"] == 0.82908
    assert _covers(three)["per_settled_cover_usd"] == 0.27636


def test_an_unfinished_row_says_in_progress(tmp_path):
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    out = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path), now=300.0))
    assert out["ended"] is False and out["verdict"].startswith("IN_PROGRESS")
    assert out["row_status"] == "IN_PROGRESS"


# --------------------------------------------------- defect 1: a PARTIAL is not a completed cover


def test_a_partial_settlement_is_not_scored_as_a_cover(tmp_path):
    """spec.yaml's unit is a RECONCILED execution whose BOTH legs filled. A PARTIAL row left naked
    contracts: its payoff is a directional gamble, and it must not enter F24's realised net."""
    p, con = _db(tmp_path)
    _exec(con, "good", "e1", "RECONCILED", 100.0, first=10.0, hedge=10.0)
    _settle(con, "good", 0.30, kind="COVER")
    _exec(con, "naked", "e2", "RECONCILED", 101.0, first=10.0, hedge=4.0)
    _settle(con, "naked", 5.75, kind="PARTIAL")     # a directional win, not a cover's return
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))
    assert out["funnel"]["settled_covers"] == 1
    assert _covers(out)["total_usd"] == 0.30, "the naked leg's payoff must not enter the realised net"
    assert out["selection"]["scored_cover_execution_ids"] == ["good"]
    dropped = out["funnel"]["excluded_non_cover_settlements"]
    assert dropped["count"] == 1 and dropped["by_kind"] == {"PARTIAL": 1}
    assert dropped["realized_usd"] == 5.75, "excluded, but never silently"
    assert [r["execution_id"] for r in dropped["rows"]] == ["naked"]


def test_an_unwound_protection_settlement_is_not_scored_as_a_cover(tmp_path):
    """records.write_unwind_settlement writes released=1 with kind UNWOUND: the protection layer's
    cost on an execution that never became a cover. Nothing is held; it is not a settled cover."""
    p, con = _db(tmp_path)
    _exec(con, "u", "e1", "UNWOUND", 100.0, first=10.0, hedge=0.0)
    _settle(con, "u", -1.85, kind="UNWOUND")
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))
    assert out["funnel"]["settled_covers"] == 0 and _covers(out)["total_usd"] == 0.0
    assert _covers(out)["per_settled_cover_usd"] is None
    assert out["funnel"]["excluded_non_cover_settlements"]["by_kind"] == {"UNWOUND": 1}
    assert out["funnel"]["excluded_non_cover_settlements"]["realized_usd"] == -1.85


def test_a_legacy_null_kind_falls_back_to_the_fills(tmp_path):
    """One production row predates the `kind` column; it is judged on the same test on the fills."""
    p, con = _db(tmp_path)
    _exec(con, "full", "e1", "RECONCILED", 100.0, first=7.0, hedge=7.0)
    _settle(con, "full", 0.2, kind=None)
    _exec(con, "part", "e2", "RECONCILED", 101.0, first=7.0, hedge=3.0)
    _settle(con, "part", 0.9, kind=None)
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))
    assert out["selection"]["scored_cover_execution_ids"] == ["full"]
    assert _covers(out)["total_usd"] == 0.2
    assert _money(out)["total_usd"] == 1.1, "the naked row's dollars are still the operator's"


# --------------------------------- the two money figures: the verdict statistic, and the money


def test_partial_and_unwound_dollars_leave_the_cover_figure_and_stay_in_the_money(tmp_path):
    """The separation this reader exists for. A PARTIAL's directional payoff and the protection
    layer's UNWOUND cost are NOT covers -- and they ARE the operator's dollars, so they must be
    out of `settled_covers_only` and in `all_in_realised`, never silently dropped from both."""
    p, con = _db(tmp_path)
    _exec(con, "cover", "e1", "RECONCILED", 100.0, first=10.0, hedge=10.0)
    _settle(con, "cover", 0.30, kind="COVER")
    _exec(con, "naked", "e2", "RECONCILED", 101.0, first=10.0, hedge=4.0)
    _settle(con, "naked", -12.50, kind="PARTIAL")
    _exec(con, "unwound", "e3", "UNWOUND", 102.0, first=10.0, hedge=0.0)
    _settle(con, "unwound", -1.85, kind="UNWOUND")
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))

    assert _covers(out)["covers"] == 1
    assert _covers(out)["total_usd"] == 0.30, "the verdict statistic sees covers only"
    assert _money(out)["total_usd"] == -14.05, "0.30 - 12.50 - 1.85: every realised dollar"
    assert _money(out)["settlement_rows"] == 3
    assert _money(out)["by_kind_usd"] == {"COVER": 0.3, "PARTIAL": -12.5, "UNWOUND": -1.85}
    assert out["end_rule"]["cumulative_loss_end_is_decided_on"] == "net.all_in_realised.total_usd"
    assert out["headline"].startswith("IN_PROGRESS: REALISED ALL-IN -14.05000")
    assert any("the two money figures differ" in w for w in out["warnings"])


def test_an_unreleased_settlement_is_not_a_cover_but_its_dollars_are_money(tmp_path):
    """settle_executions writes the row once every venue is final. If the reservation was not
    released the execution never reached RECONCILED -- so it is not a cover, and the money is
    still gone. It may not vanish from both figures the way it used to."""
    p, con = _db(tmp_path)
    _exec(con, "held", "e1", "SETTLED", 100.0, first=10.0, hedge=10.0)
    _settle(con, "held", -3.40, released=0, kind="COVER")
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))
    assert _covers(out)["covers"] == 0 and _covers(out)["total_usd"] == 0.0
    assert _money(out)["total_usd"] == -3.40
    row = out["funnel"]["excluded_non_cover_settlements"]["rows"][0]
    assert row["execution_id"] == "held" and row["released"] is False
    assert "not released" in row["excluded_because"]


def test_the_funnel_never_calls_an_unreleased_settlement_row_released(tmp_path):
    """`released_settlement_rows` counted every settlement row once unreleased ones started
    landing in the non-cover bucket. A count named `released` that includes unreleased rows is a
    field that lies, on a report the operator reads daily to decide whether to stop."""
    p, con = _db(tmp_path)
    _exec(con, "cover", "e1", "RECONCILED", 100.0)
    _settle(con, "cover", 0.30, kind="COVER")
    _exec(con, "held", "e2", "SETTLED", 101.0)
    _settle(con, "held", -3.40, released=0, kind="COVER")
    _exec(con, "naked", "e3", "RECONCILED", 102.0, first=10.0, hedge=4.0)
    _settle(con, "naked", -1.00, kind="PARTIAL")
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))
    f = out["funnel"]
    assert f["settlement_rows"] == 3
    assert f["released_settlement_rows"] == 2, "the unreleased one is not a released row"
    assert f["unreleased_settlement_rows"] == 1
    assert any("WITHOUT releasing" in w and "held" in w for w in out["warnings"])


def test_paper_dollars_never_reach_either_money_figure(tmp_path):
    """The documented way back when the override expires is PAPER_EXECUTION, in the same database.
    The all-in figure is the widest net this reader casts; the mode filter still bounds it."""
    p, con = _db(tmp_path)
    _exec(con, "real", "e1", "RECONCILED", 100.0)
    _settle(con, "real", -0.30)
    _exec(con, "paperpartial", "e2", "RECONCILED", 101.0, mode="PAPER_EXECUTION", first=10.0, hedge=2.0)
    _settle(con, "paperpartial", 99.00, kind="PARTIAL")
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))
    assert _covers(out)["total_usd"] == -0.30 and _money(out)["total_usd"] == -0.30
    assert out["funnel"]["excluded_wrong_mode"]["execution_ids"] == ["paperpartial"]


# ------------------------------------------------------------- defect 2: stop conditions are detected


def test_a_latched_kill_stops_the_row(tmp_path):
    """The $25 daily breaker latches kill/live and needs a human. One latch ends the row."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    out = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path, kill=("live",)), now=300.0))
    assert out["ended"] is True and out["verdict"] == "STOP"
    assert "kill/live is present" in out["verdict_reason"]
    assert out["row_state"]["kill"]["live_present"] is True
    assert out["row_state"]["kill"]["reasons"]["live"] == "live latched"


def test_a_vanished_override_stops_the_row(tmp_path):
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    out = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path, override=None), now=300.0))
    assert out["ended"] is True and out["verdict"] == "STOP"
    assert "arming override" in out["verdict_reason"] and "gone" in out["verdict_reason"]


def test_an_experiment_block_appearing_on_the_override_stops_the_row(tmp_path):
    """F24's arm is 'no experiment'. An experiment block is a change to the override: a stop."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    root = _live(tmp_path, override=_override(experiment={"row_id": "F22"}))
    out = rp.run(str(p), 90.0, None, **_kw(root, now=300.0))
    assert out["ended"] is True and out["verdict"] == "STOP"
    assert "experiment block" in out["verdict_reason"]


def test_a_raised_cap_on_the_override_stops_the_row(tmp_path):
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    root = _live(tmp_path, override=_override(
        caps={"stake_usd": 60.0, "max_contracts": 25.0, "day_notional_usd": 500.0}))
    out = rp.run(str(p), 90.0, None, **_kw(root, now=300.0))
    assert out["ended"] is True and out["verdict"] == "STOP"
    assert out["row_state"]["override"]["caps_match_registered"] is False


def test_an_expired_override_ends_the_row_but_is_not_a_stop(tmp_path):
    """spec.yaml puts override expiry under `end`, and stop_conditions exempt it by name."""
    p, con = _db(tmp_path)
    for i in range(12):
        _exec(con, f"c{i}", f"e{i}", "RECONCILED", 100.0 + i)
        _settle(con, f"c{i}", 0.25)
    con.commit()
    root = _live(tmp_path, override=_override(expires_utc="1970-01-01T00:00:00Z"))
    out = rp.run(str(p), 90.0, None, **_kw(root, now=300.0))
    assert out["ended"] is True
    assert out["verdict"] != "STOP", "an expiry is an end, not a safety condition firing"
    assert out["row_state"]["override"]["expired"] is True
    assert any("expired" in e for e in out["end_reasons"])


def test_an_unresolved_material_flag_stops_the_row(tmp_path):
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()

    def reader(_con, flag):
        return [(1, 250.0, flag, "naked")] if flag == "ORPHAN_FILL" else []

    out = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path), now=300.0, flag_reader=reader))
    assert out["ended"] is True and out["verdict"] == "STOP"
    assert "ORPHAN_FILL" in out["verdict_reason"]
    assert out["row_state"]["flags"]["unresolved"] == {"ORPHAN_FILL": 1}


def test_the_reader_checks_the_same_thirteen_flag_kinds_arm_f24_checks():
    text = (HERE / "arm_f24.sh").read_text()
    block = text.split("unresolved_flag_rows(con, f)) for f in (", 1)[1].split(")}", 1)[0]
    assert set(re.findall(r"[A-Z][A-Z0-9_]+", block)) == set(rp.MATERIAL_FLAGS)
    assert len(rp.MATERIAL_FLAGS) == 13


def test_a_broken_flag_probe_warns_instead_of_reporting_a_clean_in_progress(tmp_path):
    """Degrade with a named field. Never crash, and never claim IN_PROGRESS in silence.

    Round 3 strengthened this: a probe that could not read its signal now withholds the verdict
    outright (INCONCLUSIVE) rather than reading IN_PROGRESS with a warning attached, because
    IN_PROGRESS is itself a claim -- that the row is running and able to trade.
    """
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()

    def reader(_con, _flag):
        raise sqlite3.OperationalError("no such table: lane_flags")

    out = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path), now=300.0, flag_reader=reader))
    assert out["row_status"] == "INCONCLUSIVE"
    assert out["verdict"] not in VERDICTS and out["verdict"].startswith("INCONCLUSIVE")
    assert out["ended"] is False
    assert out["row_state"]["conclusive"] is False
    assert out["row_state"]["flags"]["ok"] is False
    assert any("flags:" in w for w in out["warnings"])
    assert "incomplete" in out["verdict_reason"]


def test_an_unreadable_override_is_a_named_probe_failure_not_a_silent_pass(tmp_path):
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    root = _live(tmp_path)
    (root / "kill" / "arming_override.json").write_text("{not json")
    out = rp.run(str(p), 90.0, None, **_kw(root, now=300.0))
    assert out["row_state"]["conclusive"] is False
    assert out["row_state"]["override"]["readable"] is False
    assert any("override:" in w for w in out["warnings"])


def test_a_closed_historical_window_reports_live_stops_without_applying_them(tmp_path):
    """The L141 calibration run must not be branded STOP by something that happened afterwards --
    but the live stop must still be on the face of the report."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path, kill=("live",)), now=99999.0))
    assert out["row_state"]["stop_conditions_applied"] is False
    assert out["row_state"]["stop_conditions"], "still reported"
    assert out["verdict"].startswith("IN_PROGRESS")
    assert any("RIGHT NOW" in w for w in out["warnings"])


# ---------------------------- round 3: the OTHER ways the deployed lane is stopped
#
# The 2026-09-17 round-3 audit found one family of blockers: this reader recognised TWO of the
# ways the lane at 59dd5ae can be stopped (kill/live and kill/all) out of at least seven. Each
# test below is one of the missing five, and each fails against the round-2 reader.


@pytest.mark.parametrize("name,scope", [
    ("all", "all"), ("live", "live"), ("venue-polymarket", "venue"),
    ("event-KXNFLGAME-26SEP21DETBAL", "event"), ("strategy-v3.2.1", "strategy")])
def test_every_kill_scope_in_the_directory_stops_the_row(tmp_path, name, scope):
    """nodes/risk/kill.py at 59dd5ae has FIVE scopes in ONE directory and `active()` honours all
    five. A reader that probes two names reports a clean IN_PROGRESS while a venue-, event- or
    strategy- file refuses entries -- and the operator's daily read is the only thing enforcing
    the $50 and 30-cover ends."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    out = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path, kill=(name,)), now=300.0))

    assert out["row_status"] == "STOPPED"
    assert out["ended"] is True and out["verdict"] == "STOP"
    assert f"kill/{name} is present" in out["verdict_reason"], "named, with its own reason"
    assert f"{name} latched" in out["verdict_reason"]
    assert out["row_state"]["kill"]["scopes"] == [scope]
    assert out["row_state"]["kill"]["names"] == [name]
    assert [k["name"] for k in out["row_state"]["kill"]["present"]] == [name]


def test_several_kill_files_are_each_reported_by_name(tmp_path):
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    root = _live(tmp_path, kill=("venue-kalshi", "strategy-v3.2.1"))
    out = rp.run(str(p), 90.0, None, **_kw(root, now=300.0))
    assert out["row_state"]["kill"]["names"] == ["strategy-v3.2.1", "venue-kalshi"]
    assert "kill/venue-kalshi is present" in out["verdict_reason"]
    assert "kill/strategy-v3.2.1 is present" in out["verdict_reason"]
    assert len(out["row_state"]["stop_conditions"]) == 2


def test_the_two_non_kill_files_in_the_kill_directory_are_not_read_as_kills(tmp_path):
    """kernel/paths.py keeps breaker.json and arming_override.json in KILL_ROOT. Neither is a
    kill switch: health.risk_alerts skips exactly these two names, and so does this."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    root = _live(tmp_path, breaker={"latched": False, "reason": "", "latched_utc": None})
    out = rp.run(str(p), 90.0, None, **_kw(root, now=300.0))
    assert out["row_state"]["kill"]["names"] == []
    assert out["row_state"]["kill"]["non_kill_files"] == ["arming_override.json", "breaker.json"]
    assert out["row_state"]["stop_conditions"] == []
    assert out["row_status"] == "IN_PROGRESS" and out["row_state"]["conclusive"] is True


def test_a_file_that_is_not_one_of_the_five_scopes_is_evidence_never_a_stop(tmp_path):
    """`kill/live.json`, and the stray `.guard-failure-*.lock` files the REAL box keeps in this
    directory, stop NOTHING: nodes/risk/kill.active() only ever builds the five names. Calling
    them kills this reader 'cannot classify' would make every read of the real box indeterminate
    forever, which is noise, not caution. They are listed by name and the row is untouched."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    strays = ("live.json", ".guard-failure-2026-09-11.lock", ".legacy-incident-0007.lock")
    out = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path, kill=strays), now=300.0))

    assert out["row_state"]["kill"]["other_files"] == sorted(strays)
    assert out["row_state"]["kill"]["present"] == [], "not one of them is a kill"
    assert out["row_state"]["stop_conditions"] == []
    assert out["row_state"]["conclusive"] is True, "a stray file is not a failed probe"
    assert out["row_status"] == "IN_PROGRESS"
    assert out["days_needing_a_human_look"] == []
    note = "; ".join(out["row_state"]["notes"])
    assert all(name in note for name in strays), "named, so a mistyped kill is still visible"
    assert "stop nothing on the box" in note
    assert rp.kill_scope("venue-") is None, "a bare prefix names no venue and is not a kill"
    assert rp.kill_scope("venue-kalshi") == "venue" and rp.kill_scope("live") == "live"


def test_a_latched_breaker_stops_the_row_even_with_no_kill_file(tmp_path):
    """spec.yaml's own stop condition. nodes/risk/breaker.py: the latch is the FILE; `evaluate()`
    returns BREAKER_LATCHED from it before it can latch anything, so once a human deletes
    kill/live nothing re-creates it, `clearance.clear()` refuses every candidate, and the lane
    places no order for the rest of the row while every kill-file check reads clean."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    root = _live(tmp_path, breaker=_latched())
    out = rp.run(str(p), 90.0, None, **_kw(root, now=300.0))

    assert out["row_status"] == "STOPPED"
    assert out["ended"] is True and out["verdict"] == "STOP"
    assert "breaker is LATCHED" in out["verdict_reason"]
    assert "breached 25.00" in out["verdict_reason"], "the breaker's own recorded reason"
    assert out["row_state"]["breaker"]["latched"] is True
    assert out["row_state"]["kill"]["names"] == [], "no kill file: that is the point"
    assert any("NO kill/live FILE" in n for n in out["row_state"]["notes"])
    assert any("NO kill/live FILE" in w for w in out["warnings"])
    assert out["daily_loss_breaker"]["latched_now"] is True


def test_a_cleared_breaker_with_a_kill_present_still_stops_on_the_kill(tmp_path):
    """The two signals are independent. A breaker file that says latched=false (a human ran
    LossBreaker.reset) does not un-stop a row whose kill file is still in place."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    root = _live(tmp_path, kill=("live",), breaker={"latched": False, "reason": "", "latched_utc": None})
    out = rp.run(str(p), 90.0, None, **_kw(root, now=300.0))

    assert out["row_state"]["breaker"]["latched"] is False
    assert out["row_state"]["kill"]["live_present"] is True
    assert out["row_status"] == "STOPPED" and out["verdict"] == "STOP"
    assert "kill/live is present" in out["verdict_reason"]
    assert "breaker" not in out["verdict_reason"], "the cleared breaker is not reported as a stop"
    assert not any("NO kill/live FILE" in n for n in out["row_state"]["notes"])


def test_an_unreadable_breaker_state_is_a_named_probe_failure(tmp_path):
    """The deployed LossBreaker._load would raise on it and health.risk_alerts treats it as
    latched. Either way it is not evidence of a row that could trade."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    out = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path, breaker="{not json"), now=300.0))

    assert out["row_state"]["breaker"]["latched"] is None
    assert out["row_state"]["conclusive"] is False
    assert out["row_status"] == "INCONCLUSIVE" and out["verdict"] not in VERDICTS
    assert any("breaker:" in e for e in out["row_state"]["probe_errors"])


def test_an_arm_stale_lane_stops_the_row(tmp_path):
    """The blind spot every file check shares: the override is on disk and valid-looking, the kill
    directory is empty, and the RUNNING process refuses every real order because the override no
    longer pins its code tree. grid.check_arm states it on the board outright."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    stale = _board_doc(arm_stale="override pins a different code tree (running 4f1c9ab2)")
    out = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path), now=300.0, board=stale))

    assert out["row_status"] == "STOPPED"
    assert out["ended"] is True and out["verdict"] == "STOP"
    assert "ARM_STALE" in out["verdict_reason"] and "different code tree" in out["verdict_reason"]
    assert out["row_state"]["board"]["arm_stale"].startswith("override pins a different code tree")
    assert out["row_state"]["board"]["fresh"] is True
    assert out["row_state"]["kill"]["names"] == [] and out["row_state"]["override"]["present"] is True


def test_an_arm_stale_from_the_override_expiring_is_an_end_not_a_stop(tmp_path):
    """spec.yaml exempts the expiry by name ('any change to ... the override other than its
    expiry') and lists it under `end`. The lane refusing orders BECAUSE of that expiry is the
    same end, not a safety condition firing."""
    p, con = _db(tmp_path)
    for i in range(12):
        _exec(con, f"c{i}", f"e{i}", "RECONCILED", 100.0 + i)
        _settle(con, f"c{i}", 0.25)
    con.commit()
    board = _board_doc(arm_stale="override expired at 2026-09-24T00:00:00Z")
    out = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path), now=300.0, board=board))

    assert out["verdict"] != "STOP"
    assert out["row_status"] == "ENDED" and out["ended"] is True
    assert any("ARM_STALE" in e and "expired" in e for e in out["end_reasons"])


def test_a_lane_that_dropped_below_limited_live_stops_the_row(tmp_path):
    """Switching to PAPER_EXECUTION is the documented way back when the override expires. A lane
    in it places no F24 money at all, and the kill directory says nothing about it."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    out = rp.run(str(p), 90.0, None,
                 **_kw(_live(tmp_path), now=300.0, board=_board_doc(mode="PAPER_EXECUTION")))
    assert out["row_status"] == "STOPPED" and out["verdict"] == "STOP"
    assert "PAPER_EXECUTION" in out["verdict_reason"] and "not LIMITED_LIVE" in out["verdict_reason"]


def test_f22_enabled_on_the_running_lane_stops_the_row(tmp_path):
    """F24's registered arm is 'no experiment'. The override file check catches an experiment
    block on disk; this catches the process that is actually assigning events to an arm."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    board = _board_doc(f22_enabled=True, f22_authority="F22 override block, epoch 4")
    out = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path), now=300.0, board=board))
    assert out["row_status"] == "STOPPED" and out["verdict"] == "STOP"
    assert "F22 ENABLED" in out["verdict_reason"]


def test_the_caps_the_running_process_loaded_are_checked_not_only_the_file(tmp_path):
    """grid.py reads caps from the override ONCE, at start (main: sup.caps = resolved.caps), and
    gate.stale_reason never compares caps. So an override rewritten mid-row with different caps
    leaves the running lane enforcing the old ones -- and the file check alone would pass."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    board = _board_doc(caps={"stake_usd": 60.0, "max_contracts": 25.0, "day_notional_usd": 500.0})
    out = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path), now=300.0, board=board))
    assert out["row_state"]["board"]["caps_match_registered"] is False
    assert out["row_status"] == "STOPPED" and out["verdict"] == "STOP"
    assert "RUNNING lane's caps" in out["verdict_reason"]
    assert out["row_state"]["override"]["caps_match_registered"] is True, "the FILE still matches"


def test_a_missing_board_is_a_named_probe_failure_not_a_clean_row(tmp_path):
    """No board means the lane is dead, stopped, OOM-killed, starved or writing elsewhere. None of
    those places an order, and none of them shows up in the kill directory."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    out = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path), now=300.0, board=None))

    assert out["row_state"]["board"]["present"] is False
    assert out["row_state"]["conclusive"] is False
    assert out["row_status"] == "INCONCLUSIVE"
    assert out["verdict"] not in VERDICTS and out["ended"] is False
    assert any("board:" in e for e in out["row_state"]["probe_errors"])


def test_a_stale_board_is_a_probe_failure_and_its_arm_stale_is_still_believed(tmp_path):
    """The lane rewrites the board every second. A board minutes old cannot say the lane is
    trading now -- but a stale board that says ARM_STALE is still evidence: only a new override or
    a restart clears that, so the age is named rather than used to dismiss it."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    root = _live(tmp_path)
    quiet = rp.run(str(p), 90.0, None, **_kw(root, now=300.0, board=_board_doc(as_of=100.0)))
    assert quiet["row_state"]["board"]["fresh"] is False
    assert quiet["row_state"]["board"]["age_s"] == 200.0
    assert quiet["row_status"] == "INCONCLUSIVE" and quiet["verdict"] not in VERDICTS
    assert any("board" in e and "old" in e for e in quiet["row_state"]["probe_errors"])

    stale_arm = _board_doc(as_of=100.0, arm_stale="override pins different limits (loaded 9ab1)")
    out = rp.run(str(p), 90.0, None, **_kw(root, now=300.0, board=stale_arm))
    assert out["row_status"] == "STOPPED" and out["verdict"] == "STOP"
    assert "ARM_STALE" in out["verdict_reason"] and "STALE)" in out["verdict_reason"]


def _twelve_covers_over_seven_days(con, start, *, recorded=True):
    """Twelve profitable covers SPREAD over the window's days, and a lane whose own record says it
    was working: an attempt on every completed day, and only per-candidate refusals beside them.

    Spread on purpose. Twelve covers in the first ten minutes and silence for six days is not a
    seven-day test that made money -- it is a row that traded once and then stopped, and this
    reader now says so. The control has to be a window in which the lane could actually act.
    """
    for i in range(12):
        # Two an hour apart on each of the seven days, dropping to one on the last few.
        day = i % 7
        _exec(con, f"c{i:02d}", f"e{i}", "RECONCILED", start + day * 86400.0 + 3600.0 * (i + 1))
        _settle(con, f"c{i:02d}", 0.25, ts=start + day * 86400.0 + 3600.0 * (i + 2))
    if recorded:
        for day in range(8):
            _working_day(con, start + day * 86400.0)
    con.commit()


def test_day_seven_cannot_end_with_a_money_verdict_when_the_row_could_not_trade(tmp_path):
    """THE DAY-7 CASE. The breaker latched on day 2 and someone cleared kill/live; the lane has
    placed nothing since. The round-2 reader ran the window out and issued a money verdict over
    seven days in which trading was impossible. It must report the stop instead."""
    start = 1789418782.132788
    now = start + 7.5 * 86400.0
    p, con = _db(tmp_path)
    _twelve_covers_over_seven_days(con, start)

    control = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=now))
    assert control["ended"] is True and control["verdict"] in VERDICTS, "a money verdict, if it traded"
    assert control["verdict"].startswith("MAKES_MONEY")

    root = _live(tmp_path, breaker=_latched("daily realized loss -25.31 USD breached 25.00 on 2026-09-19"))
    out = rp.run(str(p), start, None, **_kw(root, now=now))
    assert out["row_status"] == "STOPPED"
    assert out["verdict"] == "STOP", "not a verdict on a window that could not trade"
    assert "breaker is LATCHED" in out["verdict_reason"]
    assert any("elapsed days reached the registered 7" in r for r in out["end_reasons"]), (
        "the seventh day is still reported; it is the verdict that is refused")


def test_day_seven_withholds_the_verdict_when_a_probe_could_not_look(tmp_path):
    """Same seventh day, but the lane's board is gone: this reader cannot say the row was able to
    trade, so it issues no verdict at all rather than ending the row on what it could not see."""
    start = 1789418782.132788
    now = start + 7.5 * 86400.0
    p, con = _db(tmp_path)
    _twelve_covers_over_seven_days(con, start)
    out = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=now, board=None))

    assert out["row_status"] == "INCONCLUSIVE"
    assert out["ended"] is False, "seven days is not an ending when the evidence is missing"
    assert out["verdict"] not in VERDICTS
    assert out["end_reasons"], "the end is still named"
    assert any("INCONCLUSIVE -- no verdict" in w and "registered end HAS been reached" in w
               for w in out["warnings"])


def test_the_fifty_end_is_still_issued_when_a_probe_could_not_look(tmp_path):
    """A failed probe withholds the verdict because it cannot say the row was able to trade -- but
    the $50 end is about harm already done, and those dollars are in the database this reader DID
    read. It ends the row LOSES_MONEY and still names the probe it could not complete."""
    p, con = _db(tmp_path)
    for i in range(12):
        _exec(con, f"c{i}", f"e{i}", "RECONCILED", 100.0 + i)
        _settle(con, f"c{i}", -5.0)
    con.commit()
    out = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path), now=300.0, board=None))

    assert _money(out)["total_usd"] == -60.0
    assert out["row_status"] == "ENDED" and out["ended"] is True
    assert out["verdict"] == "LOSES_MONEY"
    assert out["row_state"]["conclusive"] is False, "and it still says what it could not check"
    assert any("board:" in w for w in out["warnings"])
    assert "incomplete" in out["verdict_reason"]


def test_a_day_the_lane_started_nothing_is_counted_and_named_not_averaged_away(tmp_path):
    """Every FILE probe here is point-in-time: a kill someone deleted, a breaker a human reset and
    an ARM_STALE the next override cleared leave no trace. What the database does hold is how many
    LIMITED_LIVE executions started each UTC day, and that IS durable. It is reported as the count
    it is, and a completed day with none of them is named for a human -- never explained."""
    start = 1789344000.0                       # 2026-09-14T00:00:00Z exactly
    p, con = _db(tmp_path)
    for i in range(3):                         # day 1 only; days 2 and 3 started nothing
        _exec(con, f"c{i}", f"e{i}", "RECONCILED", start + 3600.0 * (i + 1))
        _settle(con, f"c{i}", 0.25, ts=start + 7200.0 * (i + 1))
    con.commit()
    out = rp.run(str(p), start, start + 3.0 * 86400.0, **_kw(_live(tmp_path), now=start + 9e5))

    assert out["window"]["completed_utc_days"] == ["2026-09-14", "2026-09-15", "2026-09-16"]
    assert out["funnel"]["attempts_by_started_utc_day"] == {"2026-09-14": 3}
    assert out["funnel"]["completed_utc_days_with_no_attempt"] == ["2026-09-15", "2026-09-16"]
    assert out["days_needing_a_human_look"] == ["2026-09-15", "2026-09-16"]
    assert any("NO LIMITED_LIVE execution" in w and "point-in-time" in w for w in out["warnings"])
    assert "POINT-IN-TIME" in out["row_state"]["what_this_cannot_see"]
    day = [d for d in out["daily_record"]["days"] if d["utc_day"] == "2026-09-15"][0]
    assert day["executions_started"] == 0 and day["covers_settled"] == 0
    assert day["risk_channel"] == {"ticks_recorded": 0, "codes": {}}
    assert not any("could not trade" in w.lower() for w in out["warnings"])

    one_day = rp.run(str(p), start, start + 86400.0, **_kw(_live(tmp_path), now=start + 9e5))
    assert one_day["funnel"]["completed_utc_days_with_no_attempt"] == []
    assert one_day["days_needing_a_human_look"] == []
    assert not any("no attempt" in w for w in one_day["warnings"])


def test_a_stopped_row_never_reads_in_progress_on_any_of_the_new_signals(tmp_path):
    """One assertion for the whole family: none of these may produce IN_PROGRESS."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    cases = [
        ("venue kill", _kw(_live(tmp_path, kill=("venue-polymarket",)), now=300.0)),
        ("event kill", _kw(_live(tmp_path, kill=("event-X",)), now=300.0)),
        ("strategy kill", _kw(_live(tmp_path, kill=("strategy-v1",)), now=300.0)),
        ("latched breaker", _kw(_live(tmp_path, breaker=_latched()), now=300.0)),
        ("unreadable breaker", _kw(_live(tmp_path, breaker="nonsense{"), now=300.0)),
        ("arm stale", _kw(_live(tmp_path), now=300.0,
                          board=_board_doc(arm_stale="override missing or incomplete"))),
        ("no board", _kw(_live(tmp_path), now=300.0, board=None)),
        ("stale board", _kw(_live(tmp_path), now=300.0, board=_board_doc(as_of=1.0))),
        ("paper mode", _kw(_live(tmp_path), now=300.0, board=_board_doc(mode="SHADOW_LIVE"))),
    ]
    for what, kw in cases:
        out = rp.run(str(p), 90.0, None, **kw)
        assert out["row_status"] in ("STOPPED", "INCONCLUSIVE"), what
        assert not out["verdict"].startswith("IN_PROGRESS"), what
        assert out["headline"].startswith(out["row_status"]), what


# ------------------------------------------- defect 3: the $50 rule is an `end`, not a stop condition


def test_the_cumulative_loss_end_is_loses_money_not_stop(tmp_path):
    """spec.yaml lists $50 under `end`, not `stop_conditions`. The worst honest outcome is that
    the row lost money -- not that a safety condition fired."""
    p, con = _db(tmp_path)
    for i in range(3):
        _exec(con, f"x{i}", f"e{i}", "RECONCILED", 100.0 + i)
        _settle(con, f"x{i}", -20.0)
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))
    assert out["ended"] is True
    assert out["verdict"] == "LOSES_MONEY"
    assert "cumulative-loss end" in out["verdict_reason"]
    assert out["row_state"]["stop_conditions"] == []


def test_the_verdict_helper_keeps_stop_for_real_stop_conditions_only():
    assert rp.verdict(-60.0, 3, None, None, loss_end=True)[0] == "LOSES_MONEY"
    assert rp.verdict(-60.0, 3, None, "kill/live is present", loss_end=True)[0] == "STOP"


def test_the_fifty_end_fires_on_the_money_even_when_the_covers_made_a_profit(tmp_path):
    """THE failure this reader was rebuilt for. Twelve covers made +$3.00; three PARTIAL rows whose
    IOC hedge left contracts riding naked lost $54.00. The row is $51 down. A verdict computed on
    the covers alone calls that a profit and lets the test run on."""
    p, con = _db(tmp_path)
    for i in range(12):
        _exec(con, f"c{i}", f"e{i}", "RECONCILED", 100.0 + i)
        _settle(con, f"c{i}", 0.25, kind="COVER")
    for i in range(3):
        _exec(con, f"n{i}", f"ne{i}", "RECONCILED", 130.0 + i, first=10.0, hedge=3.0)
        _settle(con, f"n{i}", -18.0, kind="PARTIAL")
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))

    assert _covers(out)["total_usd"] == 3.0, "the covers alone really did make money"
    assert _money(out)["total_usd"] == -51.0
    assert out["ended"] is True and out["row_status"] == "ENDED"
    assert out["verdict"] == "LOSES_MONEY"
    assert "all-in realised net -51.00000 reached the $50 cumulative-loss end" in out["verdict_reason"]
    assert "settled covers alone: +3.00000" in out["verdict_reason"]
    assert out["row_state"]["stop_conditions"] == [], "an end, not a safety condition"
    assert any("$50 cumulative-loss end" in r for r in out["end_reasons"])
    assert _money(out)["usd_of_further_realised_loss_before_the_50_end"] == 0.0
    assert "REACHED -- stop the test" in out["headline"]


def test_profitable_covers_cannot_hide_an_all_in_loss_short_of_the_fifty_end(tmp_path):
    """Below $50 the row has not ended -- but the verdict it WOULD get must already be the honest
    one: a row whose covers made $3 while its partials lost $40 lost money."""
    p, con = _db(tmp_path)
    for i in range(12):
        _exec(con, f"c{i}", f"e{i}", "RECONCILED", 100.0 + i)
        _settle(con, f"c{i}", 0.25, kind="COVER")
    _exec(con, "naked", "ne", "RECONCILED", 130.0, first=10.0, hedge=3.0)
    _settle(con, "naked", -40.0, kind="PARTIAL")
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))
    assert _covers(out)["total_usd"] == 3.0 and _money(out)["total_usd"] == -37.0
    assert out["ended"] is False, "$37 is not $50"
    assert out["verdict"] == "IN_PROGRESS (would be LOSES_MONEY)"
    assert "the non-cover settlements took it back" in out["verdict_reason"]
    assert _money(out)["usd_of_further_realised_loss_before_the_50_end"] == 13.0


# ------------------------------- spec.yaml: the row cannot end on an unsettled cover


def _thirty_covers_and_two_open(tmp_path, con):
    for i in range(30):
        _exec(con, f"c{i:02d}", f"e{i}", "RECONCILED", 100.0 + i)
        _settle(con, f"c{i:02d}", 0.25, kind="COVER", ts=200.0 + i)
    for i in range(2):
        _exec(con, f"open{i}", f"oe{i}", "HEDGED", 140.0 + i, first=12.0, hedge=12.0)
    con.commit()


def test_an_end_with_covers_still_unsettled_withholds_the_verdict(tmp_path):
    """spec.yaml, unit_of_observation: 'An unsettled cover is not scored until it settles; the row
    cannot end on an unsettled one.' The 30th cover lands with two filled executions still open,
    so the honest report names what is outstanding rather than scoring a truncated set."""
    p, con = _db(tmp_path)
    _thirty_covers_and_two_open(tmp_path, con)
    out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))

    assert out["row_status"] == "AWAITING_SETTLEMENT"
    assert out["ended"] is False, "the registered end arrived; the row still may not end"
    assert out["verdict"] not in VERDICTS, "no final verdict over a truncated set"
    assert out["verdict"].startswith("AWAITING_SETTLEMENT (would be ")
    aw = out["awaiting_settlement"]
    assert aw["count"] == 2 and aw["blocks_the_end"] is True
    assert aw["execution_ids"] == ["open0", "open1"], "it names what is outstanding"
    assert aw["by_state"] == {"HEDGED": 2}
    assert any("30 settled covers reached the registered 30" in b
               for b in out["end_rule"]["ends_that_wait_for_outstanding_settlements"])
    assert any("cannot end on an unsettled" in w for w in out["warnings"])


def test_the_fifty_end_does_not_wait_for_outstanding_settlements(tmp_path):
    """Harm already done. Delaying the $50 end until everything settles would hide it."""
    p, con = _db(tmp_path)
    _thirty_covers_and_two_open(tmp_path, con)
    _exec(con, "naked", "ne", "RECONCILED", 141.0, first=10.0, hedge=3.0)
    _settle(con, "naked", -60.0, kind="PARTIAL", ts=260.0)
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))
    assert out["awaiting_settlement"]["count"] == 2
    assert out["awaiting_settlement"]["blocks_the_end"] is False
    assert out["ended"] is True and out["verdict"] == "LOSES_MONEY"


def test_a_stop_condition_does_not_wait_for_outstanding_settlements(tmp_path):
    p, con = _db(tmp_path)
    _thirty_covers_and_two_open(tmp_path, con)
    out = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path, kill=("live",)), now=300.0))
    assert out["row_status"] == "STOPPED"
    assert out["ended"] is True and out["verdict"] == "STOP"


def test_an_open_execution_is_judged_on_its_fills_not_on_its_state_name(tmp_path):
    """A naked position rides to settlement in PARTIAL_FILL / HEDGE_UNAVAILABLE exactly as much as
    in HEDGED. A state whitelist would hide the most exposed rows in the row."""
    p, con = _db(tmp_path)
    _exec(con, "naked", "e1", "HEDGE_UNAVAILABLE", 100.0, first=9.0, hedge=0.0)
    _exec(con, "declined", "e2", "BOOK_MOVED", 101.0, first=0.0, hedge=0.0)
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))
    assert out["awaiting_settlement"]["execution_ids"] == ["naked"]
    assert out["awaiting_settlement"]["by_state"] == {"HEDGE_UNAVAILABLE": 1}
    assert out["funnel"]["no_position"] == 1
    assert any("have not settled" in w for w in out["warnings"])


def test_open_stake_prices_what_is_still_held_and_nets_out_the_unwound(tmp_path):
    p, con = _db_full(tmp_path)
    _exec_full(con, "held", "e1", "HEDGED", 100.0, first=10.0, hedge=10.0,
               first_price=0.40, hedge_price=0.55, first_unwound=4.0)
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))
    # 6 first-leg contracts still held at 0.40, plus 10 hedge contracts at 0.55.
    assert out["awaiting_settlement"]["stake_paid_usd"] == 7.9
    assert out["awaiting_settlement"]["contracts_without_a_price"] == 0.0


def test_a_missing_price_column_is_a_named_warning_and_an_unpriced_count_not_a_crash(tmp_path):
    """The `*_avg_price` / `*_unwound` columns arrived by ALTER. A table without them must show a
    gap, never a smaller number presented as the outstanding stake."""
    p, con = _db(tmp_path)
    _exec(con, "held", "e1", "HEDGED", 100.0, first=10.0, hedge=10.0)
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))
    assert out["awaiting_settlement"]["stake_paid_usd"] == 0.0
    assert out["awaiting_settlement"]["contracts_without_a_price"] == 20.0
    assert any("has no `first_avg_price` column" in w for w in out["warnings"])
    assert any("no average price recorded" in w for w in out["warnings"])


# --------------------------------------- the registered 30-cover end truncates the scored set


def test_the_scored_set_is_truncated_at_the_registered_thirty_covers(tmp_path):
    """Nothing on the box stops the lane at 30. The 31st and 32nd covers are not part of the
    registered row's answer -- and their dollars are still the operator's."""
    p, con = _db(tmp_path)
    for i in reversed(range(32)):                   # inserted backwards: order must not be insertion order
        _exec(con, f"c{i:02d}", f"e{i}", "RECONCILED", 100.0 + i)
        _settle(con, f"c{i:02d}", 0.10 if i < 30 else 0.50, kind="COVER", ts=500.0)
    con.commit()
    out = rp.run(str(p), 90.0, 600.0, **_kw(_live(tmp_path), now=1000.0))

    reg = out["registered_end"]
    assert reg["limit_covers"] == 30
    assert reg["settled_covers_in_window"] == 32 and reg["scored_covers"] == 30
    assert reg["truncated"] is True, "the truncation is visible"
    assert reg["post_end_covers"]["count"] == 2
    assert reg["post_end_covers"]["execution_ids"] == ["c30", "c31"]
    assert reg["post_end_covers"]["realized_usd"] == 1.0, "reported separately, with their dollars"

    assert _covers(out)["covers"] == 30
    assert _covers(out)["total_usd"] == 3.0, "the post-end covers are out of the verdict statistic"
    assert _money(out)["total_usd"] == 4.0, "and in the money"
    assert out["selection"]["scored_cover_execution_ids"] == [f"c{i:02d}" for i in range(30)]
    assert any("traded past the registered 30-cover end" in w for w in out["warnings"])


def test_the_truncation_ordering_is_deterministic_and_documented(tmp_path):
    """apply_settlements stamps ONE settled_ts per pass, so covers routinely tie. The documented
    order is settled_ts ascending then execution_id ascending, and it must be exactly that."""
    assert rp.COVER_ORDER == "settled_ts ascending, then execution_id ascending"
    p, con = _db(tmp_path)
    # 31 covers. `a_early` settled in an earlier pass, so settled_ts puts it first however its id
    # sorts; the other 30 share one settled_ts, so among them the id alone decides, and `z_tie`
    # sorts after every `cNN` and is the one pushed past the registered end.
    for i in range(29):
        _exec(con, f"c{i:02d}", f"e{i}", "RECONCILED", 100.0 + i)
        _settle(con, f"c{i:02d}", 0.10, kind="COVER", ts=500.0)
    _exec(con, "z_tie", "ez", "RECONCILED", 130.0)
    _settle(con, "z_tie", 0.10, kind="COVER", ts=500.0)
    _exec(con, "a_early", "ea", "RECONCILED", 131.0)
    _settle(con, "a_early", 0.10, kind="COVER", ts=100.0)
    con.commit()
    out = rp.run(str(p), 90.0, 600.0, **_kw(_live(tmp_path), now=1000.0))

    assert out["registered_end"]["settled_covers_in_window"] == 31
    assert out["registered_end"]["ordering"] == rp.COVER_ORDER
    assert out["registered_end"]["post_end_covers"]["execution_ids"] == ["z_tie"], (
        "a_early settled first, so it is inside the 30 however its id sorts; among the 30 that "
        "share a settled_ts the id decides, and 'z_tie' sorts after every 'cNN'")
    assert out["selection"]["scored_cover_execution_ids"] == sorted(
        [f"c{i:02d}" for i in range(29)] + ["a_early"])
    again = rp.run(str(p), 90.0, 600.0, **_kw(_live(tmp_path), now=1000.0))
    assert again["registered_end"] == out["registered_end"], "deterministic across runs"


# --------------------------------------------------- defect 4: include/exclude are on the face of it


def test_include_and_exclude_are_echoed_with_every_scored_cover_id(tmp_path):
    """An honest report and a doctored one must not be byte-identical apart from the numbers."""
    p, con = _db(tmp_path)
    for i, usd in enumerate((0.3, -0.9, 0.4)):
        _exec(con, f"c{i}", f"e{i}", "RECONCILED", 100.0 + i)
        _settle(con, f"c{i}", usd)
    _exec(con, "old", "e9", "RECONCILED", 10.0)     # outside the window
    _settle(con, "old", 0.5, ts=20.0)
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, ["old"], ["c1"], **_kw(_live(tmp_path), now=1000.0))
    assert out["selection"]["include"] == ["old"] and out["selection"]["exclude"] == ["c1"]
    assert out["selection"]["excluded_by_request"] == ["c1"]
    assert out["selection"]["included_out_of_window"] == ["old"]
    assert out["selection"]["scored_cover_execution_ids"] == ["c0", "c2", "old"]


def test_an_untouched_run_still_echoes_empty_selection_lists(tmp_path):
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))
    assert out["selection"]["include"] == [] and out["selection"]["exclude"] == []
    assert out["selection"]["scored_cover_execution_ids"] == ["a"]


# -------------------------------------------------------- defect 5: only LIMITED_LIVE is real money


def test_paper_execution_rows_are_never_counted_as_f24_real_money(tmp_path):
    """The override expires at the 7-day end and the documented way back is PAPER_EXECUTION; its
    rows land in the same database."""
    p, con = _db(tmp_path)
    _exec(con, "real", "e1", "RECONCILED", 100.0)
    _settle(con, "real", 0.30)
    _exec(con, "paper", "e2", "RECONCILED", 101.0, mode="PAPER_EXECUTION")
    _settle(con, "paper", 4.20)
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))
    assert out["funnel"]["settled_covers"] == 1 and _covers(out)["total_usd"] == 0.30
    assert _money(out)["total_usd"] == 0.30, "not in the money figure either"
    assert out["selection"]["scored_cover_execution_ids"] == ["real"]
    assert out["funnel"]["excluded_wrong_mode"] == {
        "count": 1, "by_mode": {"PAPER_EXECUTION": 1}, "execution_ids": ["paper"]}


def test_an_included_paper_row_is_still_refused_by_the_mode_filter(tmp_path):
    p, con = _db(tmp_path)
    _exec(con, "real", "e1", "RECONCILED", 100.0)
    _settle(con, "real", 0.30)
    _exec(con, "paper", "e2", "RECONCILED", 10.0, mode="PAPER_EXECUTION")
    _settle(con, "paper", 4.20, ts=20.0)
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, ["paper"], **_kw(_live(tmp_path), now=1000.0))
    assert _covers(out)["total_usd"] == 0.30 and _money(out)["total_usd"] == 0.30
    assert out["funnel"]["excluded_wrong_mode"]["execution_ids"] == ["paper"]


# ------------------------------------------------ defect 6: no $/day projected out of a partial day


def test_no_dollar_per_day_figure_is_projected_from_a_partial_day(tmp_path):
    """A single +$0.28 cover an hour into the row printed 6.72/day. Nothing may do that again."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.28, ts=1000.0)
    con.commit()
    out = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path), now=90.0 + 3600.0))
    assert "per_elapsed_day_usd" not in json.dumps(out), "no projection anywhere in the report"
    assert out["window"]["completed_utc_days"] == []
    assert _covers(out)["observed_mean_usd_per_completed_utc_day"] is None
    assert _covers(out)["by_completed_utc_day_usd"] == {}


def test_realised_net_is_reported_per_completed_utc_day(tmp_path):
    """spec.yaml `daily`. A day counts only once it is wholly inside the window."""
    day = 86400.0
    p, con = _db(tmp_path)
    # start mid-day 0; days 1 and 2 complete; day 3 is still running.
    _exec(con, "a", "e1", "RECONCILED", 0.5 * day)
    _settle(con, "a", 0.40, ts=1.25 * day)
    _exec(con, "b", "e2", "RECONCILED", 0.6 * day)
    _settle(con, "b", -0.10, ts=2.50 * day)
    _exec(con, "c", "e3", "RECONCILED", 0.7 * day)
    _settle(con, "c", 9.99, ts=3.25 * day)          # in the partial day: not a completed day
    con.commit()
    out = rp.run(str(p), 0.5 * day, None, **_kw(_live(tmp_path), now=3.5 * day))
    assert out["window"]["completed_utc_days"] == ["1970-01-02", "1970-01-03"]
    assert _covers(out)["by_completed_utc_day_usd"] == {"1970-01-02": 0.4, "1970-01-03": -0.1}
    assert _covers(out)["observed_mean_usd_per_completed_utc_day"] == 0.15
    assert _covers(out)["total_usd"] == 10.29, "the running day's cover still counts in the total"
    assert _covers(out)["by_settle_day_usd"]["1970-01-04"] == 9.99


# ---------------------------------------------------------- defect 7: the start_utc must be the pin


def test_a_start_disagreeing_with_the_pinned_start_is_refused(tmp_path):
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    root = _live(tmp_path, start_pin=1789000000.123456)
    with pytest.raises(rp.StartMismatch) as e:
        rp.run(str(p), 1788000000.0, 300.0, **_kw(root, now=1000.0))
    assert "1789000000.123456" in str(e.value)


def test_a_start_within_a_second_of_the_pin_is_accepted(tmp_path):
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    root = _live(tmp_path, start_pin=100.4)
    out = rp.run(str(p), 100.0, 300.0, **_kw(root, now=1000.0))
    assert out["window"]["start_pin"]["value"] == 100.4
    assert out["window"]["start_pin"]["warning"] is None


def test_a_missing_start_pin_warns_loudly_but_still_runs(tmp_path):
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    out = rp.run(str(p), 100.0, 300.0, **_kw(_live(tmp_path), now=1000.0))
    assert out["window"]["start_pin"]["present"] is False
    assert any("UNVERIFIED" in w for w in out["warnings"])


def test_the_reader_never_creates_the_start_pin(tmp_path):
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    root = _live(tmp_path)
    rp.run(str(p), 100.0, 300.0, **_kw(root, now=1000.0))
    assert not (root / "release-audit" / "f24_start_utc").exists()


def test_an_unreadable_start_pin_warns_rather_than_passing_silently(tmp_path):
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    root = _live(tmp_path)
    (root / "release-audit" / "f24_start_utc").write_text("not a number\n")
    out = rp.run(str(p), 100.0, 300.0, **_kw(root, now=1000.0))
    assert any("NOT verified" in w for w in out["warnings"])


def test_the_cli_refuses_an_unknown_option():
    with pytest.raises(SystemExit):
        rp._parse_argv(["123", "--all-of-them"])
    assert rp._parse_argv(["123", "456", "--exclude", "x"]) == ([], ["x"], ["123", "456"])


# ------------------------------------------------------------------- read-only, and cheap to run


def test_the_reader_opens_the_store_read_only(tmp_path):
    """The lane owns this database. The daily read may never write to it."""
    assert 'mode=ro' in REPORT_PY.read_text()
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    con.close()
    os.chmod(p, 0o444)
    try:
        out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))
    finally:
        os.chmod(p, 0o644)
    assert _covers(out)["total_usd"] == 0.3


def test_the_settlements_lookup_is_chunked_so_a_long_window_cannot_blow_the_variable_cap(tmp_path):
    """One bind variable per execution in the window, and a 7-day window holds every attempt, not
    just the covers. SQLITE_MAX_VARIABLE_NUMBER is 999 before SQLite 3.32: an unchunked IN list
    turns the operator's daily read into `too many SQL variables` mid-test."""
    assert rp._ID_CHUNK <= 900
    p, con = _db(tmp_path)
    for i in range(7):
        _exec(con, f"c{i}", f"e{i}", "RECONCILED", 100.0 + i)
        _settle(con, f"c{i}", 1.0)
    con.commit()
    chunk = rp._ID_CHUNK
    rp._ID_CHUNK = 2
    try:
        out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))
    finally:
        rp._ID_CHUNK = chunk
    assert out["funnel"]["settled_covers"] == 7, "every id is still looked up"
    assert _covers(out)["total_usd"] == 7.0


# ------------------------------------------- check_f24.sh stages one script per run, and only its own

_SUDO_SHIM = r"""
sudo() {                       # the real call is: sudo -u janus <python> <script> <args...>
  shift 3
  if [ "$1" = "-m" ]; then cat >/dev/null; return 0; fi
  case "$1" in *f24_banner*) cat >/dev/null; return 0;; esac   # the banner, not the reader
  printf '%s' "$1" > "$STAGED_PATH_OUT"
  head -1 "$1" > "$STAGED_HEAD_OUT"
  nested="${NESTED:-}"
  unset NESTED                 # exactly one nested run: the child must never nest again
  if [ -n "$nested" ]; then bash "$nested"; fi
  if [ -r "$1" ]; then echo SURVIVED > "$SURVIVED_OUT"; else echo GONE > "$SURVIVED_OUT"; fi
  echo '{}'
  return 0
}
source "$PAYLOAD"
"""


def _payload_reader(payload: str) -> str:
    """The reader source the payload carries: one gzip+base64 blob, because SSM caps a command at
    97 KB and report.py alone is larger than that."""
    blob = re.search(r"printf %s '([A-Za-z0-9+/=]{200,})' \| base64 -d \| gzip -dc", payload)
    assert blob, "the payload does not carry a compressed reader"
    return gzip.decompress(base64.b64decode(blob.group(1))).decode()


def _check_payload(tmp_path, start, tag):
    """The exact script check_f24.sh hands to ops/box/run.sh. No box is touched: the runner is a
    stub that writes its one argument to a file."""
    runner = tmp_path / f"runner_{tag}.sh"
    runner.write_text('#!/usr/bin/env bash\nprintf "%s" "$1" > "$PAYLOAD_OUT"\n')
    dest = tmp_path / f"payload_{tag}.sh"
    subprocess.run(["bash", str(CHECK), start], check=True,
                   env={**os.environ, "F24_RUNNER": str(runner), "PAYLOAD_OUT": str(dest)})
    return dest.read_text()


def test_check_f24_stages_the_reader_at_a_unique_path_and_cleans_up_only_its_own(tmp_path):
    """A FIXED staging path made two simultaneous read-only checks overwrite and then delete each
    other's script -- the failure ops/box/run.sh was already changed for. Run B end to end from
    inside run A's reader invocation: B must not touch A's script, and each must remove its own."""
    payload_a = _check_payload(tmp_path, "100.0", "a")
    payload_b = _check_payload(tmp_path, "200.0", "b")
    assert "mktemp /tmp/f24_report.XXXXXX" in payload_a, (
        "one mktemp'd file per run; the template must END in the X's, because a trailing suffix "
        "is a GNU extension BSD mktemp copies verbatim")
    assert "/tmp/f24_report.py" not in payload_a, "no fixed staging path"
    assert "f24_banner" not in payload_a, "the banner renders locally now, not on the box"
    assert 'trap \'rm -f "$F24_PY"\' EXIT' in payload_a, (
        "the trap removes ONLY this run's two files")

    # Run them against tmp_path instead of the machine's real /tmp; everything else is as written.
    def staged(text, tag):
        q = tmp_path / f"run_{tag}.sh"
        q.write_text(text.replace("/tmp/f24_report.XXXXXX", f"{tmp_path}/f24_report.XXXXXX"))
        return q

    run_a, run_b = staged(payload_a, "a"), staged(payload_b, "b")
    harness = tmp_path / "harness.sh"
    harness.write_text(_SUDO_SHIM)

    def env(payload, tag, nested=None):
        e = {**os.environ, "PAYLOAD": str(payload),
             "STAGED_PATH_OUT": str(tmp_path / f"path_{tag}"),
             "STAGED_HEAD_OUT": str(tmp_path / f"head_{tag}"),
             "SURVIVED_OUT": str(tmp_path / f"survived_{tag}")}
        if nested is not None:
            e["NESTED"] = str(nested)
        return e

    nested_b = tmp_path / "nested_b.sh"
    nested_b.write_text("#!/usr/bin/env bash\nunset NESTED\n" + "".join(
        f'export {k}="{v}"\n' for k, v in env(run_b, "b").items()
        if k in ("PAYLOAD", "STAGED_PATH_OUT", "STAGED_HEAD_OUT", "SURVIVED_OUT"))
        + f'exec bash "{harness}"\n')
    subprocess.run(["bash", str(harness)], check=True, env=env(run_a, "a", nested=nested_b))

    path_a = (tmp_path / "path_a").read_text()
    path_b = (tmp_path / "path_b").read_text()
    assert path_a and path_b and path_a != path_b, "a unique staging path per run"
    assert re.fullmatch(rf"{re.escape(str(tmp_path))}/f24_report\.[A-Za-z0-9]{{6}}", path_a)
    assert (tmp_path / "survived_a").read_text().strip() == "SURVIVED", (
        "run B deleted run A's staged reader")
    assert (tmp_path / "head_a").read_text() == REPORT_PY.read_text().splitlines()[0] + "\n"
    assert not Path(path_a).exists() and not Path(path_b).exists(), "each run removed its own"


def test_check_f24_ends_with_a_banner_naming_the_rows_state(tmp_path):
    """The daily read is what enforces the $50 and 30-cover ends, and `row_status` sits in the
    middle of a few hundred pretty-printed lines. The last thing on the operator's screen must say
    what state the row is in and what stopped it -- computed from the report's own fields, so the
    banner cannot disagree with the report it summarises."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    out = rp.run(str(p), 90.0, None,
                 **_kw(_live(tmp_path, breaker=_latched()), now=300.0, board=None))
    assert out["row_status"] == "STOPPED"

    prog = _banner_program(tmp_path)
    r = subprocess.run([sys.executable, str(prog)], input=json.dumps(out),
                       capture_output=True, text=True)

    assert r.returncode == 0, r.stderr
    assert "F24_ROW_STATE: STOPPED" in r.stdout
    assert "STOPPED BY: the daily realised-loss breaker is LATCHED" in r.stdout
    assert "COULD NOT LOOK: board:" in r.stdout, "and what it could not check"
    assert "NOTE: THE BREAKER IS LATCHED AND THERE IS NO kill/live FILE" in r.stdout
    assert "VERDICT: STOP" in r.stdout
    assert r.stdout.rstrip().endswith("=" * 78), "it is the last thing printed"

    junk = subprocess.run([sys.executable, str(prog)], input="not json",
                          capture_output=True, text=True)
    assert junk.returncode == 0 and "UNREADABLE" in junk.stdout, "it never crashes the daily read"


def test_check_f24_carries_the_reader_to_the_box_unchanged(tmp_path):
    """The reader is embedded in the payload, not piped: ops/box/run.sh ignores stdin when it is
    given an argument. What arrives on the box must be this file, byte for byte."""
    payload = _check_payload(tmp_path, "100.0", "x")
    assert _payload_reader(payload) == REPORT_PY.read_text()


def test_check_f24_refuses_include_and_exclude(tmp_path):
    """--include/--exclude change WHICH covers are scored; that has to be a deliberate act on the
    box, not a flag on the daily progress check."""
    runner = tmp_path / "runner.sh"
    runner.write_text('#!/usr/bin/env bash\ntrue\n')
    r = subprocess.run(["bash", str(CHECK), "100.0", "200.0", "--exclude", "x"],
                       capture_output=True, text=True,
                       env={**os.environ, "F24_RUNNER": str(runner)})
    assert r.returncode == 2 and "--include/--exclude" in r.stderr


# ==========================================================================================
# round 5: REPORT THE NUMBERS. DO NOT JUDGE THE DAY.
#
# Round 4 read `refusal_counts` -- the lane's own per-tick counters -- and then turned each UTC
# day into a VERDICT: ATTEMPTED / BLOCKED / QUIET, with a STOP and a money verdict built on top.
# An adversarial prover broke it in BOTH directions, each reproduced end to end:
#
#   * UNDER-FIRE: `if attempts:` returned ATTEMPTED before anything else was read, so ONE cleared
#     candidate at 00:10 made a day "attempted". The banner printed "7/7 completed UTC day(s)
#     attempted, none blocked", MAKES_MONEY_PROVEN, ended=true, conclusive=true -- over a row
#     whose own risk channel had counted KILL_SWITCH x241,500 that same day.
#   * OVER-FIRE: ONE tick with n=1 of a transient code on an ordinary day printed "THE LANE COULD
#     NOT TRADE ON 1 COMPLETED UTC DAY(S) ... EVERY candidate was refused" and STOPped the row.
#     That sentence was false.
#
# Same root cause both times: a count per report tick cannot establish what the lane was able to
# do. So the classification is gone. The tests below pin what replaced it -- the day's numbers,
# withholding instead of asserting, and the short list of durable things that may still end a row
# -- and the two prover scenarios have a test each:
#
#   test_one_cleared_candidate_cannot_whitewash_a_day_of_kill_switch_counts
#   test_a_single_transient_tick_on_a_quiet_day_is_never_a_stop
# ==========================================================================================

#: 2026-09-14T00:00:00Z exactly, so the window's UTC days are whole and nameable.
DAY0 = 1789344000.0


def _seven_day_window(tmp_path):
    """A row started on a UTC midnight whose seventh day has arrived."""
    p, con = _db(tmp_path)
    return p, con, DAY0, DAY0 + 7.5 * 86400.0


def test_the_risk_channel_is_reported_per_utc_day_and_for_the_row(tmp_path):
    """spec.yaml `funnel`: 'pre-wire declines by reason'. Until L113 that stage was readable only
    by grepping journald; it is in the database now, so the daily read states it -- as counts, the
    ticks each code appeared in, and the ticks the day recorded at all."""
    p, con, start, now = _seven_day_window(tmp_path)
    for d in range(8):
        _working_day(con, start + d * 86400.0)
        _exec(con, f"x{d}", f"e{d}", "RECONCILED", start + d * 86400.0 + 3600.0)
        _settle(con, f"x{d}", 0.25, ts=start + d * 86400.0 + 7200.0)
    _refuse(con, start + 86400.0 + 60.0, "MIN_PROFIT", 5, channel="size")   # the OTHER channel
    con.commit()
    out = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=now))

    rec = out["refusal_record"]
    assert rec["present"] is True and rec["error"] is None
    assert rec["channel"] == "risk", "the size channel's flags are contaminated by its q=100 rung"
    assert out["funnel"]["pre_wire_declines_by_risk_code"] == {
        "IN_FLIGHT": {"n": 13184, "ticks": 32}, "MIN_PROFIT": {"n": 1184, "ticks": 32}}
    assert out["funnel"]["pre_wire_decline_risk_ticks"] == 32, "four ticks a day, eight days"
    assert out["funnel"]["pre_wire_declines_on_other_channels"] == "size n=5 in 1 tick(s)", (
        "the size channel is summed to ONE line and its codes are never read for meaning")
    assert rec["by_code"]["MIN_PROFIT"] == {"n": 1184, "ticks": 32}

    day1 = [d for d in out["daily_record"]["days"] if d["utc_day"] == "2026-09-15"][0]
    assert day1["executions_started"] == 1 and day1["covers_settled"] == 1
    assert day1["risk_channel"] == {"ticks_recorded": 4,
                                    "codes": {"IN_FLIGHT": {"n": 1648, "ticks": 4},
                                              "MIN_PROFIT": {"n": 148, "ticks": 4}}}
    assert day1["risk_line"] == ("risk: IN_FLIGHT n=1648 in 4 of 4 tick(s), "
                                 "MIN_PROFIT n=148 in 4 of 4 tick(s)")
    assert day1["other_channels_line"] == "size n=5 in 1 tick(s)"
    assert "status" not in day1 and "says" not in day1, "no label, and no story about the day"
    assert day1["needs_a_human_look"] is False


def test_one_tick_counts_leagues_not_ticks(tmp_path):
    """One report tick writes one row per (code, LEAGUE). Counting rows would report four ticks
    for one tick that refused across four leagues, and the tick count is the denominator every
    other number here is read against."""
    p, con, start, now = _seven_day_window(tmp_path)
    for league in ("mlb", "nfl", "nba", "cfb"):
        _refuse(con, start + 3600.0, "MIN_PROFIT", 10, league=league)
    con.commit()
    got = rp.probe_refusals(sqlite3.connect(p), start=start, stop_at=start + 86400.0)
    assert got["by_code"] == {"MIN_PROFIT": {"n": 40, "ticks": 1}}, "ONE tick, four leagues"
    assert got["ticks_in_window"] == 1
    assert "COUNT(DISTINCT seen_ts)" in rp._REFUSAL_SQL


# ------------------------------ the two defects an adversarial prover reproduced end to end


def test_one_cleared_candidate_cannot_whitewash_a_day_of_kill_switch_counts(tmp_path):
    """PROVER SCENARIO 1, the whitewash, reproduced. ONE candidate cleared at 00:10 on a day whose
    risk channel then counted KILL_SWITCH x241,500 across 240 of its 241 ticks. The earlier reader
    returned DAY_ATTEMPTED before it looked at anything else, and printed '7/7 completed UTC day(s)
    attempted, none blocked', MAKES_MONEY_PROVEN, ended=true, conclusive=true.

    One attempt may not speak for the other 23 hours. The day is named with its numbers, the
    verdict is withheld -- and it is still NOT called blocked and the row is still NOT STOPPED,
    because a count per report tick cannot establish that the lane was unable to trade."""
    p, con, start, now = _seven_day_window(tmp_path)
    for d in range(8):                               # an attempt every day: the whitewash's shape
        _working_day(con, start + d * 86400.0)
        for i in range(2):
            _exec(con, f"c{d}{i}", f"e{d}{i}", "RECONCILED", start + d * 86400.0 + 600.0 + i)
            _settle(con, f"c{d}{i}", 0.25, ts=start + d * 86400.0 + 7200.0 + i)
    for tick in range(240):                          # ... and day 2 was killed for the rest of it
        _refuse(con, start + 86400.0 + 700.0 + tick * 300.0, "KILL_SWITCH", 1006)
    con.commit()
    out = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=now))

    assert out["row_state"]["kill"]["present"] == [], "nothing on disk says so, then or now"
    assert out["row_state"]["stop_conditions"] == [], "and no file probe fires"
    assert out["row_status"] == "NEEDS_HUMAN_LOOK", "not ENDED, and not STOPPED either"
    assert out["ended"] is False
    assert out["verdict"] not in VERDICTS, "no money verdict over a day nobody has looked at"
    assert out["verdict_withheld_pending_a_human_look"] is True
    assert out["days_needing_a_human_look"] == ["2026-09-15"], "the day with an attempt IN it"

    day = [d for d in out["daily_record"]["days"] if d["utc_day"] == "2026-09-15"][0]
    assert day["executions_started"] == 2, "it did start executions, and that is reported"
    assert day["risk_channel"]["codes"]["KILL_SWITCH"] == {"n": 241440, "ticks": 240}
    assert day["risk_channel"]["ticks_recorded"] == 244
    why = " ".join(day["why"])
    assert "KILL_SWITCH n=241440 in 240 of 244 tick(s)" in why, "the day, the code, the ticks"
    assert "does not depend on the candidate" not in why.lower() or True
    # And the claims that were false are gone, from every field the operator reads.
    printed = json.dumps(out)
    assert "could not trade" not in printed
    assert "EVERY candidate was refused" not in printed
    assert "none blocked" not in printed
    assert "BLOCKED" not in out["headline"] and "QUIET" not in out["headline"]
    assert "DAY(S) NEEDING A HUMAN LOOK: 2026-09-15" in out["headline"]
    assert "DOES NOT ESTABLISH" in day["what_this_evidence_establishes"]
    assert _covers(out)["total_usd"] == 4.0, "and the money is still reported in full"


def test_a_single_transient_tick_on_a_quiet_day_is_never_a_stop(tmp_path):
    """PROVER SCENARIO 2, the over-fire, reproduced. ONE tick with n=1 of a transient code on an
    otherwise ordinary completed day made the earlier reader print 'THE LANE COULD NOT TRADE ON 1
    COMPLETED UTC DAY(S) ... EVERY candidate was refused' and report the whole row STOPPED. That
    sentence was false. The numbers are reported as they are -- 1 refusal in 1 of 5 ticks -- the
    row is not stopped, and the verdict waits for a person instead of being invented."""
    p, con, start, now = _seven_day_window(tmp_path)
    for d in range(8):
        _working_day(con, start + d * 86400.0)
        if d != 5:
            _exec(con, f"x{d}", f"e{d}", "RECONCILED", start + d * 86400.0 + 3600.0)
            _settle(con, f"x{d}", 0.25, ts=start + d * 86400.0 + 7200.0)
    _refuse(con, start + 5 * 86400.0 + 18000.0, "BREAKER", 1)       # one tick, one refusal
    con.commit()
    out = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=now))

    assert out["row_status"] != "STOPPED", "one tick is not a stop condition"
    assert out["verdict"] != "STOP"
    assert out["row_state"]["stop_conditions"] == []
    assert out["row_state"]["conclusive"] is True, "nothing failed to be read"
    printed = json.dumps(out)
    assert "could not trade" not in printed
    assert "EVERY candidate was refused" not in printed

    day = [d for d in out["daily_record"]["days"] if d["utc_day"] == "2026-09-19"][0]
    assert day["risk_channel"]["codes"]["BREAKER"] == {"n": 1, "ticks": 1}
    assert day["risk_channel"]["ticks_recorded"] == 5, "1 of 5, and the report says 1 of 5"
    assert "BREAKER n=1 in 1 of 5 tick(s)" in " ".join(day["why"])
    assert out["days_needing_a_human_look"] == ["2026-09-19"], "named, for one glance"
    assert out["row_status"] == "NEEDS_HUMAN_LOOK" and out["ended"] is False


def test_a_window_whose_days_all_counted_kill_switch_withholds_and_does_not_stop(tmp_path):
    """Someone latched the kill and cleared it again before the daily read; the lane counted
    KILL_SWITCH on every tick of six days and started nothing. Every file probe reads clean.

    The row must not end on a money verdict -- and it must not be reported STOPPED either. The
    counters say what they say; they do not say the lane was unable to trade."""
    p, con, start, now = _seven_day_window(tmp_path)
    _working_day(con, start)
    for i in range(12):                              # twelve profitable covers, all on day one
        _exec(con, f"c{i:02d}", f"e{i}", "RECONCILED", start + 3600.0 + i)
        _settle(con, f"c{i:02d}", 0.25, ts=start + 7200.0 + i)
    for d in range(1, 8):
        _blocked_day(con, start + d * 86400.0, "KILL_SWITCH", n=1521)
    con.commit()
    out = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=now))

    assert out["row_state"]["kill"]["present"] == [], "nothing on disk says so"
    assert out["row_state"]["breaker"]["latched"] is False
    assert out["row_state"]["stop_conditions"] == []
    assert out["row_status"] == "NEEDS_HUMAN_LOOK"
    assert out["row_status"] != "STOPPED" and out["verdict"] != "STOP"
    assert out["verdict"] not in VERDICTS, "and no money verdict either"
    assert _covers(out)["total_usd"] == 3.0, "the covers are still reported, and still made money"

    dr = out["daily_record"]
    assert dr["days_needing_a_human_look"] == ["2026-09-15", "2026-09-16", "2026-09-17",
                                               "2026-09-18", "2026-09-19", "2026-09-20"]
    assert dr["executions_started_by_utc_day"]["2026-09-15"] == 0
    assert dr["candidate_independent_over_the_row"] == {"KILL_SWITCH": {"n": 42588, "ticks": 28}}
    assert any("elapsed days reached the registered 7" in r for r in out["end_reasons"]), (
        "the seventh day is still reported; it is the verdict that waits")
    assert any("NEED A HUMAN LOOK" in w for w in out["warnings"])
    assert "no completed day needs a human look" not in out["headline"]


def test_a_breaker_count_names_pnl_unknown_without_asserting_anything(tmp_path):
    """`breaker.evaluate()` returns 'PNL_UNKNOWN: an UNCONFIRMED fill must be re-polled before the
    day's PnL can be computed' and clearance.clear turns it into Refused("BREAKER", ...), which
    writes nothing to kill/, nothing to breaker.json and no lane flag. The day is named with its
    counts and what the deployed code does is quoted -- and that is all that is claimed."""
    p, con, start, now = _seven_day_window(tmp_path)
    for d in range(8):
        if d == 3:
            _blocked_day(con, start + d * 86400.0, "BREAKER", n=1500)
            continue
        _working_day(con, start + d * 86400.0)
        _exec(con, f"x{d}", f"e{d}", "RECONCILED", start + d * 86400.0 + 3600.0)
        _settle(con, f"x{d}", 0.25, ts=start + d * 86400.0 + 7200.0)
    con.commit()
    out = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=now))

    assert out["row_state"]["breaker"]["latched"] is False, "nothing latched: the file probe is clean"
    assert out["row_status"] == "NEEDS_HUMAN_LOOK" and out["verdict"] != "STOP"
    assert out["days_needing_a_human_look"] == ["2026-09-17"]
    day = [d for d in out["daily_record"]["days"] if d["utc_day"] == "2026-09-17"][0]
    assert day["executions_started"] == 0
    assert day["risk_channel"]["codes"] == {"BREAKER": {"n": 6000, "ticks": 4}}
    why = " ".join(day["why"])
    assert "BREAKER n=6000 in 4 of 4 tick(s)" in why
    assert "PNL_UNKNOWN" in why, "the report must say what BREAKER can mean when nothing is latched"
    assert "could not trade" not in json.dumps(out)


def test_a_healthy_window_with_only_per_candidate_refusals_still_reaches_a_verdict(tmp_path):
    """The common case, and the one that must keep working: a lane starting executions every day
    and refusing candidates on their merits in between. Withholding costs one glance, but a reader
    that withholds on every row answers nothing, so this row still ends with F24's verdict."""
    p, con, start, now = _seven_day_window(tmp_path)
    _twelve_covers_over_seven_days(con, start)
    out = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=now))

    assert out["row_status"] == "ENDED" and out["ended"] is True
    assert out["verdict"] == "MAKES_MONEY_PROVEN", "unchanged by the new evidence"
    assert _covers(out)["total_usd"] == 3.0
    assert out["row_state"]["conclusive"] is True
    assert out["days_needing_a_human_look"] == []
    assert out["verdict_withheld_pending_a_human_look"] is False
    dr = out["daily_record"]
    assert dr["completed_days"] == 7
    assert sum(dr["executions_started_by_utc_day"].values()) == 12
    assert set(dr["risk_refusals_over_the_row"]) == {"MIN_PROFIT", "IN_FLIGHT"}
    assert dr["candidate_independent_over_the_row"] == {}
    assert "7 completed UTC day(s), 12 LIMITED_LIVE execution(s) started" in out["headline"]
    assert "no completed day needs a human look" in out["headline"]
    assert not any("HUMAN LOOK" in w for w in out["warnings"])

    # The first day alone, as a closed historical window: still no stop, still conclusive.
    first = rp.run(str(p), start, start + 86400.0, **_kw(_live(tmp_path), now=now))
    assert first["row_status"] != "STOPPED" and first["days_needing_a_human_look"] == []


def test_a_completed_day_with_only_per_candidate_codes_and_no_execution_is_named_not_labelled(tmp_path):
    """A completed day with no execution started but only per-candidate refusals. The earlier
    reader called this 'a working lane that found nothing worth trading. Normal' -- a story the
    counters do not carry, and the same story that let a paper-mode period pass silently. It is
    reported as the numbers, named for a human, and never called a stop."""
    p, con, start, now = _seven_day_window(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", start + 3600.0)
    _settle(con, "a", 0.30, ts=start + 7200.0)
    for d in range(8):
        _working_day(con, start + d * 86400.0)
    con.commit()
    out = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=now))

    assert out["row_state"]["stop_conditions"] == []
    assert out["row_status"] != "STOPPED" and out["verdict"] != "STOP"
    assert out["row_state"]["conclusive"] is True
    assert out["days_needing_a_human_look"] == ["2026-09-15", "2026-09-16", "2026-09-17",
                                                "2026-09-18", "2026-09-19", "2026-09-20"]
    day = [d for d in out["daily_record"]["days"] if d["utc_day"] == "2026-09-16"][0]
    assert day["executions_started"] == 0
    assert day["risk_channel"]["codes"] == {"IN_FLIGHT": {"n": 1648, "ticks": 4},
                                            "MIN_PROFIT": {"n": 148, "ticks": 4}}
    assert day["candidate_independent_codes"] == {} and day["unrecognised_codes"] == {}
    assert day["why"] == [w for w in day["why"] if w.startswith(rp.LOOK_NO_EXECUTION_STARTED)]
    printed = json.dumps(out)
    assert "found nothing worth trading" not in printed
    assert "Normal" not in printed and "could not trade" not in printed


def test_the_paper_mode_hole_is_stated_and_shows_up_as_days_with_no_execution(tmp_path):
    """`refusal_counts` has no mode column, so a paper-mode lane's refusals are indistinguishable
    from a live lane's and this reader invents no signal for it. What it does instead: executions
    are filtered to LIMITED_LIVE, so a paper period is a run of completed days with zero of them,
    and every one of those withholds the verdict. The limitation is in the output's own words."""
    p, con, start, now = _seven_day_window(tmp_path)
    for d in range(8):
        _working_day(con, start + d * 86400.0)               # the lane ticks in paper mode too
    for d in (0, 1):                                         # LIMITED_LIVE on the first two days
        _exec(con, f"x{d}", f"e{d}", "RECONCILED", start + d * 86400.0 + 3600.0)
        _settle(con, f"x{d}", 0.25, ts=start + d * 86400.0 + 7200.0)
    for d in range(2, 8):                                    # ... then the row was run in PAPER
        _exec(con, f"p{d}", f"pe{d}", "RECONCILED", start + d * 86400.0 + 3600.0,
              mode="PAPER_EXECUTION")
        _settle(con, f"p{d}", 5.00, ts=start + d * 86400.0 + 7200.0)
    con.commit()
    out = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=now))

    assert out["funnel"]["excluded_wrong_mode"]["count"] == 6
    assert _money(out)["total_usd"] == 0.5, "no paper dollar reaches either money figure"
    assert out["row_status"] == "NEEDS_HUMAN_LOOK" and out["ended"] is False
    assert out["days_needing_a_human_look"] == ["2026-09-16", "2026-09-17", "2026-09-18",
                                                "2026-09-19", "2026-09-20"]
    assert "NO mode column" in out["daily_record"]["mode_limitation"]
    assert out["row_state"]["board"]["mode"] == "LIMITED_LIVE", "the lane's mode NOW, and no more"
    assert any("no mode column" in w.lower() or "NO mode column" in w for w in out["warnings"])


def test_the_fifty_end_is_still_decided_on_the_money_over_a_withheld_day(tmp_path):
    """The one thing a withheld day does NOT hold up. Those dollars are in the database this
    reader DID read, the operator's plan is to stop the test at $50 of them, and a day whose
    counts need a human's eye does not make the losses less real. LOSES_MONEY, ended, today."""
    p, con, start, now = _seven_day_window(tmp_path)
    _working_day(con, start)
    for i in range(12):
        _exec(con, f"c{i:02d}", f"e{i}", "RECONCILED", start + 3600.0 + i)
        _settle(con, f"c{i:02d}", -4.5, ts=start + 7200.0 + i)
    for d in range(1, 8):                        # and every day after it needs a human look
        _blocked_day(con, start + d * 86400.0, "KILL_SWITCH", n=800)
    con.commit()
    out = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=now))

    assert _money(out)["total_usd"] == -54.0
    assert out["days_needing_a_human_look"], "the days are still named"
    assert out["verdict_withheld_pending_a_human_look"] is False, "but they do not hold this up"
    assert out["row_status"] == "ENDED" and out["ended"] is True
    assert out["verdict"] == "LOSES_MONEY"
    assert "cumulative-loss end" in out["verdict_reason"]
    assert "REACHED -- stop the test" in out["headline"]


def test_a_missing_refusal_table_is_a_named_warning_never_a_clean_in_progress(tmp_path):
    """If the lane's own record cannot be read, this reader has not read the window. A failed
    probe withholds the verdict outright and names the table."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    con.close()
    _drop_refusals(p)
    out = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path), now=300.0))

    assert out["row_status"] == "INCONCLUSIVE", "not IN_PROGRESS"
    assert not out["verdict"].startswith("IN_PROGRESS")
    assert out["verdict"] not in VERDICTS
    assert out["row_state"]["conclusive"] is False
    assert out["refusal_record"]["present"] is False
    assert any("refusal_counts" in e for e in out["row_state"]["probe_errors"]), "named"
    assert any("refusal_counts" in w and "has not ticked" in w for w in out["warnings"])


def test_a_completed_day_with_no_record_at_all_reports_zero_ticks_and_asks_for_a_look(tmp_path):
    """No execution started AND no refusal row on any channel. That is what a lane that was not
    running looks like, and also what a day with nothing to evaluate looks like. The report gives
    the numbers -- 0 and 0 -- names the day, and does not choose between them."""
    p, con, start, now = _seven_day_window(tmp_path)
    for d in (0, 1, 2, 3, 4, 6, 7):
        _working_day(con, start + d * 86400.0)
        _exec(con, f"x{d}", f"e{d}", "RECONCILED", start + d * 86400.0 + 3600.0)
        _settle(con, f"x{d}", 0.25, ts=start + d * 86400.0 + 7200.0)
    con.commit()                                   # day 5 (2026-09-19) is missing entirely
    out = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=now))

    assert out["days_needing_a_human_look"] == ["2026-09-19"]
    assert out["row_status"] == "NEEDS_HUMAN_LOOK"
    assert out["ended"] is False, "seven days is not an ending over a day nobody has read"
    assert out["verdict"] not in VERDICTS
    assert out["row_state"]["conclusive"] is True, "nothing failed: there is simply nothing there"
    day = [d for d in out["daily_record"]["days"] if d["utc_day"] == "2026-09-19"][0]
    assert day["executions_started"] == 0 and day["risk_channel"]["ticks_recorded"] == 0
    assert day["other_channels_line"] == "no row on any other channel"
    assert "0 LIMITED_LIVE executions started" in " ".join(day["why"])
    assert "2026-09-19" in out["headline"]


def test_an_unrecognised_risk_code_is_named_and_withholds_instead_of_being_guessed(tmp_path):
    """Three audits in a row found one more refusal path than the tooling knew about. A code in
    neither reference list is the next one: the reader says it does not know it, gives the counts,
    and withholds -- it does not decide the code is harmless and it does not call it a stop."""
    p, con, start, now = _seven_day_window(tmp_path)
    for d in range(8):
        _working_day(con, start + d * 86400.0)
        if d != 2:
            _exec(con, f"x{d}", f"e{d}", "RECONCILED", start + d * 86400.0 + 3600.0)
            _settle(con, f"x{d}", 0.25, ts=start + d * 86400.0 + 7200.0)
    _blocked_day(con, start + 2 * 86400.0, "SOMETHING_SHIPPED_LATER", n=900)
    con.commit()
    out = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=now))

    assert out["days_needing_a_human_look"] == ["2026-09-16"]
    day = [d for d in out["daily_record"]["days"] if d["utc_day"] == "2026-09-16"][0]
    assert day["unrecognised_codes"] == {"SOMETHING_SHIPPED_LATER": {"n": 3600, "ticks": 4}}
    why = " ".join(day["why"])
    assert rp.LOOK_UNRECOGNISED_CODE in why and "does not know" in why
    assert "nodes/risk/clearance.py" in why
    assert out["row_status"] == "NEEDS_HUMAN_LOOK" and out["verdict"] not in VERDICTS
    assert out["row_status"] != "STOPPED"
    assert out["refusal_record"]["unrecognised_by_code"] == {
        "SOMETHING_SHIPPED_LATER": {"n": 3600, "ticks": 4}}


def test_the_two_reference_lists_match_the_deployed_code_and_stop_nothing(tmp_path):
    """The lists are pinned against 59dd5ae's own clearance, because they decide which days get a
    human's eye. They decide nothing else: neither list can produce a stop condition, and no code
    in either of them appears in row_state.stop_conditions."""
    assert rp.CANDIDATE_INDEPENDENT_RISK_CODES.keys() >= {
        "KILL_SWITCH", "BREAKER", "ARM_STALE", "GUARD_FAILED", "BALANCE", "BALANCE_UNCONFIRMED",
        "FEE_SCHEDULE"}, "the seven the round-3 audit named"
    assert "PNL_UNKNOWN" not in rp.CANDIDATE_INDEPENDENT_RISK_CODES, (
        "it is not a code: breaker.evaluate returns it as the DETAIL of Refused('BREAKER', ...)")
    assert "PNL_UNKNOWN" in rp.CANDIDATE_INDEPENDENT_RISK_CODES["BREAKER"]
    for per_candidate in ("MIN_PROFIT", "IN_FLIGHT", "HEDGE_DEPTH_CHANGED", "LEAGUE_EXPOSURE"):
        assert per_candidate in rp.PER_CANDIDATE_RISK_CODES
        assert per_candidate not in rp.CANDIDATE_INDEPENDENT_RISK_CODES
    assert not (set(rp.CANDIDATE_INDEPENDENT_RISK_CODES) & set(rp.PER_CANDIDATE_RISK_CODES))
    assert rp.RISK_CHANNEL == "risk"
    assert not hasattr(rp, "BLOCKING_RISK_CODES"), "the blocking/ordinary taxonomy is gone"
    assert not hasattr(rp, "ORDINARY_RISK_CODES")
    assert not hasattr(rp, "SCOPED_RISK_CODES")
    for gone in ("DAY_ATTEMPTED", "DAY_BLOCKED", "DAY_QUIET", "DAY_NOT_JUDGED", "lane_activity"):
        assert not hasattr(rp, gone), f"{gone} classified a day; nothing classifies a day now"

    # Every candidate-independent code, on its own, over a whole window: still not a stop.
    for code in sorted(rp.CANDIDATE_INDEPENDENT_RISK_CODES):
        root = tmp_path / code
        root.mkdir()
        p, con, start, now = _seven_day_window(root)
        for d in range(8):
            _blocked_day(con, start + d * 86400.0, code, n=99)
        con.commit()
        out = rp.run(str(p), start, None, **_kw(_live(root), now=now))
        assert out["row_state"]["stop_conditions"] == [], code
        assert out["row_status"] == "NEEDS_HUMAN_LOOK", code
        assert out["verdict"] != "STOP", code
        assert "could not trade" not in json.dumps(out), code


def test_the_day_in_progress_is_reported_and_never_withholds_anything(tmp_path):
    """The running day's numbers are the operator's early warning. It is not over, so it is not
    one of the completed days and it can never withhold a verdict or stop a row."""
    p, con, start, now = _seven_day_window(tmp_path)
    for d in range(2):
        _working_day(con, start + d * 86400.0)
        _exec(con, f"x{d}", f"e{d}", "RECONCILED", start + d * 86400.0 + 3600.0)
        _settle(con, f"x{d}", 0.25, ts=start + d * 86400.0 + 7200.0)
    _blocked_day(con, start + 2 * 86400.0 + 600.0, "BALANCE_UNCONFIRMED", ticks=2, n=44)
    con.commit()
    out = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=start + 2 * 86400.0 + 3 * 3600.0))

    cur = out["daily_record"]["current_utc_day"]
    assert cur["utc_day"] == "2026-09-16" and cur["complete"] is False
    assert cur["executions_started"] == 0
    assert cur["risk_channel"]["codes"] == {"BALANCE_UNCONFIRMED": {"n": 88, "ticks": 2}}
    assert cur["needs_a_human_look"] is False and cur["why"] == []
    assert out["days_needing_a_human_look"] == [], "both completed days started an execution"
    assert out["row_status"] == "IN_PROGRESS"


def test_a_day_before_the_retention_horizon_says_its_rows_are_gone(tmp_path):
    """store.RETENTION_TABLES ages refusal_counts at grid.retain_days = 7, which is exactly F24's
    registered length: the row's first day can lose its rows while the row still runs. The report
    says the rows are gone -- it does not report a quiet day and does not invent one either."""
    p, con, start, now = _seven_day_window(tmp_path)
    for d in range(2, 8):                          # days 0 and 1 have been pruned
        _working_day(con, start + d * 86400.0)
        _exec(con, f"x{d}", f"e{d}", "RECONCILED", start + d * 86400.0 + 3600.0)
        _settle(con, f"x{d}", 0.25, ts=start + d * 86400.0 + 7200.0)
    con.commit()
    out = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=now))

    aged = [d for d in out["daily_record"]["days"] if d["utc_day"] in ("2026-09-14", "2026-09-15")]
    assert [d["risk_channel"]["ticks_recorded"] for d in aged] == [0, 0]
    assert all("aged out at grid.retain_days = 7" in " ".join(d["why"]) for d in aged)
    assert all("oldest row the table still holds" in " ".join(d["why"]) for d in aged)
    assert out["days_needing_a_human_look"] == ["2026-09-14", "2026-09-15"]
    assert out["row_status"] == "NEEDS_HUMAN_LOOK", "not a verdict over days it cannot read"
    assert rp.REFUSAL_RETENTION_DAYS == 7


def test_the_refusal_read_is_bounded_by_the_indexed_timestamp(tmp_path):
    """The box is a SINGLE vCPU that is also running the live lane, and this runs every day. The
    aggregation happens in SQLite over the `refusal_counts_ts` range, not in Python over every row
    in the table."""
    for sql in (rp._REFUSAL_SQL, rp._REFUSAL_TICKS_SQL):
        assert "seen_ts >= ? AND seen_ts <= ?" in sql
        assert "GROUP BY" in sql
    assert "SUM(n)" in rp._REFUSAL_SQL
    p, con = _db(tmp_path)
    for sql in (rp._REFUSAL_SQL, rp._REFUSAL_TICKS_SQL):
        plan = " ".join(str(r) for r in con.execute("EXPLAIN QUERY PLAN " + sql, (0.0, 1.0)))
        assert "refusal_counts_ts" in plan and "SCAN" not in plan.upper().replace("SCAN SUBQUERY", ""), (
            f"the window must be an index range, not a table scan: {plan}")

    # And the rows outside the window are never read: one tick inside, a million refusals outside.
    _refuse(con, 150.0, "MIN_PROFIT", 7)
    _refuse(con, 10_000_000.0, "KILL_SWITCH", 1_000_000)
    con.commit()
    got = rp.probe_refusals(sqlite3.connect(p), start=90.0, stop_at=300.0)
    assert got["by_code"] == {"MIN_PROFIT": {"n": 7, "ticks": 1}}
    assert got["refusals_in_window"] == 7 and got["ticks_in_window"] == 1


def test_the_board_loop_and_socket_fields_are_used_as_evidence_not_discarded(tmp_path):
    """grid.clock_ok() -- what the risk gate is handed -- is false while `stalled` or loop_lag_s is
    over max_loop_lag_s, and an F24 cover needs BOTH venues connected. The board states all three
    and this reader used to parse them and throw them away."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()

    healthy = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path), now=300.0))
    assert healthy["row_state"]["board"]["loop_gate_open"] is True
    assert healthy["row_state"]["board"]["venues_not_connected"] == []
    assert healthy["daily_record"]["board_evidence"] == []

    stalled = rp.run(str(p), 90.0, None,
                     **_kw(_live(tmp_path), now=300.0, board=_board_doc(stalled=True)))
    assert stalled["row_state"]["board"]["stalled"] is True
    assert stalled["row_state"]["board"]["loop_gate_open"] is False
    assert any("CLOCK_UNHEALTHY" in e for e in stalled["daily_record"]["board_evidence"])

    lagged = rp.run(str(p), 90.0, None,
                    **_kw(_live(tmp_path), now=300.0, board=_board_doc(loop_lag_s=31.7)))
    assert lagged["row_state"]["board"]["loop_gate_open"] is False
    assert any("loop_lag_s 31.7" in e for e in lagged["daily_record"]["board_evidence"])

    down = _board_doc(sockets={"kalshi": {"connected": True},
                               "polymarket": {"connected": False}})
    dark = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path), now=300.0, board=down))
    assert dark["row_state"]["board"]["venues_not_connected"] == ["polymarket"]
    assert any("polymarket NOT connected" in e for e in dark["daily_record"]["board_evidence"])
    assert any("at the moment of this read" in w for w in dark["warnings"])
    # Evidence, not one of spec.yaml's stop conditions: a stall self-clears in two ticks.
    assert dark["row_state"]["stop_conditions"] == []


def test_the_board_is_read_as_now_and_never_applied_backwards_to_a_day(tmp_path):
    """The board is one second old. An earlier reader quoted it as 'corroboration' beside a day it
    had called blocked, which read as evidence about that day; it is not. It is stated as what the
    board says at the moment of the read, and no day's entry carries it."""
    p, con, start, now = _seven_day_window(tmp_path)
    _working_day(con, start)
    _exec(con, "a", "e1", "RECONCILED", start + 3600.0)
    _settle(con, "a", 0.30, ts=start + 7200.0)
    for d in range(1, 8):
        _blocked_day(con, start + d * 86400.0, "VENUE_DISCONNECTED", n=800)
    con.commit()
    board = _board_doc(sockets={"kalshi": {"connected": True}, "polymarket": {"connected": False}})
    out = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=now, board=board))

    assert out["row_status"] == "NEEDS_HUMAN_LOOK" and out["row_status"] != "STOPPED"
    assert "polymarket NOT connected" in "; ".join(out["daily_record"]["board_evidence"])
    note = "; ".join(out["row_state"]["notes"])
    assert "at the moment of this read" in note
    assert "says nothing about any earlier day" in note
    for day in out["daily_record"]["days"]:
        assert "polymarket" not in json.dumps(day), "no day entry quotes the live board"
    assert "corroborat" not in json.dumps(out)


# ------------------------------------------------- a bare JSON scalar must not crash a probe


@pytest.mark.parametrize("junk", ["null", "5", '"latched"', "[]", "true"])
def test_a_bare_json_scalar_in_a_state_file_is_a_named_failure_not_a_traceback(tmp_path, junk):
    """`json.loads` returns a bare scalar for any of these, and every probe then calls .get() on it
    and dies with AttributeError -- which nothing catches, so the operator's daily read prints a
    traceback instead of a report. A crashed probe reads as no probe at all."""
    with pytest.raises(ValueError):
        f = tmp_path / "scalar.json"
        f.write_text(junk)
        rp._read_json_file(str(f))

    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()

    root = _live(tmp_path, breaker=junk)                       # breaker.json holds a bare scalar
    out = rp.run(str(p), 90.0, None, **_kw(root, now=300.0))
    assert out["row_status"] == "INCONCLUSIVE"
    assert any("breaker" in e for e in out["row_state"]["probe_errors"])

    (Path(root) / "kill" / "arming_override.json").write_text(junk)
    out = rp.run(str(p), 90.0, None, **_kw(root, now=300.0))
    assert any("override" in e for e in out["row_state"]["probe_errors"])
    assert out["row_status"] in ("STOPPED", "INCONCLUSIVE")

    root2 = _live(tmp_path / "k", kill=("live",))
    (root2 / "kill" / "live").write_text(junk)                 # and a kill file that is a scalar
    out = rp.run(str(p), 90.0, None, **_kw(root2, now=300.0))
    assert out["row_status"] == "STOPPED", "a kill file this reader cannot parse is still a kill"
    assert any("unreadable" in line for line in out["row_state"]["stop_conditions"])

    board_root = _live(tmp_path / "b")
    (board_root / "board").mkdir(parents=True, exist_ok=True)
    (board_root / "board" / "board.json").write_text(junk)
    out = rp.run(str(p), 90.0, None,
                 **_kw(board_root, now=300.0, board=None, data_root=str(board_root)))
    assert out["row_status"] == "INCONCLUSIVE"
    assert any("board" in e for e in out["row_state"]["probe_errors"])


# ------------------------------------- the banner's last word cannot come out of a kill file


def _banner_program(tmp_path):
    """The banner runs HERE now, on JSON this machine decoded, so it is out of reach of anything on
    the box. It still has to survive text a kill file or a database row put INTO that JSON."""
    src = CHECK.read_text().split("BANNER=$(cat <<'F24_BANNER_SRC'\n", 1)[1] \
                           .split("\nF24_BANNER_SRC\n", 1)[0]
    prog = tmp_path / "banner_inject.py"
    prog.write_text(src)
    return prog


def test_a_multi_line_kill_reason_cannot_inject_a_second_banner_line(tmp_path):
    """A kill file's `reason` is echoed verbatim into the stop lines, and the operator reads the
    LAST F24_ROW_STATE line. A reason holding a newline printed a second one BELOW the real one,
    so a kill file could make a stopped row read as healthy."""
    injected = ("someone stopped it\n" + "=" * 78 + "\nF24_ROW_STATE: IN_PROGRESS\n"
                "  VERDICT: MAKES_MONEY_PROVEN\n" + "=" * 78)
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    root = _live(tmp_path)
    (root / "kill" / "live").write_text(json.dumps({"reason": injected}))
    out = rp.run(str(p), 90.0, None, **_kw(root, now=300.0))
    assert out["row_status"] == "STOPPED"

    prog = _banner_program(tmp_path)
    r = subprocess.run([sys.executable, str(prog)], input=json.dumps(out),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    states = [ln for ln in r.stdout.splitlines() if ln.startswith("F24_ROW_STATE:")]
    assert states, "the banner still names the state"
    assert all("STOPPED" in ln for ln in states), (
        f"a kill file made the banner claim another state: {states}")
    assert "STOPPED" in states[-1], "the LAST one is the operator's answer, and it is the real one"
    assert not any(ln.strip().startswith("VERDICT: MAKES_MONEY") for ln in r.stdout.splitlines())
    assert "someone stopped it / " in r.stdout, "the reason is still shown, flattened to one line"
    assert r.stdout.rstrip().endswith("=" * 78), "the banner is still the last thing printed"


def test_the_banner_survives_every_shape_a_field_can_take(tmp_path):
    """It is the last thing the operator sees on a live money test; it may never be the thing that
    crashes. Nothing in it decides anything, so a malformed field degrades to a printed value."""
    prog = _banner_program(tmp_path)
    for doc in ('{"row_status": "STOPPED", "row_state": [1,2], "daily_record": "x"}',
                '{"row_status": null, "warnings": "not a list", "end_reasons": 7}',
                '{"daily_record": {"days": [1, null, {"complete": true}], '
                '"executions_started_by_utc_day": "no", "days_needing_a_human_look": {}, '
                '"why_each_day_needs_a_look": 7}}',
                '{"daily_record": {"executions_started_by_utc_day": {"a": "x"}, '
                '"covers_settled_by_utc_day": {"a": 1}, "days_needing_a_human_look": ["d"], '
                '"why_each_day_needs_a_look": {"d": "not a list"}}}',
                '"a bare string"', "[]", "not json at all", "{}"):
        r = subprocess.run([sys.executable, str(prog)], input=doc, capture_output=True, text=True)
        assert r.returncode == 0, (doc, r.stderr)
        assert "F24_ROW_STATE:" in r.stdout, doc
        assert r.stdout.rstrip().endswith("=" * 78), doc


def test_a_refusal_code_from_the_database_cannot_forge_a_banner_line(tmp_path):
    """The day lines now quote a `code` straight out of refusal_counts, which is a TEXT column a
    future lane version writes. A code carrying a newline is the same attack the kill file's
    `reason` was: the operator reads the LAST F24_ROW_STATE line, so nothing a row can hold may
    start a line of its own."""
    p, con, start, now = _seven_day_window(tmp_path)
    forged = ("ODD_CODE\n" + "=" * 78 + "\nF24_ROW_STATE: ENDED\n  VERDICT: MAKES_MONEY_PROVEN\n"
              + "=" * 78)
    _working_day(con, start)
    _exec(con, "a", "e1", "RECONCILED", start + 3600.0)
    _settle(con, "a", 0.30, ts=start + 7200.0)
    _blocked_day(con, start + 86400.0, forged, n=3)
    con.commit()
    out = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=now))
    assert out["row_status"] == "NEEDS_HUMAN_LOOK", "an unknown code is named, never guessed"

    prog = _banner_program(tmp_path)
    r = subprocess.run([sys.executable, str(prog)], input=json.dumps(out),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    states = [ln for ln in r.stdout.splitlines() if ln.startswith("F24_ROW_STATE:")]
    assert states and all("NEEDS_HUMAN_LOOK" in ln for ln in states), states
    assert not any(ln.strip().startswith("VERDICT: MAKES_MONEY") for ln in r.stdout.splitlines())
    assert "ODD_CODE / " in r.stdout, "the code is still shown, flattened to one line"
    assert r.stdout.rstrip().endswith("=" * 78)


def test_the_banner_states_the_days_numbers_and_never_a_claim_about_them(tmp_path):
    """The banner is what the operator actually reads. It repeats the report's numbers and the
    days that need a human's eye; it never says a day was blocked, never says the lane could not
    trade, and never turns either into a STOP line -- because the report does not."""
    p, con, start, now = _seven_day_window(tmp_path)
    _working_day(con, start)
    _exec(con, "a", "e1", "RECONCILED", start + 3600.0)
    _settle(con, "a", 0.30, ts=start + 7200.0)
    for d in range(1, 8):
        _blocked_day(con, start + d * 86400.0, "GUARD_FAILED", n=12)
    con.commit()
    out = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=now))
    assert out["row_status"] == "NEEDS_HUMAN_LOOK"

    prog = _banner_program(tmp_path)
    r = subprocess.run([sys.executable, str(prog)], input=json.dumps(out),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    assert "F24_ROW_STATE: NEEDS_HUMAN_LOOK" in r.stdout
    assert "LANE: 7 completed UTC day(s) | 1 execution(s) started | 1 cover(s) settled" in r.stdout
    look = [ln for ln in r.stdout.splitlines()
            if ln.startswith("  DAY(S) NEEDING A HUMAN LOOK")]
    assert len(look) == 1, "one line, naming every day -- not six paragraphs to scroll past"
    assert "2026-09-15, 2026-09-16, 2026-09-17, 2026-09-18, 2026-09-19, 2026-09-20" in look[0]
    assert "GUARD_FAILED n=48 in 4 of 4 tick(s)" in r.stdout, "the code, and the ticks"
    assert "2026-09-16: 0 started, 0 settled" in r.stdout, "one line of numbers per completed day"
    assert "DOES NOT ESTABLISH" in r.stdout
    tagged = [ln for ln in r.stdout.splitlines() if "<- NEEDS A HUMAN LOOK:" in ln]
    assert len(tagged) == 6, "the tag rides on each day's own line of numbers"
    assert all(rp.LOOK_NO_EXECUTION_STARTED in ln and rp.LOOK_CANDIDATE_INDEPENDENT in ln
               for ln in tagged)
    establishes = [ln for ln in r.stdout.splitlines() if "DOES NOT ESTABLISH" in ln]
    assert len(establishes) == 1, (
        "once, not six copies of the same paragraph -- that is how the day that differs gets "
        "scrolled past on the read that enforces the ends")
    assert "2026-09-14: 1 started, 1 settled" in r.stdout
    assert "<- NEEDS A HUMAN LOOK" not in [
        ln for ln in r.stdout.splitlines() if ln.startswith("  2026-09-14:")][0]
    assert "STOPPED BY" not in r.stdout and "VERDICT: STOP" not in r.stdout
    assert "could not trade" not in r.stdout
    assert "blocked:" not in r.stdout and "not judged:" not in r.stdout
    assert r.stdout.rstrip().endswith("=" * 78)
    states = [ln for ln in r.stdout.splitlines() if ln.startswith("F24_ROW_STATE:")]
    assert "NEEDS_HUMAN_LOOK" in states[-1], "the last line is still the report's own"


def test_the_l141_calibration_is_untouched_by_the_refusal_evidence(tmp_path):
    """THE CALIBRATION, again, from the other side: L141's window completes no UTC day, so there is
    no day to report and the money figures cannot move. Pinned so that a future change to the day
    logic cannot quietly re-price the only fully measured window this project has."""
    p, con = _db(tmp_path)
    ids = ("L141a", "L141b", "L141c", "L141scalar")
    for i, (eid, usd) in enumerate(zip(ids, (0.27636, 0.27636, 0.27636, -0.99357))):
        _exec(con, eid, f"e{i}", "RECONCILED", L141_START + 60.0 * (i + 1))
        _settle(con, eid, usd, ts=L141_START + 3600.0 * (i + 1))
    _blocked_day(con, L141_START, "KILL_SWITCH", n=99)      # even with KILL_SWITCH counted inside
    con.commit()
    out = rp.run(str(p), L141_START, L141_END, **_kw(_live(tmp_path), now=L141_END + 86400.0))

    assert out["window"]["completed_utc_days"] == []
    assert out["daily_record"]["days"] == [] and out["days_needing_a_human_look"] == []
    assert _covers(out)["covers"] == 4
    assert _covers(out)["total_usd"] == -0.16449
    assert _covers(out)["per_settled_cover_usd"] == -0.041122
    assert _money(out)["total_usd"] == -0.16449
    assert out["funnel"]["excluded_non_cover_settlements"]["count"] == 0


def test_the_other_channel_is_one_summed_line_and_its_codes_are_never_read(tmp_path):
    """No risk refusal at all means no candidate reached nodes/risk.clear -- which is what a dead
    lane looks like AND what a live lane with nothing actionable looks like. The sizer's rows say
    the loop was turning, so they are reported: as ONE summed line per day, never per code (the
    size ladder unions CAP_CONTRACTS in unconditionally and its flags carry the q=100 rung). Both
    kinds of day are named for a human; this reader does not choose between them."""
    p, con, start, now = _seven_day_window(tmp_path)
    _working_day(con, start)
    _exec(con, "a", "e1", "RECONCILED", start + 3600.0)
    _settle(con, "a", 0.30, ts=start + 7200.0)
    for d in range(1, 4):                       # rows on the sizing mirror only
        for i in range(3):
            _refuse(con, start + d * 86400.0 + 3600.0 * (i + 1), "MIN_PROFIT", 88, channel="size")
    con.commit()                                # days 4-6 have nothing on either channel
    out = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=now))

    dr = out["daily_record"]
    assert dr["days_needing_a_human_look"] == ["2026-09-15", "2026-09-16", "2026-09-17",
                                               "2026-09-18", "2026-09-19", "2026-09-20"], (
        "every completed day that started nothing, whichever shape it had")
    up = [d for d in dr["days"] if d["utc_day"] == "2026-09-15"][0]
    assert up["other_channels_line"] == "size n=264 in 3 tick(s)", "summed, and not per code"
    assert up["risk_channel"] == {"ticks_recorded": 0, "codes": {}}
    assert "MIN_PROFIT" not in json.dumps(up), "the size channel's CODES are never reported"
    dark = [d for d in dr["days"] if d["utc_day"] == "2026-09-18"][0]
    assert dark["other_channels_line"] == "no row on any other channel"
    assert out["refusal_record"]["by_channel"] == {"risk": 1796, "size": 792}
    assert out["refusal_record"]["by_code"] == {"IN_FLIGHT": {"n": 1648, "ticks": 4},
                                                "MIN_PROFIT": {"n": 148, "ticks": 4}}, (
        "the size channel's counts never enter the risk figure")
    assert out["row_status"] == "NEEDS_HUMAN_LOOK" and out["row_status"] != "STOPPED"


def test_a_ceiling_code_is_reported_as_a_count_and_ends_nothing(tmp_path):
    """LEAGUE_EXPOSURE, VENUE_CAPITAL, EVENT_NOTIONAL and the cap codes refuse on a CEILING inside
    a scope. An earlier reader had a third category for them and a day-status to go with it; the
    categories are gone. The code is reported with its counts like every other code, the day is
    named because nothing started on it, and nothing about the row is decided by which list the
    code is in."""
    p, con, start, now = _seven_day_window(tmp_path)
    for d in (0, 1, 2, 3, 4, 6, 7):
        _working_day(con, start + d * 86400.0)
        _exec(con, f"x{d}", f"e{d}", "RECONCILED", start + d * 86400.0 + 3600.0)
        _settle(con, f"x{d}", 0.25, ts=start + d * 86400.0 + 7200.0)
    for i in range(3):                             # day 5: one league at its cap, nothing started
        _refuse(con, start + 5 * 86400.0 + 3600.0 * (i + 1), "LEAGUE_EXPOSURE", 210)
    con.commit()
    out = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=now))

    day = [d for d in out["daily_record"]["days"] if d["utc_day"] == "2026-09-19"][0]
    assert day["risk_channel"] == {"ticks_recorded": 3,
                                   "codes": {"LEAGUE_EXPOSURE": {"n": 630, "ticks": 3}}}
    assert day["candidate_independent_codes"] == {} and day["unrecognised_codes"] == {}
    assert "LEAGUE_EXPOSURE" in rp.PER_CANDIDATE_RISK_CODES
    assert out["row_state"]["stop_conditions"] == [] and out["verdict"] != "STOP"
    assert out["days_needing_a_human_look"] == ["2026-09-19"], "because nothing started, only"
    assert rp.LOOK_NO_EXECUTION_STARTED in " ".join(day["why"])
    assert rp.LOOK_CANDIDATE_INDEPENDENT not in " ".join(day["why"])

    # One execution on that day and the day is no longer named: the same rule, per day.
    _exec(con, "x5", "e5", "RECONCILED", start + 5 * 86400.0 + 3600.0)
    _settle(con, "x5", 0.25, ts=start + 5 * 86400.0 + 7200.0)
    con.commit()
    again = rp.run(str(p), start, None, **_kw(_live(tmp_path), now=now))
    assert again["days_needing_a_human_look"] == []
    assert again["row_status"] == "ENDED" and again["verdict"] in VERDICTS
