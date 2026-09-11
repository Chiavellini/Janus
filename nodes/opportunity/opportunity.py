#!/usr/bin/env python3
"""The Opportunity record: one candidate cover, its total cost, its size frontier, and every
status it passes through -- persisted with the books it was priced from.

Spec §9/§12: opportunity transitions are persisted; full order-book context is retained around
detected opportunities. An `Opportunity` is created when an evaluation first clears the
discovery threshold or is PROFITABLE_UNEXECUTED, and `transition()` enforces the allowed moves
so a record cannot skip from DETECTED to HEDGED or go backwards out of a terminal state.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from kernel.schema import OpportunityStatus as S
from nodes.cover.capacity import Frontier
from nodes.opportunity.thresholds import STRATEGY_VERSION

OPPORTUNITY_DDL = """
CREATE TABLE IF NOT EXISTS opportunities(
  opportunity_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, league TEXT NOT NULL,
  strategy_version TEXT NOT NULL, status TEXT NOT NULL, first_seen_ts REAL NOT NULL,
  last_seen_ts REAL NOT NULL, quantity REAL, gross REAL, fees REAL, settlement_buffer REAL,
  slippage_buffer REAL, fixed_cost REAL, net_profit REAL, locked_return REAL,
  n_max REAL, n_star REAL, limit_reason TEXT, slippage_modelled INTEGER, blocked_by TEXT,
  legs_json TEXT, books_json TEXT);
CREATE TABLE IF NOT EXISTS opportunity_transitions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, seen_ts REAL NOT NULL, opportunity_id TEXT NOT NULL,
  from_status TEXT, to_status TEXT NOT NULL, detail TEXT);
CREATE INDEX IF NOT EXISTS opportunity_transitions_opp ON opportunity_transitions(opportunity_id, seen_ts);
CREATE TABLE IF NOT EXISTS frontiers(
  id INTEGER PRIMARY KEY AUTOINCREMENT, seen_ts REAL NOT NULL, opportunity_id TEXT NOT NULL,
  n_max REAL, n_star REAL, best_profit REAL, best_capital REAL, limit_reason TEXT,
  slippage_per_contract REAL, slippage_modelled INTEGER, fixed_cost_usd REAL, rungs_json TEXT);
CREATE INDEX IF NOT EXISTS frontiers_opp ON frontiers(opportunity_id, seen_ts);
CREATE TABLE IF NOT EXISTS sizing_decisions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, seen_ts REAL NOT NULL, event_id TEXT NOT NULL,
  book_epoch TEXT NOT NULL, selected_opportunity_id TEXT, decision_json TEXT NOT NULL,
  input_hash TEXT, occurrence INTEGER);
CREATE UNIQUE INDEX IF NOT EXISTS sizing_decisions_epoch ON sizing_decisions(event_id, book_epoch);
"""

#: from -> allowed to. Terminal states allow nothing. Anything not listed is refused.
TRANSITIONS: dict[S, frozenset] = {
    S.DISCOVERED: frozenset({S.PROFITABLE_UNEXECUTED, S.NO_EDGE, S.BLOCKED_MATCH, S.BLOCKED_RULES,
                             S.BLOCKED_STALE, S.BLOCKED_DEPTH, S.BLOCKED_FEES, S.BLOCKED_BALANCE}),
    S.PROFITABLE_UNEXECUTED: frozenset({S.DISCOVERED, S.NO_EDGE, S.BLOCKED_MATCH, S.BLOCKED_RULES,
                                        S.BLOCKED_STALE, S.BLOCKED_DEPTH, S.BLOCKED_FEES,
                                        S.BLOCKED_BALANCE, S.EXECUTION_PENDING}),
    S.EXECUTION_PENDING: frozenset({S.PARTIALLY_FILLED, S.HEDGED, S.FAILED_HEDGE, S.PROFITABLE_UNEXECUTED}),
    S.PARTIALLY_FILLED: frozenset({S.HEDGED, S.FAILED_HEDGE}),
    S.HEDGED: frozenset({S.SETTLED}),
    S.FAILED_HEDGE: frozenset({S.SETTLED, S.HEDGED}),      # HEDGED: the protection layer hedged it after all (2026-09-08)
    S.SETTLED: frozenset({S.RECONCILED}),
    S.RECONCILED: frozenset(),
    S.NO_EDGE: frozenset({S.DISCOVERED, S.PROFITABLE_UNEXECUTED, S.BLOCKED_MATCH, S.BLOCKED_RULES,
                          S.BLOCKED_STALE, S.BLOCKED_DEPTH, S.BLOCKED_FEES, S.BLOCKED_BALANCE}),
}
#: Every block may move to every other block and back to the three evaluation states. The set is
#: fixed BEFORE the loop: reading `TRANSITIONS` while inserting into it gave each block only the
#: blocks inserted before it, so BLOCKED_MATCH could reach no other block and a socket died on
#: `BLOCKED_MATCH -> BLOCKED_STALE` on every reconnect (2026-09-03).
_BLOCKS = (S.BLOCKED_MATCH, S.BLOCKED_RULES, S.BLOCKED_STALE, S.BLOCKED_DEPTH, S.BLOCKED_FEES, S.BLOCKED_BALANCE)
for _b in _BLOCKS:
    TRANSITIONS[_b] = frozenset({S.DISCOVERED, S.PROFITABLE_UNEXECUTED, S.NO_EDGE, *_BLOCKS} - {_b})


#: Statuses an EVALUATION may move a record between. Everything from EXECUTION_PENDING on is
#: owned by the execution and reconcile paths.
_EVALUATION_OWNED = frozenset({S.DISCOVERED, S.PROFITABLE_UNEXECUTED, S.NO_EDGE, S.BLOCKED_MATCH, S.BLOCKED_RULES,
                               S.BLOCKED_STALE, S.BLOCKED_DEPTH, S.BLOCKED_FEES, S.BLOCKED_BALANCE})


class IllegalTransition(Exception):
    pass


@dataclass
class Opportunity:
    opportunity_id: str
    event_id: str
    league: str
    status: S
    first_seen_ts: float
    last_seen_ts: float
    strategy_version: str = STRATEGY_VERSION
    quantity: float | None = None
    gross: float | None = None
    fees: float | None = None
    settlement_buffer: float | None = None
    slippage_buffer: float | None = None
    fixed_cost: float | None = None
    net_profit: float | None = None
    locked_return: float | None = None
    n_max: float | None = None
    n_star: float | None = None
    limit_reason: str | None = None
    slippage_modelled: bool = False
    blocked_by: str | None = None
    legs: list[dict] = field(default_factory=list)
    books: dict = field(default_factory=dict)      # outcome -> [{venue, market_id, asks:[[p,s]..]}]
    history: list[tuple[float, S | None, S, str]] = field(default_factory=list)

    @staticmethod
    def id_for(event_id: str, quantity: float) -> str:
        return f"{event_id}:moneyline:{STRATEGY_VERSION}:{int(quantity)}"

    def transition(self, to: S, *, now: float, detail: str = "") -> bool:
        """Move if allowed. A no-op when unchanged. Raises on an illegal move."""
        if to is self.status:
            self.last_seen_ts = now
            return False
        if to not in TRANSITIONS.get(self.status, frozenset()):
            raise IllegalTransition(f"{self.opportunity_id}: {self.status.value} -> {to.value}")
        self.history.append((now, self.status, to, detail))
        self.status, self.last_seen_ts = to, now
        return True


def books_snapshot(offers: Mapping[str, Sequence]) -> dict:
    """The exact ladders a cover was priced from, compact: outcome -> legs -> asks."""
    out: dict = {}
    for outcome, legs in offers.items():
        out[outcome] = [{"venue": l.venue, "market_id": l.market_id, "outcome_id": l.outcome_id,
                         "source": l.book.source, "fetched_utc": l.book.fetched_utc,
                         "asks": [[round(q.price, 6), round(q.size, 4)] for q in l.book.asks[:25]]}
                        for l in legs]
    return out


class OpportunityStore:
    """Persistence for records, transitions and frontiers. Idempotent upserts; append-on-change."""

    def __init__(self, store):
        self.store = store
        store.ensure_ddl(OPPORTUNITY_DDL)
        have = {r[1] for r in store.con.execute("PRAGMA table_info(sizing_decisions)").fetchall()}
        for column, declaration in (("input_hash", "TEXT"), ("occurrence", "INTEGER")):
            if column not in have:
                store.con.execute(f"ALTER TABLE sizing_decisions ADD COLUMN {column} {declaration}")
        store.con.commit()
        self.live: dict[str, Opportunity] = {}

    def observe(self, *, event_id: str, league: str, quantity: float, status: S, now: float,
                gross: float | None, fees: float | None, settlement_buffer: float | None,
                net_profit: float | None, locked_return: float | None, blocked_by: str | None,
                legs: list[dict], offers: Mapping[str, Sequence] | None = None,
                detail: str = "") -> Opportunity:
        """Fold one evaluation into the record for (event, quantity). Creates it on first sight."""
        oid = Opportunity.id_for(event_id, quantity)
        opp = self.live.get(oid)
        moved = False
        if opp is None:
            opp = Opportunity(oid, event_id, league, status, now, now, quantity=quantity)
            opp.history.append((now, None, status, detail))
            self.live[oid] = opp
            moved = True
        elif opp.status in _EVALUATION_OWNED:
            moved = opp.transition(status, now=now, detail=detail)
        else:
            # Once an execution has started, the record's status belongs to the coordinator and the
            # reconcile pass. Later evaluations refresh the numbers, never the status.
            opp.last_seen_ts = now
            moved = False
        opp.gross, opp.fees, opp.settlement_buffer = gross, fees, settlement_buffer
        opp.net_profit, opp.locked_return, opp.blocked_by, opp.legs = net_profit, locked_return, blocked_by, legs
        # Keep the books from the EDGE. A later move to NO_EDGE must not overwrite what was priced.
        if offers is not None and (not opp.books or status in (S.PROFITABLE_UNEXECUTED, S.DISCOVERED)):
            opp.books = books_snapshot(offers)
        self._upsert(opp)
        if moved:
            frm = opp.history[-1][1]
            self.store.con.execute(
                "INSERT INTO opportunity_transitions(seen_ts, opportunity_id, from_status, to_status, detail) "
                "VALUES(?,?,?,?,?)", (now, oid, frm.value if frm else None, status.value, detail))
        return opp

    def move(self, opp: Opportunity, status: S, *, now: float, detail: str = "") -> bool:
        """An execution-owned status change (EXECUTION_PENDING and everything after it), persisted
        with its transition row. Until 2026-09-05 the coordinator called `transition()` and
        `_upsert()` directly, and the transition INSERT lived only in `observe()`: the
        `opportunities` row moved while `opportunity_transitions` never saw EXECUTION_PENDING,
        HEDGED or RECONCILED -- F3's own `cleared_cover` predicate counted zero against four
        executions. Raises IllegalTransition like `transition()`; a no-op returns False."""
        frm = opp.status
        if not opp.transition(status, now=now, detail=detail):
            self._upsert(opp)
            return False
        self._upsert(opp)
        self.store.con.execute(
            "INSERT INTO opportunity_transitions(seen_ts, opportunity_id, from_status, to_status, detail) "
            "VALUES(?,?,?,?,?)", (now, opp.opportunity_id, frm.value, status.value, detail))
        return True

    def load(self, opportunity_id: str) -> Opportunity | None:
        """The record from its row when it is not in `live` (the lane restarted; the settlement
        pass runs hours after the execution). Numbers and legs come back; books and history do
        not (books stay in the row; history is `opportunity_transitions`)."""
        opp = self.live.get(opportunity_id)
        if opp is not None:
            return opp
        r = self.store.con.execute(
            "SELECT opportunity_id, event_id, league, strategy_version, status, first_seen_ts, last_seen_ts, quantity, gross, "
            "fees, settlement_buffer, slippage_buffer, fixed_cost, net_profit, locked_return, n_max, n_star, limit_reason, "
            "slippage_modelled, blocked_by, legs_json FROM opportunities WHERE opportunity_id=?", (opportunity_id,)).fetchone()
        if r is None:
            return None
        opp = Opportunity(r[0], r[1], r[2], S(r[4]), r[5], r[6], strategy_version=r[3], quantity=r[7], gross=r[8], fees=r[9],
                          settlement_buffer=r[10], slippage_buffer=r[11], fixed_cost=r[12], net_profit=r[13],
                          locked_return=r[14], n_max=r[15], n_star=r[16], limit_reason=r[17], slippage_modelled=bool(r[18]),
                          blocked_by=r[19], legs=json.loads(r[20]) if r[20] else [])
        self.live[opportunity_id] = opp
        return opp

    def record_frontier(self, opp: Opportunity, fr: Frontier, *, now: float) -> None:
        opp.n_max, opp.n_star, opp.limit_reason = fr.n_max, fr.n_star, fr.limit_reason
        opp.slippage_modelled, opp.slippage_buffer, opp.fixed_cost = fr.slippage_modelled, fr.slippage_per_contract, fr.fixed_cost_usd
        self._upsert(opp)
        self.store.con.execute(
            "INSERT INTO frontiers(seen_ts, opportunity_id, n_max, n_star, best_profit, best_capital, limit_reason, "
            "slippage_per_contract, slippage_modelled, fixed_cost_usd, rungs_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (now, opp.opportunity_id, fr.n_max, fr.n_star, fr.best.profit if fr.best else None,
             fr.best.capital if fr.best else None, fr.limit_reason, fr.slippage_per_contract,
             int(fr.slippage_modelled), fr.fixed_cost_usd,
             json.dumps([[r.contracts, round(r.cost_per_contract, 6), round(r.profit, 4)] for r in fr.rungs])))

    def record_sizing_decision(self, *, event_id: str, book_epoch: str | None = None,
                               input_hash: str | None = None,
                               selected_opportunity_id: str | None, decision: Mapping,
                               now: float, executable: bool = True) -> bool:
        """Append exactly one auditable live sizing choice per frozen book epoch.

        A duplicate of the immediately preceding complete input is a no-op. If inputs change
        A→B→A, the second A gets a new occurrence: a real market transition can be retried while
        heartbeats, bid-only updates, and byte-identical snapshots cannot mint another order.

        `executable=False` (L74, 2026-09-11) says this epoch selected nothing: it is recorded only
        when the event's last recorded decision HAD selected something, so the row that explains
        why sizing stopped exists and the ~2 M/day blocked epochs (an 11 KB candidate ladder
        each, 24.7 GB in four days) do not. Those epochs keep their stream_evaluations row. The
        single-flight guard above is untouched: an executable epoch is compared with the last
        recorded input exactly as before, and every skipped epoch had a different input by
        definition (its books differed).
        """
        ih = str(input_hash or book_epoch or "")
        if not ih:
            raise ValueError("input_hash is required")
        previous = self.store.con.execute(
            "SELECT input_hash,occurrence,selected_opportunity_id FROM sizing_decisions WHERE event_id=? ORDER BY id DESC LIMIT 1",
            (event_id,),
        ).fetchone()
        if previous is not None and previous[0] == ih:
            return False
        if not executable and (previous is None or previous[2] is None):
            return False
        occurrence = int(previous[1] or 0) + 1 if previous is not None else 1
        epoch = hashlib.sha256(f"{ih}:{occurrence}".encode()).hexdigest()
        cur = self.store.con.execute(
            "INSERT OR IGNORE INTO sizing_decisions(seen_ts,event_id,book_epoch,selected_opportunity_id,decision_json,input_hash,occurrence) "
            "VALUES(?,?,?,?,?,?,?)",
            (now, event_id, epoch, selected_opportunity_id,
             json.dumps(dict(decision), sort_keys=True, separators=(",", ":")), ih, occurrence),
        )
        return cur.rowcount == 1

    def _upsert(self, o: Opportunity) -> None:
        self.store.con.execute(
            "INSERT INTO opportunities VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(opportunity_id) DO UPDATE SET status=excluded.status, last_seen_ts=excluded.last_seen_ts, "
            "quantity=excluded.quantity, gross=excluded.gross, fees=excluded.fees, settlement_buffer=excluded.settlement_buffer, "
            "slippage_buffer=excluded.slippage_buffer, fixed_cost=excluded.fixed_cost, net_profit=excluded.net_profit, "
            "locked_return=excluded.locked_return, n_max=excluded.n_max, n_star=excluded.n_star, "
            "limit_reason=excluded.limit_reason, slippage_modelled=excluded.slippage_modelled, blocked_by=excluded.blocked_by, "
            "legs_json=excluded.legs_json, books_json=COALESCE(excluded.books_json, opportunities.books_json)",
            (o.opportunity_id, o.event_id, o.league, o.strategy_version, o.status.value, o.first_seen_ts,
             o.last_seen_ts, o.quantity, o.gross, o.fees, o.settlement_buffer, o.slippage_buffer, o.fixed_cost,
             o.net_profit, o.locked_return, o.n_max, o.n_star, o.limit_reason, int(o.slippage_modelled),
             o.blocked_by, json.dumps(o.legs), json.dumps(o.books) if o.books else None))
