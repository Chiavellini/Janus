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

The rest of this file is the 2026-09-17 audit's six defects, one test each, the start pin, and the
two-figure separation with the registered-end truncation and the unsettled-cover rule beside it.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sqlite3
import subprocess
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


def _db(tmp_path):
    """The executions table as it shipped: no `*_avg_price` / `*_unwound` (records._LATER_COLUMNS)."""
    p = tmp_path / "t.sqlite"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE executions(execution_id TEXT, event_id TEXT, league TEXT, mode TEXT, "
                "state TEXT, started_utc REAL, first_filled REAL, hedge_filled REAL)")
    con.execute("CREATE TABLE execution_settlements(execution_id TEXT, realized_usd REAL, released INTEGER, "
                "kind TEXT, settled_ts REAL)")
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
    return p, con


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


def _live(tmp_path, *, override="default", kill=(), start_pin=None):
    """A stand-in for the box's /srv/janus. Nothing here is ever written by the reader."""
    root = tmp_path / "srv"
    (root / "kill").mkdir(parents=True, exist_ok=True)
    (root / "release-audit").mkdir(parents=True, exist_ok=True)
    if override == "default":
        override = _override()
    if override is not None:
        (root / "kill" / "arming_override.json").write_text(json.dumps(override))
    for name in kill:
        (root / "kill" / name).write_text(json.dumps({"reason": f"{name} latched", "latched_utc": 1.0}))
    if start_pin is not None:
        (root / "release-audit" / "f24_start_utc").write_text(f"{start_pin}\n")
    return root


def _quiet(_con, _flag):
    return []


def _kw(root, **extra):
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
    """Degrade with a named field. Never crash, and never claim IN_PROGRESS in silence."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()

    def reader(_con, _flag):
        raise sqlite3.OperationalError("no such table: lane_flags")

    out = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path), now=300.0, flag_reader=reader))
    assert out["verdict"].startswith("IN_PROGRESS")
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
    assert 'trap \'rm -f "$F24_PY"\' EXIT' in payload_a, "the trap removes ONLY this run's file"

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


def test_check_f24_carries_the_reader_to_the_box_unchanged(tmp_path):
    """The reader is embedded in the payload, not piped: ops/box/run.sh ignores stdin when it is
    given an argument. What arrives on the box must be this file, byte for byte."""
    payload = _check_payload(tmp_path, "100.0", "x")
    body = payload.split("<<'F24_REPORT_EOF'\n", 1)[1].split("\nF24_REPORT_EOF\n", 1)[0]
    assert body == REPORT_PY.read_text().rstrip("\n")


def test_check_f24_refuses_include_and_exclude(tmp_path):
    """--include/--exclude change WHICH covers are scored; that has to be a deliberate act on the
    box, not a flag on the daily progress check."""
    runner = tmp_path / "runner.sh"
    runner.write_text('#!/usr/bin/env bash\ntrue\n')
    r = subprocess.run(["bash", str(CHECK), "100.0", "200.0", "--exclude", "x"],
                       capture_output=True, text=True,
                       env={**os.environ, "F24_RUNNER": str(runner)})
    assert r.returncode == 2 and "--include/--exclude" in r.stderr
