import json

import pytest

from kernel.execution_protocol import OrderRequest
from kernel.schema import ExecutionState as X, FillState
from nodes.execute.plan import LegPlan, Plan
from nodes.execute.records import Execution, ExecutionRecords
from nodes.reconcile.reconcile import settle
from nodes.store_tuples.store import TupleStore


def _plan():
    first = LegPlan("polymarket", "tok", "tok", "buy_yes", 0.58, 10.0, "ioc", vwap=0.57, tick=0.01)
    hedge = LegPlan("kalshi", "K-GEA", "K-GEA", "buy_yes", 0.31, 10.0, "ioc", vwap=0.31, tick=0.01)
    return Plan("opp1", "ev1", "atp", 10.0, first, hedge, max_cost_per_contract=0.9901, fee_per_contract=0.0272)


def test_sell_sides_are_orders_and_say_so():
    r = OrderRequest("polymarket", "tok", "tok", "sell_yes", 0.55, 10.0, "ioc", "c1", "opp1", hedge=True)
    assert r.is_sell and not OrderRequest("kalshi", "K", "K", "buy_no", 0.4, 1.0, "ioc", "c2", "opp1").is_sell
    with pytest.raises(ValueError):
        OrderRequest("polymarket", "tok", "tok", "short_yes", 0.55, 10.0, "ioc", "c3", "opp1")


def test_the_two_new_states_sit_where_the_layer_needs_them():
    assert not X.UNWIND_SUBMITTED.is_terminal and not X.UNWIND_SUBMITTED.holds_position and not X.UNWIND_SUBMITTED.is_failure
    assert X.UNWOUND.is_terminal and X.UNWOUND.is_failure and not X.UNWOUND.holds_position


def test_an_old_table_gains_the_columns_and_a_row_reads_back_with_its_plan(tmp_path):
    st = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    # an executions table from before 2026-09-08: no unwind columns
    st.con.executescript("""CREATE TABLE executions(
      execution_id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, event_id TEXT NOT NULL, league TEXT NOT NULL,
      mode TEXT NOT NULL, state TEXT NOT NULL, started_utc REAL NOT NULL, last_utc REAL NOT NULL,
      quantity REAL NOT NULL, first_client_id TEXT, hedge_client_ids TEXT, first_filled REAL DEFAULT 0,
      first_avg_price REAL, hedge_filled REAL DEFAULT 0, hedge_avg_price REAL, unhedged REAL DEFAULT 0,
      reservation_id TEXT, released INTEGER DEFAULT 0, detail TEXT, plan_json TEXT, books_json TEXT);""")
    rec = ExecutionRecords(st)
    cols = {r[1] for r in st.con.execute("PRAGMA table_info(executions)")}
    assert {"stages_json", "first_unwound", "hedge_unwind_avg", "protect_json", "corrected_utc"} <= cols
    p = _plan()
    ex = Execution("e1", "opp1", "ev1", "atp", "LIMITED_LIVE", 10.0, 1000.0, reservation_id="r1")
    rec.start(ex, plan={"first": p.first.__dict__, "hedge": p.hedge.__dict__, "max_cost": p.max_cost_per_contract,
                        "fee": p.fee_per_contract}, books={})
    rec.move(ex, X.VALIDATED, now=1000.1); rec.move(ex, X.CAPITAL_RESERVED, now=1000.2); rec.move(ex, X.LEG_A_SUBMITTED, now=1000.3)
    ex.first_filled, ex.first_avg_price, ex.first_client_id = 10.175, 0.57, "a1"
    rec.move(ex, X.LEG_A_FILLED, now=1001.0)
    ex.protect = {"attempts": [{"t": 1001.5, "kind": "hedge", "limit": 0.31}]}
    ex.first_unwound, ex.first_unwind_avg, ex.unwind_client_ids = 10.175, 0.55, ["u1"]
    rec.sync(ex, now=1002.0)
    back = rec.load("e1")
    assert back.state is X.LEG_A_FILLED and back.first_filled == 10.175 and back.first_unwound == 10.175
    assert back.unwind_client_ids == ["u1"] and back.protect["attempts"][0]["kind"] == "hedge"
    assert back.unhedged == 0.0 and back.net_first == 0.0 and not back.holds_anything
    assert rec.load("e") is not None and rec.load("zz") is None, "a unique prefix reads; an unknown id is None"
    plan = rec.plan_of("e1")
    assert plan == p, "the plan comes back exactly as the machine ran it"


def test_the_guard_corrects_fills_and_reopens_a_released_row(tmp_path):
    st = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    rec = ExecutionRecords(st)
    ex = Execution("e2", "opp2", "ev2", "atp", "LIMITED_LIVE", 10.0, 1000.0)
    rec.start(ex, plan={}, books={})
    rec.move(ex, X.LEG_A_SUBMITTED, now=1000.5)
    rec.move(ex, X.UNKNOWN_PROVIDER_STATE, now=1001.0, detail="machine error")
    # the venue says 10.175 filled @ 0.57 (GEA V ZANDSCH, 2026-09-08 01:39Z)
    rec.correct_fills(ex, first_filled=10.175, first_avg=0.57, note="polymarket trade 5fc95d33 10.175 @ 0.57", now=1100.0)
    row = rec.row("e2")
    assert row["first_filled"] == 10.175 and row["unhedged"] == 10.175 and row["corrected_utc"] == 1100.0
    assert row["state"] == "UNKNOWN_PROVIDER_STATE", "a correction never moves the state"
    tr = st.con.execute("SELECT from_state, to_state, detail FROM execution_transitions WHERE execution_id='e2' ORDER BY id").fetchall()[-1]
    assert tr == ("UNKNOWN_PROVIDER_STATE", "UNKNOWN_PROVIDER_STATE", "guard: polymarket trade 5fc95d33 10.175 @ 0.57")
    # a released rejection the venue contradicts is reopened as holding
    ex3 = Execution("e3", "opp3", "ev3", "mlb", "LIMITED_LIVE", 5.0, 1000.0)
    rec.start(ex3, plan={}, books={}); rec.move(ex3, X.LEG_A_SUBMITTED, now=1000.5)
    ex3.released = True; rec.move(ex3, X.ORDER_REJECTED, now=1001.0, detail="leg A unfilled")
    with pytest.raises(ValueError):
        rec.reopen(ex, note="not terminal", now=1200.0)
    rec.reopen(ex3, note="venue shows a fill", now=1200.0)
    assert ex3.state is X.UNKNOWN_PROVIDER_STATE and not ex3.released
    assert rec.row("e3")["released"] == 0 and rec.row("e3")["state"] == "UNKNOWN_PROVIDER_STATE"


def test_an_unwind_settlement_row_carries_the_layer_s_loss_today(tmp_path):
    st = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    rec = ExecutionRecords(st)
    ex = Execution("e4", "opp4", "ev4", "atp", "LIMITED_LIVE", 10.0, 1000.0, first_filled=10.0, first_avg_price=0.57,
                   first_unwound=10.0, first_unwind_avg=0.55)
    rec.start(ex, plan={}, books={})
    rec.write_unwind_settlement(ex, realized_usd=-0.2 - 0.05, legs=[{"side": "buy_yes"}, {"side": "sell_yes"}], now=1500.0)
    r = st.con.execute("SELECT kind, realized_usd, released, hedged_contracts, directional_usd FROM execution_settlements WHERE execution_id='e4'").fetchone()
    assert r == ("UNWOUND", -0.25, 1, 0.0, -0.25)


def test_settle_prices_a_sell_leg_with_the_sign_flipped():
    legs = [{"venue": "polymarket", "client_order_id": "a", "outcome_id": "tok", "side": "buy_yes", "contracts": 10.0,
             "price": 0.57, "fee_usd": 0.05, "state": "FILLED", "final": True},
            {"venue": "polymarket", "client_order_id": "u", "outcome_id": "tok", "side": "sell_yes", "contracts": 10.0,
             "price": 0.55, "fee_usd": 0.05, "state": "FILLED", "final": True}]
    won = settle(legs=legs, winners={"polymarket": "tok"}, now=2000.0)
    lost = settle(legs=legs, winners={"polymarket": "other"}, now=2000.0)
    # bought 10 @ 0.57 and sold 10 @ 0.55: the position is flat, the result is -0.20 less both fees, whoever wins
    assert round(sum(r.realized_usd for r in won), 4) == round(sum(r.realized_usd for r in lost), 4) == -0.30
    assert won[1].state is FillState.FILLED
