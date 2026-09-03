#!/usr/bin/env python3
"""The record, its allowed moves, and what is kept beside it."""
from __future__ import annotations

from pathlib import Path

import pytest

from kernel.schema import OpportunityStatus as S
from nodes.cover.capacity import frontier
from nodes.game_poller.tests.test_poller import FEES, mlb, sync_all
from nodes.opportunity.opportunity import IllegalTransition, Opportunity, OpportunityStore
from nodes.opportunity.record import record_evaluation
from nodes.opportunity.thresholds import EXECUTION_MIN_LOCKED_RETURN, EXECUTION_MIN_NET_PROFIT_USD
from nodes.store_tuples.store import TupleStore

T = 1000.0


def test_transitions_follow_the_machine_and_terminals_are_terminal():
    o = Opportunity("o", "e", "mlb", S.DISCOVERED, T, T)
    assert o.transition(S.PROFITABLE_UNEXECUTED, now=T + 1)
    assert not o.transition(S.PROFITABLE_UNEXECUTED, now=T + 2), "unchanged is a no-op"
    assert o.transition(S.EXECUTION_PENDING, now=T + 3) and o.transition(S.HEDGED, now=T + 4)
    with pytest.raises(IllegalTransition):
        o.transition(S.DISCOVERED, now=T + 5)
    assert o.transition(S.SETTLED, now=T + 6) and o.transition(S.RECONCILED, now=T + 7)
    with pytest.raises(IllegalTransition):
        o.transition(S.HEDGED, now=T + 8)
    assert [h[2] for h in o.history] == [S.PROFITABLE_UNEXECUTED, S.EXECUTION_PENDING, S.HEDGED, S.SETTLED, S.RECONCILED]


def test_a_discovered_cover_below_the_dollar_floor_is_not_profitable_unexecuted(tmp_path: Path):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    opps = OpportunityStore(store)
    p = mlb(quantities=(5.0,))                     # 5 contracts: a 12% edge is only ~$0.60... at 0.44+0.44
    sync_all(p, kh=0.47, ka=0.99, ph=0.99, pa=0.47)   # gross 0.94, ~4% locked: $0.20 on 5 contracts
    ev = p.on_event("kalshi", "K_H", now=T)[0]
    rec = record_evaluation(store, ev, league="mlb", fee_params=FEES, hurdle=EXECUTION_MIN_LOCKED_RETURN, opportunities=opps)
    assert rec.locked_return > EXECUTION_MIN_LOCKED_RETURN and rec.net_profit_usd < EXECUTION_MIN_NET_PROFIT_USD
    assert rec.status is S.DISCOVERED
    row = store.con.execute("SELECT status, net_profit, books_json FROM opportunities").fetchone()
    assert row[0] == "DISCOVERED" and row[1] == pytest.approx(rec.net_profit_usd) and '"asks"' in row[2]


def test_a_profitable_cover_records_its_books_transitions_and_frontier(tmp_path: Path):
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    opps = OpportunityStore(store)
    p = mlb()
    sync_all(p, kh=0.44, ka=0.99, ph=0.99, pa=0.44)
    ev = p.on_event("kalshi", "K_H", now=T)[0]
    rec = record_evaluation(store, ev, league="mlb", fee_params=FEES, hurdle=0.01, opportunities=opps)
    assert rec.status is S.PROFITABLE_UNEXECUTED
    opp = opps.live[Opportunity.id_for("g1", 100.0)]
    fr = frontier({o: list(v) for o, v in ev.offers.items()}, now_utc=T, proof=p.proof, hurdle=0.01)
    assert fr.actionable
    opps.record_frontier(opp, fr, now=T)
    assert opp.n_max == fr.n_max and opp.n_star == fr.n_star and not opp.slippage_modelled
    assert store.con.execute("SELECT COUNT(*) FROM frontiers").fetchone()[0] == 1
    # the market goes away: a transition to NO_EDGE is recorded, the books from the edge are kept
    sync_all(p, kh=0.60, ka=0.99, ph=0.99, pa=0.60, now=T + 1)
    ev2 = p.on_event("kalshi", "K_H", now=T + 1)[0]
    record_evaluation(store, ev2, league="mlb", fee_params=FEES, hurdle=0.01, opportunities=opps)
    tr = store.con.execute("SELECT from_status, to_status FROM opportunity_transitions ORDER BY id").fetchall()
    assert tr == [(None, "PROFITABLE_UNEXECUTED"), ("PROFITABLE_UNEXECUTED", "NO_EDGE")]
    books = store.con.execute("SELECT books_json FROM opportunities").fetchone()[0]
    assert "0.44" in books
