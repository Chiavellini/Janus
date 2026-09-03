#!/usr/bin/env python3
"""Polymarket's wire format and its one integrity check."""
from __future__ import annotations

import asyncio
import json

import pytest

from nodes.book_replica.replica import BookReplica, Fault, ReplicaState
from nodes.stream_polymarket.protocol import (AssetBook, events_in, operation_frame, parse_event,
                                              subscribe_frame)
from nodes.stream_polymarket.stream import PolymarketStream

T = 1000.0
A = "asset-1"
BOOK = {"event_type": "book", "asset_id": A, "tick_size": "0.01",
        "bids": [{"price": "0.01", "size": "5"}, {"price": "0.19", "size": "10"}],
        "asks": [{"price": "0.99", "size": "5"}, {"price": "0.20", "size": "8"}]}


def change(price, size, side="BUY", bb=None, ba=None, aid=A):
    ch = {"asset_id": aid, "price": str(price), "size": str(size), "side": side}
    if bb is not None: ch["best_bid"] = str(bb)
    if ba is not None: ch["best_ask"] = str(ba)
    return {"event_type": "price_change", "price_changes": [ch]}


# ── wire traps ──────────────────────────────────────────────────────────
def test_best_price_is_last_in_both_ladders():
    """Indexing [0] for 'best' prices every trade at the far end of the book."""
    books = {}
    parse_event(BOOK, books)
    assert books[A].best_bid == 0.19 and books[A].best_ask == 0.20


def test_size_is_absolute_not_a_delta():
    """The opposite of Kalshi. Adding it would silently double resting size."""
    books = {}
    parse_event(BOOK, books)
    parse_event(change(0.19, 3), books)
    assert books[A].bids[0.19] == 3.0


def test_zero_size_removes_the_level():
    books = {}
    parse_event(BOOK, books)
    parse_event(change(0.19, 0), books)
    assert 0.19 not in books[A].bids


def test_buy_and_sell_map_to_bid_and_ask():
    books = {}
    parse_event(BOOK, books)
    parse_event(change(0.30, 7, "SELL"), books)
    assert books[A].asks[0.30] == 7.0


def test_a_subscribe_answers_with_a_list_of_book_events():
    assert len(events_in([BOOK, dict(BOOK, asset_id="b")])) == 2
    assert len(events_in(BOOK)) == 1


def test_an_unknown_side_is_an_error_not_a_silent_drop():
    books = {}
    parse_event(BOOK, books)
    assert parse_event(change(0.2, 1, "SIDEWAYS"), books)[0].kind == "error"


def test_a_change_without_a_snapshot_is_ignored_not_applied_to_nothing():
    assert parse_event(change(0.5, 1), {})[0].kind == "ignored"


def test_prices_outside_zero_one_are_rejected():
    books = {}
    assert parse_event({"event_type": "book", "asset_id": A,
                        "bids": [{"price": "40", "size": "1"}], "asks": []}, books)[0].kind == "error"


def test_unhandled_event_types_are_reported_not_dropped_silently():
    assert parse_event({"event_type": "brand_new", "asset_id": A}, {})[0].kind == "ignored"


def test_frames_are_deterministic():
    assert subscribe_frame(["b", "a"])["assets_ids"] == ["a", "b"]
    assert operation_frame(["b", "a"], "unsubscribe") == {"assets_ids": ["a", "b"],
                                                          "operation": "unsubscribe"}


# ── the integrity check ─────────────────────────────────────────────────
def test_agreement_with_the_venues_claimed_top_of_book():
    books = {}
    parse_event(BOOK, books)
    assert books[A].agrees_with(0.19, 0.20)
    assert not books[A].agrees_with(0.18, 0.20)


def test_a_missing_level_is_caught_as_drift():
    """Live, every disagreement was exactly this: the venue's best referenced a level we lacked."""
    b = AssetBook()
    b.apply_book({"bids": [{"price": "0.10", "size": "1"}], "asks": []})
    assert not b.agrees_with(0.10, 1.00), "an ask we never received must not read as agreement"


def test_drift_invalidates_the_replica_and_forces_a_resnapshot():
    s = PolymarketStream()
    r = BookReplica("polymarket", A, verification="stream")
    s.register(A, r)
    s.handle(BOOK, now=T)
    assert r.snapshot(T) is not None
    s.resubscribe_needed = False
    s.handle(change(0.19, 0, bb=0.77, ba=0.20), now=T)      # venue claims a bid we do not have
    assert s.drift == 1
    assert r.state is ReplicaState.RESYNCING
    assert r.snapshot(T) is None
    assert A in s.resnapshot, "queued for an unsubscribe/subscribe round trip"
    assert A not in s.books, "the drifted local ladder is dropped, not patched"


def test_agreement_is_tracked_so_the_check_can_be_audited():
    s = PolymarketStream()
    r = BookReplica("polymarket", A, verification="stream")
    s.register(A, r)
    s.handle(BOOK, now=T)
    for _ in range(4):
        s.handle(change(0.19, 10, bb=0.19, ba=0.20), now=T)
    assert s.checks == 4 and s.agreed == 4 and s.agreement == 1.0


def test_a_change_with_no_claimed_top_is_applied_without_a_check():
    s = PolymarketStream()
    r = BookReplica("polymarket", A, verification="stream")
    s.register(A, r)
    s.handle(BOOK, now=T)
    s.handle(change(0.18, 4), now=T)
    assert s.checks == 0 and r.state is ReplicaState.SYNCED


# ── transport ───────────────────────────────────────────────────────────
def test_pong_keeps_replicas_alive_without_touching_the_book():
    s = PolymarketStream()
    r = BookReplica("polymarket", A, verification="stream")
    s.register(A, r)
    s.handle(BOOK, now=T)
    s.handle("PONG", now=T + 9)
    assert r.heartbeat_utc == T + 9 and r.updated_utc == T


def test_any_frame_proves_liveness_for_every_asset_on_the_socket():
    s = PolymarketStream()
    busy, quiet = (BookReplica("polymarket", A, verification="stream"),
                   BookReplica("polymarket", "b", verification="stream"))
    s.register(A, busy)
    s.register("b", quiet)
    s.handle(BOOK, now=T)
    s.handle(dict(BOOK, asset_id="b"), now=T)
    for i in range(1, 20):
        s.handle(change(0.18, i, bb=0.19, ba=0.20), now=T + i)
    assert quiet.heartbeat_utc == T + 19 and quiet.updated_utc == T


def test_a_non_json_frame_is_counted_not_fatal():
    s = PolymarketStream()
    assert s.handle("{not json", now=T) == ["error"] and s.errors == 1


def test_reconnect_marks_every_replica_disconnected():
    s = PolymarketStream()
    r = BookReplica("polymarket", A, verification="stream")
    s.register(A, r)
    s.handle(BOOK, now=T)

    class Boom:
        async def __aenter__(self): raise ConnectionResetError("dropped")
        async def __aexit__(self, *a): return False

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(s.run(stop, connect=lambda u: Boom()))
        await asyncio.sleep(0.05); stop.set(); task.cancel()
        try: await task
        except asyncio.CancelledError: pass

    asyncio.run(go())
    assert r.state is ReplicaState.DISCONNECTED and r.snapshot(T) is None


def test_a_slate_change_uses_an_operation_frame_not_a_reconnect():
    """A game starting must not cost fresh snapshots for every other game on the socket."""
    s = PolymarketStream()
    sent = []

    class FakeWS:
        def __init__(self): self.n = 0
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def send(self, m): sent.append(json.loads(m) if m.startswith("{") else m)
        async def recv(self):
            self.n += 1
            if self.n == 1:
                s.register("b", BookReplica("polymarket", "b", verification="stream"))
                return json.dumps(BOOK)
            raise asyncio.CancelledError

    s.register(A, BookReplica("polymarket", A, verification="stream"))

    async def go():
        stop = asyncio.Event()
        try:
            await asyncio.wait_for(s.run(stop, connect=lambda u: FakeWS()), timeout=1.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    asyncio.run(go())
    frames = [f for f in sent if isinstance(f, dict)]
    assert frames[0] == {"assets_ids": [A], "type": "market"}
    assert any(f.get("operation") == "subscribe" and f["assets_ids"] == ["b"] for f in frames)


def test_a_passing_check_keeps_an_actively_traded_market_verified():
    """Caught in production: quiet PM markets hit UNVERIFIED_TOO_LONG while the stream was
    actively verifying them on every message. An outside check IS verification."""
    s = PolymarketStream()
    r = BookReplica("polymarket", A, verification="external", max_unverified_s=30.0,
                    heartbeat_timeout_s=120.0)
    s.register(A, r)
    s.handle(BOOK, now=T)
    for i in range(1, 60):
        s.handle(change(0.18, 4, bb=0.19, ba=0.20), now=T + i)
    assert r.check(T + 59, max_age_s=1e9) is None, "its own traffic proved it"


def test_a_genuinely_quiet_market_still_decays_and_forces_a_resnapshot():
    """The other half: nothing verified it, so it must not serve forever on a stale snapshot."""
    s = PolymarketStream()
    r = BookReplica("polymarket", A, verification="external", max_unverified_s=30.0,
                    heartbeat_timeout_s=120.0)
    s.register(A, r)
    s.handle(BOOK, now=T)
    for i in range(1, 60):
        s.handle("PONG", now=T + i)                 # socket alive, no book traffic at all
    assert r.check(T + 59, max_age_s=1e9) is Fault.UNVERIFIED_TOO_LONG


def test_a_drift_actually_sends_an_unsubscribe_and_subscribe_frame():
    """Found by reading the run loop: drift set `resubscribe_needed`, but the wanted set was
    unchanged, so the diff was empty and NO frame went out. The replica sat in RESYNCING until the
    venue happened to push a fresh book. A forced resnapshot is a frame, not a wish."""
    s = PolymarketStream()
    sent = []

    class FakeWS:
        def __init__(self): self.n = 0
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def send(self, m): sent.append(json.loads(m) if m.startswith("{") else m)
        async def recv(self):
            self.n += 1
            if self.n == 1:
                return json.dumps(BOOK)
            if self.n == 2:
                return json.dumps(change(0.19, 0, bb=0.77, ba=0.20))      # drift
            if self.n == 3:
                return json.dumps(BOOK)                                    # the fresh snapshot
            raise asyncio.CancelledError

    r = BookReplica("polymarket", A, verification="stream")
    s.register(A, r)

    async def go():
        stop = asyncio.Event()
        try:
            await asyncio.wait_for(s.run(stop, connect=lambda u: FakeWS()), timeout=1.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    asyncio.run(go())
    frames = [f for f in sent if isinstance(f, dict)]
    ops = [(f.get("operation"), tuple(f["assets_ids"])) for f in frames if "operation" in f]
    assert ops == [("unsubscribe", (A,)), ("subscribe", (A,))], ops
    assert s.drift == 1 and not s.resnapshot
    assert r.state is ReplicaState.SYNCED, "the forced snapshot re-synced it"


def test_a_change_after_drift_is_not_folded_into_the_dropped_book():
    s = PolymarketStream()
    r = BookReplica("polymarket", A, verification="stream")
    s.register(A, r)
    s.handle(BOOK, now=T)
    s.handle(change(0.19, 0, bb=0.77, ba=0.20), now=T)
    kinds = s.handle(change(0.18, 3), now=T)
    assert kinds == ["ignored"] and A not in s.books
    assert r.state is ReplicaState.RESYNCING
