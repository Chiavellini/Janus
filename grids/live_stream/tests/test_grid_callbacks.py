#!/usr/bin/env python3
"""The supervisor's socket callback: it records, it sizes, and it never raises into the socket."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from grids.live_stream.grid import Supervised, Supervisor
from nodes.game_poller.tests.test_poller import FEES, mlb, sync_all
from nodes.opportunity.opportunity import OpportunityStore
from nodes.store_tuples.store import TupleStore

T = 1000.0


def _supervisor(tmp_path: Path) -> tuple[Supervisor, Supervised]:
    sup = Supervisor(["mlb"])
    sup.store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    sup.opportunities = OpportunityStore(sup.store)
    p = mlb()
    s = Supervised(p, "SF @ PIT", T, ("K_H", "K_A"), ("P_H", "P_A"), fee_params=dict(FEES))
    sup.live["g1"] = s
    return sup, s


def test_a_profitable_evaluation_is_sized_on_its_own_books(tmp_path: Path, capsys):
    """2026-09-03: every PROFITABLE_UNEXECUTED print ended '(capacity failed: TypeError)' because the
    grid called frontier() with a keyword it does not have. The frontier must land."""
    sup, s = _supervisor(tmp_path)
    sync_all(s.poller, kh=0.44, ka=0.99, ph=0.99, pa=0.44)
    sup._on_update("g1")("K_H", T)
    out = capsys.readouterr().out
    assert "PROFITABLE_UNEXECUTED" in out and "N_max=" in out, out
    assert "capacity failed" not in out
    # Two rungs, not one: since the dollar floor moved to $0.10 (2026-09-08) both the venues'
    # smallest size and the 100 rung clear it, and each profitable rung records its frontier.
    assert sup.store.con.execute("SELECT COUNT(*) FROM frontiers").fetchone()[0] == 2
    assert s.evaluations == 2 and s.written == 2, "the venues' smallest size (3) and the 100 rung, both written"


def test_live_book_epoch_dispatches_exactly_one_profit_maximizing_quantity(tmp_path: Path, monkeypatch):
    import time
    from kernel.schema import Mode
    from nodes.risk.breaker import LossBreaker
    from nodes.risk.kill import KillSwitches
    from nodes.risk.ledger import ExposureLedger
    from nodes.risk.limits import load_limits

    sup, s = _supervisor(tmp_path)
    s.poller.quantities = (5.0, 10.0)
    sup.mode = Mode.LIMITED_LIVE
    sup.limits = load_limits()
    sup.ledger = ExposureLedger()
    sup.kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    sup.breaker = LossBreaker(kill=sup.kill)
    sup.caps = {"stake_usd": 12.0, "max_contracts": 10.0, "day_notional_usd": 250.0}
    sup.balance_snapshot = {"kalshi": 100.0, "polymarket": 100.0}
    sup.balance_snapshot_mono = time.monotonic()
    sup.coordinator = object()
    calls = []
    monkeypatch.setattr(sup, "_execute", lambda _s, ev, rec, sizing=None: calls.append((ev, rec, sizing)))
    sync_all(s.poller, kh=0.44, ka=0.99, ph=0.99, pa=0.44)

    sup._on_update("g1")("K_H", T)

    assert len(calls) == 1
    ev, rec, decision = calls[0]
    assert ev.quantity == 10.0 == decision.n_star_feasible == decision.n_max_feasible
    assert rec.net_profit_usd > 0 and decision.selected.profit_usd > 0
    assert decision.fill_model == "BOUNDED_TAKER_V1"
    for replica in s.poller.replicas.values():
        replica.received_mono = (replica.received_mono or 0.0) + 100.0
    sup._on_update("g1")("K_H", T + 1)
    assert len(calls) == 1, "identical decision inputs with new receive stamps are one epoch"


def test_live_selector_runs_even_when_every_legacy_fixed_rung_misses(tmp_path: Path, monkeypatch):
    """An intermediate integer may clear the dollar floor when q_min/5 are too small and 10 has
    crossed a depth/fee step. Fixed-rung profitability must not gate exhaustive live sizing."""
    import time
    from types import SimpleNamespace
    from kernel.schema import Mode
    from nodes.cover.cover import best_cover
    from nodes.risk.breaker import LossBreaker
    from nodes.risk.kill import KillSwitches
    from nodes.risk.ledger import ExposureLedger
    from nodes.risk.limits import load_limits

    sup, s = _supervisor(tmp_path)
    s.poller.quantities = (5.0, 10.0)
    sup.mode, sup.limits, sup.ledger = Mode.LIMITED_LIVE, load_limits(), ExposureLedger()
    sup.kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    sup.breaker = LossBreaker(kill=sup.kill)
    sup.caps = {"stake_usd": 12.0, "max_contracts": 10.0, "day_notional_usd": 250.0}
    sup.balance_snapshot = {"kalshi": 100.0, "polymarket": 100.0}
    sup.balance_snapshot_mono = time.monotonic()
    sup.coordinator = object()
    calls = []
    monkeypatch.setattr(sup, "_execute", lambda _s, ev, rec, sizing=None: calls.append(ev.quantity))

    def intermediate(offers, **kwargs):
        cov = best_cover(offers, 7, now_utc=T, proof=s.poller.proof,
                         required_venues=frozenset({"polymarket", "kalshi"}), leg_count=2)
        selected = SimpleNamespace(quantity=7, cover=cov, profit_usd=.105)
        return SimpleNamespace(selected=selected, n_star_feasible=7, n_max_feasible=7,
                               binding_constraints=("MIN_PROFIT", "CAP_CONTRACTS"),
                               fill_model="UNMEASURED_SIZE_DEPENDENT_MAKER_FILL",
                               audit=lambda: {"n_star_feasible": 7})

    monkeypatch.setattr("grids.live_stream.grid.choose_live_size", intermediate)
    # gross 0.99: the rungs miss on fees and the $0.10 floor, not on edge. (L79 skips the sweep only
    # when the cheapest gross is 1.0 or more, where no whole quantity can lock a profit.)
    sync_all(s.poller, kh=.50, ka=.99, ph=.99, pa=.49)
    sup._on_update("g1")("K_H", T)
    assert calls == [7]


def test_live_hedge_capacity_maps_plan_buy_side_to_replica_side(tmp_path: Path, monkeypatch):
    import time
    from kernel.schema import Mode
    from nodes.risk.ledger import ExposureLedger
    from nodes.risk.limits import load_limits
    from nodes.execute.sizing import choose_live_size

    sup, s = _supervisor(tmp_path)
    sup.mode, sup.limits, sup.ledger = Mode.LIMITED_LIVE, load_limits(), ExposureLedger()
    sup.caps = {"stake_usd": 12.0, "max_contracts": 10.0, "day_notional_usd": 250.0}
    sync_all(s.poller, kh=.44, ka=.99, ph=.99, pa=.44)
    base = s.poller.on_event("stream", "K_H", now=T)[0]
    decision = choose_live_size({o: list(v) for o, v in base.offers.items()}, now_utc=T,
                                proof=s.poller.proof, event_id="g1", league="mlb", caps=sup.caps,
                                limits=sup.limits, ledger=sup.ledger,
                                balances={"kalshi": 100, "polymarket": 100})
    monkeypatch.setattr("grids.live_stream.grid.time.time", lambda: T)
    assert decision.selected is not None
    assert sup._hedge_capacity_ok(s, decision.selected.plan, decision.selected.quantity)


def test_a_record_failure_is_counted_and_never_reaches_the_socket(tmp_path: Path, capsys, monkeypatch):
    """The callback runs inside the venue socket's receive loop. On 2026-09-03 an IllegalTransition
    from the record layer tore both sockets down 5-20 times a minute; the transport's blanket
    handler was the only thing catching it."""
    sup, s = _supervisor(tmp_path)
    sync_all(s.poller, kh=0.50, ka=0.50, ph=0.50, pa=0.50)
    cb = sup._on_update("g1")
    cb("K_H", T)
    assert sup.record_errors == {}

    def boom(*_a, **_k):
        raise RuntimeError("the record layer is wrong, not the socket")

    monkeypatch.setattr(sup, "_record", boom)
    cb("K_H", T + 1)          # must not raise
    cb("K_H", T + 2)
    # two quantities per event (the venues' smallest size and the 100 rung): two failed records per frame
    assert sup.record_errors == {("g1", "RuntimeError"): 4}
    assert s.evaluations == 6, "the poller still evaluated; only the record failed"
    out = capsys.readouterr().out
    assert out.count("[record] SF @ PIT RuntimeError") == 1, "said once per cause, not per frame"
    assert sup.stats()["record_errors"] == 4
    monkeypatch.undo()
    cb("K_H", T + 3)          # and it recovers without a reconnect
    assert sup.record_errors == {("g1", "RuntimeError"): 4}


def test_discovery_is_split_into_a_network_half_and_a_state_half(monkeypatch, tmp_path: Path):
    """Ledger L37 (2026-09-04): the discovery pass ran its HTTP inside the event loop and silenced
    both sockets for 43-107 s every five minutes. The network half must touch nothing the loop
    owns, and the composition must equal the old synchronous discover()."""
    import threading
    from types import SimpleNamespace
    import grids.live_stream.grid as G
    threads = {}

    def fake_discover(leagues, now, live, pre_hours, pc, kc):
        threads["fetch"] = threading.get_ident()
        return SimpleNamespace(games=[], fee_errors={"kalshi": {"mlb": "boom"}})

    monkeypatch.setattr(G, "discover", fake_discover)
    monkeypatch.setattr(G, "co_listed", lambda d, first_seen, now: ({}, {"g": "INCOMPLETE"}))
    monkeypatch.setattr(G, "record_events", lambda store, d, slate, blocked: threads.setdefault("record", threading.get_ident()))
    sup = Supervisor(["mlb"])
    sup.store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    fetched = sup.fetch_discovery()
    assert "record" not in threads, "the network half never touches the store"
    slate = sup.apply_discovery(*fetched)
    assert slate == {} and sup.blocked == {"g": "INCOMPLETE", "fees:kalshi:mlb": "FEE_SCHEDULE: boom"}
    assert sup.wake_state[0] == "DRAIN"
    assert sup.discover() == {}, "the synchronous form is the composition"
    assert sup.fetch_watch() is None and sup.apply_watch(None) == (0, 0)


def test_transient_schedule_failure_keeps_streams_warm_but_suspends_evaluation(monkeypatch, tmp_path: Path):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    import grids.live_stream.grid as G

    sup, live = _supervisor(tmp_path)
    spec = {"league": "mlb", "short_name": "SF @ PIT", "state": "in", "tier": "live",
            "outcomes": {}, "fee_params": FEES, "rules": {}, "settlement": {}}
    sup.last_specs["g1"] = dict(spec)
    live.execution_spec = G._execution_spec(spec)
    d = SimpleNamespace(games=[], schedule_failures={"mlb": "ESPN HTTP 503"},
                        fee_errors={}, per_league={})
    monkeypatch.setattr(G, "co_listed", lambda *_a, **_k: ({}, {}))
    monkeypatch.setattr(G, "record_events", lambda *_a, **_k: None)

    held = sup.apply_discovery(datetime.fromtimestamp(T, timezone.utc), d)
    assert held["g1"]["_discovery_block"].startswith("SCHEDULE_FETCH:")
    sup.reconcile(held)
    before = live.evaluations
    sup._on_update("g1")("K_H", T)
    assert live.evaluations == before and live.discovery_block

    sup.reconcile({"g1": spec})
    assert live.discovery_block is None, "a healthy pass resumes the already-warm actor"


def test_execution_fingerprint_changes_for_fees_tokens_limits_and_rules():
    import grids.live_stream.grid as G
    base = {"league": "mlb", "outcomes": {"home": {"polymarket": "p1", "kalshi": "k1"}},
            "fee_params": FEES, "pm_limits": {"min_order_contracts": 5, "tick": .01},
            "rules": {"polymarket": {"market": {"rules": "v1"}}}}
    original = G._execution_spec(base)
    for changed in (
        {**base, "fee_params": {**FEES, "polymarket": {"fee_rate": .07}}},
        {**base, "outcomes": {"home": {"polymarket": "p2", "kalshi": "k1"}}},
        {**base, "pm_limits": {"min_order_contracts": 10, "tick": .01}},
        {**base, "rules": {"polymarket": {"market": {"rules": "v2"}}}},
    ):
        assert G._execution_spec(changed) != original
    stamped = {**base, "rules": {"retrieved_at": T, **base["rules"]}}
    assert G._execution_spec(stamped) == original, "a retrieval timestamp must not churn every actor"


def test_the_report_tick_names_a_stall_apart_from_a_clock_fault(tmp_path: Path, capsys):
    """Both halt pricing; only one is a clock finding. The loop probe decides which."""
    from nodes.stream_kalshi.stream import KalshiStream
    from nodes.stream_polymarket.stream import PolymarketStream
    sup, s = _supervisor(tmp_path)
    sup.ks, sup.ps = KalshiStream(api_key="k", private_key=None), PolymarketStream()
    sup.on_report_tick(now=T)
    assert s.poller.halt is None and sup.clock_ok()
    for i in range(25):                                      # the venue's stamps 30 s off, loop prompt
        sup.ks.clock.observe(T + i * 0.1, T + i * 0.1 - 30.0)
    sup.on_report_tick(now=T + 3)
    assert s.poller.halt == "CLOCK_UNHEALTHY" and not sup.clock_ok()
    assert "[clock] HALT CLOCK kalshi" in capsys.readouterr().out
    sup.ks.clock = type(sup.ks.clock)()                      # clocks fine, the loop stalled
    sup.loop_probe_reading(12.4)
    sup.on_report_tick(now=T + 6)
    assert s.poller.halt == "LOOP_STALLED" and not sup.clock_ok()
    out = capsys.readouterr().out
    assert "[clock] HALT STALL 12.4s" in out
    row = sup.store.con.execute("SELECT loop_lag_s FROM socket_health ORDER BY seen_ts DESC LIMIT 1").fetchone()
    assert row[0] == 12.4, "the stall is on the record beside the clock"
    assert sup.loop_lag_max_s == 0.0, "the tick resets the probe"
    sup.on_report_tick(now=T + 9)
    assert s.poller.halt is None and sup.clock_ok() and "healthy again" in capsys.readouterr().out
    # A stall's own late stamps are OUR delay wearing the venue's name, so the tick that detects
    # the stall discards both windows (L111). Before that, they aged out over the clock's 60 s
    # window while a 30 s tick gave one tick of grace, and the lane went on refusing to price --
    # measured over 7 days: at 2-3 s of loop lag, 47.6 % of ticks read unhealthy and 48.9 % of
    # those named BOTH venues, which two independent venue clocks do not do.
    sup.loop_probe_reading(30.0)
    for i in range(25):
        sup.ps.clock.observe(T + 12 + i * 0.1, T + 12 + i * 0.1 - 30.0)
    sup.on_report_tick(now=T + 12)
    assert s.poller.halt == "LOOP_STALLED"
    assert "window dropped after a 30.0s stall" in capsys.readouterr().out
    sup.on_report_tick(now=T + 15)                         # loop prompt, and the skew went with it
    assert s.poller.halt is None and sup.clock_ok(), "a prompt loop prices again at the next tick"

    # A GENUINE skew arriving soon after a stall is still labelled aftermath rather than a clock
    # fault, while the dropped window refills -- and it still halts either way.
    sup.loop_probe_reading(30.0)
    sup.on_report_tick(now=T + 18)
    assert s.poller.halt == "LOOP_STALLED"
    for i in range(25):
        sup.ps.clock.observe(T + 21 + i * 0.1, T + 21 + i * 0.1 - 30.0)
    capsys.readouterr()
    sup.on_report_tick(now=T + 21)                         # loop prompt, stamps off, one tick on
    assert s.poller.halt == "LOOP_STALLED", "inside the grace it is aftermath, not a clock finding"
    assert "HALT STALL aftermath" in capsys.readouterr().out, "and it must be able to SAY so"
    sup.ps.clock = type(sup.ps.clock)()
    sup.on_report_tick(now=T + 24)
    assert s.poller.halt is None


def test_apply_watch_records_first_seen_starts_for_the_settlement_collector(tmp_path: Path):
    from nodes.discovery.census import GameEvent
    from nodes.discovery.watchlist import Watchlist
    from nodes.discovery.tests.test_watchlist import FakeSocket
    sup, _ = _supervisor(tmp_path)
    sup.watch, sup.ks, sup.ps = Watchlist(), FakeSocket(), FakeSocket()
    sup.capture_pm_tags = ("tennis",)
    e = GameEvent("polymarket", "tennis", "atp-x-y-2026-09-05", "2026-09-05", T + 3600, ["X", "Y"], [], 1, True, None, None, None, ["tokX"])
    assert sup.apply_watch(([], [("tokX", e.event_id)], [e])) == (1, 0)
    assert sup.watch_rows == 1
    row = sup.store.con.execute("SELECT event_id, start_utc, league_hint FROM watch_events").fetchone()
    assert row == ("atp-x-y-2026-09-05", T + 3600, "atp")
    assert sup.apply_watch(None) == (0, 0)


def test_a_spawn_block_is_said_once_and_written_to_the_event_row(tmp_path: Path, capsys):
    """2026-09-04: LIV @ IPS and KOE @ VFB were co-listed all evening and never spawned; the reason
    (TEMPLATE_UNKNOWN) lived in an in-memory dict, the [slate] line printed a count, and
    events.block_reason stayed null. Now the reason is printed once and persisted, and survives
    the next discovery pass."""
    import json
    from nodes.discovery.discovery import EVENTS_DDL
    sup = Supervisor(["epl"])
    sup.store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    sup.store.ensure_ddl(EVENTS_DDL)
    sup.opportunities = OpportunityStore(sup.store)
    spec = {"league": "epl", "short_name": "LIV @ IPS", "outcomes": {"epl:ips": {"kalshi": "K-IPS", "polymarket": "t-ips"},
                                                                     "epl:liv": {"kalshi": "K-LIV", "polymarket": "t-liv"},
                                                                     "draw": {"kalshi": "K-TIE", "polymarket": "t-draw"}},
            "fee_params": {"kalshi": FEES["kalshi"], "polymarket": FEES["polymarket"]}, "rules": {},
            "settlement": {"result": "BLOCKED", "code": "TEMPLATE_UNKNOWN", "detail": "polymarket rules text matches no reviewed template (template_hash 7580dcecfba14bc3)"}}
    sup.store.con.execute("INSERT INTO events(event_id, league, phase, spec_json, first_seen_ts, last_seen_ts) VALUES('g9','epl','in:co_listed',?,?,?)",
                          (json.dumps(spec), T, T))
    sup.store.con.commit()
    sup.reconcile({"g9": spec})
    sup.reconcile({"g9": spec})
    out = capsys.readouterr().out
    assert out.count("[spawn-blocked] LIV @ IPS (epl) SPAWN:") == 1, out
    assert "TEMPLATE_UNKNOWN" in out and "7580dcecfba14bc3" in out
    assert "g9" not in sup.live and sup.blocked["g9"].startswith("SPAWN:")
    reason = sup.store.con.execute("SELECT block_reason FROM events WHERE event_id='g9'").fetchone()[0]
    assert reason and "TEMPLATE_UNKNOWN" in reason
    assert sup.store.con.execute("SELECT COUNT(*) FROM event_transitions WHERE event_id='g9'").fetchone()[0] == 1


def test_a_stale_arm_refuses_real_orders_before_anything_is_minted(tmp_path: Path, capsys):
    """Until 2026-09-07 the override was read once at start: one that expired, or was rewritten for
    another code tree, stopped nothing already running. check_arm() re-reads it on the report
    tick; while it is stale, _execute refuses at the door (no plan, no balance call, no
    clearance), pricing goes on, and a matching override lifts it without a restart."""
    import json
    from types import SimpleNamespace
    from kernel.schema import Mode
    sup, s = _supervisor(tmp_path)
    sup.mode, sup.code_sha, sup.override_path = Mode.LIMITED_LIVE, "c0de", tmp_path / "arming_override.json"
    sup.limits = SimpleNamespace(sha="11m1")
    calls = []
    sup.coordinator = SimpleNamespace(execute=lambda *a, **k: calls.append(a))
    good = {"operator_statement": "I approve.", "signed_by": "operator", "mode": "LIMITED_LIVE", "runner_sha": "head",
            "code_sha": "c0de", "limits_sha": "11m1", "caps": {"stake_usd": 12.0}, "expires_utc": "2099-01-01T00:00:00Z"}
    sup.override_path.write_text(json.dumps(good))
    assert sup.check_arm() is None and sup.arm_stale is None
    assert "[arm]" not in capsys.readouterr().out, "a matching arm says nothing"
    sup.override_path.write_text(json.dumps({**good, "code_sha": "another-tree"}))
    assert sup.check_arm() and sup.arm_stale and "code tree" in sup.arm_stale
    sup.check_arm()
    assert capsys.readouterr().out.count("[arm] STALE") == 1, "said once per change"
    ev = SimpleNamespace(cover=None, game_id="g1", quantity=100.0, offers={}, evaluated_utc=T, latency_ms=0.0)
    sup._execute(s, ev, SimpleNamespace(net_profit_usd=1.0, locked_return=0.02))     # a plan would raise on cover=None
    out = capsys.readouterr().out
    assert "[risk] refused SF @ PIT: ARM_STALE" in out and "code tree" in out
    assert calls == [] and sup.executions == 0
    sup.override_path.write_text(json.dumps({**good, "expires_utc": "2020-01-01T00:00:00Z"}))
    assert "expired" in sup.check_arm()
    sup.override_path.write_text(json.dumps(good))
    assert sup.check_arm() is None and sup.arm_stale is None
    assert "real orders resume" in capsys.readouterr().out
    sup.mode = Mode.PAPER_EXECUTION
    sup.override_path.unlink()
    assert sup.check_arm() is None, "paper has no arm to go stale"


def test_a_real_execution_leaves_the_socket_loop_one_at_a_time_and_writes_the_store_from_the_loop(tmp_path: Path, capsys):
    """2026-09-07: the machine ran inside the venue's receive callback; every real cover blocked
    frame reading for its round trips, the probe declared a STALL and the gate refused the next
    cover CLOCK_UNHEALTHY. Now: the callback returns at once, a second cover during the flight is
    refused IN_FLIGHT, the machine's store writes run on the loop thread, and the bookkeeping
    (count, backoff after a rejected leg A) lands when the flight ends."""
    import asyncio
    import threading
    import time
    from types import SimpleNamespace
    from nodes.execute.on_loop import OnLoop
    from kernel.schema import Mode as _M
    sup, s = _supervisor(tmp_path)
    sup.mode = _M.LIMITED_LIVE
    sup.caps = {"stake_usd": 1000.0, "max_contracts": 1000.0}
    sup.limits = SimpleNamespace(min_net_profit_usd=0.0, sha="x")
    threads, seen = [], []

    class Venue:
        def balance(self):
            time.sleep(0.05)                                    # a round trip, in the worker
            return SimpleNamespace(available_usd=500.0)
    sup.venues = {"kalshi": Venue(), "polymarket": Venue()}
    sup.ks = sup.ps = SimpleNamespace(connected=True, clock=SimpleNamespace(healthy=True))

    from kernel.schema import OpportunityStatus as S
    from nodes.opportunity.opportunity import Opportunity
    opps = OnLoop(sup.opportunities, nowait={"move"})
    sup.on_loop.append(opps)
    # Since the dollar floor moved to $0.10 (2026-09-08) the smallest rung clears it too -- 3
    # contracts at ~10.5% on ~0.90 is ~$0.29 -- and the smallest size is priced first, so the 3
    # rung is the one dispatched and the 100 rung is refused IN_FLIGHT behind it. At the old $0.50
    # floor this was the other way round.
    oid = Opportunity.id_for("g1", 3.0)

    from nodes.store_tuples.store import TupleStore as _TS
    sup.worker_store = _TS(tmp_path / "t.sqlite", enforce_volume=False, check_same_thread=False)

    def execute(plan, clearance, **k):
        seen.append(threading.get_ident())
        sup.worker_store.con.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()   # the worker's own connection
        threads.append(sup.opportunities.load(oid).status)      # already owned by the loop before dispatch
        opps.move(sup.opportunities.load(oid), S.FAILED_HEDGE, now=T + 5, detail="test")   # queued to the loop
        time.sleep(0.2)
        return SimpleNamespace(state=SimpleNamespace(value="ORDER_REJECTED"), first_filled=0.0, first_avg_price=None,
                               hedge_filled=0.0, hedge_avg_price=None, unhedged=0.0, detail="leg A rejected: test",
                               stages={}, released=False, reservation_id="r")
    sup.coordinator = SimpleNamespace(execute=execute)
    sync_all(s.poller, kh=0.44, ka=0.99, ph=0.99, pa=0.44)

    def _clear(cand, **k):
        return SimpleNamespace(opportunity_id=cand.opportunity_id, reservation=None, max_hedge_submits=1, valid=lambda *_: True)
    import grids.live_stream.grid as G
    old = G.clear
    G.clear = _clear
    try:
        async def main():
            loop_thread = threading.get_ident()
            t0 = time.monotonic()
            sup._on_update("g1")("K_H", T)
            assert time.monotonic() - t0 < 0.2, "the callback did not wait for the machine (0.05 s balances + 0.2 s machine)"
            assert sup.in_flight == "g1" and len(sup.exec_tasks) == 1
            assert sup.opportunities.load(oid).status is S.EXECUTION_PENDING, "owned on the loop at dispatch"
            await asyncio.sleep(0.1)                            # the balances are being fetched in the worker
            sup._on_update("g1")("K_H", T + 0.1)                # a second cover during the flight
            out = capsys.readouterr().out
            assert "IN_FLIGHT g1" in out and sup.executions == 0
            await asyncio.gather(*sup.exec_tasks)
            assert sup.in_flight is None and sup.executions == 1, capsys.readouterr().out
            assert seen and seen[0] != loop_thread, "the machine ran in a worker"
            assert threads == [S.EXECUTION_PENDING], "the record was the machine's before the worker started"
            assert sup.opportunities.load(oid).status is S.FAILED_HEDGE, "the queued move landed on the loop"
            assert sup.backoff.get("g1"), "the rejected leg A set the backoff"
        asyncio.run(main())
    finally:
        G.clear = old


def test_the_guard_pass_feeds_the_breaker_and_holds_the_flight_slot(tmp_path: Path, capsys):
    """2026-09-08: `clear()` was fed fills_today=() so the daily-loss breaker could never latch
    from trading; the guard's report is what it sees now, and a pass never overlaps an execution."""
    import asyncio
    from types import SimpleNamespace
    from kernel.schema import FillState
    from nodes.risk.breaker import RealizedFill
    sup, s = _supervisor(tmp_path)
    fills = (RealizedFill("x", FillState.FILLED, -3.0, "2026-09-08"),)
    rep = SimpleNamespace(findings=["CORRECTED abc12345 ev venue fills: first_filled 0->10"], to_protect=["abc12345"],
                          fills_today=fills, corrected=["abc12345"], orphans=[], mismatches=[])
    seen = {}

    class Guard:
        def fetch(self):
            seen["fetch_in_flight"] = sup.in_flight
            return "snap"

        def apply(self, snap):
            seen["apply_got"] = snap
            return rep
    sup.guard = Guard()
    sup.limits = SimpleNamespace(protect=SimpleNamespace(protect_auto=False))

    async def main():
        await sup.guard_pass()
        assert sup.in_flight is None and sup.fills_today == fills and sup.guard_passes == 1
        assert seen == {"fetch_in_flight": "guard", "apply_got": "snap"}
        sup.in_flight = "g9"                                   # an execution is flying: the guard waits
        await sup.guard_pass()
        assert sup.guard_passes == 1
    asyncio.run(main())
    out = capsys.readouterr().out
    assert "[guard] CORRECTED abc12345" in out and "naked and idle: abc12345 (protect_auto off" in out
    # the breaker feed reaches the gate
    import grids.live_stream.grid as G
    got = {}
    old = G.clear
    G.clear = lambda cand, **k: got.update(k) or SimpleNamespace(code="TEST", detail="stop here")
    try:
        sup.mode = G.Mode.LIMITED_LIVE
        sup.ks = sup.ps = SimpleNamespace(connected=True, clock=SimpleNamespace(healthy=True))
        pre = {}
        sup._clear(s, SimpleNamespace(opportunity_id="o", legs=()), None, pre)
        assert got["fills_today"] == fills
    finally:
        G.clear = old


def test_real_entry_requires_the_authenticated_polymarket_account_stream(tmp_path: Path):
    """Market data alone is insufficient: without account events a delayed fill can go naked."""
    from types import SimpleNamespace
    from kernel.schema import Mode
    sup, _ = _supervisor(tmp_path)
    sup.mode = Mode.LIMITED_LIVE
    sup.ks = sup.ps = SimpleNamespace(connected=True, clock=SimpleNamespace(healthy=True))
    sup.venues = {"polymarket": SimpleNamespace(transport=SimpleNamespace())}
    assert sup._connected() == {"kalshi": True, "polymarket": False}
    user_stream = SimpleNamespace(connected=False)
    sup.venues = {"polymarket": SimpleNamespace(transport=SimpleNamespace(user_stream=user_stream))}
    assert sup._connected() == {"kalshi": True, "polymarket": False}
    user_stream.connected = True
    assert sup._connected() == {"kalshi": True, "polymarket": True}


def test_maker_rest_uses_replica_currentness_not_last_mutation_time(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace
    from kernel.schema import Mode
    from nodes.execute.sizing import choose_live_size
    from nodes.risk.ledger import ExposureLedger, Reservation
    from nodes.risk.limits import load_limits
    sup, s = _supervisor(tmp_path)
    sup.mode, sup.limits = Mode.LIMITED_LIVE, load_limits()
    sup.caps = {"stake_usd": 12.0, "max_contracts": 10.0, "day_notional_usd": 250.0}
    sup.ks = sup.ps = SimpleNamespace(connected=True, clock=SimpleNamespace(healthy=True))
    sup.venues = {"polymarket": SimpleNamespace(
        transport=SimpleNamespace(user_stream=SimpleNamespace(connected=True)))}
    sup.kill = SimpleNamespace(active=lambda **_kw: [])
    sup.breaker = SimpleNamespace(evaluate=lambda *_a, **_kw: None)
    sync_all(s.poller, kh=.44, ka=.99, ph=.99, pa=.44, now=T)
    for replica in s.poller.replicas.values():
        replica.received_mono = 10.0       # ladder has been quiet for a long time
        replica.heartbeat_utc = T + 100.0  # but the sequence-checked socket is current
        replica.verified_utc = T + 100.0
    base = s.poller.on_event("stream", "K_H", now=T + 100.0)[0]
    decision = choose_live_size({o: list(v) for o, v in base.offers.items()}, now_utc=T + 100.0,
                                proof=s.poller.proof, event_id="g1", league="mlb", caps=sup.caps,
                                limits=sup.limits, ledger=ExposureLedger(),
                                balances={"kalshi": 100, "polymarket": 100})
    plan = decision.selected.plan
    reservation = Reservation("r", "g1", "mlb",
                              {plan.first.venue: plan.first.contracts * plan.first.limit_price,
                               plan.hedge.venue: plan.hedge.contracts * plan.hedge.limit_price},
                              plan.opportunity_id, T)
    sup.ledger = ExposureLedger(open={"r": reservation})
    sup.balance_snapshot = {"kalshi": 100, "polymarket": 100}
    sup.balance_snapshot_mono = 500.0
    monkeypatch.setattr("grids.live_stream.grid.time.time", lambda: T + 100.0)
    monkeypatch.setattr("grids.live_stream.grid.time.monotonic", lambda: 500.0)
    clearance = SimpleNamespace(opportunity_id=plan.opportunity_id, maker_rest_deadline_mono=502.0)
    assert sup._maker_rest_refusal(s, plan, clearance, plan.quantity) is None


def test_report_tick_persists_authenticated_account_stream_health(tmp_path: Path):
    from types import SimpleNamespace
    from nodes.stream_kalshi.stream import KalshiStream
    from nodes.stream_polymarket.stream import PolymarketStream
    sup, _ = _supervisor(tmp_path)
    sup.ks, sup.ps = KalshiStream(api_key="k", private_key=None), PolymarketStream()
    user_stream = SimpleNamespace(stats=lambda: {"connected": True, "frames": 7, "errors": 0,
                                                  "last_error": "", "age_s": 1.0})
    sup.venues = {"polymarket": SimpleNamespace(transport=SimpleNamespace(user_stream=user_stream))}
    sup.on_report_tick(now=T)
    row = sup.store.con.execute(
        "SELECT connected, frames, errors FROM socket_health WHERE venue='polymarket_user'").fetchone()
    assert row == (1, 7, 0)


def test_a_recent_guard_balance_snapshot_removes_the_entry_round_trips(tmp_path: Path):
    """Paper filled at the decision instant; live used to spend 300-400 ms asking both balances
    after the decision. The guard already confirms them every 30 s, so the hot path reuses that
    fresh snapshot and falls back to the venues only when it is stale."""
    import time
    from types import SimpleNamespace
    sup, _ = _supervisor(tmp_path)
    calls = []

    class Venue:
        def __init__(self, name): self.name = name
        def balance(self):
            calls.append(self.name)
            return SimpleNamespace(available_usd=100.0)

    sup.venues = {v: Venue(v) for v in ("kalshi", "polymarket")}
    sup.balance_snapshot = {"kalshi": 90.0, "polymarket": 80.0}
    sup.balance_snapshot_mono = time.monotonic()
    pre = {}
    assert sup._balances(pre) == sup.balance_snapshot and calls == []
    assert pre["balances_ms"] < 10 and pre["balance_cache_age_ms"] < 100

    sup.balance_snapshot_mono = time.monotonic() - sup.balance_snapshot_ttl_s - 1
    pre = {}
    assert sup._balances(pre) == {"kalshi": 100.0, "polymarket": 100.0}
    assert calls == ["kalshi", "polymarket"] and pre["balance_cache_age_ms"] == 0.0


def test_off_loop_entry_does_not_queue_a_fresh_balance_snapshot_in_the_worker(tmp_path: Path, monkeypatch):
    """The first F9 flight had balances_ms=0 but waited ~760 ms for the zero-work to_thread
    future to re-enter a busy socket loop. A fresh snapshot must be consumed before any yield."""
    import asyncio
    import time
    from types import SimpleNamespace
    sup, s = _supervisor(tmp_path)
    sup.balance_snapshot = {"kalshi": 90.0, "polymarket": 80.0}
    sup.balance_snapshot_mono = time.monotonic()
    seen = {}
    sup._clear = lambda _s, _c, balances, pre: seen.update(balances=balances, pre=dict(pre)) or None

    async def forbidden(*_a, **_k):
        raise AssertionError("a fresh balance snapshot must not enter asyncio.to_thread")

    monkeypatch.setattr(asyncio, "to_thread", forbidden)

    async def main():
        await sup._execute_off_loop(s, SimpleNamespace(game_id="g1"), None, object(), {}, {}, time.monotonic())

    asyncio.run(main())
    assert seen["balances"] == sup.balance_snapshot
    assert seen["pre"]["balances_ms"] < 10


def test_an_unprotected_position_latches_the_live_kill_and_flags(tmp_path: Path, capsys):
    from types import SimpleNamespace
    from kernel.schema import Mode
    from nodes.risk.flags import recent_flags
    from nodes.risk.kill import KillSwitches
    sup, s = _supervisor(tmp_path)
    sup.mode = Mode.LIMITED_LIVE
    sup.kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    sup.limits = SimpleNamespace(protect=SimpleNamespace(protect_kill_on_failure=True, protect_auto=True,
                                                         protect_retry_s=3.0, protect_fast_window_s=60.0))
    ex = SimpleNamespace(execution_id="abcdef0123456789", event_id="pm:atp:1")
    import time as _t
    t0 = _t.monotonic()
    sup.on_unprotected(ex, "UNPROTECTED: 10 unhedged after 7 attempts; no hedge inside the loss cap")
    assert sup.kill.active(live=True) == ["live"]
    # L76: the fast retry is registered: due in ~3 s, for ~60 s
    due, until = sup.reprotect_fast["abcdef0123456789"]
    assert 2.5 < due - t0 < 3.6 and 59 < until - t0 < 61
    assert recent_flags(tmp_path / "t.sqlite", "PROTECT_FAILED")
    out = capsys.readouterr().out
    assert "[PROTECT FAILED] pm:atp:1 abcdef01" in out and "kill/live latched" in out
    # a paper mode never latches the live kill
    sup.kill = KillSwitches(tmp_path / "kill2", enforce_volume=False)
    sup.mode = Mode.PAPER_EXECUTION
    sup.on_unprotected(ex, "UNPROTECTED (paper)")
    assert sup.kill.active(live=True) == []


def test_the_grid_raises_every_flag_through_one_method():
    """`raise_flag` must appear in grid.py exactly once: inside `Supervisor.flag`.

    The 3,373-of-3,373 silent failure was not a typo, it was a CHOICE offered at every call site --
    `self.store` (the loop's connection) or `self.worker_store` (the worker's) -- with the wrong
    answer swallowed by a blind `except`. Four sites chose, one of them ran in the worker, and the
    watchdog lost the alarm for six days. So no site chooses any more. This test is what stops a
    fifth call site reintroducing the question.
    """
    src = (Path(__file__).resolve().parents[1] / "grid.py").read_text()
    calls = [ln.strip() for ln in src.splitlines() if "raise_flag(" in ln and not ln.strip().startswith("#")]
    assert calls == ["raise_flag(store, name, detail)"], calls
    assert "def flag(self, name: str, detail: str" in src


def test_an_unprotected_position_writes_its_flag_from_the_worker_thread(tmp_path: Path):
    """The flag must be written on the connection the calling thread owns.

    `on_unprotected` only ever runs in the worker (`asyncio.to_thread`, from `_execute_off_loop` and
    `_protect_off_loop`), while `sup.store` is the loop's connection, opened check_same_thread=True.
    Every write therefore raised ProgrammingError into a swallowing `except` -- 3,373 of 3,373 real
    protect latches between 2026-09-08 and 2026-09-14 carried no flag, so the watchdog's
    PROTECT_FAILED alarm could never fire beside the kill it belongs to. The test above drives
    `on_unprotected` on its OWN thread, which is exactly why it passed throughout.
    """
    import asyncio
    from types import SimpleNamespace
    from kernel.schema import Mode
    from nodes.risk.flags import recent_flags
    from nodes.risk.kill import KillSwitches
    sup, _s = _supervisor(tmp_path)
    sup.mode = Mode.LIMITED_LIVE
    sup.kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    # As grid.py:1591 builds it for the worker.
    sup.worker_store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False,
                                  check_same_thread=False, isolation_level="IMMEDIATE")
    sup.limits = SimpleNamespace(protect=SimpleNamespace(protect_kill_on_failure=True,
                                                         protect_auto=False, protect_retry_s=0.0,
                                                         protect_fast_window_s=0.0))
    ex = SimpleNamespace(execution_id="fedcba9876543210", event_id="pm:atp:2", protect={})

    async def main():
        await asyncio.to_thread(sup.on_unprotected, ex,
                                "UNPROTECTED: 3 unhedged; no hedge inside the loss cap")

    asyncio.run(main())
    assert recent_flags(tmp_path / "t.sqlite", "PROTECT_FAILED"), "the kill latched with no flag beside it"
    assert "protect_flag_error" not in ex.protect, ex.protect
    assert sup.kill.active(live=True) == ["live"]


def test_the_guard_s_hand_over_re_runs_the_layer_from_the_row_when_protect_auto_is_on(tmp_path: Path, capsys):
    """R5 (2026-09-08): a naked execution the guard hands over is loaded from its row with its plan,
    cleared through clear_protect on the loop and protected in the worker; a released end state
    releases its reservation."""
    import asyncio
    from types import SimpleNamespace
    from kernel.schema import ExecutionState as X, Mode
    from nodes.execute.plan import LegPlan, Plan
    from nodes.execute.records import Execution, ExecutionRecords
    from nodes.risk.kill import KillSwitches
    from nodes.risk.limits import load_limits
    sup, s = _supervisor(tmp_path)
    sup.mode = Mode.LIMITED_LIVE
    sup.kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    lim = load_limits()
    from dataclasses import replace
    sup.limits = replace(lim, protect=replace(lim.protect, protect_auto=True, unwind_enabled=True))
    records = ExecutionRecords(sup.store)
    first = LegPlan("polymarket", "tok", "tok", "buy_yes", 0.58, 10.0, "ioc", vwap=0.57)
    hedge = LegPlan("kalshi", "K-GEA", "K-GEA", "buy_yes", 0.31, 10.0, "ioc", vwap=0.31)
    plan = Plan("g1:moneyline:v1:10", "g1", "mlb", 10.0, first, hedge, 0.9901, 0.0272)
    ex = Execution("naked001", plan.opportunity_id, "g1", "mlb", "LIMITED_LIVE", 10.0, T, first_filled=10.175, first_avg_price=0.57,
                   state=X.UNKNOWN_PROVIDER_STATE, reservation_id="r-1")
    records.start(ex, plan={"first": first.__dict__, "hedge": hedge.__dict__, "max_cost": plan.max_cost_per_contract, "fee": plan.fee_per_contract}, books={})
    records.sync(ex, now=T)
    ran = {}

    def protect_existing(ex2, plan2, c):
        ran["ex"], ran["plan"], ran["c"] = ex2, plan2, c
        ex2.state, ex2.released, ex2.first_unwound, ex2.detail = X.UNWOUND, True, 10.175, "UNWOUND (test)"
        return ex2
    released = []
    sup.coordinator = SimpleNamespace(records=records, protect_existing=protect_existing)
    sup.ledger = SimpleNamespace(release=lambda rid, **k: released.append(rid) or True)
    sup.guard = SimpleNamespace(fetch=lambda: "snap", apply=lambda snap: SimpleNamespace(
        findings=[], to_protect=["naked001"], fills_today=(), corrected=[], orphans=[], mismatches=[]))

    async def main():
        await sup.guard_pass()
    asyncio.run(main())
    assert ran["ex"].execution_id == "naked001" and ran["plan"] == plan and ran["c"].used and not ran["c"].valid()
    assert released == ["r-1"] and sup.in_flight is None and sup.executions == 1 and sup.reprotect_queue == []
    out = capsys.readouterr().out
    assert "[protect] re-run naked001" in out and "UNWOUND" in out


def test_the_slate_tier_sets_and_moves_the_poller_s_window(tmp_path: Path):
    """2026-09-08: a pre-match poller prices every 5 s, a game starting soon every second, a game in
    play on every frame; the window follows the tier on every discovery pass."""
    sup, s = _supervisor(tmp_path)
    assert s.poller.min_eval_interval_s == 0.0, "the test harness spawns with no window at all"
    from nodes.game_poller.poller import eval_interval_for
    slate = {"g1": {"tier": "newborn"}}
    for gid, spec in slate.items():
        sup.live[gid].poller.min_eval_interval_s = eval_interval_for(spec.get("tier"), default=0.2)
    assert s.poller.min_eval_interval_s == 5.0


def test_the_report_tick_stops_the_lane_under_the_disk_floor(tmp_path: Path):
    """L72: the lane must stop between records when the data volume is under the floor, with
    DiskPressure (main() maps it to exit 75), not die inside a commit."""
    from collections import namedtuple
    import pytest
    from grids.live_stream.grid import DiskPressure
    U = namedtuple("usage", "total used free")
    sup, s = _supervisor(tmp_path)
    sup.db = tmp_path / "t.sqlite"
    sup.disk_floor_bytes = 2 * 2 ** 30
    sup.disk_usage = lambda p: U(50 * 2 ** 30, 40 * 2 ** 30, 10 * 2 ** 30)
    sup.on_report_tick(now=T)                                    # room: ticks as before
    sup.disk_usage = lambda p: U(50 * 2 ** 30, 49 * 2 ** 30, 2 ** 30)
    with pytest.raises(DiskPressure, match="DISK_PRESSURE 1.00 GiB free"):
        sup.on_report_tick(now=T)

    def unreadable(p):
        raise OSError("gone")
    sup.disk_usage = unreadable
    sup.on_report_tick(now=T)                                    # unreadable is not a verdict


def test_retain_once_ages_the_store_and_the_frame_days(tmp_path: Path):
    """L72: one pass, on its own connection, deletes old observation rows and old frame days."""
    from nodes.capture.capture import FrameWriter
    sup, s = _supervisor(tmp_path)
    sup.db = tmp_path / "t.sqlite"
    sup.enforce_volume = False
    sup.retain_days = 7
    NOW = T + 30 * 86400
    for i in range(12):
        sup.store.quote(venue="k", market_id=f"m{i}", best_bid=0.4, best_ask=0.45, bid_depth=1.0, ask_depth=1.0,
                        n_bid_levels=1, n_ask_levels=1, two_sided=True, seen_ts=NOW - 20 * 86400 + i)
    sup.store.quote(venue="k", market_id="fresh", best_bid=0.4, best_ask=0.45, bid_depth=1.0, ask_depth=1.0,
                    n_bid_levels=1, n_ask_levels=1, two_sided=True, seen_ts=NOW - 60)
    sup.store.commit()

    class Sock:
        capture = None
    sup.ks, sup.ps = Sock(), Sock()
    sup.ks.capture = FrameWriter("kalshi", tmp_path / "frames", enforce_volume=False)
    sup.ks.capture.write("old", received_utc=NOW - 20 * 86400)
    sup.ks.capture.write("new", received_utc=NOW)
    sup.ks.capture.close()
    got = sup.retain_once(now=NOW)
    assert got["quote_history"] == 12 and got["_more"] == 0
    assert len(got["frames"]) == 1 and got["frames"][0].startswith("kalshi:")
    assert sup.store.con.execute("SELECT count(*) FROM quote_history").fetchone()[0] == 1
    assert len(list((tmp_path / "frames" / "kalshi").iterdir())) == 1


def test_the_fast_reprotect_tick_retries_a_naked_position_every_few_seconds_then_hands_back_to_the_guard(tmp_path: Path):
    """L76 (2026-09-12): VARILLA V WILD hedged at +39 s because rounds two and three waited for the
    30 s guard pass. A naked execution is re-run from the loop every protect_retry_s inside the
    fast window; a run that leaves it hedged drops it; the window's end drops it too."""
    import asyncio
    from types import SimpleNamespace
    from kernel.schema import ExecutionState as X
    sup, s = _supervisor(tmp_path)
    sup.limits = SimpleNamespace(protect=SimpleNamespace(protect_auto=True, protect_retry_s=3.0,
                                                         protect_fast_window_s=60.0, protect_dust_contracts=1.0))
    calls = []
    outcomes = {"e1": [X.HEDGE_SLIPPAGE_EXCEEDED, X.HEDGE_SLIPPAGE_EXCEEDED, X.HEDGED]}

    async def fake_protect(exid):
        calls.append(exid)
        st = outcomes[exid].pop(0)
        return SimpleNamespace(state=st, released=False, unhedged=0.0 if st is X.HEDGED else 25.0)
    sup._protect_off_loop = fake_protect
    T0 = 1000.0
    sup.reprotect_fast = {"e1": (T0 + 3.0, T0 + 60.0)}
    assert sup.fast_reprotect_due(T0 + 1.0) == []                          # not due yet
    assert sup.fast_reprotect_due(T0 + 3.0) == ["e1"]

    async def main():
        import time as _t
        real = _t.monotonic
        # first tick: still naked -> rescheduled ~3 s later
        _t.monotonic = lambda: T0 + 3.0
        try:
            await sup.fast_reprotect_tick()
            assert calls == ["e1"] and 5.9 < sup.reprotect_fast["e1"][0] - T0 < 6.1
            _t.monotonic = lambda: T0 + 4.0
            await sup.fast_reprotect_tick()                                  # not due: no call
            assert calls == ["e1"]
            _t.monotonic = lambda: T0 + 6.0
            await sup.fast_reprotect_tick()                                  # second run, still naked
            assert calls == ["e1", "e1"]
            _t.monotonic = lambda: T0 + 9.0
            await sup.fast_reprotect_tick()                                  # hedged: dropped
            assert calls == ["e1"] * 3 and "e1" not in sup.reprotect_fast
            # the window's end drops an entry without a run
            sup.reprotect_fast = {"e2": (T0 + 3.0, T0 + 60.0)}
            _t.monotonic = lambda: T0 + 61.0
            await sup.fast_reprotect_tick()
            assert calls == ["e1"] * 3 and sup.reprotect_fast == {}
            # a flight in progress defers the tick
            sup.reprotect_fast = {"e3": (T0 + 3.0, T0 + 60.0)}
            sup.in_flight = "guard"
            _t.monotonic = lambda: T0 + 5.0
            await sup.fast_reprotect_tick()
            assert calls == ["e1"] * 3 and "e3" in sup.reprotect_fast
        finally:
            _t.monotonic = real
    asyncio.run(main())


def test_polymarket_token_metadata_is_warmed_once_and_never_blocks(tmp_path: Path):
    """L102 (2026-09-14): `create_market_order` resolves per-token metadata BEFORE it signs, which on
    an unseen token is two blocking GETs. Sports tokens are new every game, so leg A measured 559.6 ms
    p50 on the FIRST order for a token against 205.7 ms on a repeat, with 56 % of orders being firsts.
    Warming at discovery moves that off the order path entirely."""
    from types import SimpleNamespace
    sup, _ = _supervisor(tmp_path)
    calls = []

    class Client:
        def get_fee_exponent(self, token):
            calls.append(token)
            if token == "boom":
                raise RuntimeError("the venue said no")
            return 0.0

    sup.venues = {"polymarket": SimpleNamespace(transport=SimpleNamespace(_c=Client()))}
    sup.live = {"g1": SimpleNamespace(pm_assets=("t1", "t2")),
                "g2": SimpleNamespace(pm_assets=("t2", "boom"))}
    out = sup.warm_pm_metadata(spacing_s=0.0)
    assert sorted(calls) == ["boom", "t1", "t2"], "one call per DISTINCT token, deduped across games"
    assert out["warmed"] == 2 and out["errors"] == 1

    calls.clear()
    sup.warm_pm_metadata(spacing_s=0.0)
    assert calls == ["boom"], "a warm token costs no HTTP; a failed one is simply retried"

    # a token that rotates off the slate is forgotten rather than accumulating forever
    sup.live = {"g1": SimpleNamespace(pm_assets=("t1",))}
    calls.clear()
    sup.warm_pm_metadata(spacing_s=0.0)
    assert calls == [] and sup._pm_warmed == {"t1"}

    # and a burst is bounded, so the backlog drains across discovery passes instead of at once
    sup.live = {"g": SimpleNamespace(pm_assets=tuple(f"n{i}" for i in range(30)))}
    calls.clear()
    out3 = sup.warm_pm_metadata(budget=5, spacing_s=0.0)
    assert out3["warmed"] == 5 and len(calls) == 5 and out3["pending"] == 25


def test_warming_no_ops_without_a_transport_and_never_raises(tmp_path: Path):
    """PAPER and SHADOW hold no Polymarket transport, and a warm-up failure must leave the cache as
    cold as it already is -- never a blocked or failed trade."""
    from types import SimpleNamespace
    sup, _ = _supervisor(tmp_path)
    sup.live = {"g": SimpleNamespace(pm_assets=("t1",))}
    sup.venues = {"polymarket": SimpleNamespace(transport=None)}
    assert sup.warm_pm_metadata() == {}
    sup.venues = {}
    assert sup.warm_pm_metadata() == {}


def test_a_repeated_protect_failure_does_not_extend_its_own_retry_window(tmp_path: Path):
    """L100 (2026-09-13): the window was re-armed on EVERY failure, so `until` moved forward
    `protect_fast_window_s` each time and never expired. Execution 77013052 held a 1.5625-share
    residual that protect.py's quantity cap can never hedge without new authority; it re-ran 2,840
    times over two hours and wrote 2,836 of the 5,322 rows in execution_transitions -- 53 % of the
    table -- for a verdict that could not change. The window belongs to the naked POSITION, not to
    the latest failed attempt."""
    from types import SimpleNamespace
    from kernel.schema import Mode
    from nodes.risk.kill import KillSwitches
    sup, s = _supervisor(tmp_path)
    sup.mode = Mode.PAPER_EXECUTION
    sup.kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    sup.limits = SimpleNamespace(protect=SimpleNamespace(protect_kill_on_failure=False, protect_auto=True,
                                                         protect_retry_s=3.0, protect_fast_window_s=60.0))
    ex = SimpleNamespace(execution_id="dead0000beef1111", event_id="espn:nfl:401872928")
    text = "UNPROTECTED: 1.5625 unhedged after 0 attempts; hedged in part"
    import time as _t
    real = _t.monotonic
    try:
        _t.monotonic = lambda: 1000.0
        sup.on_unprotected(ex, text)
        until = sup.reprotect_fast[ex.execution_id][1]
        assert until == 1060.0, "armed once, for one window"
        for t in (1003.0, 1006.0, 1030.0, 1059.0):
            _t.monotonic = lambda t=t: t
            sup.on_unprotected(ex, text)
            assert sup.reprotect_fast[ex.execution_id][1] == until, \
                "a repeated failure must not push the window's end forward"
            assert sup.reprotect_fast[ex.execution_id][0] == t + 3.0, \
                "the next attempt is still rescheduled inside the window"
        # so the window expires and the guard's own 30 s cadence takes over
        _t.monotonic = lambda: 1061.0
        assert sup.fast_reprotect_due() == [] and sup.reprotect_fast == {}
    finally:
        _t.monotonic = real


def _live_sized(tmp_path, monkeypatch, caps=None):
    import time
    from kernel.schema import Mode
    from nodes.risk.breaker import LossBreaker
    from nodes.risk.kill import KillSwitches
    from nodes.risk.ledger import ExposureLedger
    from nodes.risk.limits import load_limits
    sup, s = _supervisor(tmp_path)
    s.poller.quantities = (5.0, 10.0)
    sup.mode, sup.limits, sup.ledger = Mode.LIMITED_LIVE, load_limits(), ExposureLedger()
    sup.kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    sup.breaker = LossBreaker(kill=sup.kill)
    sup.caps = caps or {"stake_usd": 30.0, "max_contracts": 25.0, "day_notional_usd": 500.0}
    sup.balance_snapshot = {"kalshi": 100.0, "polymarket": 100.0}
    sup.balance_snapshot_mono = time.monotonic()
    sup.coordinator = object()
    calls = []
    monkeypatch.setattr(sup, "_execute", lambda _s, ev, rec, sizing=None: calls.append((ev, rec, sizing)))
    return sup, s, calls


def test_an_epoch_with_no_edge_is_not_sized_and_one_with_edge_is(tmp_path: Path, monkeypatch):
    """L79 (L78 profile, 2026-09-12): the q = 1..cap sweep was 55 % of the loop on epochs that could
    select nothing. No edge (gross at or above 1): the sweep is skipped and counted; an edge: it
    runs and dispatches exactly as before."""
    sup, s, calls = _live_sized(tmp_path, monkeypatch)
    sized = []
    real = sup._execute_sized
    monkeypatch.setattr(sup, "_execute_sized", lambda su, ev: (sized.append(1), real(su, ev)))
    sync_all(s.poller, kh=0.60, ka=0.60, ph=0.60, pa=0.60)     # gross 1.2: NO_EDGE at every size
    sup._on_update("g1")("K_H", T)
    assert sized == [] and s.sizing_skipped == 1 and calls == []
    sync_all(s.poller, kh=0.44, ka=0.99, ph=0.99, pa=0.44)     # the edge the first callback test dispatches on
    sup._on_update("g1")("K_H", T + 1)
    assert sized == [1] and calls and s.sizing_skipped == 1 and s.last_sizing_executable is True


def test_the_exit_from_an_executable_epoch_is_still_sized_once_so_l74_records_it(tmp_path: Path, monkeypatch):
    sup, s, calls = _live_sized(tmp_path, monkeypatch)
    sync_all(s.poller, kh=0.44, ka=0.99, ph=0.99, pa=0.44)
    sup._on_update("g1")("K_H", T)
    assert s.last_sizing_executable is True and len(calls) == 1
    n0 = sup.store.con.execute("SELECT count(*) FROM sizing_decisions").fetchone()[0]
    sync_all(s.poller, kh=0.60, ka=0.60, ph=0.60, pa=0.60)     # edge gone
    sup._on_update("g1")("K_H", T + 1)
    assert s.last_sizing_executable is False and s.sizing_skipped == 0, "sized once more: the exit is recorded (L74)"
    assert sup.store.con.execute("SELECT count(*) FROM sizing_decisions").fetchone()[0] == n0 + 1
    sup._on_update("g1")("K_H", T + 2)
    assert s.sizing_skipped == 1 and sup.store.con.execute("SELECT count(*) FROM sizing_decisions").fetchone()[0] == n0 + 1


def test_the_frontier_report_runs_at_most_once_per_period_per_game(tmp_path: Path, monkeypatch, capsys):
    import grids.live_stream.grid as g
    sup, s = _supervisor(tmp_path)
    s.poller.quantities = (5.0,)
    n = []
    from types import SimpleNamespace
    def fake_frontier(*a, **k):
        n.append(1)
        return SimpleNamespace(actionable=False)
    monkeypatch.setattr(g, "frontier", fake_frontier)
    sync_all(s.poller, kh=0.44, ka=0.99, ph=0.99, pa=0.44)
    sup._on_update("g1")("K_H", T)
    sup._on_update("g1")("K_H", T + 1)
    sup._on_update("g1")("K_H", T + g.FRONTIER_PERIOD_S + 1)
    assert n == [1, 1], "solved at T and at T+5, not at T+1 (one rung per epoch here)"


def test_refusals_are_counted_per_tick_not_rowed_per_refusal(tmp_path: Path):
    """L113: both refusal channels used to end at `print()`, so the largest attrition in the funnel
    was readable only by grepping journald.

    They are COUNTS, and that is not a preference. Both fire on a hot path at roughly 200 book
    events a second, and a row apiece is exactly what `sizing_decisions` did: 24.7 of 27.4 GB and
    ~1.95 M rows a day, which L74 had to gate away and which helped fill the disk on 2026-09-11,
    killing the lane inside a commit. One row per (channel, code, league) per report tick.
    """
    from nodes.stream_kalshi.stream import KalshiStream
    from nodes.stream_polymarket.stream import PolymarketStream
    sup, _s = _supervisor(tmp_path)
    sup.ks, sup.ps = KalshiStream(api_key="k", private_key=None), PolymarketStream()

    # 10,000 refusals across a handful of distinct (channel, code, league) keys.
    for i in range(10_000):
        sup.refuse("risk", ["IN_FLIGHT", "CLOCK_UNHEALTHY", "KILL_SWITCH"][i % 3], "mlb")
        sup.refuse("size", ["MIN_PROFIT", "VENUE_WIRE_MIN"][i % 2], "itf")
    assert len(sup.refusals) == 5, sup.refusals

    sup.on_report_tick(now=T)
    rows = sup.store.con.execute(
        "SELECT channel, code, league, n FROM refusal_counts ORDER BY channel, code").fetchall()
    assert len(rows) == 5, f"{len(rows)} rows for 20,000 refusals"
    assert sum(r[3] for r in rows) == 20_000
    got = {(ch, code, lg): n for ch, code, lg, n in rows}
    assert got[("risk", "IN_FLIGHT", "mlb")] > 3_000
    assert got[("size", "MIN_PROFIT", "itf")] == 5_000, "the two channels are counted apart"
    assert sup.refusals == {}, "the accumulator resets, or the next tick double-counts"

    # A tick with nothing refused writes nothing at all.
    sup.on_report_tick(now=T + 60)
    assert sup.store.con.execute("SELECT COUNT(*) FROM refusal_counts").fetchone()[0] == 5


def test_a_failed_refusal_write_never_breaks_the_report_tick(tmp_path: Path, capsys):
    """Telemetry is not allowed to take the lane down with it."""
    from nodes.stream_kalshi.stream import KalshiStream
    from nodes.stream_polymarket.stream import PolymarketStream
    sup, _s = _supervisor(tmp_path)
    sup.ks, sup.ps = KalshiStream(api_key="k", private_key=None), PolymarketStream()
    sup.refuse("risk", "IN_FLIGHT", "mlb")

    def boom(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")
    sup.store.refusal_counts = boom
    sup.on_report_tick(now=T)
    assert "refusal counts not written" in capsys.readouterr().out
    assert sup.refusals == {}, "a failed flush still clears, or the accumulator grows without bound"


def test_a_hedged_execution_tells_the_ledger_the_event_is_free(tmp_path: Path, capsys):
    """L114, and the reason this test exists at all.

    The first version of this branch referred to `X.HEDGED` in a module where `X` is not imported.
    Every test passed, because nothing drove the HEDGED path -- exactly the shape of L104, where a
    swallowed failure on an unexercised branch went unnoticed for six days. So the branch is driven
    here, with a real ledger, and the assertion is on the ledger's state rather than on a log line.
    """
    from types import SimpleNamespace
    from kernel.schema import Mode
    from nodes.risk.ledger import ExposureLedger
    from nodes.risk.limits import load_limits

    sup, s_ = _supervisor(tmp_path)
    sup.mode = Mode.LIMITED_LIVE
    sup.ledger = ExposureLedger(store=sup.store)
    res = sup.ledger.reserve(event_id="espn:mlb:1", league="mlb",
                             per_venue_usd={"kalshi": 5.0, "polymarket": 5.0}, limits=load_limits())
    assert sup.ledger.has_event("espn:mlb:1")

    ex = SimpleNamespace(state=SimpleNamespace(value="HEDGED"), released=False,
                         reservation_id=res.reservation_id, execution_id="abcdef01" * 4,
                         event_id="espn:mlb:1", first_filled=10, first_avg_price=0.45,
                         hedge_filled=10, hedge_avg_price=0.5, unhedged=0, detail="hedged",
                         stages={}, protect={})
    sup._after_execution(s_, SimpleNamespace(game_id="g1", quantity=10.0), ex)

    assert not sup.ledger.has_event("espn:mlb:1"), "the event is enterable again"
    assert sup.ledger.event_usd("espn:mlb:1") == 10.0, "and the capital is still committed"
    assert "free to enter again" in capsys.readouterr().out

