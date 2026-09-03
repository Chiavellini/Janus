#!/usr/bin/env python3
"""The REST backstop: quiet replicas get an outside check; busy ones are left alone."""
from __future__ import annotations

from nodes.book_replica.replica import BookReplica, Fault, ReplicaState
from nodes.stream_polymarket.reconcile import Reconciler, due
from nodes.stream_polymarket.stream import PolymarketStream

T = 1000.0


def stream_with(*assets):
    s = PolymarketStream()
    reps = {}
    for a in assets:
        r = BookReplica("polymarket", a, verification="external", max_unverified_s=30.0,
                        heartbeat_timeout_s=1e9)
        r.snapshot_in([(0.40, 10)], [(0.45, 10)], now=T)
        s.register(a, r)
        reps[a] = r
    return s, reps


def test_only_synced_replicas_past_half_their_budget_are_due():
    s, reps = stream_with("a", "b", "c")
    reps["b"].stream_verified(T + 14)           # busy market: verified by its own traffic
    reps["c"].invalidate(Fault.HASH_MISMATCH)   # resyncing: the socket path owns it
    assert due(s.regs, T + 16) == ["a"]
    assert due(s.regs, T + 10) == []


def test_a_quiet_replica_is_reverified_and_kept_servable():
    s, reps = stream_with("a")
    seen = []
    s.regs["a"][0].on_update = lambda m, t: seen.append((m, t))
    rc = Reconciler(s, lambda aid: ([(0.40, 10)], [(0.45, 10)]), period_s=1.0)
    assert rc.once(now=T + 20, mono=5.0) == ["a"]
    r = reps["a"]
    assert r.check(T + 20, max_age_s=5.0) is None and r.state is ReplicaState.SYNCED
    assert r.snapshot(T + 20).source == "rest" and r.snapshot(T + 20).received_mono == 5.0
    assert rc.stats()["reconciles"] == 1 and rc.rest_drift == 0
    assert seen == [("a", T + 20)], "the poller is told, with the reconcile time"


def test_a_disagreement_adopts_rest_and_reports_drift():
    s, reps = stream_with("a")
    rc = Reconciler(s, lambda aid: ([(0.40, 10)], [(0.46, 10)]))
    rc.once(now=T + 20)
    assert rc.rest_drift == 1 and rc.drifted == ["a"]
    assert reps["a"].snapshot(T + 20).best_ask.price == 0.46, "REST is the truth adopted"


def test_a_failed_fetch_is_counted_and_the_pass_continues():
    s, reps = stream_with("a", "b")
    calls = []
    def fetch(aid):
        calls.append(aid)
        if aid == "a":
            raise RuntimeError("HTTP 503")
        return [(0.40, 10)], [(0.45, 10)]
    rc = Reconciler(s, fetch)
    assert rc.once(now=T + 20) == ["b"]
    assert rc.errors == 1 and "503" in rc.last_error and calls == ["a", "b"]


def test_run_fetches_off_the_loop_and_applies_on_it():
    """The fetch may block in a worker thread; the adoption and the poller callback must not.
    The callback records to sqlite, whose connection belongs to the loop's thread."""
    import asyncio
    import threading

    s, reps = stream_with("a")
    main = threading.get_ident()
    threads = {}
    stop = asyncio.Event()

    def fetch(aid):
        threads["fetch"] = threading.get_ident()
        return [(0.40, 10)], [(0.45, 10)]

    def on_update(m, t):
        threads["apply"] = threading.get_ident()
        stop.set()

    s.regs["a"][0].on_update = on_update
    reps["a"].verified_utc = 0.0                      # due now
    rc = Reconciler(s, fetch, period_s=0.01)

    async def go():
        task = asyncio.create_task(rc.run(stop))
        await asyncio.wait_for(stop.wait(), 5.0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(go())
    assert threads["fetch"] != main, "the network half runs in a worker"
    assert threads["apply"] == main, "the state half runs on the loop"
    assert rc.reconciles == 1
