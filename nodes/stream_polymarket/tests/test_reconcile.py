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


def test_a_reconciled_book_is_priced_at_its_real_age_not_at_zero():
    """L101 (2026-09-14): `fetch_due` fetches SEQUENTIALLY in a worker and the whole batch is applied
    afterwards, so the first asset's book can be seconds old by the time it prices. Passing its FETCH
    stamp to the poller as `now` made `now - as_of()` identically 0.0, so `max_rest_book_age_s` (3.0 s)
    could never fire on this path -- while Polymarket-triggered evaluations measured p90 3,543 ms and
    max 8,249 ms, on 10.7 % of all recorded evaluations, every one reporting an age of zero.

    The replica still records WHEN THE BOOK WAS TRUE; only the clock the poller prices against moves."""
    s, reps = stream_with("a")
    seen = []
    s.regs["a"][0].on_update = lambda m, t: seen.append((m, t))
    rc = Reconciler(s, lambda aid: ([(0.40, 10)], [(0.45, 10)]), period_s=1.0)
    books = rc.fetch_due(rc.prepare(T + 20), now=T + 20, mono=5.0)   # fetched at T+20 ...
    rc.apply(books, now=T + 26)                                      # ... applied six seconds later
    assert seen == [("a", T + 26)], "the poller is told the time it is pricing AT, not the fetch stamp"
    r = reps["a"]
    assert r.updated_utc == T + 20 and r.verified_utc == T + 20, "the replica keeps when it was true"
    assert r.check(T + 26, max_age_s=3.0) is not None, "a six-second-old REST book must read as stale"
    assert r.check(T + 26, max_age_s=10.0) is None, "and fresh against a bound that allows it"
    assert r.snapshot(T + 26, max_age_s=3.0) is None, "and it is not servable at the lane's own bound"
    assert r.snapshot(T + 26, max_age_s=10.0).fetched_utc == T + 20


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


def test_a_ws_update_while_rest_is_in_flight_wins_over_the_old_response():
    s, reps = stream_with("a")
    seen = []
    s.regs["a"][0].on_update = lambda *_: seen.append("rest")
    rc = Reconciler(s, lambda _aid: ([(0.10, 10)], [(0.90, 10)]))

    targets = rc.prepare(T + 20)
    books = rc.fetch_due(targets, now=T + 21, mono=6.0)
    reps["a"].delta_in([("ask", 0.45, 0), ("ask", 0.46, 10)], now=T + 20.5, mono=5.5)

    assert rc.apply(books, now=T + 21) == []
    assert reps["a"].snapshot(T + 21).best_ask.price == 0.46
    assert rc.superseded == 1 and rc.reconciles == 0 and seen == []


def test_each_rest_book_is_stamped_when_its_response_arrives():
    s, reps = stream_with("a", "b")
    clock = iter((T + 21, T + 22))
    import nodes.stream_polymarket.reconcile as module
    original = module.time.time
    module.time.time = lambda: next(clock)
    try:
        rc = Reconciler(s, lambda _aid: ([(0.40, 10)], [(0.45, 10)]))
        books = rc.fetch_due(rc.prepare(T + 20))
    finally:
        module.time.time = original
    assert books["a"].received_utc == T + 21
    assert books["b"].received_utc == T + 22


# ── L149: a REST disagreement resyncs the book from the websocket ──────────────────────────────
# These drive the stream's own ladder (`stream.books`) through real `book` events; `stream_with`
# above seeds replicas directly and leaves it empty. "The venue answers" means delivering the full
# `book` event the run loop's unsubscribe/subscribe produces -- the last test drives that loop itself.
import asyncio
import json

from nodes.stream_polymarket.reconcile import FetchedBook

TRUTH_BIDS = [(0.19, 10.0)]
TRUTH_ASKS = [(0.20, 8.0), (0.21, 10.0), (0.23, 10.0)]
STALE = [(0.20, 8), (0.21, 10), (0.22, 10), (0.23, 10)]      # holds 0.22, which the venue removed


def _book(asks, aid="a"):
    return {"event_type": "book", "asset_id": aid, "tick_size": "0.01",
            "bids": [{"price": "0.19", "size": "10"}],
            "asks": [{"price": str(p), "size": str(s)} for p, s in asks]}


def _change(price, size, side="BUY", bb=0.19, ba=0.20, aid="a"):
    return {"event_type": "price_change", "price_changes": [
        {"asset_id": aid, "price": str(price), "size": str(size), "side": side,
         "best_bid": str(bb), "best_ask": str(ba)}]}


def _pm_replica():
    return BookReplica("polymarket", "a", verification="external", max_unverified_s=30.0,
                       heartbeat_timeout_s=1e9)


def _quiet_stream(asks):
    s = PolymarketStream()
    r = _pm_replica()
    s.register("a", r)
    s.handle(_book(asks), now=T)
    for i in range(1, 21):
        s.handle("PONG", now=T + i)
    return s, r


def _truth_fetch(_aid):
    return list(TRUTH_BIDS), list(TRUTH_ASKS)


def test_a_disagreement_queues_a_websocket_resnapshot():
    s, r = _quiet_stream(STALE)
    rc = Reconciler(s, _truth_fetch)
    assert rc.once(now=T + 20) == ["a"]
    assert rc.rest_drift == 1 and r.last_fault is Fault.HASH_MISMATCH
    assert s.resnapshot == {"a"}


def test_only_the_disagreeing_asset_is_queued():
    s = PolymarketStream()
    ra, rb = _pm_replica(), BookReplica("polymarket", "b", verification="external",
                                        max_unverified_s=30.0, heartbeat_timeout_s=1e9)
    s.register("a", ra)
    s.register("b", rb)
    s.handle(_book(STALE, aid="a"), now=T)
    s.handle(_book(TRUTH_ASKS, aid="b"), now=T)
    for i in range(1, 21):
        s.handle("PONG", now=T + i)
    rc = Reconciler(s, _truth_fetch)                      # both fetch the same venue book
    assert rc.once(now=T + 20) == ["a", "b"]
    assert rc.rest_drift == 1 and rc.drifted == ["a"]
    assert s.resnapshot == {"a"}, "b agreed, so it is not resubscribed"


def test_an_agreement_queues_nothing():
    s, r = _quiet_stream(TRUTH_ASKS)
    rc = Reconciler(s, _truth_fetch)
    assert rc.once(now=T + 20) == ["a"]
    assert rc.rest_drift == 0 and s.resnapshot == set()


def test_a_superseded_fetch_neither_reconciles_nor_queues():
    s, r = _quiet_stream(STALE)
    rc = Reconciler(s, _truth_fetch)
    books = rc.fetch_due(rc.prepare(T + 20), now=T + 21, mono=6.0)
    s.handle(_change(0.18, 4), now=T + 20.5)              # agreeing frame lands during the flight
    assert rc.apply(books, now=T + 21) == []
    assert rc.superseded == 1 and rc.reconciles == 0 and s.resnapshot == set()


def test_the_reconciler_never_writes_the_streams_ladder():
    """REST is used to DETECT a disagreement. It is never the content kept (L148 withdrawn)."""
    s, r = _quiet_stream(STALE)
    before_obj, before_asks = s.books["a"], dict(s.books["a"].asks)
    Reconciler(s, _truth_fetch).once(now=T + 20)
    assert s.books["a"] is before_obj and s.books["a"].asks == before_asks


def test_the_venues_fresh_book_corrects_the_book_and_the_level_stays_gone():
    """L146 R3, fixed. The correction now comes from the socket, so later updates keep it."""
    s, r = _quiet_stream(STALE)
    Reconciler(s, _truth_fetch).once(now=T + 20)
    assert s.resnapshot == {"a"}, "the only thing that brings the venue's book"
    s.handle(_book(TRUTH_ASKS), now=T + 21)               # the venue answers the resubscribe
    assert s.books["a"].asks == dict(TRUTH_ASKS) and r.asks == dict(TRUTH_ASKS)
    assert r.source == "ws" and r.check(T + 21, max_age_s=5.0) is None
    for i in range(22, 27):
        s.handle(_change(0.18, i), now=T + i)
    assert 0.22 not in r.asks and 0.22 not in s.books["a"].asks


def test_l148_n1_a_lagging_rest_response_cannot_make_a_removed_level_permanent():
    """The case that withdrew L148. The websocket removed 0.22; REST still shows it. The end state
    holds even without the venue's book, because nothing wrote REST into the stream's ladder; only
    the resnapshot assertion depends on L149 (review round 1)."""
    s = PolymarketStream()
    r = _pm_replica()
    s.register("a", r)
    s.handle(_book([(0.20, 8), (0.21, 10), (0.22, 10)]), now=T)
    s.handle(_change(0.22, 0, side="SELL"), now=T + 1)    # correct websocket removal, verified
    for i in range(2, 21):
        s.handle("PONG", now=T + i)
    lagging = ([(0.19, 10.0)], [(0.20, 8.0), (0.21, 10.0), (0.22, 10.0)])
    Reconciler(s, lambda _aid: lagging).once(now=T + 20)
    assert 0.22 not in s.books["a"].asks, "the stale REST level never reaches the stream's ladder"
    assert s.resnapshot == {"a"}
    s.handle(_book([(0.20, 8), (0.21, 10)]), now=T + 21)  # the venue's own book
    for i in range(22, 27):
        s.handle(_change(0.18, i), now=T + i)
    assert 0.22 not in r.asks and 0.22 not in s.books["a"].asks


def test_l148_wt1_an_unsynced_second_owner_ends_with_the_newer_depth():
    s = PolymarketStream()
    capture = _pm_replica()
    s.register("a", capture)
    s.handle(_book([(0.20, 8), (0.21, 10), (0.25, 10)]), now=T)
    poller = _pm_replica()
    s.register("a", poller)                               # no new book is sent for it
    for i in range(1, 21):
        s.handle("PONG", now=T + i)
    rc = Reconciler(s, lambda _aid: ([(0.19, 10.0)], [(0.20, 8.0), (0.21, 10.0), (0.25, 10.0)]))
    books = rc.fetch_due(rc.prepare(T + 20), now=T + 20.1, mono=1.0)
    s.handle(_change(0.25, 3, side="SELL"), now=T + 20.05)   # newer deep change during the flight
    rc.apply(books, now=T + 20.2)
    assert s.books["a"].asks[0.25] == 3.0, "the newer websocket depth is untouched"
    assert s.resnapshot == {"a"}
    s.handle(_book([(0.20, 8), (0.21, 10), (0.25, 3)]), now=T + 21)
    assert capture.asks[0.25] == 3.0 and poller.asks[0.25] == 3.0
    assert capture.state is ReplicaState.SYNCED and poller.state is ReplicaState.SYNCED


def test_l148_wt2_a_replica_invalidated_in_flight_ends_with_the_venues_book():
    s = PolymarketStream()
    watch, late = _pm_replica(), _pm_replica()
    s.register("a", watch)
    s.handle(_book([(0.20, 8), (0.21, 10), (0.22, 10)]), now=T)
    s.register("a", late)
    late.snapshot_in([(0.19, 10)], [(0.20, 8), (0.21, 10), (0.22, 10)], now=T)
    late.invalidate(Fault.HEARTBEAT_LOST)
    for i in range(1, 21):
        s.handle("PONG", now=T + i)
    rc = Reconciler(s, lambda _aid: ([(0.19, 10.0)], [(0.20, 8.0), (0.21, 10.0), (0.22, 10.0)]))
    books = rc.fetch_due(rc.prepare(T + 20), now=T + 20.2, mono=1.0)
    s.handle(_change(0.22, 0, side="SELL"), now=T + 20.5)    # the venue removed 0.22
    rc.apply(books, now=T + 21)
    assert rc.superseded == 1 and rc.reconciles == 1, "watch moved on; late did not"
    assert 0.22 not in s.books["a"].asks
    # Pre-existing: `reconcile` re-syncs the invalidated replica with the (stale) REST ladder, labelled
    # "rest" and held to the REST freshness bound. L149 is what asks the socket to replace it.
    assert late.source == "rest" and 0.22 in late.asks
    assert s.resnapshot == {"a"}
    s.handle(_book([(0.20, 8), (0.21, 10)]), now=T + 22)
    assert 0.22 not in watch.asks and 0.22 not in late.asks


def test_l148_m1_a_malformed_book_is_never_filled_by_the_reconciler():
    s, r = _quiet_stream([(0.20, 8), (0.22, 10)])
    rc = Reconciler(s, lambda _aid: ([(0.19, 10.0)], [(0.20, 8.0)]))
    books = rc.fetch_due(rc.prepare(T + 20), now=T + 20.2, mono=1.0)
    s.handle(_change(0.18, 4, ba=0.21), now=T + 20.5)        # drift drops the ladder
    bad = _book([(0.20, 8)])
    bad["asks"].append({"price": "1.5", "size": "1"})       # apply_book raises after setdefault
    s.handle(bad, now=T + 20.6)
    assert s.books["a"].asks == {}
    assert s.resnapshot == {"a"}, "the stream's own drift check already asked for a fresh book"
    rc.apply(books, now=T + 21)
    assert s.books["a"].asks == {}, "REST was not written into the empty entry"
    s.handle(_book([(0.20, 8)]), now=T + 22)
    assert s.books["a"].asks == {0.20: 8.0} and r.asks == {0.20: 8.0}


def test_l148_f1_rest_ahead_of_queued_frames_no_longer_causes_false_drift():
    """F1 was a cost of writing REST into the stream's ladder. With no write-through, the queued
    frames fold into the websocket's own ladder and their claims agree."""
    s, r = _quiet_stream([(0.20, 8), (0.21, 10), (0.23, 10)])
    rc = Reconciler(s, lambda _aid: ([(0.19, 10.0)], [(0.21, 10.0), (0.23, 5.0)]))
    rc.apply(rc.fetch_due(rc.prepare(T + 20), now=T + 20.1, mono=1.0), now=T + 20.2)
    s.handle(_change(0.23, 5, side="SELL", ba=0.20), now=T + 20.3)   # X: 0.20 still best
    s.handle(_change(0.20, 0, side="SELL", ba=0.21), now=T + 20.4)   # Y: 0.20 removed
    assert s.drift == 0, "no false drift from a REST ladder the socket had not caught up to"
    assert s.books["a"].asks == {0.21: 10.0, 0.23: 5.0}


def test_a_queued_resnapshot_is_actually_unsubscribed_and_resubscribed():
    """Integration. The real run loop must turn the Reconciler's request into frames -- the gap
    that let a non-executable recovery script pass its tests (F23 audit, Blocker 2)."""
    import time as _time

    s = PolymarketStream()
    r = _pm_replica()
    s.register("a", r)
    rc = Reconciler(s, _truth_fetch)
    sent = []

    class FakeWS:
        def __init__(self):
            self.n = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def send(self, m):
            sent.append(json.loads(m) if m.startswith("{") else m)

        async def recv(self):
            self.n += 1
            if self.n == 1:
                return json.dumps(_book(STALE))
            if self.n == 2:
                fb = FetchedBook(list(TRUTH_BIDS), list(TRUTH_ASKS), _time.time(), 0.0,
                                 ((id(r), r.updated_utc),))
                rc.apply({"a": fb})                         # REST disagrees: queue the resnapshot
                return "PONG"
            if self.n == 3:
                return json.dumps(_book(TRUTH_ASKS))        # the venue answers the resubscribe
            raise asyncio.CancelledError

    async def go():
        stop = asyncio.Event()
        try:
            await asyncio.wait_for(s.run(stop, connect=lambda u: FakeWS()), timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    asyncio.run(go())
    ops = [f for f in sent if isinstance(f, dict) and "operation" in f]
    assert ops == [{"assets_ids": ["a"], "operation": "unsubscribe"},
                   {"assets_ids": ["a"], "operation": "subscribe"}]
    assert s.resnapshot == set(), "the request was consumed"
    assert s.books["a"].asks == dict(TRUTH_ASKS) and r.asks == dict(TRUTH_ASKS)
