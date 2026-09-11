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


def test_socket_health_lands_with_the_clock_verdict(store):
    store.socket_health(venue="kalshi", seen_ts=5.0, stats={
        "connected": True, "tickers": 4, "frames": 100, "snapshots": 4, "deltas": 96, "seq_gaps": 0,
        "errors": 0, "last_error": "", "age_s": 0.3, "clock": {"offset_s": -0.07, "healthy": True}})
    store.socket_health(venue="polymarket", seen_ts=5.0, stats={
        "connected": True, "assets": 4, "frames": 50, "snapshots": 6, "changes": 90, "drift": 2,
        "agreement": 0.993, "errors": 0, "last_error": "drift", "age_s": 1.0, "clock": {"offset_s": 12.0, "healthy": False}})
    rows = store.con.execute("SELECT venue, subscriptions, updates, drift, agreement, clock_healthy, last_error "
                             "FROM socket_health ORDER BY venue").fetchall()
    assert rows == [("kalshi", 4, 96, None, None, 1, None), ("polymarket", 4, 90, 2, 0.993, 0, "drift")]


def test_socket_health_gains_loop_lag_on_an_old_table(tmp_path):
    """The column was added after the table shipped; an existing store gets it by ALTER, once."""
    import sqlite3
    db = tmp_path / "old.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE socket_health(seen_ts REAL NOT NULL, venue TEXT NOT NULL, connected INTEGER, subscriptions INTEGER, "
                "frames INTEGER, snapshots INTEGER, updates INTEGER, seq_gaps INTEGER, drift INTEGER, agreement REAL, errors INTEGER, "
                "clock_offset_s REAL, clock_healthy INTEGER, age_s REAL, last_error TEXT)")
    con.commit(); con.close()
    st = TupleStore(db, enforce_volume=False)
    st.socket_health(venue="kalshi", stats={"connected": True, "frames": 1, "clock": {"offset_s": 0.1, "healthy": True}, "loop_lag_s": 2.5}, seen_ts=1.0)
    st.socket_health(venue="kalshi", stats={"connected": True, "frames": 2, "clock": {}}, seen_ts=2.0)
    rows = st.con.execute("SELECT seen_ts, loop_lag_s FROM socket_health ORDER BY seen_ts").fetchall()
    assert rows == [(1.0, 2.5), (2.0, None)]


def test_retain_ages_out_only_the_observation_series_and_leaves_evidence_untouched(store):
    """L72 (2026-09-11): the box's volume filled because nothing aged anything out. Retention
    must delete only rows older than the cutoff in RETENTION_TABLES, and must be structurally
    unable to touch any other table: count every other table before and after."""
    from nodes.store_tuples.store import RETENTION_TABLES
    NOW = 2_000_000.0
    OLD, NEW = NOW - 10 * 86400, NOW - 1 * 86400
    for i in range(30):
        q(store, market_id=f"m{i}", seen_ts=OLD + i)            # 30 old quote rows
    for i in range(5):
        q(store, market_id=f"n{i}", seen_ts=NEW + i)            # 5 new quote rows
    for i in range(20):
        store.evaluation(game_id="g", league="mlb", quantity=1.0, status="PROFITABLE", cost=0.90 + i * 0.01,
                         gross=1.0, fees=0.0, return_locked=0.1, required_ask_sum=None, cents_from_actionable=None,
                         blocked_by=None, triggered_by="k", latency_ms=1.0, seen_ts=OLD + i)
    store.evaluation(game_id="g", league="mlb", quantity=1.0, status="PROFITABLE", cost=0.5, gross=1.0, fees=0.0,
                     return_locked=0.1, required_ask_sum=None, cents_from_actionable=None, blocked_by=None,
                     triggered_by="k", latency_ms=1.0, seen_ts=NEW)
    for i in range(10):
        store.socket_health(venue="kalshi", stats={"connected": True, "frames": i}, seen_ts=OLD + i)
    store.socket_health(venue="kalshi", stats={"connected": True, "frames": 99}, seen_ts=NEW)
    # Evidence stand-ins: tables retain() must never name, populated with OLD timestamps.
    store.ensure_ddl("CREATE TABLE IF NOT EXISTS orders(order_id TEXT PRIMARY KEY, seen_ts REAL);"
                     "CREATE TABLE IF NOT EXISTS venue_fills(fill_id TEXT PRIMARY KEY, seen_ts REAL);"
                     "CREATE TABLE IF NOT EXISTS lane_flags(id INTEGER PRIMARY KEY, seen_ts REAL);")
    for i in range(7):
        store.con.execute("INSERT INTO orders VALUES(?,?)", (f"o{i}", OLD))
        store.con.execute("INSERT INTO venue_fills VALUES(?,?)", (f"f{i}", OLD))
        store.con.execute("INSERT INTO lane_flags(seen_ts) VALUES(?)", (OLD,))
    store.commit()
    names = [r[0] for r in store.con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    retained = {t for t, _ in RETENTION_TABLES}
    before = {n: store.con.execute(f"SELECT count(*) FROM {n}").fetchone()[0] for n in names if n not in retained}

    got = store.retain(max_age_s=7 * 86400, now=NOW, batch=8)
    assert got["quote_history"] == 30 and got["stream_evaluations"] == 20 and got["socket_health"] == 10
    assert got["opportunity_history"] == 0 and got["_more"] == 0
    assert store.con.execute("SELECT count(*) FROM quote_history").fetchone()[0] == 5
    assert store.con.execute("SELECT min(seen_ts) FROM quote_history").fetchone()[0] >= NEW
    assert store.con.execute("SELECT count(*) FROM stream_evaluations").fetchone()[0] == 1
    assert store.con.execute("SELECT count(*) FROM socket_health").fetchone()[0] == 1
    after = {n: store.con.execute(f"SELECT count(*) FROM {n}").fetchone()[0] for n in before}
    assert after == before, "an evidence table changed"
    assert before["orders"] == 7 and before["venue_fills"] == 7 and before["lane_flags"] == 7
    # A second pass finds nothing; a foreign table is refused outright.
    assert store.retain(max_age_s=7 * 86400, now=NOW)["quote_history"] == 0
    with pytest.raises(ValueError, match="not a retention table"):
        store.retain(max_age_s=1.0, now=NOW, tables=(("orders", "seen_ts"),))


def test_retain_stops_at_its_budget_and_says_so(store):
    NOW = 2_000_000.0
    for i in range(50):
        q(store, market_id=f"m{i}", seen_ts=NOW - 30 * 86400 + i)
    store.commit()
    got = store.retain(max_age_s=7 * 86400, now=NOW, batch=10, budget_s=0.0)
    assert got["_more"] == 1 and 0 <= got["quote_history"] <= 10
    got = store.retain(max_age_s=7 * 86400, now=NOW, batch=10, budget_s=5.0)
    assert got["_more"] == 0 and store.con.execute("SELECT count(*) FROM quote_history").fetchone()[0] == 0
