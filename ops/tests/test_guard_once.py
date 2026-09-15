#!/usr/bin/env python3
"""The one-shot guard hydrates historical event fee schedules before replaying venue fills."""
from __future__ import annotations

import json
from types import SimpleNamespace
import pytest

from nodes.discovery.discovery import EVENTS_DDL
from nodes.execute.records import EXECUTION_DDL
from nodes.execution.journal import JOURNAL_DDL
from nodes.store_tuples.store import TupleStore
from ops.guard_once import load_polymarket_fee_params
import ops.guard_once as guard_once


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


def _guard_fixture(monkeypatch, *, positions, fills_read_complete=True, errors=None,
                   orphans=(), mismatches=(), to_protect=(), findings=()):
    class FakeGuard:
        def __init__(self, **_kwargs):
            pass
        def fetch(self):
            return type("Snap", (), {"errors": errors or {}, "positions": positions,
                                     "fills_read_complete": fills_read_complete, "unconfirmed": {},
                                     "adopted": []})()
        def apply(self, _snap):
            return type("Rep", (), {"findings": list(findings), "corrected": 0, "to_protect": list(to_protect),
                                     "orphans": list(orphans), "mismatches": list(mismatches), "fills_today": []})()
    monkeypatch.setattr(guard_once, "PositionGuard", FakeGuard)


def test_require_complete_quiet_requires_both_readable_positions(monkeypatch):
    _guard_fixture(monkeypatch, positions={"kalshi": [], "polymarket": []})
    limits = type("Limits", (), {"protect": object()})()
    got = guard_once.run_once(venues={}, store=None, journal=None, records=None, limits=limits,
                              kill=None, started_utc=1, require_complete_quiet=True, log=lambda *_: None)
    assert got["complete_quiet"]

    _guard_fixture(monkeypatch, positions={"kalshi": [], "polymarket": [], "extra": []})
    got = guard_once.run_once(venues={}, store=None, journal=None, records=None, limits=limits,
                              kill=None, started_utc=1, require_complete_quiet=True, log=lambda *_: None)
    assert not got["complete_quiet"]


def test_require_complete_quiet_accepts_exact_resolution_findings(monkeypatch):
    _guard_fixture(monkeypatch, positions={"kalshi": [], "polymarket": []}, findings=(
        "ORPHAN_FILL_RESOLVED_EXACT: exact external ownership; kill unchanged",
        "ORDER_OVERFILL_RESOLVED_EXACT: exact bounded-taker residual acknowledgement; kill unchanged",
        "POST_ONLY_PERSISTENCE_FAILED_RESOLVED_EXACT: additive migration false alarms; kill unchanged",
    ))
    limits = type("Limits", (), {"protect": object()})()
    got = guard_once.run_once(venues={}, store=None, journal=None, records=None, limits=limits,
                              kill=None, started_utc=1, require_complete_quiet=True, log=lambda *_: None)
    assert got["complete_quiet"]


@pytest.mark.parametrize("kwargs", [
    {"fills_read_complete": False}, {"errors": {"fills": "timeout"}},
    {"orphans": ["x"]}, {"mismatches": ["x"]}, {"to_protect": ["x"]},
    {"findings": ["FEE_ABOVE_PIN bad"]},
])
def test_require_complete_quiet_rejects_any_incomplete_or_material_finding(monkeypatch, kwargs):
    _guard_fixture(monkeypatch, positions={"kalshi": [], "polymarket": []}, **kwargs)
    limits = type("Limits", (), {"protect": object()})()
    got = guard_once.run_once(venues={}, store=None, journal=None, records=None, limits=limits,
                              kill=None, started_utc=1, require_complete_quiet=True, log=lambda *_: None)
    assert not got["complete_quiet"]
