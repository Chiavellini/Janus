#!/usr/bin/env python3
"""Every execution and every state it passes through, persisted with the books it was priced from.

Since 2026-09-08 a row also carries what the protection layer did to it (`*_unwound`,
`protect_json`) and what the position guard corrected on it (`corrected_utc`), and the module can
read a row back into an `Execution` and its `Plan` (`load`, `plan_of`): the guard re-runs the
layer from the record, hours after the machine that wrote it is gone.
"""

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
  reservation_id TEXT, released INTEGER DEFAULT 0, detail TEXT, plan_json TEXT, books_json TEXT,
  stages_json TEXT, first_unwound REAL DEFAULT 0, first_unwind_avg REAL, hedge_unwound REAL DEFAULT 0,
  hedge_unwind_avg REAL, unwind_client_ids TEXT, protect_json TEXT, corrected_utc REAL);
CREATE INDEX IF NOT EXISTS executions_opp ON executions(opportunity_id);
CREATE TABLE IF NOT EXISTS execution_transitions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, seen_ts REAL NOT NULL, execution_id TEXT NOT NULL,
  from_state TEXT, to_state TEXT NOT NULL, detail TEXT);
CREATE INDEX IF NOT EXISTS execution_transitions_exec ON execution_transitions(execution_id, seen_ts);
"""
#: Columns added after the table first shipped; an old table gets them by ALTER, once, guarded.
_LATER_COLUMNS = {"stages_json": "TEXT", "first_unwound": "REAL DEFAULT 0", "first_unwind_avg": "REAL",
                  "hedge_unwound": "REAL DEFAULT 0", "hedge_unwind_avg": "REAL", "unwind_client_ids": "TEXT",
                  "protect_json": "TEXT", "corrected_utc": "REAL"}


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
    #: Per-stage timing, ms from the machine's entry (frame->eval and the grid's pre-machine stages
    #: arrive from the caller), plus counters. Written as stages_json; read by ops/latency_report.py.
    stages: dict[str, float] = field(default_factory=dict)
    #: The exception a machine error ended this execution with (not persisted; the state and
    #: detail are). Set by Coordinator.execute when the run raised (2026-09-08).
    machine_error: Exception | None = None
    #: The protection layer's sells (2026-09-08): contracts of the first leg / the hedge leg sold
    #: back, their average prices, the client ids, and the attempt log (`protect`).
    first_unwound: float = 0.0
    first_unwind_avg: float | None = None
    hedge_unwound: float = 0.0
    hedge_unwind_avg: float | None = None
    unwind_client_ids: list[str] = field(default_factory=list)
    protect: dict = field(default_factory=dict)
    #: When the position guard last rewrote the fills on this row from the venue's own record.
    corrected_utc: float | None = None

    @property
    def net_first(self) -> float:
        """Contracts of the first leg still held."""
        return max(0.0, self.first_filled - self.first_unwound)

    @property
    def net_hedge(self) -> float:
        return max(0.0, self.hedge_filled - self.hedge_unwound)

    @property
    def unhedged(self) -> float:
        return max(0.0, self.net_first - self.net_hedge)

    @property
    def overhedged(self) -> float:
        return max(0.0, self.net_hedge - self.net_first)

    @property
    def holds_anything(self) -> bool:
        return self.net_first > 1e-9 or self.net_hedge > 1e-9


_ROW_COLUMNS = ("execution_id", "opportunity_id", "event_id", "league", "mode", "state", "started_utc", "last_utc",
                "quantity", "first_client_id", "hedge_client_ids", "first_filled", "first_avg_price", "hedge_filled",
                "hedge_avg_price", "unhedged", "reservation_id", "released", "detail", "plan_json", "books_json",
                "stages_json", "first_unwound", "first_unwind_avg", "hedge_unwound", "hedge_unwind_avg",
                "unwind_client_ids", "protect_json", "corrected_utc")


class ExecutionRecords:
    def __init__(self, store):
        self.store = store
        store.ensure_ddl(EXECUTION_DDL)
        have = {r[1] for r in store.con.execute("PRAGMA table_info(executions)").fetchall()}
        for col, decl in _LATER_COLUMNS.items():
            if col not in have:
                store.con.execute(f"ALTER TABLE executions ADD COLUMN {col} {decl}")
        store.con.commit()

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
            "first_avg_price=?, hedge_filled=?, hedge_avg_price=?, unhedged=?, reservation_id=?, released=?, detail=?, "
            "stages_json=?, first_unwound=?, first_unwind_avg=?, hedge_unwound=?, hedge_unwind_avg=?, "
            "unwind_client_ids=?, protect_json=?, corrected_utc=? WHERE execution_id=?",
            (ex.state.value, now or time.time(), ex.first_client_id, json.dumps(ex.hedge_client_ids), ex.first_filled,
             ex.first_avg_price, ex.hedge_filled, ex.hedge_avg_price, ex.unhedged, ex.reservation_id, int(ex.released),
             ex.detail, json.dumps(ex.stages, sort_keys=True), ex.first_unwound, ex.first_unwind_avg, ex.hedge_unwound,
             ex.hedge_unwind_avg, json.dumps(ex.unwind_client_ids), json.dumps(ex.protect, sort_keys=True, default=str),
             ex.corrected_utc, ex.execution_id))
        self.store.con.commit()

    def open_unhedged(self) -> list[tuple[str, float]]:
        return self.store.con.execute("SELECT execution_id, unhedged FROM executions WHERE unhedged > 0 AND released = 0").fetchall()

    # ── reading a row back (the guard, ops) ─────────────────────────────
    def row(self, execution_id: str) -> dict | None:
        """The raw row by id or unique id prefix."""
        rows = self.store.con.execute(
            "SELECT " + ", ".join(_ROW_COLUMNS) + " FROM executions WHERE execution_id LIKE ?", (execution_id + "%",)).fetchall()
        if len(rows) != 1:
            return None
        return dict(zip(_ROW_COLUMNS, rows[0]))

    def load(self, execution_id: str) -> Execution | None:
        r = self.row(execution_id)
        if r is None:
            return None

        def js(v, default):
            try:
                return json.loads(v) if v else default
            except (TypeError, ValueError):
                return default
        ex = Execution(r["execution_id"], r["opportunity_id"], r["event_id"], r["league"], r["mode"],
                       float(r["quantity"]), float(r["started_utc"]), state=ExecutionState(r["state"]),
                       first_client_id=r["first_client_id"], hedge_client_ids=list(js(r["hedge_client_ids"], [])),
                       first_filled=float(r["first_filled"] or 0.0), first_avg_price=r["first_avg_price"],
                       hedge_filled=float(r["hedge_filled"] or 0.0), hedge_avg_price=r["hedge_avg_price"],
                       reservation_id=r["reservation_id"], released=bool(r["released"]), detail=r["detail"] or "",
                       stages=dict(js(r["stages_json"], {})), first_unwound=float(r["first_unwound"] or 0.0),
                       first_unwind_avg=r["first_unwind_avg"], hedge_unwound=float(r["hedge_unwound"] or 0.0),
                       hedge_unwind_avg=r["hedge_unwind_avg"], unwind_client_ids=list(js(r["unwind_client_ids"], [])),
                       protect=dict(js(r["protect_json"], {})), corrected_utc=r["corrected_utc"])
        return ex

    def plan_of(self, execution_id: str):
        """The Plan the machine ran, from plan_json plus the row's ids. None when the row or its
        plan is missing (a row written before plans were persisted)."""
        from nodes.execute.plan import Plan
        r = self.row(execution_id)
        if r is None or not r["plan_json"]:
            return None
        d = json.loads(r["plan_json"])
        if not (isinstance(d, dict) and "first" in d and "hedge" in d):
            return None
        return Plan.from_dict(d, opportunity_id=r["opportunity_id"], event_id=r["event_id"], league=r["league"],
                              quantity=float(r["quantity"]))

    # ── the guard's corrections ─────────────────────────────────────────
    def correct_fills(self, ex: Execution, *, first_filled: float | None = None, first_avg: float | None = None,
                      hedge_filled: float | None = None, hedge_avg: float | None = None, note: str, now: float) -> None:
        """The venue's fills are the truth, the row is the claim: rewrite the claim, say so in a
        transition row (state -> state) and stamp `corrected_utc`. Never changes the state."""
        if first_filled is not None:
            ex.first_filled, ex.first_avg_price = float(first_filled), first_avg
        if hedge_filled is not None:
            ex.hedge_filled, ex.hedge_avg_price = float(hedge_filled), hedge_avg
        ex.corrected_utc = now
        ex.history.append((now, ex.state, ex.state, f"guard: {note}"))
        self.store.con.execute("INSERT INTO execution_transitions(seen_ts, execution_id, from_state, to_state, detail) "
                               "VALUES(?,?,?,?,?)", (now, ex.execution_id, ex.state.value, ex.state.value, f"guard: {note}"))
        self.sync(ex, now=now)

    def reopen(self, ex: Execution, *, note: str, now: float) -> None:
        """The ONE sanctioned move out of a released, terminal failure: the venue shows a fill on
        an order the row said never filled. The row becomes UNKNOWN_PROVIDER_STATE (holding, not
        released) so the guard can protect it and the alarms see it."""
        if not ex.state.is_terminal:
            raise ValueError(f"{ex.execution_id}: {ex.state.value} is not terminal; nothing to reopen")
        frm = ex.state
        ex.history.append((now, frm, ExecutionState.UNKNOWN_PROVIDER_STATE, f"guard reopen: {note}"))
        self.store.con.execute("INSERT INTO execution_transitions(seen_ts, execution_id, from_state, to_state, detail) "
                               "VALUES(?,?,?,?,?)", (now, ex.execution_id, frm.value, ExecutionState.UNKNOWN_PROVIDER_STATE.value,
                                                     f"guard reopen: {note}"))
        ex.state, ex.released, ex.detail, ex.corrected_utc = ExecutionState.UNKNOWN_PROVIDER_STATE, False, f"guard reopen: {note}", now
        self.sync(ex, now=now)

    def write_unwind_settlement(self, ex: Execution, *, realized_usd: float, legs: list[dict], now: float) -> None:
        """An `execution_settlements` row of kind UNWOUND, so the day's realized PnL (the breaker's
        feed) carries the protection layer's loss the moment it happens, not at the game's end."""
        from nodes.reconcile.settle_executions import SETTLEMENTS_DDL, _ensure_columns
        self.store.ensure_ddl(SETTLEMENTS_DDL)
        _ensure_columns(self.store)
        # UNWOUND: nothing is held any more; the whole realized figure is the layer's cost, none of it a cover.
        self.store.con.execute(
            "INSERT OR REPLACE INTO execution_settlements(execution_id, opportunity_id, event_id, league, mode, settled_ts, "
            "kalshi_winner, polymarket_winner, realized_usd, released, legs_json, kind, hedged_contracts, unhedged_contracts, "
            "cover_usd, directional_usd) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ex.execution_id, ex.opportunity_id, ex.event_id, ex.league, ex.mode, now, None, None, float(realized_usd), 1,
             json.dumps(legs, default=str), "UNWOUND", 0.0, 0.0, 0.0, round(float(realized_usd), 4)))
        self.store.con.commit()
