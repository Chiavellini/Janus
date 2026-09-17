"""F24 report pins: the verdict follows the registered rule, and the interval is event-clustered.

The report was also calibrated on the box against L141's window: all four covers total -$0.16449
(-$0.041122 each) and, excluding the scalar cover, three total +$0.82908 ($0.27636 each). Nothing
here may change how an ORDINARY reconciled cover's realised net is summed, or that calibration
stops meaning anything.

The rest of this file is the 2026-09-17 audit's six defects, one test each, plus the start pin.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("f24_report", Path(__file__).with_name("report.py"))
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)

HERE = Path(__file__).parent


# ----------------------------------------------------------------------------------------- fixtures


def _db(tmp_path):
    p = tmp_path / "t.sqlite"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE executions(execution_id TEXT, event_id TEXT, league TEXT, mode TEXT, "
                "state TEXT, started_utc REAL, first_filled REAL, hedge_filled REAL)")
    con.execute("CREATE TABLE execution_settlements(execution_id TEXT, realized_usd REAL, released INTEGER, "
                "kind TEXT, settled_ts REAL)")
    return p, con


def _exec(con, eid, event, state, started, *, mode="LIMITED_LIVE", first=10.0, hedge=10.0, league="mlb"):
    con.execute("INSERT INTO executions VALUES(?,?,?,?,?,?,?,?)",
                (eid, event, league, mode, state, started, first, hedge))


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
    assert out["net"]["total_usd"] == 0.4


def test_an_ordinary_reconciled_cover_is_summed_exactly_as_before(tmp_path):
    """The L141 calibration must keep reproducing: four covers, -0.16449, -0.041122 each."""
    p, con = _db(tmp_path)
    for i, usd in enumerate((0.27636, 0.27636, 0.27636, -0.99357)):
        _exec(con, f"c{i}", f"e{i}", "RECONCILED", 100.0 + i)
        _settle(con, f"c{i}", usd)
    con.commit()
    out = rp.run(str(p), 90.0, 300.0, **_kw(_live(tmp_path), now=1000.0))
    assert out["funnel"]["settled_covers"] == 4
    assert out["net"]["total_usd"] == -0.16449
    assert out["net"]["per_settled_cover_usd"] == -0.041122


def test_an_unfinished_row_says_in_progress(tmp_path):
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.3)
    con.commit()
    out = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path), now=300.0))
    assert out["ended"] is False and out["verdict"].startswith("IN_PROGRESS")


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
    assert out["net"]["total_usd"] == 0.30, "the naked leg's payoff must not enter the realised net"
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
    assert out["funnel"]["settled_covers"] == 0 and out["net"]["total_usd"] == 0.0
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
    assert out["net"]["total_usd"] == 0.2


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
    assert out["funnel"]["settled_covers"] == 1 and out["net"]["total_usd"] == 0.30
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
    assert out["net"]["total_usd"] == 0.30
    assert out["funnel"]["excluded_wrong_mode"]["execution_ids"] == ["paper"]


# ------------------------------------------------ defect 6: no $/day projected out of a partial day


def test_no_dollar_per_day_figure_is_projected_from_a_partial_day(tmp_path):
    """A single +$0.28 cover an hour into the row printed 6.72/day. Nothing may do that again."""
    p, con = _db(tmp_path)
    _exec(con, "a", "e1", "RECONCILED", 100.0)
    _settle(con, "a", 0.28, ts=1000.0)
    con.commit()
    out = rp.run(str(p), 90.0, None, **_kw(_live(tmp_path), now=90.0 + 3600.0))
    assert "per_elapsed_day_usd" not in out["net"]
    assert out["window"]["completed_utc_days"] == []
    assert out["net"]["observed_mean_usd_per_completed_utc_day"] is None
    assert out["net"]["by_completed_utc_day_usd"] == {}


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
    assert out["net"]["by_completed_utc_day_usd"] == {"1970-01-02": 0.4, "1970-01-03": -0.1}
    assert out["net"]["observed_mean_usd_per_completed_utc_day"] == 0.15
    assert out["net"]["total_usd"] == 10.29, "the running day's cover still counts in the total"
    assert out["net"]["by_settle_day_usd"]["1970-01-04"] == 9.99


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
