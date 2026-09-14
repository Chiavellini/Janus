#!/usr/bin/env python3
"""The funnel joins stages that were previously three tools and some arithmetic by hand."""
from __future__ import annotations

import time
from pathlib import Path

from nodes.store_tuples.store import TupleStore
from ops.funnel_report import report

T = time.time() - 600.0


def _world(tmp_path: Path) -> Path:
    st = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    st.ensure_ddl("""
CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY, league TEXT, start_utc INTEGER,
  participants TEXT, short_name TEXT, phase TEXT NOT NULL, kalshi_event TEXT, pm_slug TEXT,
  fee_params_json TEXT, spec_json TEXT, first_seen_ts REAL NOT NULL, last_seen_ts REAL NOT NULL,
  block_reason TEXT, tier TEXT);
CREATE TABLE IF NOT EXISTS orders(client_order_id TEXT PRIMARY KEY, venue TEXT, mode TEXT,
  market_id TEXT, outcome_id TEXT, side TEXT, price REAL, contracts REAL, time_in_force TEXT,
  opportunity_id TEXT, state TEXT, filled_contracts REAL, avg_price REAL, fee_usd REAL,
  submitted_utc REAL, last_utc REAL);
CREATE TABLE IF NOT EXISTS executions(execution_id TEXT PRIMARY KEY, mode TEXT, state TEXT,
  started_utc REAL, last_utc REAL);
CREATE TABLE IF NOT EXISTS execution_settlements(execution_id TEXT PRIMARY KEY, mode TEXT,
  settled_ts REAL, realized_usd REAL, kind TEXT, hedged_contracts REAL, unhedged_contracts REAL,
  cover_usd REAL, directional_usd REAL);
""")
    c = st.con
    # two co-listed, one unpaired because Kalshi does not list it -- the live 84% case
    c.execute("INSERT INTO events VALUES('e1','mlb',0,'','A v B','in:co_listed','','','','',?,?,NULL,'live')", (T, T))
    c.execute("INSERT INTO events VALUES('e2','mlb',0,'','C v D','in:co_listed','','','','',?,?,NULL,'live')", (T, T))
    c.execute("INSERT INTO events VALUES('e3','itf',0,'','E v F','in','','','','',?,?,"
              "'UNPAIRED:kalshi=missing,polymarket=found','live')", (T, T))
    for i in range(7):                                    # actionable prints on the q=10 rung
        st.evaluation(game_id="e1", league="mlb", quantity=10.0, status="PROFITABLE_UNEXECUTED",
                      cost=0.97, gross=1.03, fees=0.01, return_locked=0.03, required_ask_sum=0.99,
                      cents_from_actionable=4.0, blocked_by=None, triggered_by="k", latency_ms=1.0,
                      legs=[], seen_ts=T + i, epsilon=0.0, heartbeat_s=0.0)
    st.evaluation(game_id="e2", league="mlb", quantity=10.0, status="BLOCKED_STALE", cost=None,
                  gross=None, fees=None, return_locked=None, required_ask_sum=None,
                  cents_from_actionable=None, blocked_by="supervisor:halt:CLOCK_UNHEALTHY",
                  triggered_by="k", latency_ms=1.0, legs=[], seen_ts=T, epsilon=0.0, heartbeat_s=0.0)
    st.refusal_counts({("risk", "IN_FLIGHT", "mlb"): 900, ("size", "MIN_PROFIT", "mlb"): 40}, seen_ts=T)
    c.execute("INSERT INTO executions VALUES('x1','LIMITED_LIVE','HEDGED',?,?)", (T, T))
    c.execute("INSERT INTO orders VALUES('a','polymarket','LIMITED_LIVE','m','o','buy_yes',0.5,10,'fok',"
              "'op','FILLED',10,0.5,0.0,?,?)", (T, T))
    c.execute("INSERT INTO execution_settlements VALUES('x1','LIMITED_LIVE',?,0.12,'COVER',10,0,0.12,0.0)", (T,))
    c.commit()
    return tmp_path / "t.sqlite"


def test_the_funnel_joins_prints_refusals_orders_and_money(tmp_path: Path):
    r = report(_world(tmp_path), hours=1.0, quantity=10.0)
    s = r["stages"]
    assert s["events_seen"] == 3 and s["co_listed"] == 2 and s["unpaired"] == 1
    assert s["actionable_prints"] == 7, "seven prints, one rung, no double counting across quantities"
    assert s["halted_prints"] == 1, "a halted epoch priced nothing and is counted apart (L111)"
    assert s["executions"] == 1 and s["orders"] == 1 and s["orders_filled"] == 1
    assert s["covers"] == 1
    # The middle of the funnel, which used to exist only in journald.
    got = {(d["channel"], d["code"]): d["n"] for d in r["detail"]["refusals"]}
    assert got[("risk", "IN_FLIGHT")] == 900 and got[("size", "MIN_PROFIT")] == 40
    # Arbitrage money and lucky money are never added together.
    assert r["money"]["cover_usd"] == 0.12 and r["money"]["directional_usd"] == 0.0


def test_a_lane_that_has_not_ticked_since_the_counters_shipped_says_so(tmp_path: Path):
    """An empty refusals section must not read as 'nothing was refused'."""
    db = _world(tmp_path)
    TupleStore(db, enforce_volume=False).con.execute("DROP TABLE refusal_counts")
    assert report(db, hours=1.0, quantity=10.0)["detail"]["refusals"] == []
