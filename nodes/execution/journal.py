#!/usr/bin/env python3
"""The order journal: a row BEFORE the POST, updated by every answer. Shared by every venue.

The pattern is the parked Cloudbet client's, generalised: journal PENDING with the client order
id, then send, then record what came back. A process that dies between the two leaves a row in
UNCONFIRMED, which the reconcile pass resolves through `status()` before anything is retried.
The journal is the fill FIFO the loss breaker reads, so it also carries the venue-final flag.
"""

from __future__ import annotations

import json
import time

from kernel.execution_protocol import Ack, OrderRequest
from kernel.schema import FillState

JOURNAL_DDL = """
CREATE TABLE IF NOT EXISTS orders(
  client_order_id TEXT PRIMARY KEY, venue TEXT NOT NULL, mode TEXT NOT NULL, market_id TEXT NOT NULL,
  outcome_id TEXT NOT NULL, side TEXT NOT NULL, price REAL NOT NULL, contracts REAL NOT NULL,
  time_in_force TEXT NOT NULL, opportunity_id TEXT NOT NULL, state TEXT NOT NULL,
  venue_order_id TEXT, filled_contracts REAL DEFAULT 0, avg_price REAL, fee_usd REAL,
  open INTEGER DEFAULT 0, settlement_pending INTEGER DEFAULT 0, raw_status TEXT,
  submitted_utc REAL NOT NULL, last_utc REAL NOT NULL, detail TEXT, execution_id TEXT);
CREATE INDEX IF NOT EXISTS orders_opp ON orders(opportunity_id);
CREATE TABLE IF NOT EXISTS order_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, seen_ts REAL NOT NULL, client_order_id TEXT NOT NULL,
  kind TEXT NOT NULL, state TEXT, raw_json TEXT);
CREATE INDEX IF NOT EXISTS order_events_order ON order_events(client_order_id, seen_ts);
CREATE TABLE IF NOT EXISTS venue_fills(
  fill_id TEXT PRIMARY KEY, venue TEXT NOT NULL, venue_order_id TEXT NOT NULL, contracts REAL NOT NULL,
  price REAL NOT NULL, fee_usd REAL NOT NULL, is_taker INTEGER NOT NULL, ts REAL NOT NULL, final INTEGER NOT NULL);
"""


class Journal:
    def __init__(self, store):
        self.store = store
        store.ensure_ddl(JOURNAL_DDL)
        have = {r[1] for r in store.con.execute("PRAGMA table_info(orders)").fetchall()}
        if "execution_id" not in have:
            store.con.execute("ALTER TABLE orders ADD COLUMN execution_id TEXT")
            store.con.commit()

    def pending(self, req: OrderRequest, *, mode: str, now: float | None = None) -> None:
        """BEFORE the POST. An existing row with the same client id is a duplicate submit and
        is refused here, which is what makes the id idempotent on our side of the wire."""
        t = now or time.time()
        exists = self.store.con.execute("SELECT state FROM orders WHERE client_order_id=?",
                                        (req.client_order_id,)).fetchone()
        if exists is not None:
            raise ValueError(f"client_order_id {req.client_order_id!r} already journaled ({exists[0]}); "
                             "reconcile it, never resubmit")
        self.store.con.execute(
            "INSERT INTO orders(client_order_id, venue, mode, market_id, outcome_id, side, price, contracts, "
            "time_in_force, opportunity_id, state, submitted_utc, last_utc, execution_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (req.client_order_id, req.venue, mode, req.market_id, req.outcome_id, req.side, req.price,
             req.contracts, req.time_in_force, req.opportunity_id, FillState.UNCONFIRMED.value, t, t,
             req.execution_id or None))
        self._event(req.client_order_id, "pending", FillState.UNCONFIRMED, None, t)
        self.store.con.commit()

    def record(self, ack: Ack, *, kind: str, raw: dict | None = None, now: float | None = None) -> None:
        t = now or ack.received_utc or time.time()
        self.store.con.execute(
            "UPDATE orders SET state=?, venue_order_id=COALESCE(?, venue_order_id), filled_contracts=?, "
            "avg_price=?, fee_usd=?, open=?, settlement_pending=?, raw_status=?, last_utc=?, detail=? "
            "WHERE client_order_id=?",
            (ack.state.value, ack.venue_order_id, ack.filled_contracts, ack.avg_price, ack.fee_usd,
             int(ack.open), int(ack.settlement_pending), ack.raw_status, t, ack.detail, ack.client_order_id))
        self._event(ack.client_order_id, kind, ack.state, raw, t)
        self.store.con.commit()

    def _event(self, cid: str, kind: str, state: FillState | None, raw, t: float) -> None:
        self.store.con.execute("INSERT INTO order_events(seen_ts, client_order_id, kind, state, raw_json) VALUES(?,?,?,?,?)",
                               (t, cid, kind, state.value if state else None, json.dumps(raw) if raw is not None else None))

    def get(self, client_order_id: str) -> dict | None:
        row = self.store.con.execute(
            "SELECT client_order_id, venue, mode, market_id, outcome_id, side, price, contracts, time_in_force, "
            "opportunity_id, state, venue_order_id, filled_contracts, avg_price, fee_usd, open, settlement_pending, "
            "raw_status, submitted_utc, last_utc, detail, execution_id FROM orders WHERE client_order_id=?",
            (client_order_id,)).fetchone()
        if row is None:
            return None
        keys = ("client_order_id", "venue", "mode", "market_id", "outcome_id", "side", "price", "contracts",
                "time_in_force", "opportunity_id", "state", "venue_order_id", "filled_contracts", "avg_price",
                "fee_usd", "open", "settlement_pending", "raw_status", "submitted_utc", "last_utc", "detail",
                "execution_id")
        return dict(zip(keys, row))

    def unconfirmed(self) -> list[dict]:
        rows = self.store.con.execute("SELECT client_order_id FROM orders WHERE state=? OR open=1",
                                      (FillState.UNCONFIRMED.value,)).fetchall()
        return [self.get(r[0]) for r in rows]

    def record_fill(self, f) -> bool:
        cur = self.store.con.execute(
            "INSERT INTO venue_fills VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(fill_id) DO UPDATE SET "
            "venue=excluded.venue, venue_order_id=excluded.venue_order_id, contracts=excluded.contracts, "
            "price=excluded.price, fee_usd=excluded.fee_usd, is_taker=excluded.is_taker, ts=excluded.ts, final=excluded.final",
            (f.fill_id, f.venue, f.venue_order_id, f.contracts, f.price, f.fee_usd, int(f.is_taker), f.ts, int(f.final)))
        self.store.con.commit()
        return cur.rowcount > 0
