#!/usr/bin/env python3
"""The one-shot guard hydrates historical event fee schedules before replaying venue fills."""
from __future__ import annotations

import json
from types import SimpleNamespace

from nodes.discovery.discovery import EVENTS_DDL
from nodes.execute.records import EXECUTION_DDL
from nodes.execution.journal import JOURNAL_DDL
from nodes.store_tuples.store import TupleStore
from ops.guard_once import load_polymarket_fee_params


def test_historical_polymarket_tokens_receive_their_own_fee_schedule(tmp_path):
    st = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    st.ensure_ddl(EVENTS_DDL)
    st.ensure_ddl(EXECUTION_DDL)
    st.ensure_ddl(JOURNAL_DDL)
    fees = {"polymarket": {"fee_rate": 0.05, "taker_only": True}, "kalshi": {"fee_multiplier": 0.5}}
    st.con.execute(
        "INSERT INTO events(event_id,league,start_utc,phase,fee_params_json,first_seen_ts,last_seen_ts) VALUES(?,?,?,?,?,?,?)",
        ("e", "mlb", 1, "post", json.dumps(fees), 1, 1),
    )
    st.con.execute(
        "INSERT INTO executions(execution_id,opportunity_id,event_id,league,mode,state,started_utc,last_utc,quantity,first_client_id,released) "
        "VALUES('x','opp','e','mlb','LIMITED_LIVE','HEDGED',1,1,10,'cid',0)"
    )
    st.con.execute(
        "INSERT INTO orders(client_order_id,venue,mode,market_id,outcome_id,side,price,contracts,time_in_force,opportunity_id,state,submitted_utc,last_utc) "
        "VALUES('cid','polymarket','LIMITED_LIVE','token','token','buy_yes',0.63,10,'ioc','opp','FILLED',1,1)"
    )
    st.con.commit()
    venue = SimpleNamespace(fee_params_by_market={})
    assert load_polymarket_fee_params(st, venue) == 1
    assert venue.fee_params_by_market == {"token": fees["polymarket"]}
