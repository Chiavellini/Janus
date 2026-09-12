#!/usr/bin/env python3
"""L93: whether the lane is WINNING, which nothing else in the watchdog asks.

Before this, all ~33 watchdog conditions were operational (CRASHED, STALE, KILL_FILE_PRESENT,
COVERAGE_GAP...) and the first automatic money signal was the daily realized-loss breaker at -$25 --
about twenty-five losing covers in a day. On 2026-09-12 two covers lost $2.33 between them and
nothing said a word; the operator found it by eye on the board.
"""
from __future__ import annotations

import sqlite3

from nodes.risk.health import cover_pnl_alerts


def _db(tmp_path, rows):
    """rows: (realized_usd, hedged_detail, mode)"""
    p = tmp_path / "t.sqlite"
    con = sqlite3.connect(p)
    con.executescript(
        "CREATE TABLE execution_settlements (execution_id TEXT, realized_usd REAL, settled_ts REAL);"
        "CREATE TABLE executions (execution_id TEXT, mode TEXT);"
        "CREATE TABLE execution_transitions (id INTEGER PRIMARY KEY, execution_id TEXT, to_state TEXT, detail TEXT);")
    for i, (usd, detail, mode) in enumerate(rows):
        eid = f"e{i}"
        con.execute("INSERT INTO execution_settlements VALUES (?,?,?)", (eid, usd, 1000.0 + i))
        con.execute("INSERT INTO executions VALUES (?,?)", (eid, mode))
        con.execute("INSERT INTO execution_transitions (execution_id, to_state, detail) VALUES (?,?,?)",
                    (eid, "HEDGED", detail))
    con.commit()
    return p


def test_a_run_of_losing_covers_is_an_alert(tmp_path):
    db = _db(tmp_path, [(-0.5, "ok", "LIMITED_LIVE")] * 4 + [(+0.2, "ok", "LIMITED_LIVE")] * 2)
    out = cover_pnl_alerts(db)
    assert any("COVERS_LOSING" in x for x in out)
    assert "-1.60 USD" in " ".join(out), "the window's net, not just a count"


def test_covers_that_settled_above_their_own_break_even_are_an_alert(tmp_path):
    """`protect._hedged` writes ABOVE_BREAK_EVEN onto the HEDGED transition -- the label the lane has
    always produced and never read. `executions.detail` is overwritten at settle; the history is not."""
    hedged = "25.0 hedged @ 0.51 ABOVE_BREAK_EVEN 0.4233: a locked loss inside the cap, still a cover"
    db = _db(tmp_path, [(+0.1, hedged, "LIMITED_LIVE")] * 3 + [(+0.5, "clean", "LIMITED_LIVE")] * 3)
    out = cover_pnl_alerts(db)
    assert any("HEDGE_ABOVE_BREAK_EVEN" in x for x in out)
    assert not any("COVERS_LOSING" in x for x in out), "these all made money; the hedge still cost too much"


def test_paper_covers_are_never_money(tmp_path):
    db = _db(tmp_path, [(-5.0, "ok", "PAPER_EXECUTION")] * 8)
    assert cover_pnl_alerts(db) == []


def test_a_healthy_window_and_an_absent_database_are_both_silent(tmp_path):
    assert cover_pnl_alerts(_db(tmp_path, [(+0.3, "ok", "LIMITED_LIVE")] * 6)) == []
    assert cover_pnl_alerts(tmp_path / "nope.sqlite") == []
