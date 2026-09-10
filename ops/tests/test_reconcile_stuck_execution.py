#!/usr/bin/env python3
"""ops/reconcile_stuck_execution.py end to end against a temp store.

Why: until 2026-09-07 its --confirm inserted into order_events(client_order_id, kind, state,
seen_ts, detail), a column the journal's table does not have, so the last statement raised and
the execution stayed LEG_A_SUBMITTED, which is the very row the script exists to close.
"""
from __future__ import annotations

import json
import sqlite3
import sys

from nodes.execute.records import ExecutionRecords
from nodes.execution.journal import Journal
from nodes.risk.ledger import ExposureLedger, Refused
from nodes.risk.limits import load_limits
from nodes.store_tuples.store import TupleStore
import ops.reconcile_stuck_execution as rse

T = 1_800_000_000.0
EXEC_ID = "abc123def456stuck"


def _stuck_store(tmp_path):
    db = tmp_path / "t.sqlite"
    store = TupleStore(db, enforce_volume=False)
    ExecutionRecords(store)
    Journal(store)
    r = ExposureLedger(store).reserve(event_id="espn:mlb:1", league="mlb", per_venue_usd={"kalshi": 4.4, "polymarket": 4.4},
                                      limits=load_limits(), opportunity_id="o1", now=T - 300)
    assert not isinstance(r, Refused), r
    store.con.execute(
        "INSERT INTO executions(execution_id, opportunity_id, event_id, league, mode, state, started_utc, last_utc, quantity, "
        "first_filled, hedge_filled, unhedged, reservation_id, released) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (EXEC_ID, "o1", "espn:mlb:1", "mlb", "LIMITED_LIVE", "LEG_A_SUBMITTED", T - 300, T - 300, 10, 0, 0, 0, r.reservation_id, 0))
    # a kalshi order: the script imports the Polymarket transport only when a polymarket order exists
    store.con.execute(
        "INSERT INTO orders(client_order_id, venue, mode, market_id, outcome_id, side, price, contracts, time_in_force, "
        "opportunity_id, state, submitted_utc, last_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("cid-a", "kalshi", "LIMITED_LIVE", "KXMLBGAME-X", "KXMLBGAME-X", "yes", 0.44, 10, "IOC", "o1", "UNCONFIRMED", T - 299, T - 299))
    store.con.commit()
    store.con.close()
    return db, r.reservation_id


def _run(monkeypatch, db, *args):
    monkeypatch.setattr(rse, "TupleStore", lambda p, **kw: TupleStore(p, enforce_volume=False))
    monkeypatch.setitem(sys.modules, "nodes.exec_polymarket.client", None)      # any venue import is a test failure
    monkeypatch.setattr(sys, "argv", ["reconcile_stuck_execution.py", EXEC_ID[:6], "--db", str(db), *args])
    return rse.main()


def test_the_dry_run_writes_nothing_and_confirm_closes_every_row(tmp_path, monkeypatch, capsys):
    db, rid = _stuck_store(tmp_path)
    assert _run(monkeypatch, db) == 0
    assert "Re-run with --confirm" in capsys.readouterr().out
    con = sqlite3.connect(db)
    assert con.execute("SELECT state, released FROM executions").fetchone() == ("LEG_A_SUBMITTED", 0)
    assert con.execute("SELECT COUNT(*) FROM execution_transitions").fetchone() == (0,)
    con.close()

    assert _run(monkeypatch, db, "--confirm") == 0
    out = capsys.readouterr().out
    assert "reservation released: True" in out and "written: ('ORDER_UNFILLED', 1)" in out, out
    con = sqlite3.connect(db)
    assert con.execute("SELECT state, released FROM executions WHERE execution_id=?", (EXEC_ID,)).fetchone() == ("ORDER_UNFILLED", 1)
    assert con.execute("SELECT from_state, to_state FROM execution_transitions WHERE execution_id=?", (EXEC_ID,)).fetchall() == \
        [("LEG_A_SUBMITTED", "ORDER_UNFILLED")]
    assert con.execute("SELECT state FROM orders WHERE client_order_id='cid-a'").fetchone() == ("UNFILLED",)
    ev = con.execute("SELECT kind, state, raw_json FROM order_events WHERE client_order_id='cid-a'").fetchall()
    assert len(ev) == 1 and ev[0][0] == "manual" and ev[0][1] == "UNFILLED", ev
    assert json.loads(ev[0][2])["note"].startswith("manual reconcile "), ev
    released_utc, reason = con.execute("SELECT released_utc, release_reason FROM capital_reservations WHERE reservation_id=?", (rid,)).fetchone()
    assert released_utc is not None and reason.startswith("manual reconcile "), (released_utc, reason)
    con.close()

    assert _run(monkeypatch, db, "--confirm") == 0
    assert "already terminal" in capsys.readouterr().out


def test_a_row_that_says_something_filled_is_refused_to_the_unhedged_path(tmp_path, monkeypatch, capsys):
    db, _ = _stuck_store(tmp_path)
    con = sqlite3.connect(db)
    con.execute("UPDATE executions SET first_filled=10, unhedged=10, state='LEG_A_FILLED'")
    con.commit(); con.close()
    assert _run(monkeypatch, db, "--confirm") == 3
    assert "UNHEDGED path" in capsys.readouterr().out
    con = sqlite3.connect(db)
    assert con.execute("SELECT state, released FROM executions").fetchone() == ("LEG_A_FILLED", 0)
    assert con.execute("SELECT released_utc FROM capital_reservations").fetchone() == (None,)
    con.close()
