#!/usr/bin/env python3
"""Every execution and every state it passes through, persisted with the books it was priced from."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from kernel.schema import ExecutionState

EXECUTION_DDL = """
CREATE TABLE IF NOT EXISTS executions(
  execution_id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, event_id TEXT NOT NULL, league TEXT NOT NULL,
  mode TEXT NOT NULL, state TEXT NOT NULL, started_utc REAL NOT NULL, last_utc REAL NOT NULL,
  quantity REAL NOT NULL, first_client_id TEXT, hedge_client_ids TEXT, first_filled REAL DEFAULT 0,
  first_avg_price REAL, hedge_filled REAL DEFAULT 0, hedge_avg_price REAL, unhedged REAL DEFAULT 0,
  reservation_id TEXT, released INTEGER DEFAULT 0, detail TEXT, plan_json TEXT, books_json TEXT);
CREATE INDEX IF NOT EXISTS executions_opp ON executions(opportunity_id);
CREATE TABLE IF NOT EXISTS execution_transitions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, seen_ts REAL NOT NULL, execution_id TEXT NOT NULL,
  from_state TEXT, to_state TEXT NOT NULL, detail TEXT);
CREATE INDEX IF NOT EXISTS execution_transitions_exec ON execution_transitions(execution_id, seen_ts);
"""


@dataclass
class Execution:
    execution_id: str
    opportunity_id: str
    event_id: str
    league: str
    mode: str
    quantity: float
    started_utc: float
    state: ExecutionState = ExecutionState.DETECTED
    first_client_id: str | None = None
    hedge_client_ids: list[str] = field(default_factory=list)
    first_filled: float = 0.0
    first_avg_price: float | None = None
    hedge_filled: float = 0.0
    hedge_avg_price: float | None = None
    reservation_id: str | None = None
    released: bool = False
    detail: str = ""
    history: list[tuple[float, ExecutionState, ExecutionState, str]] = field(default_factory=list)

    @property
    def unhedged(self) -> float:
        return max(0.0, self.first_filled - self.hedge_filled)


class ExecutionRecords:
    def __init__(self, store):
        self.store = store
        store.ensure_ddl(EXECUTION_DDL)

    def start(self, ex: Execution, *, plan: dict, books: dict) -> None:
        self.store.con.execute(
            "INSERT INTO executions(execution_id, opportunity_id, event_id, league, mode, state, started_utc, last_utc, "
            "quantity, plan_json, books_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (ex.execution_id, ex.opportunity_id, ex.event_id, ex.league, ex.mode, ex.state.value, ex.started_utc,
             ex.started_utc, ex.quantity, json.dumps(plan, default=str), json.dumps(books, default=str)))
        self.store.con.execute("INSERT INTO execution_transitions(seen_ts, execution_id, from_state, to_state, detail) "
                               "VALUES(?,?,?,?,?)", (ex.started_utc, ex.execution_id, None, ex.state.value, "detected"))
        self.store.con.commit()

    def move(self, ex: Execution, to: ExecutionState, *, now: float, detail: str = "") -> None:
        if ex.state.is_terminal and to is not ex.state:
            raise ValueError(f"{ex.execution_id}: {ex.state.value} is terminal; cannot move to {to.value}")
        ex.history.append((now, ex.state, to, detail))
        self.store.con.execute("INSERT INTO execution_transitions(seen_ts, execution_id, from_state, to_state, detail) "
                               "VALUES(?,?,?,?,?)", (now, ex.execution_id, ex.state.value, to.value, detail))
        ex.state, ex.detail = to, detail
        self.sync(ex, now=now)

    def sync(self, ex: Execution, *, now: float | None = None) -> None:
        self.store.con.execute(
            "UPDATE executions SET state=?, last_utc=?, first_client_id=?, hedge_client_ids=?, first_filled=?, "
            "first_avg_price=?, hedge_filled=?, hedge_avg_price=?, unhedged=?, reservation_id=?, released=?, detail=? "
            "WHERE execution_id=?",
            (ex.state.value, now or time.time(), ex.first_client_id, json.dumps(ex.hedge_client_ids), ex.first_filled,
             ex.first_avg_price, ex.hedge_filled, ex.hedge_avg_price, ex.unhedged, ex.reservation_id, int(ex.released),
             ex.detail, ex.execution_id))
        self.store.con.commit()

    def open_unhedged(self) -> list[tuple[str, float]]:
        return self.store.con.execute("SELECT execution_id, unhedged FROM executions WHERE unhedged > 0 AND released = 0").fetchall()
