from __future__ import annotations

import json

from nodes.execute.entry_experiment import F22_CAPS, F22_DECISIONS_DDL, assign_entry_arm
from nodes.execute.records import EXECUTION_DDL
from nodes.execution.journal import JOURNAL_DDL
from nodes.opportunity.opportunity import OPPORTUNITY_DDL
from nodes.opportunity.thresholds import STRATEGY_VERSION
from nodes.exec_polymarket.post_only import POST_ONLY_DDL
from nodes.reconcile.settle_executions import SETTLEMENTS_DDL
from nodes.store_tuples.store import TupleStore
from ops.f22_report import _identity_matches, _maker_guard_status, report


def test_identity_caps_are_compared_to_registered_caps_not_a_shadowed_argument():
    assignment = assign_entry_arm("caps-event").as_record(F22_CAPS)
    row = dict(assignment, event_id="caps-event", sizing_input_hash=None, sizing_occurrence=None,
               sizing_book_epoch=None)
    assert _identity_matches(assignment, row, F22_CAPS)
    changed = dict(assignment, caps={**F22_CAPS, "stake_usd": 30.01})
    assert not _identity_matches(changed, row, F22_CAPS)
    # Both identity copies must agree with the registered caps; accepting a self-consistent but
    # unregistered cap set would let a later override silently change the experiment.
    changed = dict(assignment, caps={"stake_usd": 7.0, "max_contracts": 2.0, "day_notional_usd": 8.0},
                   active_caps={"stake_usd": 7.0, "max_contracts": 2.0, "day_notional_usd": 8.0})
    assert not _identity_matches(changed, row, F22_CAPS)


def test_f23_maker_guard_proof_requires_clean_fill_or_terminal_rest_evidence():
    row = {"arm": "maker"}
    pm = {"state": "FILLED"}

    def execution(evidence):
        return {"protect_json": json.dumps({"maker_guard": evidence})}

    clean_fill = {"checks": 2, "errors": 0, "timeouts": 0, "outcome": "maker_fill"}
    assert _maker_guard_status(execution(clean_fill), row, pm, 5.0, required=True) is None
    assert _maker_guard_status(execution({**clean_fill, "timeouts": 1}), row, pm, 5.0, required=True) == \
        "persistence_or_reconciliation_failure"
    assert _maker_guard_status(execution({**clean_fill, "outcome": "rest_deadline"}), row, pm, 5.0, required=True) == \
        "persistence_or_reconciliation_failure"
    assert _maker_guard_status({"protect_json": "{}"}, row, pm, 5.0, required=True) == \
        "persistence_or_reconciliation_failure"

    for outcome in ("guard_refusal", "rest_deadline"):
        zero = {"checks": 1, "errors": 0, "timeouts": 0,
                "outcome": outcome, "last_reason": "HEDGE_BOOK_STALE"}
        assert _maker_guard_status(execution(zero), row, {"state": "CANCELED"}, 0.0, required=True) is None
    assert _maker_guard_status(
        execution({"checks": 1, "errors": 0, "timeouts": 0,
                   "outcome": "rest_deadline"}), row, {"state": "CANCELED"}, 0.0, required=True
    ) == "persistence_or_reconciliation_failure"


def test_f23_immediate_maker_rejection_may_have_no_rest_guard_proof():
    assert _maker_guard_status(
        {"protect_json": None}, {"arm": "maker"}, {"state": "REJECTED"}, 0.0, required=True
    ) is None


def _decision(st, event: str, *, epoch: str, quantity: float, arm: str | None = None,
              outcome: str | None = None, execution_id: str | None = None, now: float = 1000.0):
    assignment = assign_entry_arm(event).as_record(F22_CAPS)
    if arm is not None:
        assignment["arm"] = arm
    identity = dict(assignment, sizing_input_hash="hash-" + event, sizing_occurrence=1,
                    sizing_book_epoch=epoch)
    decision = {"entry_experiment": identity,
                "candidates": [{"quantity": quantity, "selected": True, "profit_usd": 0.25}]}
    st.con.execute(
        "INSERT INTO f22_decisions(event_id,forward_row_id,assignment_algorithm,digest,arm,sizing_input_hash,"
        "sizing_occurrence,sizing_book_epoch,selected_quantity,decision_json,outcome,outcome_detail,execution_id,created_utc,updated_utc) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (event, assignment["forward_row_id"], assignment["assignment_algorithm"], assignment["digest"], assignment["arm"],
         "hash-" + event, 1, epoch, quantity, json.dumps(decision), outcome, None, execution_id, now, now))
    st.con.execute(
        "INSERT INTO sizing_decisions(seen_ts,event_id,book_epoch,selected_opportunity_id,decision_json,input_hash,occurrence) "
        "VALUES(?,?,?,?,?,?,?)",
        (now, event, epoch, event + ":opp", json.dumps(decision), "hash-" + event, 1))
    st.con.execute(
        "INSERT OR IGNORE INTO opportunities(opportunity_id,event_id,league,strategy_version,status,first_seen_ts,last_seen_ts) "
        "VALUES(?,?,?,?,?,?,?)",
        (event + ":opp", event, "mlb", STRATEGY_VERSION, "EXECUTION_PENDING", now, now))


def _execution(st, execution_id: str, event: str, *, state: str = "RECONCILED", quantity: float = 5.0,
               first_filled: float = 5.0, released: int = 1):
    assignment = assign_entry_arm(event).as_record(F22_CAPS)
    identity = dict(assignment, sizing_input_hash="hash-" + event, sizing_occurrence=1,
                    sizing_book_epoch=next((r[0] for r in st.con.execute(
                        "SELECT sizing_book_epoch FROM f22_decisions WHERE event_id=?", (event,))), None))
    maker = assignment["arm"] == "maker"
    plan = {"first": {"venue": "polymarket", "market_id": "m", "outcome_id": "tok", "side": "buy_yes",
                       "limit_price": .4, "contracts": quantity, "time_in_force": "gtc" if maker else "ioc",
                       "post_only": maker},
            "hedge": {"venue": "kalshi", "market_id": "k", "outcome_id": "tok", "side": "buy_yes",
                      "limit_price": .4, "contracts": quantity, "time_in_force": "ioc", "post_only": False},
            "sizing": {"entry_experiment": identity}}
    st.con.execute(
        "INSERT INTO executions(execution_id,opportunity_id,event_id,league,mode,state,started_utc,last_utc,quantity,"
        "first_filled,hedge_filled,released,detail,plan_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (execution_id, event + ":opp", event, "mlb", "LIMITED_LIVE", state, 1000.0, 1001.0, quantity,
         first_filled, first_filled, released, "structured", json.dumps(plan)))


def _order(st, cid: str, execution_id: str, *, state: str, filled: float, fee: float | None,
           venue: str = "polymarket", venue_order_id: str = "vo-", time_in_force: str = "ioc"):
    st.con.execute(
        "INSERT INTO orders(client_order_id,venue,mode,market_id,outcome_id,side,price,contracts,time_in_force,"
        "opportunity_id,state,venue_order_id,filled_contracts,avg_price,fee_usd,open,settlement_pending,submitted_utc,last_utc,execution_id) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (cid, venue, "LIMITED_LIVE", "m", "tok", "buy_yes", .4, 5.0, time_in_force,
         st.con.execute("SELECT opportunity_id FROM executions WHERE execution_id=?", (execution_id,)).fetchone()[0], state,
         venue_order_id, filled, .4 if filled else None, fee, 0, 0, 1000.0, 1001.0, execution_id))
    if venue == "polymarket":
        st.con.execute("UPDATE executions SET first_client_id=? WHERE execution_id=?", (cid, execution_id))
    elif venue == "kalshi":
        ids = json.loads(st.con.execute(
            "SELECT hedge_client_ids FROM executions WHERE execution_id=?", (execution_id,)).fetchone()[0] or "[]")
        ids.append(cid)
        st.con.execute("UPDATE executions SET hedge_client_ids=? WHERE execution_id=?", (json.dumps(ids), execution_id))


def test_report_keeps_no_wire_zero_distinct_from_unresolved_and_reports_settled_dollars(tmp_path):
    st = TupleStore(tmp_path / "f22.sqlite", enforce_volume=False)
    st.ensure_ddl(F22_DECISIONS_DDL + EXECUTION_DDL + JOURNAL_DDL + SETTLEMENTS_DDL + OPPORTUNITY_DDL)
    _decision(st, "no-wire", epoch="e1", quantity=5, outcome="local_or_risk_refused_no_wire")
    _decision(st, "rej0", epoch="e2", quantity=5, execution_id="x-reject")
    _execution(st, "x-reject", "rej0", state="ORDER_REJECTED", first_filled=0, released=1)
    _order(st, "reject-pm", "x-reject", state="REJECTED", filled=0, fee=0.0)
    _decision(st, "settled", epoch="e3", quantity=5, execution_id="x-settled")
    _execution(st, "x-settled", "settled")
    _order(st, "settled-pm", "x-settled", state="FILLED", filled=5, fee=.10, venue_order_id="vo-pm")
    _order(st, "settled-k", "x-settled", state="FILLED", filled=5, fee=.20, venue="kalshi", venue_order_id="vo-k")
    st.con.execute(
        "INSERT INTO execution_settlements(execution_id,opportunity_id,event_id,league,mode,settled_ts,realized_usd,released,legs_json,kind,hedged_contracts,unhedged_contracts,cover_usd,directional_usd) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("x-settled", "settled:opp", "settled", "mlb", "LIMITED_LIVE", 1100.0, .70, 1, "[]", "COVER", 5, 0, .70, 0.0))
    st.con.commit()
    out = report(tmp_path / "f22.sqlite")
    by_event = {r["event_id"]: r for r in out["decisions"]}
    assert by_event["no-wire"]["outcome"] == "local_or_risk_refused_no_wire"
    assert by_event["no-wire"]["settled_pnl_usd"] == 0.0
    assert by_event["rej0"]["outcome"] == "provider_rejected_no_position"
    assert by_event["rej0"]["settled_pnl_usd"] == 0.0
    assert by_event["settled"]["outcome"] == "accepted_full_fill"
    assert by_event["settled"]["combined_fee_usd"] == .30
    assert by_event["settled"]["settled_pnl_usd"] == .70


def test_report_unknown_never_becomes_zero_and_maker_role_is_structured(tmp_path):
    st = TupleStore(tmp_path / "f22.sqlite", enforce_volume=False)
    st.ensure_ddl(F22_DECISIONS_DDL + EXECUTION_DDL + JOURNAL_DDL + SETTLEMENTS_DDL + POST_ONLY_DDL + OPPORTUNITY_DDL)
    unknown = next(f"unknown-{n}" for n in range(100) if assign_entry_arm(f"unknown-{n}").arm == "maker")
    _decision(st, unknown, epoch="e1", quantity=5, execution_id="x-unknown")
    _execution(st, "x-unknown", unknown, state="UNKNOWN_PROVIDER_STATE", released=1)
    _order(st, "unknown-pm", "x-unknown", state="UNCONFIRMED", filled=5, fee=None,
           venue_order_id="vo-u", time_in_force="gtc")
    st.con.execute("INSERT INTO pm_post_only_orders(client_order_id,venue_order_id,maker_amount,taker_amount,wire_json) VALUES(?,?,?,?,?)",
                   ("unknown-pm", "vo-u", "5", "5000000", "{}"))
    role = next(f"role-{n}" for n in range(100) if assign_entry_arm(f"role-{n}").arm == "maker")
    _decision(st, role, epoch="e2", quantity=5, execution_id="x-role")
    _execution(st, "x-role", role, released=1)
    _order(st, "role-pm", "x-role", state="FILLED", filled=5, fee=.1,
           venue_order_id="vo-r", time_in_force="gtc")
    _order(st, "role-k", "x-role", state="FILLED", filled=5, fee=.1,
           venue="kalshi", venue_order_id="vo-role-k")
    st.con.execute("INSERT INTO pm_post_only_orders(client_order_id,venue_order_id,maker_amount,taker_amount,wire_json,terminal_proved,violated) VALUES(?,?,?,?,?,?,?)",
                   ("role-pm", "vo-r", "5", "5000000", "{}", 1, 1))
    st.con.commit()
    by_event = {r["event_id"]: r for r in report(tmp_path / "f22.sqlite")["decisions"]}
    assert by_event[unknown]["outcome"] == "unknown_provider_state"
    assert by_event[unknown]["settled_pnl_usd"] is None
    assert by_event[unknown]["combined_fee_usd"] is None
    assert by_event[role]["outcome"] == "role_violation"


def test_maker_fill_requires_gtc_terminal_marker_and_final_maker_quantity_evidence(tmp_path):
    st = TupleStore(tmp_path / "f22.sqlite", enforce_volume=False)
    st.ensure_ddl(F22_DECISIONS_DDL + EXECUTION_DDL + JOURNAL_DDL + SETTLEMENTS_DDL + POST_ONLY_DDL + OPPORTUNITY_DDL)
    event = next(f"maker-{n}" for n in range(100) if assign_entry_arm(f"maker-{n}").arm == "maker")
    _decision(st, event, epoch="e1", quantity=5, execution_id="x-maker")
    _execution(st, "x-maker", event)
    _order(st, "maker-pm", "x-maker", state="FILLED", filled=5, fee=0.0,
           venue_order_id="vo-maker", time_in_force="gtc")
    _order(st, "maker-k", "x-maker", state="FILLED", filled=5, fee=.20,
           venue="kalshi", venue_order_id="vo-k")
    st.con.execute(
        "INSERT INTO pm_post_only_orders(client_order_id,venue_order_id,maker_amount,taker_amount,wire_json,terminal_proved,violated) "
        "VALUES('maker-pm','vo-maker','5','5000000','{}',1,0)"
    )
    st.con.execute(
        "INSERT INTO venue_fills VALUES('fill-maker','polymarket','vo-maker',5,.4,0,0,1001,1)"
    )
    st.con.execute(
        "INSERT INTO execution_settlements(execution_id,opportunity_id,event_id,league,mode,settled_ts,realized_usd,released,legs_json,kind,hedged_contracts,unhedged_contracts,cover_usd,directional_usd) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("x-maker", event + ":opp", event, "mlb", "LIMITED_LIVE", 1100, .8, 1, "[]", "COVER", 5, 0, .8, 0),
    )
    st.con.commit()
    row = report(tmp_path / "f22.sqlite")["decisions"][0]
    assert row["outcome"] == "accepted_full_fill" and row["settled_pnl_usd"] == .8

    st.con.execute("UPDATE venue_fills SET contracts=4 WHERE fill_id='fill-maker'")
    st.con.commit()
    assert report(tmp_path / "f22.sqlite")["decisions"][0]["outcome"] == "persistence_or_reconciliation_failure"

def test_maker_zero_fill_is_unknown_until_post_only_terminal_proof(tmp_path):
    st = TupleStore(tmp_path / "f22.sqlite", enforce_volume=False)
    st.ensure_ddl(F22_DECISIONS_DDL + EXECUTION_DDL + JOURNAL_DDL + SETTLEMENTS_DDL + POST_ONLY_DDL + OPPORTUNITY_DDL)
    event = next(f"zero-{n}" for n in range(100) if assign_entry_arm(f"zero-{n}").arm == "maker")
    _decision(st, event, epoch="e1", quantity=5, execution_id="x-zero")
    _execution(st, "x-zero", event, state="ORDER_UNFILLED", first_filled=0, released=1)
    _order(st, "zero-pm", "x-zero", state="CANCELED", filled=0, fee=0.0,
           venue_order_id="vo-zero", time_in_force="gtc")
    st.con.execute(
        "INSERT INTO pm_post_only_orders(client_order_id,venue_order_id,maker_amount,taker_amount,wire_json,terminal_proved,violated) "
        "VALUES('zero-pm','vo-zero','5','5000000','{}',0,0)"
    )
    st.con.commit()
    assert report(tmp_path / "f22.sqlite")["decisions"][0]["outcome"] == "unknown_provider_state"
    st.con.execute("UPDATE pm_post_only_orders SET terminal_proved=1 WHERE client_order_id='zero-pm'")
    st.con.commit()
    row = report(tmp_path / "f22.sqlite")["decisions"][0]
    assert row["outcome"] == "accepted_terminal_zero_fill" and row["settled_pnl_usd"] == 0.0


def test_report_requires_exact_durable_sizing_join(tmp_path):
    st = TupleStore(tmp_path / "f22.sqlite", enforce_volume=False)
    st.ensure_ddl(F22_DECISIONS_DDL + EXECUTION_DDL + JOURNAL_DDL + SETTLEMENTS_DDL + OPPORTUNITY_DDL)
    _decision(st, "missing-sizing", epoch="e1", quantity=5, outcome="local_or_risk_refused_no_wire")
    st.con.execute("DELETE FROM sizing_decisions WHERE event_id='missing-sizing'")
    st.con.commit()
    row = report(tmp_path / "f22.sqlite")["decisions"][0]
    assert row["outcome"] == "persistence_or_reconciliation_failure"
    assert row["persistence_or_reconciliation_failure"] is True


def test_report_validates_taker_wire_contract_and_state_contradictions(tmp_path):
    st = TupleStore(tmp_path / "f22.sqlite", enforce_volume=False)
    st.ensure_ddl(F22_DECISIONS_DDL + EXECUTION_DDL + JOURNAL_DDL + SETTLEMENTS_DDL + OPPORTUNITY_DDL)
    event = next(f"taker-{n}" for n in range(100) if assign_entry_arm(f"taker-{n}").arm == "taker")
    _decision(st, event, epoch="e1", quantity=5, execution_id="x-wire")
    _execution(st, "x-wire", event, released=1)
    plan = json.loads(st.con.execute("SELECT plan_json FROM executions WHERE execution_id='x-wire'").fetchone()[0])
    plan["first"]["post_only"] = True
    plan["first"]["time_in_force"] = "gtc"
    st.con.execute("UPDATE executions SET plan_json=? WHERE execution_id='x-wire'", (json.dumps(plan),))
    _order(st, "wire-pm", "x-wire", state="FILLED", filled=5, fee=.1)
    st.con.commit()
    row = report(tmp_path / "f22.sqlite")["decisions"][0]
    assert row["outcome"] == "role_violation"

    contradiction = next(f"contradiction-{n}" for n in range(100) if assign_entry_arm(f"contradiction-{n}").arm == "taker")
    _decision(st, contradiction, epoch="e2", quantity=5, execution_id="x-contradiction")
    _execution(st, "x-contradiction", contradiction, released=1)
    _order(st, "bad-pm", "x-contradiction", state="REJECTED", filled=5, fee=.1)
    _order(st, "bad-k", "x-contradiction", state="FILLED", filled=5, fee=.1, venue="kalshi")
    st.con.commit()
    rows = {r["event_id"]: r for r in report(tmp_path / "f22.sqlite")["decisions"]}
    assert rows[contradiction]["outcome"] == "persistence_or_reconciliation_failure"


def test_report_does_not_score_filled_row_without_complete_settlement(tmp_path):
    st = TupleStore(tmp_path / "f22.sqlite", enforce_volume=False)
    st.ensure_ddl(F22_DECISIONS_DDL + EXECUTION_DDL + JOURNAL_DDL + SETTLEMENTS_DDL + OPPORTUNITY_DDL)
    event = next(f"filled-{n}" for n in range(100) if assign_entry_arm(f"filled-{n}").arm == "taker")
    _decision(st, event, epoch="e1", quantity=5, execution_id="x-filled")
    _execution(st, "x-filled", event, released=1)
    _order(st, "filled-pm", "x-filled", state="FILLED", filled=5, fee=.1)
    _order(st, "filled-k", "x-filled", state="FILLED", filled=5, fee=.1, venue="kalshi")
    st.con.commit()
    row = report(tmp_path / "f22.sqlite")["decisions"][0]
    assert row["outcome"] == "persistence_or_reconciliation_failure"
    assert row["settled_pnl_usd"] is None


def test_report_rejects_unproved_explicit_zero_and_execution_state_contradiction(tmp_path):
    st = TupleStore(tmp_path / "f22.sqlite", enforce_volume=False)
    st.ensure_ddl(F22_DECISIONS_DDL + EXECUTION_DDL + JOURNAL_DDL + SETTLEMENTS_DDL + OPPORTUNITY_DDL)
    _decision(st, "claimed-zero", epoch="e1", quantity=5, outcome="accepted_terminal_zero_fill")
    event = next(f"state-bad-{n}" for n in range(100) if assign_entry_arm(f"state-bad-{n}").arm == "taker")
    _decision(st, event, epoch="e2", quantity=5, execution_id="x-state")
    _execution(st, "x-state", event, state="ORDER_REJECTED")
    _order(st, "state-pm", "x-state", state="FILLED", filled=5, fee=.1)
    _order(st, "state-k", "x-state", state="FILLED", filled=5, fee=.1, venue="kalshi")
    st.con.execute(
        "INSERT INTO execution_settlements(execution_id,opportunity_id,event_id,league,mode,settled_ts,realized_usd,released,legs_json,kind,hedged_contracts,unhedged_contracts,cover_usd,directional_usd) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("x-state", event + ":opp", event, "mlb", "LIMITED_LIVE", 1100, .2, 1, "[]", "COVER", 5, 0, .2, 0))
    st.con.commit()
    rows = {r["event_id"]: r for r in report(tmp_path / "f22.sqlite")["decisions"]}
    assert rows["claimed-zero"]["outcome"] == "persistence_or_reconciliation_failure"
    assert rows[event]["outcome"] == "persistence_or_reconciliation_failure"


def test_report_rejects_opportunity_identity_and_noncover_settlement(tmp_path):
    st = TupleStore(tmp_path / "f22.sqlite", enforce_volume=False)
    st.ensure_ddl(F22_DECISIONS_DDL + EXECUTION_DDL + JOURNAL_DDL + SETTLEMENTS_DDL + OPPORTUNITY_DDL)
    event = next(f"opp-bad-{n}" for n in range(100) if assign_entry_arm(f"opp-bad-{n}").arm == "taker")
    _decision(st, event, epoch="e1", quantity=5, execution_id="x-opp")
    st.con.execute("UPDATE opportunities SET league='nba' WHERE opportunity_id=?", (event + ":opp",))
    st.con.commit()
    assert report(tmp_path / "f22.sqlite")["decisions"][0]["outcome"] == "persistence_or_reconciliation_failure"

    st.con.execute("UPDATE opportunities SET league='mlb' WHERE opportunity_id=?", (event + ":opp",))
    _execution(st, "x-opp", event)
    _order(st, "opp-pm", "x-opp", state="FILLED", filled=5, fee=.1)
    _order(st, "opp-k", "x-opp", state="FILLED", filled=5, fee=.1, venue="kalshi")
    st.con.execute(
        "INSERT INTO execution_settlements(execution_id,opportunity_id,event_id,league,mode,settled_ts,realized_usd,released,legs_json,kind,hedged_contracts,unhedged_contracts,cover_usd,directional_usd) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("x-opp", event + ":opp", event, "mlb", "LIMITED_LIVE", 1100, -.2, 1, "[]", "UNWOUND", 5, 0, 0, -.2))
    st.con.commit()
    assert report(tmp_path / "f22.sqlite")["decisions"][0]["outcome"] == "persistence_or_reconciliation_failure"


def test_report_validates_kalshi_hedge_wire_and_no_wire_execution_identity(tmp_path):
    st = TupleStore(tmp_path / "f22.sqlite", enforce_volume=False)
    st.ensure_ddl(F22_DECISIONS_DDL + EXECUTION_DDL + JOURNAL_DDL + SETTLEMENTS_DDL + OPPORTUNITY_DDL)
    event = next(f"hedge-contract-{n}" for n in range(100) if assign_entry_arm(f"hedge-contract-{n}").arm == "taker")
    _decision(st, event, epoch="e1", quantity=5, execution_id="x-hedge")
    _execution(st, "x-hedge", event)
    _order(st, "hedge-pm", "x-hedge", state="FILLED", filled=5, fee=.1)
    _order(st, "hedge-k", "x-hedge", state="FILLED", filled=5, fee=.1, venue="kalshi")
    plan = json.loads(st.con.execute("SELECT plan_json FROM executions WHERE execution_id='x-hedge'").fetchone()[0])
    plan["hedge"]["time_in_force"] = "gtc"
    plan["hedge"]["post_only"] = True
    st.con.execute("UPDATE executions SET plan_json=? WHERE execution_id='x-hedge'", (json.dumps(plan),))

    no_wire = "identity-no-wire"
    _decision(st, no_wire, epoch="e2", quantity=5, outcome="local_or_risk_refused_no_wire", execution_id="x-no-wire")
    _execution(st, "x-no-wire", no_wire, state="BOOK_MOVED", first_filled=0, released=1)
    st.con.execute("UPDATE executions SET opportunity_id='wrong-opportunity' WHERE execution_id='x-no-wire'")
    st.con.commit()
    rows = {r["event_id"]: r for r in report(tmp_path / "f22.sqlite")["decisions"]}
    assert rows[event]["outcome"] == "role_violation"
    assert rows[no_wire]["outcome"] == "persistence_or_reconciliation_failure"

    st.con.execute("UPDATE executions SET opportunity_id=?, hedge_client_ids='[\"ghost\"]' WHERE execution_id='x-no-wire'",
                   (no_wire + ":opp",))
    st.con.commit()
    rows = {r["event_id"]: r for r in report(tmp_path / "f22.sqlite")["decisions"]}
    assert rows[no_wire]["outcome"] == "persistence_or_reconciliation_failure"

    st.con.execute("UPDATE executions SET hedge_client_ids='[]' WHERE execution_id='x-no-wire'")
    st.con.execute(
        "INSERT INTO execution_settlements(execution_id,opportunity_id,event_id,league,mode,settled_ts,realized_usd,released,legs_json,kind,hedged_contracts,unhedged_contracts,cover_usd,directional_usd) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("x-no-wire", no_wire + ":opp", no_wire, "mlb", "LIMITED_LIVE", 1100, 0, 1, "[]", "COVER", 0, 0, 0, 0))
    st.con.commit()
    rows = {r["event_id"]: r for r in report(tmp_path / "f22.sqlite")["decisions"]}
    assert rows[no_wire]["outcome"] == "persistence_or_reconciliation_failure"
