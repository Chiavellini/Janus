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
    assert s.evaluations == 1 and s.written == 1


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
    assert sup.record_errors == {("g1", "RuntimeError"): 2}
    assert s.evaluations == 3, "the poller still evaluated; only the record failed"
    out = capsys.readouterr().out
    assert out.count("[record] SF @ PIT RuntimeError") == 1, "said once per cause, not per frame"
    assert sup.stats()["record_errors"] == 2
    monkeypatch.undo()
    cb("K_H", T + 3)          # and it recovers without a reconnect
    assert sup.record_errors == {("g1", "RuntimeError"): 2}


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
