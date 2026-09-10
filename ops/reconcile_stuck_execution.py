#!/usr/bin/env python3
"""Reconcile an execution the machine left before a terminal state, by hand, with the evidence.

    python3 ops/reconcile_stuck_execution.py <execution_id_prefix>            # show: the row, its order, the venue's answer
    python3 ops/reconcile_stuck_execution.py <execution_id_prefix> --confirm  # write the terminal state

The machine records its own failures; this is for the case it could not (2026-09-08 01:17Z: the
worker raised on the journal write after the leg A POST and the row stayed LEG_A_SUBMITTED). It
asks the venue for trades since the execution started and for the balance before it writes
anything; with any trade on the order's asset it refuses ("a position: reconcile that first,
nodes/reconcile"). With none: the execution -> ORDER_REJECTED (released), its order ->
UNFILLED, the reservation released, the transition rows carry this text. Run on the host that
owns the store (the box: `sudo -u janus JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box ...`).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kernel.schema import ExecutionState  # noqa: E402
from nodes.risk.ledger import ExposureLedger  # noqa: E402
from nodes.store_tuples.store import DEFAULT_DB, TupleStore  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("execution_id")
    ap.add_argument("--db", default=os.environ.get("JANUS_TUPLES_DB", str(DEFAULT_DB)))
    ap.add_argument("--confirm", action="store_true")
    a = ap.parse_args()
    st = TupleStore(a.db, isolation_level="IMMEDIATE", timeout_s=120.0)   # beside a running lane: wait for its lock, never fail on a snapshot upgrade
    c = st.con
    rows = c.execute("SELECT * FROM executions WHERE execution_id LIKE ?", (a.execution_id + "%",)).fetchall()
    if len(rows) != 1:
        print(f"{len(rows)} executions match {a.execution_id!r}; need exactly one"); return 2
    cols = [r[1] for r in c.execute("PRAGMA table_info(executions)")]
    ex = dict(zip(cols, rows[0]))
    state = ExecutionState(ex["state"])
    print(f"execution {ex['execution_id']} {ex['event_id']} q={ex['quantity']:g} state={state.value} "
          f"first_filled={ex['first_filled']} unhedged={ex['unhedged']} released={ex['released']} started={ex['started_utc']:.0f}")
    if state.is_terminal:
        print("already terminal; nothing to do"); return 0
    orders = c.execute("SELECT client_order_id, venue, state, price, contracts, filled_contracts, venue_order_id, outcome_id "
                       "FROM orders WHERE opportunity_id=? AND submitted_utc >= ? ORDER BY submitted_utc",
                       (ex["opportunity_id"], ex["started_utc"] - 1)).fetchall()
    for o in orders:
        print("  order", o)
    if ex["first_filled"] or ex["unhedged"]:
        print("the row says something filled: this is the UNHEDGED path (nodes/reconcile), not this script"); return 3
    # the venue's answer: trades since the execution started
    venues = {o[1] for o in orders}
    trades = []
    if "polymarket" in venues:
        from nodes.exec_polymarket.client import PyClobTransport
        t = PyClobTransport()
        trades = t.trades(after_ts=ex["started_utc"] - 60)
        print(f"  polymarket: {len(trades)} trades since start; balance {t.balance_usd()}")
    if "kalshi" in venues:
        print("  kalshi orders: check the fills by hand (ops/kalshi_shards.py / the venue's UI) before --confirm")
    assets = {o[7] for o in orders}
    hits = [tr for tr in trades if str(tr.get("asset_id")) in assets or str(tr.get("market")) in assets]
    if hits:
        print(f"  {len(hits)} trades on this order's asset: a position; reconcile that first (nodes/reconcile)"); return 4
    if not a.confirm:
        print("no trade on the order's asset. Re-run with --confirm to write ORDER_UNFILLED (released), UNFILLED, release the reservation.")
        return 0
    now = time.time()
    detail = (f"manual reconcile {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))}: no terminal state after "
              f"{state.value}; venue shows no trade on the asset since start ({len(trades)} trades total); nothing filled; released")
    c.execute("INSERT INTO execution_transitions(seen_ts, execution_id, from_state, to_state, detail) VALUES(?,?,?,?,?)",
              (now, ex["execution_id"], state.value, ExecutionState.ORDER_UNFILLED.value, detail))
    sets = {"state": ExecutionState.ORDER_UNFILLED.value, "last_utc": now, "released": 1}
    if "detail" in cols:
        sets["detail"] = detail
    c.execute("UPDATE executions SET " + ", ".join(f"{k}=?" for k in sets) + " WHERE execution_id=?", (*sets.values(), ex["execution_id"]))
    for o in orders:
        if o[2] in ("UNCONFIRMED",):
            c.execute("UPDATE orders SET state='UNFILLED', last_utc=? WHERE client_order_id=?", (now, o[0]))
            # the journal's columns (nodes/execution/journal.py JOURNAL_DDL): no `detail`; the note rides in raw_json.
            # Until 2026-09-07 this named a column the table lacks, so --confirm failed here and wrote nothing.
            c.execute("INSERT INTO order_events(seen_ts, client_order_id, kind, state, raw_json) VALUES(?,?,?,?,?)",
                      (now, o[0], "manual", "UNFILLED", json.dumps({"note": detail})))
    c.commit()
    if ex.get("reservation_id"):
        print("reservation released:", ExposureLedger(st).release(ex["reservation_id"], reason=detail, now=now))
    print("written:", c.execute("SELECT state, released FROM executions WHERE execution_id=?", (ex["execution_id"],)).fetchone())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
