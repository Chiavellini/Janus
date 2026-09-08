#!/usr/bin/env python3
"""The supervisor's socket callback: it records, it sizes, and it never raises into the socket."""
from __future__ import annotations

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
    assert sup.store.con.execute("SELECT COUNT(*) FROM frontiers").fetchone()[0] == 1
    assert s.evaluations == 2 and s.written == 2, "the venues' smallest size (3) and the 100 rung, both written"


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
    # the tick after a stall: the clock window still holds the late stamps; that is aftermath, not a clock fault
    sup.loop_probe_reading(30.0)
    for i in range(25):
        sup.ps.clock.observe(T + 12 + i * 0.1, T + 12 + i * 0.1 - 30.0)
    sup.on_report_tick(now=T + 12)
    assert s.poller.halt == "LOOP_STALLED"
    sup.on_report_tick(now=T + 15)                         # loop prompt now, stamps still off
    assert s.poller.halt == "LOOP_STALLED" and "HALT CLOCK" not in capsys.readouterr().out, "aftermath, not a clock fault"
    sup.ps.clock = type(sup.ps.clock)()
    sup.on_report_tick(now=T + 18)
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
    oid = Opportunity.id_for("g1", 100.0)                       # the 100 rung is the profitable one here (3 stays DISCOVERED)

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


def test_an_unprotected_position_latches_the_live_kill_and_flags(tmp_path: Path, capsys):
    from types import SimpleNamespace
    from kernel.schema import Mode
    from nodes.risk.flags import recent_flags
    from nodes.risk.kill import KillSwitches
    sup, s = _supervisor(tmp_path)
    sup.mode = Mode.LIMITED_LIVE
    sup.kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    sup.limits = SimpleNamespace(protect=SimpleNamespace(protect_kill_on_failure=True))
    ex = SimpleNamespace(execution_id="abcdef0123456789", event_id="pm:atp:1")
    sup.on_unprotected(ex, "UNPROTECTED: 10 unhedged after 7 attempts; no hedge inside the loss cap")
    assert sup.kill.active(live=True) == ["live"]
    assert recent_flags(tmp_path / "t.sqlite", "PROTECT_FAILED")
    out = capsys.readouterr().out
    assert "[PROTECT FAILED] pm:atp:1 abcdef01" in out and "kill/live latched" in out
    # a paper mode never latches the live kill
    sup.kill = KillSwitches(tmp_path / "kill2", enforce_volume=False)
    sup.mode = Mode.PAPER_EXECUTION
    sup.on_unprotected(ex, "UNPROTECTED (paper)")
    assert sup.kill.active(live=True) == []


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
