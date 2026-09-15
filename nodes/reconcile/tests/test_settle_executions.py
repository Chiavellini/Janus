#!/usr/bin/env python3
"""A hedged execution settles against each venue's result, releases its capital, and is recorded."""
from __future__ import annotations

import json

import pytest
from pathlib import Path

from kernel.schema import OpportunityStatus as S
from nodes.discovery.discovery import EVENTS_DDL
from nodes.execute.records import EXECUTION_DDL
from nodes.execution.journal import JOURNAL_DDL
from nodes.opportunity.opportunity import Opportunity, OpportunityStore
from nodes.reconcile.settle_executions import apply_settlements, fetch_results, pending, refresh_settlement_accounting
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
    st.con.execute("INSERT INTO executions(execution_id, opportunity_id, event_id, league, mode, state, started_utc, last_utc, quantity, "
                   "first_client_id, hedge_client_ids, reservation_id, released) "
                   "VALUES('x1',?,'espn:mlb:1','mlb','PAPER_EXECUTION','HEDGED',?,?,100,'a','[\"b\"]',?,0)",
                   (OID, T - 3600, T - 3600, res.reservation_id))
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


def test_pending_polls_held_executions_even_when_the_schedule_phase_is_stale(tmp_path):
    st, *_ = _hedged(tmp_path, phase="in:co_listed", start=T - 3600)
    assert len(pending(st, now=T)) == 1, "venue finality, not the schedule phase, decides settlement"
    assert len(pending(st, now=T + 7 * 3600)) == 1
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


def test_scalar_and_half_maps_settle_and_survive_refresh(tmp_path):
    st, ledger, opps, rid = _hedged(tmp_path)
    items = pending(st, now=T)

    def fk(ticker, _cl):
        values = {"K-LAD": "0.4400", "K-STL": "0.5600"}
        return {"market": {"status": "finalized", "result": "scalar",
                            "settlement_value_dollars": values[ticker]}}

    def fe(_slug):
        return {"markets": [{"slug": "mlb-stl-lad-2026-09-03", "sportsMarketType": "moneyline",
                              "closed": True, "umaResolutionStatus": "resolved",
                              "umaResolutionStatuses": ["proposed", "proposed"],
                              "outcomes": '["Los Angeles Dodgers","St. Louis Cardinals"]',
                              "clobTokenIds": json.dumps([LAD, STL]),
                              "outcomePrices": '["0.5","0.5"]'}]}

    result = fetch_results(items, None, fetch_kalshi=fk, fetch_event=fe)
    assert result["x1"]["kalshi"] is None and result["x1"]["polymarket"] is None
    assert result["x1"]["kalshi_payouts"] == {"K-LAD": 0.44, "K-STL": 0.56}
    assert result["x1"]["polymarket_payouts"] == {LAD: 0.5, STL: 0.5}
    out = apply_settlements(st, ledger, None, opps, items, result, now=T, log=lambda *_: None)
    assert out == {"settled": 1, "waiting": 0, "unreleasable": 0}
    row = st.con.execute("SELECT realized_usd, released, kalshi_winner, polymarket_winner FROM execution_settlements").fetchone()
    assert row[0] == pytest.approx(11.0) and row[1:4] == (1, None, None)
    assert st.con.execute("SELECT venue,payouts_json FROM execution_venue_payouts ORDER BY venue").fetchall() == [
        ("kalshi", '{"K-LAD": 0.44, "K-STL": 0.56}'),
        ("polymarket", f'{{"{LAD}": 0.5, "{STL}": 0.5}}'),
    ]
    assert st.con.execute("SELECT venue,payouts_json FROM execution_settlement_payouts ORDER BY venue").fetchall() == [
        ("kalshi", '{"K-LAD": 0.44, "K-STL": 0.56}'),
        ("polymarket", f'{{"{LAD}": 0.5, "{STL}": 0.5}}'),
    ]
    st.con.execute("UPDATE orders SET fee_usd=0.2 WHERE client_order_id='a'")
    st.con.commit()
    assert refresh_settlement_accounting(st, now=T + 1, log=lambda *_: None) == 1
    assert st.con.execute("SELECT realized_usd FROM execution_settlements").fetchone()[0] == pytest.approx(10.8)


def test_invalid_or_contradictory_final_evidence_never_releases(tmp_path):
    st, ledger, opps, rid = _hedged(tmp_path)
    items = pending(st, now=T)
    incomplete = {"x1": {"kalshi": None, "polymarket": None,
                          "kalshi_payouts": {"K-LAD": 0.44},
                          "polymarket_payouts": {LAD: 0.5, STL: 0.5}}}
    assert apply_settlements(st, ledger, None, opps, items, incomplete,
                             now=T, log=lambda *_: None)["waiting"] == 1
    assert st.con.execute("SELECT released_utc FROM capital_reservations WHERE reservation_id=?",
                          (rid,)).fetchone() == (None,)

    st.con.execute(
        "INSERT OR REPLACE INTO execution_venue_payouts(execution_id,venue,payouts_json,observed_ts) "
        "VALUES('x1','kalshi',?,?)", (json.dumps({"K-LAD": 0.44, "K-STL": 0.56}), T))
    st.con.commit()
    changed = {"x1": {"kalshi": "K-STL", "polymarket": None}}
    with pytest.raises(RuntimeError, match="contradictory durable"):
        apply_settlements(st, ledger, None, opps, items, changed, now=T + 1, log=lambda *_: None)
    assert st.con.execute("SELECT released_utc FROM capital_reservations WHERE reservation_id=?",
                          (rid,)).fetchone() == (None,)


def test_a_late_fee_correction_revises_settled_pnl_once_with_an_audit_row(tmp_path):
    st, ledger, opps, _ = _hedged(tmp_path)
    items = pending(st, now=T)
    fk, fe = _fetchers({"K-LAD": "no", "K-STL": "yes"}, "STL")
    apply_settlements(st, ledger, None, opps, items,
                      fetch_results(items, None, fetch_kalshi=fk, fetch_event=fe), now=T, log=lambda *_: None)
    st.con.execute("UPDATE orders SET fee_usd=0.2 WHERE client_order_id='a'")
    st.con.commit()
    assert refresh_settlement_accounting(st, now=T + 2, log=lambda *_: None) == 1
    assert st.con.execute("SELECT realized_usd,cover_usd FROM execution_settlements").fetchone() == pytest.approx((4.8, 4.8))
    audit = st.con.execute(
        "SELECT old_realized_usd,new_realized_usd,reason FROM execution_settlement_revisions"
    ).fetchone()
    assert audit[:2] == pytest.approx((5.0, 4.8)) and "accounting changed" in audit[2]
    assert refresh_settlement_accounting(st, now=T + 3, log=lambda *_: None) == 0
    assert st.con.execute("SELECT COUNT(*) FROM execution_settlement_revisions").fetchone()[0] == 1
    assert "settled +4.8000 USD" in st.con.execute("SELECT detail FROM executions WHERE execution_id='x1'").fetchone()[0]


def test_settlement_uses_exact_execution_order_ids_not_a_retried_opportunity(tmp_path):
    st, ledger, opps, _ = _hedged(tmp_path)
    # A later retry deliberately has the same opportunity id. Even a filled order on it must not
    # enter x1's PnL or venue set; the execution row does not own client id `retry`.
    st.con.execute(
        "INSERT INTO orders(client_order_id, venue, mode, market_id, outcome_id, side, price, contracts, "
        "time_in_force, opportunity_id, state, filled_contracts, avg_price, fee_usd, submitted_utc, last_utc) "
        "VALUES('retry','polymarket','PAPER_EXECUTION',?,?, 'buy_yes',0.99,100,'fok',?,'FILLED',100,0.99,0,?,?)",
        (STL, STL, OID, T - 100, T - 100),
    )
    st.con.commit()
    items = pending(st, now=T)
    fk, fe = _fetchers({"K-LAD": "no", "K-STL": "yes"}, "STL")
    apply_settlements(st, ledger, None, opps, items,
                      fetch_results(items, None, fetch_kalshi=fk, fetch_event=fe), now=T, log=lambda s: None)
    assert st.con.execute("SELECT realized_usd FROM execution_settlements WHERE execution_id='x1'").fetchone() == (5.0,)


def test_the_other_result_and_an_open_venue(tmp_path):
    st, ledger, opps, rid = _hedged(tmp_path)
    items = pending(st, now=T)
    fk, fe = _fetchers({"K-LAD": "yes", "K-STL": "no"}, None)           # Kalshi settled, Polymarket still open
    winners = fetch_results(items, None, fetch_kalshi=fk, fetch_event=fe)
    assert winners["x1"] == {"kalshi": "K-LAD", "polymarket": None}
    assert apply_settlements(st, ledger, None, opps, items, winners, now=T, log=lambda s: None) == {"settled": 0, "waiting": 1, "unreleasable": 0}
    assert st.con.execute("SELECT state FROM executions").fetchone() == ("HEDGED",)
    assert st.con.execute("SELECT venue,winner FROM execution_venue_results").fetchall() == [("kalshi", "K-LAD")]
    fk, fe = _fetchers({"K-LAD": "yes", "K-STL": "no"}, "LAD")           # the Dodgers won
    winners = fetch_results(items, None, fetch_kalshi=fk, fetch_event=fe)
    apply_settlements(st, ledger, None, opps, items, winners, now=T + 1, log=lambda s: None)
    # PM LAD YES won (+100 - 45); Kalshi NO on LAD lost (-50): net +5.00 -- a cover pays the same either way
    assert st.con.execute("SELECT realized_usd FROM execution_settlements").fetchone()[0] == 5.0


def test_results_persist_across_alternating_venue_outages(tmp_path):
    st, ledger, opps, _ = _hedged(tmp_path)
    items = pending(st, now=T)
    first = {"x1": {"kalshi": "K-LAD", "polymarket": None}}
    assert apply_settlements(st, ledger, None, opps, items, first, now=T, log=lambda *_: None)["waiting"] == 1
    second = {"x1": {"kalshi": None, "polymarket": LAD}}
    out = apply_settlements(st, ledger, None, opps, pending(st, now=T + 1), second,
                            now=T + 1, log=lambda *_: None)
    assert out == {"settled": 1, "waiting": 0, "unreleasable": 0}
    assert st.con.execute("SELECT COUNT(*) FROM execution_venue_results").fetchone() == (2,)


def test_provisional_polymarket_fill_cannot_release_capital(tmp_path):
    st, ledger, opps, rid = _hedged(tmp_path)
    st.con.execute("UPDATE orders SET settlement_pending=1 WHERE client_order_id='a'")
    st.con.commit()
    both = {"x1": {"kalshi": "K-STL", "polymarket": STL}}
    out = apply_settlements(st, ledger, None, opps, pending(st, now=T), both,
                            now=T, log=lambda *_: None)
    assert out == {"settled": 0, "waiting": 0, "unreleasable": 1}
    assert st.con.execute("SELECT state,released FROM executions").fetchone() == ("SETTLED", 0)
    assert st.con.execute("SELECT released_utc FROM capital_reservations WHERE reservation_id=?", (rid,)).fetchone() == (None,)

    st.con.execute("UPDATE orders SET settlement_pending=0 WHERE client_order_id='a'")
    st.con.commit()
    out = apply_settlements(st, ledger, None, opps, pending(st, now=T + 1), both,
                            now=T + 1, log=lambda *_: None)
    assert out == {"settled": 1, "waiting": 0, "unreleasable": 0}
    assert st.con.execute("SELECT state,released FROM executions").fetchone() == ("RECONCILED", 1)
    assert opps.live[OID].status is S.RECONCILED


def test_retry_after_release_commit_is_idempotently_reconciled(tmp_path):
    st, ledger, opps, rid = _hedged(tmp_path)
    assert ledger.release(rid, reason="simulated crash after release", now=T)
    both = {"x1": {"kalshi": "K-STL", "polymarket": STL}}
    out = apply_settlements(st, ledger, None, opps, pending(st, now=T + 1), both,
                            now=T + 1, log=lambda *_: None)
    assert out == {"settled": 1, "waiting": 0, "unreleasable": 0}
    assert st.con.execute("SELECT state,released FROM executions").fetchone() == ("RECONCILED", 1)


def test_one_venue_result_survives_the_other_venues_transport_error(tmp_path):
    st, *_ = _hedged(tmp_path)
    items = pending(st, now=T)
    fk, _ = _fetchers({"K-LAD": "yes", "K-STL": "no"}, None)
    def pm_down(_slug):
        raise TimeoutError("gamma unavailable")
    winners = fetch_results(items, None, fetch_kalshi=fk, fetch_event=pm_down)
    assert winners["x1"]["kalshi"] == "K-LAD"
    assert winners["x1"]["polymarket"] is None and winners["x1"]["polymarket_error"] == "TimeoutError"


def test_closed_malformed_final_payload_is_an_error_not_an_open_market(tmp_path):
    st, *_ = _hedged(tmp_path)
    items = pending(st, now=T)

    def fk(ticker, _cl):
        return {"market": {"status": "finalized", "result": "scalar"}}

    def fe(slug):
        return {"markets": [{"slug": slug, "sportsMarketType": "moneyline", "closed": True,
                             "umaResolutionStatus": "resolved", "outcomes": '["A","B"]',
                             "outcomePrices": '["0.5"]'}]}

    got = fetch_results(items, None, fetch_kalshi=fk, fetch_event=fe)["x1"]
    assert got["kalshi_error"] == "InvalidFinalPayout"
    assert got["polymarket_error"] == "InvalidFinalPayout"


def _partial(tmp_path: Path):
    """Execution 69852b86, MIL @ CIN, 2026-09-05 00:49:35Z: Polymarket CIN YES 100 @ 0.13 filled;
    Kalshi MIL YES hedge 64.18 @ 0.84 PARTIAL, two more attempts UNFILLED; 35.82 unhedged."""
    st = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    st.ensure_ddl(EVENTS_DDL); st.ensure_ddl(EXECUTION_DDL); st.ensure_ddl(JOURNAL_DDL)
    CIN, MIL = "tok-cin", "tok-mil"
    spec = {"outcomes": {"mlb:cin": {"kalshi": "K-CIN", "polymarket": CIN}, "mlb:mil": {"kalshi": "K-MIL", "polymarket": MIL}}}
    oid = Opportunity.id_for("espn:mlb:401816802", 100.0)
    st.con.execute("INSERT INTO events(event_id, league, start_utc, phase, pm_slug, spec_json, first_seen_ts, last_seen_ts) VALUES(?,?,?,?,?,?,?,?)",
                   ("espn:mlb:401816802", "mlb", T - 4 * 3600, "post:co_listed", "mlb-mil-cin-2026-09-04", json.dumps(spec), T - 5 * 3600, T))
    ledger = ExposureLedger(st)
    res = ledger.reserve(event_id="espn:mlb:401816802", league="mlb", per_venue_usd={"kalshi": 85.0, "polymarket": 13.0}, limits=load_limits(),
                         opportunity_id=oid, now=T - 3600)
    st.con.execute("INSERT INTO executions(execution_id, opportunity_id, event_id, league, mode, state, started_utc, last_utc, quantity, "
                   "first_client_id, hedge_client_ids, first_filled, first_avg_price, hedge_filled, hedge_avg_price, unhedged, reservation_id, released) "
                   "VALUES('x2',?,'espn:mlb:401816802','mlb','PAPER_EXECUTION','PARTIAL_FILL',?,?,100,'a','[\"b1\",\"b2\",\"b3\"]',"
                   "100,0.13,64.18,0.84,35.82,?,0)",
                   (oid, T - 3600, T - 3600, res.reservation_id))
    ins = ("INSERT INTO orders(client_order_id, venue, mode, market_id, outcome_id, side, price, contracts, time_in_force, opportunity_id, state, "
           "filled_contracts, avg_price, fee_usd, submitted_utc, last_utc) VALUES(?,?,'PAPER_EXECUTION',?,?,?,?,?,?,?,?,?,?,?,?,?)")
    st.con.execute(ins, ("a", "polymarket", CIN, CIN, "buy_yes", 0.13, 100, "fok", oid, "FILLED", 100, 0.13, 0.0, T - 3600, T - 3600))
    st.con.execute(ins, ("b1", "kalshi", "K-MIL", "K-MIL", "buy_yes", 0.8452, 100, "ioc", oid, "PARTIAL", 64.18, 0.84, 0.0, T - 3600, T - 3600))
    st.con.execute(ins, ("b2", "kalshi", "K-MIL", "K-MIL", "buy_yes", 0.8452, 35.82, "ioc", oid, "UNFILLED", 0, None, 0.0, T - 3600, T - 3600))
    st.con.execute(ins, ("b3", "kalshi", "K-MIL", "K-MIL", "buy_yes", 0.8452, 35.82, "ioc", oid, "UNFILLED", 0, None, 0.0, T - 3600, T - 3600))
    opps = OpportunityStore(st)
    o = opps.observe(status=S.PROFITABLE_UNEXECUTED, now=T - 3600, event_id="espn:mlb:401816802", league="mlb", quantity=100.0, gross=0.97, fees=0.01,
                     settlement_buffer=0.0, net_profit=1.5, locked_return=0.015, blocked_by=None, legs=[])
    opps.move(o, S.EXECUTION_PENDING, now=T - 3599); opps.move(o, S.FAILED_HEDGE, now=T - 3598)
    st.con.commit()
    fresh = OpportunityStore(st)            # the lane restarted since: `live` is empty
    return st, ledger, fresh, res.reservation_id, oid, CIN, MIL


def _fetchers2(kalshi: dict, pm_label: str | None, CIN, MIL):
    def fk(ticker, cl):
        r = kalshi.get(ticker)
        return {"market": {"status": "settled" if r else "active", "result": r or ""}}
    def fe(slug):
        return {"markets": [{"slug": slug, "sportsMarketType": "moneyline", "closed": True, "outcomes": '["Milwaukee Brewers","Cincinnati Reds"]',
                             "clobTokenIds": json.dumps([MIL, CIN]), "outcomePrices": '["1","0"]' if pm_label == "MIL" else '["0","1"]'}]}
    return fk, fe


def test_a_partial_fill_settles_as_a_cover_plus_a_directional_remainder_and_releases(tmp_path):
    st, ledger, opps, rid, oid, CIN, MIL = _partial(tmp_path)
    items = pending(st, now=T)
    assert [i["state"] for i in items] == ["PARTIAL_FILL"], "a holding failure with a filled first leg is pending"
    fk, fe = _fetchers2({"K-CIN": "yes", "K-MIL": "no"}, "CIN", CIN, MIL)           # the Reds won
    winners = fetch_results(items, None, fetch_kalshi=fk, fetch_event=fe)
    out = apply_settlements(st, ledger, None, opps, items, winners, now=T, log=lambda s: None)
    assert out == {"settled": 1, "waiting": 0, "unreleasable": 0}
    row = st.con.execute("SELECT realized_usd, released, kind, hedged_contracts, unhedged_contracts, cover_usd, directional_usd FROM execution_settlements").fetchone()
    # PM CIN YES won: +100 - 13 = +87.00; Kalshi MIL YES lost: -64.18 x 0.84 = -53.91; total +33.09
    assert row[0] == pytest.approx(33.0888, abs=1e-3) and row[1] == 1 and row[2] == "PARTIAL"
    assert row[3] == pytest.approx(64.18) and row[4] == pytest.approx(35.82)
    # the hedged 64.18 were a cover at 1 - 0.13 - 0.84 = 0.03 each: +1.93; the rest is directional
    assert row[5] == pytest.approx(64.18 * 0.03, abs=1e-3) and row[6] == pytest.approx(row[0] - row[5], abs=1e-3)
    assert st.con.execute("SELECT state, released FROM executions").fetchone() == ("RECONCILED", 1)
    assert st.con.execute("SELECT released_utc IS NOT NULL FROM capital_reservations WHERE reservation_id=?", (rid,)).fetchone()[0] == 1
    moves = [r[0] for r in st.con.execute("SELECT to_status FROM opportunity_transitions WHERE opportunity_id=? ORDER BY id", (oid,)).fetchall()]
    assert moves[-3:] == ["FAILED_HEDGE", "SETTLED", "RECONCILED"], moves
    assert pending(st, now=T) == []


def test_the_partial_fill_losing_side(tmp_path):
    st, ledger, opps, rid, oid, CIN, MIL = _partial(tmp_path)
    items = pending(st, now=T)
    fk, fe = _fetchers2({"K-CIN": "no", "K-MIL": "yes"}, "MIL", CIN, MIL)           # the Brewers won
    winners = fetch_results(items, None, fetch_kalshi=fk, fetch_event=fe)
    apply_settlements(st, ledger, None, opps, items, winners, now=T, log=lambda s: None)
    row = st.con.execute("SELECT realized_usd, kind, cover_usd, directional_usd FROM execution_settlements").fetchone()
    # PM CIN YES lost: -13.00; Kalshi MIL YES won on 64.18: +64.18 x 0.16 = +10.27; total -2.73
    assert row[0] == pytest.approx(-2.7312, abs=1e-3) and row[1] == "PARTIAL"
    assert row[2] == pytest.approx(64.18 * 0.03, abs=1e-3), "the cover part pays the same either way"
    assert row[3] == pytest.approx(row[0] - row[2], abs=1e-3)


def test_a_hedged_cover_is_kind_cover(tmp_path):
    st, ledger, opps, rid = _hedged(tmp_path)
    items = pending(st, now=T)
    fk, fe = _fetchers({"K-LAD": "no", "K-STL": "yes"}, "STL")
    apply_settlements(st, ledger, None, opps, items, fetch_results(items, None, fetch_kalshi=fk, fetch_event=fe), now=T, log=lambda s: None)
    # (the fixture's execution row records no fill counts; a COVER row carries the whole PnL as cover_usd)
    assert st.con.execute("SELECT kind, unhedged_contracts, cover_usd, directional_usd FROM execution_settlements").fetchone() == ("COVER", 0.0, 5.0, 0.0)


def test_the_write_lock_is_released_between_settled_items(tmp_path):
    """L110 (2026-09-14): the pass held the file's single WAL write lock across every item.

    `store.con` is DEFERRED, so the first item's write took the lock and nothing released it until
    the end of the loop. Everything else on that file queued behind it -- and the order path's
    journal write has a 30 s busy timeout, which is why `db_ms` has been seen at 37,386 ms. The
    2026-09-08 GEA V ZANDSCH incident was this collision from the other side: leg A filled, the
    hedge never sent, because the journal write waited out the lane's lock and raised.

    The pass's own log callback runs immediately after the per-item commit, so it is the honest
    place to ask whether the lock is still held.
    """
    st, ledger, opps, _rid = _hedged(tmp_path)
    items = pending(st, now=T)
    fk, fe = _fetchers({"K-LAD": "no", "K-STL": "yes"}, "STL")
    winners = fetch_results(items, None, fetch_kalshi=fk, fetch_event=fe)

    seen: list[bool] = []
    out = apply_settlements(st, ledger, None, opps, items, winners, now=T,
                            log=lambda _s: seen.append(st.con.in_transaction))
    assert out["settled"] == 1
    assert seen and not any(seen), "the item's writes are still uncommitted: the lock is held"

    # And a second connection can in fact write while the lane holds none.
    other = TupleStore(tmp_path / "t.sqlite", enforce_volume=False, isolation_level="IMMEDIATE",
                       timeout_s=1.0)
    other.con.execute("INSERT INTO execution_venue_results(execution_id,venue,winner,observed_ts) "
                      "VALUES('probe','kalshi','K-STL',?)", (T,))
    other.con.commit()
    other.con.close()
