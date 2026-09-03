#!/usr/bin/env python3
"""The write path. It gates on material change; a test that it does so is what was missing."""
from __future__ import annotations

from pathlib import Path

import pytest

from nodes.store_tuples.store import TupleStore


@pytest.fixture
def store(tmp_path: Path):
    s = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    yield s
    s.close()


def test_the_root_disk_is_structurally_barred(tmp_path):
    with pytest.raises(ValueError, match="Volumes/Kilos"):
        TupleStore(tmp_path / "t.sqlite")


def q(store, **kw):
    base = dict(venue="k", market_id="m", best_bid=0.40, best_ask=0.45, bid_depth=100.0,
                ask_depth=100.0, n_bid_levels=2, n_ask_levels=2, two_sided=True, seen_ts=1.0)
    base.update(kw)
    return store.quote(**base)


def test_quotes_land_only_on_a_material_change(store):
    assert q(store)                              # FIRST_SEEN
    assert not q(store)                          # identical
    assert not q(store, best_ask=0.454)          # sub-tick (but latest_quotes DOES move to 0.454)
    assert q(store, best_ask=0.465)              # ASK_TICK, measured from the stored 0.454
    assert q(store, best_ask=0.465, ask_depth=115.0)   # DEPTH_10PCT
    reasons = [r[0] for r in store.con.execute(
        "SELECT material_reason FROM quote_history ORDER BY id").fetchall()]
    assert reasons == ["FIRST_SEEN", "ASK_TICK", "DEPTH_10PCT"]


def test_opportunities_land_on_a_fingerprint_change(store):
    kw = dict(tuple_id="t", relation_type="pair", status="NO_EDGE", gross_cost=1.01, fees=0.01,
              net_profit=-0.02, return_locked=-0.02, capacity=100.0, seen_ts=1.0)
    assert store.opportunity(**kw)
    assert not store.opportunity(**kw)
    assert store.opportunity(**{**kw, "status": "ACTIONABLE"})
    n = store.con.execute("SELECT COUNT(*) FROM opportunity_history").fetchone()[0]
    assert n == 2


def test_evaluations_gate_on_epsilon_status_and_heartbeat(store):
    kw = dict(game_id="g", league="mlb", quantity=100.0, status="NO_EDGE", cost=1.0100,
              gross=1.0, fees=0.01, return_locked=-0.01, required_ask_sum=0.98,
              cents_from_actionable=2.0, blocked_by=None, triggered_by="m", latency_ms=1.0)
    assert store.evaluation(**kw, seen_ts=0.0)
    assert not store.evaluation(**{**kw, "cost": 1.0105}, seen_ts=1.0)     # under 0.1c
    assert store.evaluation(**{**kw, "cost": 1.0120}, seen_ts=2.0)         # 0.2c move
    assert store.evaluation(**{**kw, "cost": 1.0120}, seen_ts=2.0 + 15.0)  # heartbeat
    assert store.evaluation(**{**kw, "cost": None, "status": "STALE", "blocked_by": "k:h:STALE"},
                            seen_ts=18.0)                                  # status + null flip
    assert store.con.execute("SELECT COUNT(*) FROM stream_evaluations").fetchone()[0] == 4


def test_a_node_can_own_its_tables_idempotently(store):
    ddl = "CREATE TABLE IF NOT EXISTS mine(id INTEGER PRIMARY KEY);"
    store.ensure_ddl(ddl); store.ensure_ddl(ddl)
    store.con.execute("INSERT INTO mine DEFAULT VALUES")
    assert store.con.execute("SELECT COUNT(*) FROM mine").fetchone()[0] == 1


def test_a_failed_sweep_keeps_its_error(store):
    store.sweep(sweep_id="s", started_ts=1.0, finished_ts=2.0, universe="u", n_discovered=0,
                n_watched=0, n_changed=0, n_opportunities=0, status="ERROR",
                error="RuntimeError: boom")
    assert store.con.execute("SELECT status, error FROM sweep_runs").fetchone() == ("ERROR", "RuntimeError: boom")
