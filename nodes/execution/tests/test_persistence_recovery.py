import json
import sqlite3

import pytest

from nodes.execution.persistence_recovery import resolve_recovered_persistence
from nodes.risk.flags import FLAGS_DDL, unresolved_flag_rows


CID = "b" * 32
HEDGE = "c" * 32
EXID = "e" * 32


class Store:
    def __init__(self, con):
        self.con = con


def world():
    con = sqlite3.connect(":memory:")
    con.executescript(FLAGS_DDL + """
    CREATE TABLE orders(
      client_order_id TEXT PRIMARY KEY, venue TEXT, mode TEXT, market_id TEXT, outcome_id TEXT,
      side TEXT, price REAL, contracts REAL, time_in_force TEXT, opportunity_id TEXT, state TEXT,
      venue_order_id TEXT, filled_contracts REAL, avg_price REAL, fee_usd REAL, open INTEGER,
      settlement_pending INTEGER, raw_status TEXT, submitted_utc REAL, last_utc REAL, detail TEXT,
      execution_id TEXT);
    CREATE TABLE executions(
      execution_id TEXT PRIMARY KEY, opportunity_id TEXT, event_id TEXT, league TEXT, mode TEXT,
      state TEXT, first_client_id TEXT, hedge_client_ids TEXT, unwind_client_ids TEXT,
      reservation_id TEXT, released INTEGER);
    CREATE TABLE venue_fills(
      fill_id TEXT PRIMARY KEY, venue TEXT, venue_order_id TEXT, contracts REAL, price REAL,
      fee_usd REAL, is_taker INTEGER, ts REAL, final INTEGER);
    CREATE TABLE pm_bounded_taker_orders(
      client_order_id TEXT PRIMARY KEY, requested_contracts REAL, max_requested_contracts TEXT,
      max_collateral_usd TEXT, max_accepted_excess TEXT, authorized_utc REAL);
    CREATE TABLE execution_settlements(
      execution_id TEXT PRIMARY KEY, opportunity_id TEXT, event_id TEXT, league TEXT, mode TEXT,
      settled_ts REAL, released INTEGER, legs_json TEXT);
    CREATE TABLE capital_reservations(
      reservation_id TEXT PRIMARY KEY, event_id TEXT, league TEXT, opportunity_id TEXT,
      released_utc REAL);
    """)
    common = ("LIMITED_LIVE", "opp", EXID)
    con.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (CID, "polymarket", common[0], "pm", "pm", "buy_yes", .41, 10, "ioc", common[1],
                 "FILLED", "pm-order", 10.75, .38, .12, 0, 0, "guard_fills", 1000, 1002, "final", common[2]))
    con.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (HEDGE, "kalshi", common[0], "ks", "ks:NO", "buy_no", .64, 10, "ioc", common[1],
                 "FILLED", "ks-order", 10, .64, .16, 0, 0, "executed", 1001, 1003, "final", common[2]))
    con.execute("INSERT INTO executions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (EXID, "opp", "event", "wta", common[0], "RECONCILED", CID,
                 json.dumps([HEDGE]), "[]", "reserve", 1))
    con.execute("INSERT INTO venue_fills VALUES(?,?,?,?,?,?,?,?,?)",
                ("pm-fill", "polymarket", "pm-order", 10.75, .38, .12, 1, 1001, 1))
    con.execute("INSERT INTO venue_fills VALUES(?,?,?,?,?,?,?,?,?)",
                ("ks-fill", "kalshi", "ks-order", 10, .64, .16, 1, 1002, 1))
    con.execute("INSERT INTO pm_bounded_taker_orders VALUES(?,?,?,?,?,?)",
                (CID, 10, "10", "12", "1", 1000))
    legs = [
        dict(venue="polymarket", client_order_id=CID, outcome_id="pm", side="buy_yes",
             contracts=10.75, price=.38, fee_usd=.12, state="FILLED", final=True),
        dict(venue="kalshi", client_order_id=HEDGE, outcome_id="ks:NO", side="buy_no",
             contracts=10, price=.64, fee_usd=.16, state="FILLED", final=True),
    ]
    con.execute("INSERT INTO execution_settlements VALUES(?,?,?,?,?,?,?,?)",
                (EXID, "opp", "event", "wta", common[0], 1100, 1, json.dumps(legs)))
    con.execute("INSERT INTO capital_reservations(reservation_id, event_id, league, opportunity_id, released_utc) VALUES(?,?,?,?,?)",
                ("reserve", "event", "wta", "opp", 1100))
    con.execute("INSERT INTO lane_flags(seen_ts,flag,detail) VALUES(?,?,?)", (1001,
        "ORDER_PERSISTENCE_FAILED",
        f"ORDER_PERSISTENCE_FAILED: {CID}: OperationalError: database is locked; independent kill failed: "
        "PermissionError: [Errno 13] Permission denied: '/srv/janus/kill/live'"))
    con.commit()
    return con, Store(con)


def test_complete_terminal_economic_record_resolves_exact_flag():
    con, store = world()
    assert resolve_recovered_persistence(store, now=1200, verify_pass=lambda: True)
    assert unresolved_flag_rows(con, "ORDER_PERSISTENCE_FAILED") == []
    marker = con.execute("SELECT flag,detail FROM lane_flags ORDER BY id DESC").fetchone()
    assert marker[0] == "ORDER_PERSISTENCE_FAILED_RESOLVED_EXACT"
    assert CID not in marker[1], "the exact flag digest owns identity; resolution detail stays bounded"


@pytest.mark.parametrize("mutation", [
    "bad_detail", "open", "cash_pending", "fifo_partial", "unreconciled", "unreleased",
    "no_settlement", "no_reservation", "no_bound", "excess_over_bound", "unsafe_pass",
])
def test_incomplete_or_changed_evidence_never_resolves(mutation):
    con, store = world()
    if mutation == "bad_detail":
        con.execute("UPDATE lane_flags SET detail=detail||' extra'")
    elif mutation == "open":
        con.execute("UPDATE orders SET open=1 WHERE client_order_id=?", (CID,))
    elif mutation == "cash_pending":
        con.execute("UPDATE orders SET settlement_pending=1 WHERE client_order_id=?", (CID,))
    elif mutation == "fifo_partial":
        con.execute("UPDATE venue_fills SET final=0 WHERE fill_id='pm-fill'")
    elif mutation == "unreconciled":
        con.execute("UPDATE executions SET state='HEDGED'")
    elif mutation == "unreleased":
        con.execute("UPDATE executions SET released=0")
    elif mutation == "no_settlement":
        con.execute("DELETE FROM execution_settlements")
    elif mutation == "no_reservation":
        con.execute("DELETE FROM capital_reservations")
    elif mutation == "no_bound":
        con.execute("DELETE FROM pm_bounded_taker_orders")
    elif mutation == "excess_over_bound":
        con.execute("UPDATE pm_bounded_taker_orders SET max_accepted_excess='.5'")
    con.commit()
    safe = mutation != "unsafe_pass"
    assert not resolve_recovered_persistence(store, now=1200, verify_pass=lambda: safe)
    assert len(unresolved_flag_rows(con, "ORDER_PERSISTENCE_FAILED")) == 1


def test_evidence_change_between_precheck_and_writer_lock_never_resolves():
    con, store = world()
    calls = 0

    def raced():
        nonlocal calls
        calls += 1
        if calls == 2:
            con.execute("UPDATE venue_fills SET final=0 WHERE fill_id='pm-fill'")
        return True

    assert not resolve_recovered_persistence(store, now=1200, verify_pass=raced)
    assert len(unresolved_flag_rows(con, "ORDER_PERSISTENCE_FAILED")) == 1
