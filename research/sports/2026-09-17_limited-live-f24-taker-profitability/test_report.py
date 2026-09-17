"""F24 report pins: the verdict follows the registered rule, and the interval is event-clustered.

The report was also calibrated on the box against L141's window: all four covers total -$0.16449
(-$0.041122 each) and, excluding the scalar cover, three total +$0.82908 ($0.27636 each).
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

_spec = importlib.util.spec_from_file_location("f24_report", Path(__file__).with_name("report.py"))
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)


def test_registered_constants():
    assert (rp.END_COVERS, rp.END_DAYS, rp.CUMULATIVE_LOSS_STOP_USD) == (30, 7, 50.0)
    assert (rp.MIN_COVERS_FOR_VERDICT, rp.RESAMPLES, rp.SEED) == (10, 10000, 170924)


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


def _db(tmp_path):
    p = tmp_path / "t.sqlite"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE executions(execution_id TEXT, event_id TEXT, league TEXT, state TEXT, started_utc REAL)")
    con.execute("CREATE TABLE execution_settlements(execution_id TEXT, realized_usd REAL, released INTEGER, "
                "kind TEXT, settled_ts REAL)")
    return p, con


def test_only_released_settlements_are_scored_and_unsettled_fills_are_counted(tmp_path):
    p, con = _db(tmp_path)
    con.executemany("INSERT INTO executions VALUES(?,?,?,?,?)", [
        ("a", "e1", "mlb", "RECONCILED", 100.0),
        ("b", "e2", "mlb", "HEDGED", 101.0),          # filled, not yet settled
        ("c", "e3", "mlb", "BOOK_MOVED", 102.0),      # declined before the wire
        ("d", "e4", "mlb", "RECONCILED", 50.0),       # before the window
    ])
    con.executemany("INSERT INTO execution_settlements VALUES(?,?,?,?,?)", [
        ("a", 0.4, 1, "COVER", 200.0),
        ("d", 9.0, 1, "COVER", 60.0),
    ])
    con.commit()
    out = rp.run(str(p), 90.0, 300.0)
    assert out["funnel"]["executions"] == 3 and out["funnel"]["settled_covers"] == 1
    assert out["funnel"]["filled_not_yet_settled"] == 1
    assert out["net"]["total_usd"] == 0.4


def test_the_cumulative_loss_stop_ends_the_row(tmp_path):
    p, con = _db(tmp_path)
    for i in range(3):
        con.execute("INSERT INTO executions VALUES(?,?,?,?,?)", (f"x{i}", f"e{i}", "mlb", "RECONCILED", 100.0 + i))
        con.execute("INSERT INTO execution_settlements VALUES(?,?,?,?,?)", (f"x{i}", -20.0, 1, "COVER", 200.0))
    con.commit()
    out = rp.run(str(p), 90.0, 300.0)
    assert out["ended"] is True and out["verdict"] == "STOP"


def test_an_unfinished_row_says_in_progress(tmp_path):
    p, con = _db(tmp_path)
    con.execute("INSERT INTO executions VALUES('a','e1','mlb','RECONCILED',100.0)")
    con.execute("INSERT INTO execution_settlements VALUES('a',0.3,1,'COVER',200.0)")
    con.commit()
    out = rp.run(str(p), 90.0, 300.0)
    assert out["ended"] is False and out["verdict"].startswith("IN_PROGRESS")
