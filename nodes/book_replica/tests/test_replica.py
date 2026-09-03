#!/usr/bin/env python3
"""A desynced replica invents arbitrage that never existed. These tests are the whole defence."""
from __future__ import annotations

import pytest

from nodes.book_replica.replica import BookReplica, Fault, ReplicaState

T = 1000.0


def kalshi() -> BookReplica:
    r = BookReplica("kalshi", "K1", verification="own_sequence")
    r.subscribed(T)
    r.snapshot_in([(0.40, 100)], [(0.42, 100)], seq=5, now=T)
    return r


def polymarket() -> BookReplica:
    r = BookReplica("polymarket", "P1", verification="external", max_unverified_s=30.0)
    r.subscribed(T)
    r.snapshot_in([(0.55, 100)], [(0.58, 100)], seq=None, now=T)
    return r


# ── the gate ────────────────────────────────────────────────────────────
def test_only_synced_yields_a_book():
    r = BookReplica("kalshi", "K1")
    for _ in range(1):
        assert r.snapshot(T) is None            # DISCONNECTED
    r.connecting(T);   assert r.snapshot(T) is None
    r.subscribed(T);   assert r.snapshot(T) is None
    r.snapshot_in([(0.4, 10)], [(0.42, 10)], seq=1, now=T)
    assert r.snapshot(T) is not None


def test_deltas_before_the_snapshot_are_discarded():
    """Applying a delta to an empty book would fabricate a one-sided market."""
    r = BookReplica("kalshi", "K1")
    r.subscribed(T)
    assert r.delta_in([("ask", 0.42, 50)], seq=1, now=T) is Fault.NOT_SYNCED
    assert r.asks == {}


# ── kalshi: sequence is the proof ───────────────────────────────────────
def test_sequence_gap_invalidates_the_whole_book_not_just_the_message():
    """Every level after a missed delta is unverifiable, so the book is fiction, not stale."""
    r = kalshi()
    assert r.delta_in([("ask", 0.42, 0)], seq=7, now=T + 1) is Fault.SEQ_GAP
    assert r.state is ReplicaState.RESYNCING
    assert r.snapshot(T + 1) is None
    assert r.bids == {} and r.asks == {}


def test_in_order_deltas_apply_and_keep_the_replica_usable():
    r = kalshi()
    assert r.delta_in([("ask", 0.41, 30)], seq=6, now=T + 1) is None
    b = r.snapshot(T + 1)
    assert b.best_ask.price == 0.41


def test_a_replayed_or_duplicate_sequence_is_ignored_not_treated_as_a_gap():
    r = kalshi()
    assert r.delta_in([("ask", 0.99, 1)], seq=5, now=T + 1) is None
    assert r.state is ReplicaState.SYNCED
    assert 0.99 not in r.asks, "a stale replay must not mutate the book"


def test_zero_size_removes_a_level():
    r = kalshi()
    r.delta_in([("ask", 0.42, 0)], seq=6, now=T + 1)
    assert r.asks == {}


def test_resync_recovers_via_a_fresh_snapshot():
    r = kalshi()
    r.delta_in([], seq=99, now=T + 1)
    assert r.state is ReplicaState.RESYNCING
    r.snapshot_in([(0.40, 10)], [(0.43, 10)], seq=100, now=T + 2)
    assert r.state is ReplicaState.SYNCED and r.snapshot(T + 2) is not None


# ── polymarket: no sequence, so an outside check is mandatory ───────────
def test_polymarket_decays_to_unusable_without_reconciliation():
    """No seq means the stream cannot prove itself. Silence must not read as health."""
    r = polymarket()
    r.heartbeat(T + 40)                              # connection alive
    assert r.check(T + 40, max_age_s=1e9) is Fault.UNVERIFIED_TOO_LONG
    assert r.snapshot(T + 40, max_age_s=1e9) is None


def test_reconciliation_that_agrees_re_verifies():
    r = polymarket()
    r.heartbeat(T + 40)
    assert r.reconcile([(0.55, 100)], [(0.58, 100)], now=T + 40) is None
    assert r.snapshot(T + 40) is not None


def test_reconciliation_that_disagrees_adopts_rest_and_reports_the_drift():
    """A replica that silently self-heals hides the drift this exists to catch."""
    r = polymarket()
    assert r.reconcile([(0.55, 100)], [(0.61, 100)], now=T + 10) is Fault.HASH_MISMATCH
    assert r.last_fault is Fault.HASH_MISMATCH
    assert r.snapshot(T + 10).best_ask.price == 0.61, "REST is adopted as truth"


def test_kalshi_does_not_need_reconciliation_because_seq_verifies_it():
    r = kalshi()
    for i, ts in enumerate(range(1, 40), start=6):
        r.delta_in([("ask", 0.42, 100)], seq=i, now=T + ts)
    assert r.check(T + 39) is None


# ── liveness is not freshness ───────────────────────────────────────────
def test_a_quiet_market_and_a_dead_socket_are_different_things():
    """The book timestamp cannot tell them apart. Only the heartbeat can."""
    quiet = kalshi()
    for ts in range(1, 60):
        quiet.heartbeat(T + ts)                      # socket alive, no book events
    assert quiet.check(T + 59, max_age_s=1e9) is None, "a quiet market is still tradeable"

    dead = kalshi()
    assert dead.check(T + 60) is Fault.HEARTBEAT_LOST
    assert dead.snapshot(T + 60) is None


def test_heartbeat_loss_invalidates_a_previously_synced_replica():
    r = kalshi()
    r.check(T + 60)
    assert r.state is ReplicaState.RESYNCING


def test_staleness_still_applies_within_a_live_connection():
    r = kalshi()
    r.heartbeat(T + 10)
    assert r.check(T + 10, max_age_s=5.0) is Fault.STALE


# ── incoherence ─────────────────────────────────────────────────────────
def test_a_crossed_book_is_rejected_rather_than_priced():
    """bid >= ask is not a 100% arbitrage, it is a broken replica."""
    r = kalshi()
    r.delta_in([("bid", 0.50, 10)], seq=6, now=T + 1)
    assert r.check(T + 1) is Fault.CROSSED_BOOK
    assert r.snapshot(T + 1) is None


def test_disconnect_clears_the_book_so_it_cannot_be_served_after_reconnect():
    r = kalshi()
    r.disconnected(T + 1)
    r.connecting(T + 2)
    assert r.snapshot(T + 2) is None and r.bids == {} and r.asks == {}


def test_snapshot_orders_both_ladders_correctly():
    r = BookReplica("kalshi", "K1")
    r.subscribed(T)
    r.snapshot_in([(0.30, 1), (0.40, 2), (0.35, 3)], [(0.60, 1), (0.50, 2), (0.55, 3)],
                  seq=1, now=T)
    b = r.snapshot(T)
    assert [q.price for q in b.bids] == [0.40, 0.35, 0.30], "bids descend"
    assert [q.price for q in b.asks] == [0.50, 0.55, 0.60], "asks ascend"


def test_a_reconciled_book_is_labelled_rest_and_a_streamed_one_ws():
    r = BookReplica("polymarket", "m", verification="external")
    r.snapshot_in([(0.4, 10)], [(0.5, 10)], now=1000.0, server_utc=999.9, mono=1.0)
    b = r.snapshot(1000.0)
    assert (b.source, b.server_utc, b.received_mono) == ("ws", 999.9, 1.0)
    assert r.reconcile([(0.4, 10)], [(0.5, 10)], now=1001.0, mono=2.0) is None
    b = r.snapshot(1001.0)
    assert b.source == "rest" and b.server_utc is None and b.received_mono == 2.0


def test_the_clock_monitor_is_unknown_healthy_and_tracks_the_worst_sample():
    from nodes.book_replica.clock import ClockMonitor
    c = ClockMonitor(max_skew_s=1.0, min_samples=2)
    assert c.healthy and c.stats()["offset_s"] is None
    c.observe(10.0, None)
    assert c.samples == 0, "a frame without a stamp is not evidence"
    c.observe(10.0, 9.95); c.observe(11.0, 10.95)
    assert c.healthy and c.stats()["offset_s"] == pytest.approx(0.05)
    c.observe(12.0, 5.0)
    assert c.stats()["worst_s"] == pytest.approx(7.0)


def test_a_few_stale_stamps_cannot_halt_the_lane():
    """Found live: pre-game Polymarket books carry hours-old stamps. Snapshots are no longer fed,
    and even a stamped event needs company before the monitor may judge."""
    from nodes.book_replica.clock import ClockMonitor
    c = ClockMonitor(max_skew_s=5.0, min_samples=20)
    for _ in range(19):
        c.observe(10_000.0, 100.0)                 # hours of apparent skew
    assert c.healthy, "19 samples: no verdict yet"
    c.observe(10_000.0, 100.0)
    assert not c.healthy
