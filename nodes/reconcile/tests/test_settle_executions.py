#!/usr/bin/env python3
"""A hedged execution settles against each venue's result, releases its capital, and is recorded."""
from __future__ import annotations

import json
from pathlib import Path

from kernel.schema import OpportunityStatus as S
from nodes.discovery.discovery import EVENTS_DDL
from nodes.execute.records import EXECUTION_DDL
from nodes.execution.journal import JOURNAL_DDL
from nodes.opportunity.opportunity import Opportunity, OpportunityStore
from nodes.reconcile.settle_executions import apply_settlements, fetch_results, pending
from nodes.risk.ledger import ExposureLedger
from nodes.risk.limits import load_limits
from nodes.store_tuples.store import TupleStore

T = 1_800_000_000.0
LAD, STL = "tok-lad", "tok-stl"
OID = Opportunity.id_for("espn:mlb:1", 100.0)
SPEC = {"outcomes": {"mlb:lad": {"kalshi": "K-LAD", "polymarket": LAD}, "mlb:stl": {"kalshi": "K-STL", "polymarket": STL}}}


def _hedged(tmp_path: Path, *, phase="post:co_listed", start=T - 4 * 3600):
    st = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    st.ensure_ddl(EVENTS_DDL); st.ensure_ddl(EXECUTION_DDL); st.ensure_ddl(JOURNAL_DDL)
    st.con.execute("INSERT INTO events(event_id, league, start_utc, phase, pm_slug, spec_json, first_seen_ts, last_seen_ts) VALUES(?,?,?,?,?,?,?,?)",
                   ("espn:mlb:1", "mlb", start, phase, "mlb-stl-lad-2026-09-03", json.dumps(SPEC), T - 5 * 3600, T))
    ledger = ExposureLedger(st)
    res = ledger.reserve(event_id="espn:mlb:1", league="mlb", per_venue_usd={"kalshi": 50.0, "polymarket": 45.0}, limits=load_limits(),
                         opportunity_id=OID, now=T - 3600)
    st.con.execute("INSERT INTO executions(execution_id, opportunity_id, event_id, league, mode, state, started_utc, last_utc, quantity, reservation_id, released) "
                   "VALUES('x1',?,'espn:mlb:1','mlb','PAPER_EXECUTION','HEDGED',?,?,100,?,0)", (OID, T - 3600, T - 3600, res.reservation_id))
    # the two legs: Polymarket LAD YES at 0.45, Kalshi NO on LAD (= STL) at 0.50
    st.con.execute("INSERT INTO orders(client_order_id, venue, mode, market_id, outcome_id, side, price, contracts, time_in_force, opportunity_id, state, "
                   "filled_contracts, avg_price, fee_usd, submitted_utc, last_utc) VALUES('a','polymarket','PAPER_EXECUTION',?,?,'buy_yes',0.45,100,'fok',?,'FILLED',100,0.45,0.0,?,?)",
                   (LAD, LAD, OID, T - 3600, T - 3600))
    st.con.execute("INSERT INTO orders(client_order_id, venue, mode, market_id, outcome_id, side, price, contracts, time_in_force, opportunity_id, state, "
                   "filled_contracts, avg_price, fee_usd, submitted_utc, last_utc) VALUES('b','kalshi','PAPER_EXECUTION','K-LAD','K-LAD:NO','buy_no',0.51,100,'ioc',?,'FILLED',100,0.50,0.0,?,?)",
                   (OID, T - 3600, T - 3600))
    opps = OpportunityStore(st)
    o = opps.observe(status=S.PROFITABLE_UNEXECUTED, now=T - 3600, event_id="espn:mlb:1", league="mlb", quantity=100.0, gross=0.95, fees=0.02,
                     settlement_buffer=0.0, net_profit=2.0, locked_return=0.026, blocked_by=None, legs=[])
    o.transition(S.EXECUTION_PENDING, now=T - 3599); o.transition(S.HEDGED, now=T - 3598); opps._upsert(o)
    st.con.commit()
    return st, ledger, opps, res.reservation_id


def _fetchers(kalshi: dict, pm_label: str | None):
    def fk(ticker, cl):
        r = kalshi.get(ticker)
        return {"market": {"status": "settled" if r else "active", "result": r or ""}}
    def fe(slug):
        if pm_label is None:
            return {"markets": [{"slug": slug, "sportsMarketType": "moneyline", "closed": False}]}
        return {"markets": [{"slug": slug, "sportsMarketType": "moneyline", "closed": True, "outcomes": '["Los Angeles Dodgers","St. Louis Cardinals"]',
                             "clobTokenIds": json.dumps([LAD, STL]), "outcomePrices": '["1","0"]' if pm_label == "LAD" else '["0","1"]'}]}
    return fk, fe


def test_pending_waits_for_the_game_to_end(tmp_path):
    st, *_ = _hedged(tmp_path, phase="in:co_listed", start=T - 3600)
    assert pending(st, now=T) == []
    assert len(pending(st, now=T + 7 * 3600)) == 1, "six hours after the start counts as ended"
    (tmp_path / "b").mkdir()
    st2, *_ = _hedged(tmp_path / "b", phase="post:co_listed")
    assert len(pending(st2, now=T)) == 1


def test_a_hedged_cover_settles_on_both_results_and_releases(tmp_path):
    st, ledger, opps, rid = _hedged(tmp_path)
    items = pending(st, now=T)
    fk, fe = _fetchers({"K-LAD": "no", "K-STL": "yes"}, "STL")          # the Cardinals won
    winners = fetch_results(items, None, fetch_kalshi=fk, fetch_event=fe)
    assert winners == {"x1": {"kalshi": "K-STL", "polymarket": STL}}
    out = apply_settlements(st, ledger, None, opps, items, winners, now=T, log=lambda s: None)
    assert out == {"settled": 1, "waiting": 0, "unreleasable": 0}
    row = st.con.execute("SELECT realized_usd, released, kalshi_winner, polymarket_winner FROM execution_settlements").fetchone()
    # PM LAD YES lost (-45); Kalshi NO on LAD won (+100 - 50): net +5.00
    assert row == (5.0, 1, "K-STL", STL)
    assert st.con.execute("SELECT state, released FROM executions").fetchone() == ("RECONCILED", 1)
    assert st.con.execute("SELECT released_utc IS NOT NULL, release_reason FROM capital_reservations WHERE reservation_id=?", (rid,)).fetchone()[0] == 1
    assert opps.live[OID].status is S.RECONCILED
    assert pending(st, now=T) == [], "released executions are not asked again"


def test_the_other_result_and_an_open_venue(tmp_path):
    st, ledger, opps, rid = _hedged(tmp_path)
    items = pending(st, now=T)
    fk, fe = _fetchers({"K-LAD": "yes", "K-STL": "no"}, None)           # Kalshi settled, Polymarket still open
    winners = fetch_results(items, None, fetch_kalshi=fk, fetch_event=fe)
    assert winners["x1"] == {"kalshi": "K-LAD", "polymarket": None}
    assert apply_settlements(st, ledger, None, opps, items, winners, now=T, log=lambda s: None) == {"settled": 0, "waiting": 1, "unreleasable": 0}
    assert st.con.execute("SELECT state FROM executions").fetchone() == ("HEDGED",)
    fk, fe = _fetchers({"K-LAD": "yes", "K-STL": "no"}, "LAD")           # the Dodgers won
    winners = fetch_results(items, None, fetch_kalshi=fk, fetch_event=fe)
    apply_settlements(st, ledger, None, opps, items, winners, now=T + 1, log=lambda s: None)
    # PM LAD YES won (+100 - 45); Kalshi NO on LAD lost (-50): net +5.00 -- a cover pays the same either way
    assert st.con.execute("SELECT realized_usd FROM execution_settlements").fetchone()[0] == 5.0
