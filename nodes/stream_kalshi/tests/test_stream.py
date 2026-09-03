#!/usr/bin/env python3
"""The shared socket: registration, replica feeding, gap recovery, reconnect."""
from __future__ import annotations

import asyncio
import json

import pytest

from nodes.book_replica.replica import BookReplica, Fault, ReplicaState
from nodes.stream_kalshi.stream import KalshiStream, ws_headers

T = 1000.0

#: One key for the module -- RSA keygen is ~100ms and every transport test needs a signable key.
_KEY = None


def key():
    global _KEY
    if _KEY is None:
        from cryptography.hazmat.primitives.asymmetric import rsa
        _KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return _KEY


SNAP = {"type": "orderbook_snapshot", "seq": 1,
        "msg": {"market_ticker": "K1", "yes": [[0.40, 100]], "no": [[0.55, 200]]}}


def wired() -> tuple[KalshiStream, BookReplica, list]:
    s = KalshiStream(api_key="k", private_key=key())
    r = BookReplica("kalshi", "K1", verification="stream")
    seen: list = []
    s.register("K1", r, "yes", on_update=lambda m, _t: seen.append(m))
    return s, r, seen


def delta(seq, side="yes", price=0.40, d=-30.0):
    return {"type": "orderbook_delta", "seq": seq,
            "msg": {"market_ticker": "K1", "side": side, "price": price, "delta": d}}


# ── feeding replicas ────────────────────────────────────────────────────
def test_a_snapshot_syncs_the_registered_replica():
    s, r, seen = wired()
    assert s.handle(SNAP, now=T) == "snapshot"
    assert r.state is ReplicaState.SYNCED
    assert r.snapshot(T).best_ask.price == pytest.approx(0.45)
    assert seen == ["K1"]


def test_a_delta_updates_the_replica_and_notifies():
    s, r, seen = wired()
    s.handle(SNAP, now=T)
    assert s.handle(delta(2), now=T) == "delta"
    assert r.snapshot(T).best_bid.size == 70.0
    assert seen == ["K1", "K1"]


def test_one_socket_feeds_many_markets():
    """The reason connections are shared: one handshake, N tickers."""
    s = KalshiStream(api_key="k", private_key=key())
    reps = {t: BookReplica("kalshi", t) for t in ("K1", "K2", "K3")}
    for t, r in reps.items():
        s.register(t, r, "yes")
    for t in reps:
        s.handle({"type": "orderbook_snapshot", "seq": 1,
                  "msg": {"market_ticker": t, "yes": [[0.4, 10]], "no": [[0.5, 10]]}}, now=T)
    assert all(r.state is ReplicaState.SYNCED for r in reps.values())
    assert s.tickers == ["K1", "K2", "K3"]


def test_both_outcomes_of_one_market_can_register_on_the_same_ticker():
    """A Kalshi market carries both sides; yes and no replicas share one subscription."""
    s = KalshiStream(api_key="k", private_key=key())
    yes, no = BookReplica("kalshi", "K1"), BookReplica("kalshi", "K1")
    s.register("K1", yes, "yes")
    s.register("K1", no, "no")
    s.handle(SNAP, now=T)
    assert yes.snapshot(T).best_bid.price == 0.40
    assert no.snapshot(T).best_bid.price == 0.55


# ── the recovery path ───────────────────────────────────────────────────
def test_a_sequence_gap_invalidates_the_replica_and_trips_a_resubscribe():
    s, r, _ = wired()
    s.handle(SNAP, now=T)
    s.resubscribe_needed = False
    s.handle(delta(5), now=T)                      # expected 2
    assert s.gaps == 1
    assert r.state is ReplicaState.RESYNCING
    assert r.snapshot(T) is None, "a gapped book must stop serving immediately"
    assert s.resubscribe_needed, "recovery is: reconnect and wait for a fresh snapshot"


def test_a_fresh_snapshot_after_a_gap_restores_service():
    s, r, _ = wired()
    s.handle(SNAP, now=T)
    s.handle(delta(9), now=T)
    s.handle({"type": "orderbook_snapshot", "seq": 20,
              "msg": {"market_ticker": "K1", "yes": [[0.41, 10]], "no": [[0.56, 10]]}}, now=T)
    assert r.state is ReplicaState.SYNCED and r.snapshot(T) is not None


def test_a_malformed_frame_is_counted_not_fatal():
    s, r, _ = wired()
    s.handle(SNAP, now=T)
    s.handle({"type": "orderbook_delta", "seq": 2,
              "msg": {"market_ticker": "K1", "side": "sideways", "price": 0.4, "delta": 1}}, now=T)
    assert s.errors == 1
    assert r.state is ReplicaState.SYNCED, "one bad frame must not invalidate a good book"


def test_a_heartbeat_frame_keeps_replicas_alive_without_touching_the_book():
    """A quiet market still needs proof the socket is up."""
    s, r, _ = wired()
    s.handle(SNAP, now=T)
    s.handle({"type": "subscribed", "msg": {}}, now=T + 10)
    assert r.heartbeat_utc == T + 10
    assert r.updated_utc == T, "a heartbeat is not a book event"


def test_unregister_drops_the_ticker_and_its_book_state():
    s, _r, _ = wired()
    s.handle(SNAP, now=T)
    s.unregister("K1")
    assert s.tickers == [] and "K1" not in s.books


# ── transport ───────────────────────────────────────────────────────────
def test_reconnect_marks_every_replica_disconnected():
    """On a dropped socket the books must stop serving at once, not decay on a timeout."""
    s, r, _ = wired()
    s.handle(SNAP, now=T)

    class Boom:
        async def __aenter__(self): raise ConnectionResetError("dropped")
        async def __aexit__(self, *a): return False

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(s.run(stop, connect=lambda u, h: Boom()))
        await asyncio.sleep(0.05)
        stop.set(); task.cancel()
        try: await task
        except asyncio.CancelledError: pass

    asyncio.run(go())
    assert r.state is ReplicaState.DISCONNECTED
    assert r.snapshot(T) is None
    assert "ConnectionResetError" in s.last_error


def test_the_run_loop_subscribes_then_pumps_frames():
    s, r, _ = wired()
    sent: list = []

    class FakeWS:
        def __init__(self): self.frames = [json.dumps(SNAP), json.dumps(delta(2))]
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def send(self, m): sent.append(json.loads(m))
        async def recv(self):
            if self.frames: return self.frames.pop(0)
            raise asyncio.CancelledError

    async def go():
        stop = asyncio.Event()
        try:
            await asyncio.wait_for(s.run(stop, connect=lambda u, h: FakeWS()), timeout=1.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    asyncio.run(go())
    assert sent and sent[0]["cmd"] == "subscribe"
    assert sent[0]["params"]["market_tickers"] == ["K1"]
    assert r.applied >= 1, "frames reached the replica"


# ── auth ────────────────────────────────────────────────────────────────
def test_signing_input_is_timestamp_method_path_and_is_deterministic():
    h = ws_headers("my-key", key(), now_ms=1700000000000)
    assert h["KALSHI-ACCESS-KEY"] == "my-key"
    assert h["KALSHI-ACCESS-TIMESTAMP"] == "1700000000000"
    assert h["KALSHI-ACCESS-SIGNATURE"]
    # PSS is randomised, so two signatures differ -- but both must verify against the same input.
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    import base64
    key().public_key().verify(
        base64.b64decode(h["KALSHI-ACCESS-SIGNATURE"]),
        b"1700000000000GET/trade-api/ws/v2",
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
        hashes.SHA256())


def test_the_key_is_never_placed_in_the_url_or_a_log_field():
    s = KalshiStream(api_key="secret-key", private_key=key())
    assert "secret-key" not in s.url
    assert "secret-key" not in json.dumps(s.stats())


def test_any_frame_proves_liveness_for_every_replica_on_the_socket():
    """A quiet market is not a dead connection.

    Caught live: two tickers on a healthy socket with 2,500+ frames went HEARTBEAT_LOST purely
    because no event named THEM. Liveness belongs to the connection; freshness belongs to the
    market.
    """
    s = KalshiStream(api_key="k", private_key=key())
    busy, quiet = BookReplica("kalshi", "K1", verification="stream"), BookReplica("kalshi", "K2", verification="stream")
    s.register("K1", busy, "yes")
    s.register("K2", quiet, "yes")
    s.handle(SNAP, now=T)
    s.handle({"type": "orderbook_snapshot", "seq": 2,
              "msg": {"market_ticker": "K2", "yes": [[0.3, 10]], "no": [[0.6, 10]]}}, now=T)
    for i, ts in enumerate(range(1, 30), start=3):
        s.handle(delta(i), now=T + ts)                 # only K1 ever moves
    assert quiet.heartbeat_utc == T + 29, "the socket is alive, so K2 is alive"
    assert quiet.updated_utc == T, "but K2's BOOK is untouched"
    assert quiet.check(T + 29, max_age_s=1e9) is None, "quiet market still serves"


def test_a_subscription_gap_invalidates_every_replica_not_just_one():
    """seq is per SUBSCRIPTION, so a lost message could have belonged to any ticker."""
    s = KalshiStream(api_key="k", private_key=key())
    a, b = BookReplica("kalshi", "K1", verification="stream"), BookReplica("kalshi", "K2", verification="stream")
    s.register("K1", a, "yes")
    s.register("K2", b, "yes")
    s.handle(SNAP, now=T)
    s.handle({"type": "orderbook_snapshot", "seq": 2,
              "msg": {"market_ticker": "K2", "yes": [[0.3, 10]], "no": [[0.6, 10]]}}, now=T)
    assert a.snapshot(T) and b.snapshot(T)
    assert s.handle(delta(9), now=T) == "gap"          # expected 3
    assert a.snapshot(T) is None and b.snapshot(T) is None


def test_interleaved_tickers_on_one_subscription_are_not_gaps():
    """Measured live: ATH saw 1,10,11,13,15,17 -- a per-market check would fire on every message."""
    s = KalshiStream(api_key="k", private_key=key())
    a, b = BookReplica("kalshi", "K1", verification="stream"), BookReplica("kalshi", "K2", verification="stream")
    s.register("K1", a, "yes")
    s.register("K2", b, "yes")
    s.handle(SNAP, now=T)
    s.handle({"type": "orderbook_snapshot", "seq": 2,
              "msg": {"market_ticker": "K2", "yes": [[0.3, 10]], "no": [[0.6, 10]]}}, now=T)
    # Deep in the book on purpose: a bid at the folded ask price would cross the replica and be
    # rejected by the coherence guard, which is a different (correct) refusal from a seq gap.
    for i, tk in enumerate(["K1", "K2", "K2", "K1", "K2"], start=3):
        s.handle({"type": "orderbook_delta", "seq": i,
                  "msg": {"market_ticker": tk, "side": "yes", "price": 0.20, "delta": 1}}, now=T)
    assert s.gaps == 0
    assert a.snapshot(T) and b.snapshot(T)

    # And the other half: a replica left on the per-market default would have torn itself apart on
    # exactly this traffic. This is why verification mode is explicit rather than assumed.
    naive = BookReplica("kalshi", "K3", verification="own_sequence")
    naive.subscribed(T)
    naive.snapshot_in([(0.4, 10)], [(0.5, 10)], seq=1, now=T)
    assert naive.project_in([(0.4, 10)], [(0.5, 10)], seq=4, now=T) is Fault.SEQ_GAP


def test_the_sequence_re_anchors_after_a_gap():
    """Holding the old baseline would report a second gap for the same single loss."""
    s, r, _ = wired()
    s.handle(SNAP, now=T)
    s.handle(delta(9), now=T)
    assert s.gaps == 1 and s.last_seq == {}, "re-anchored: the sid's baseline is dropped"
    s.handle({"type": "orderbook_snapshot", "seq": 40,
              "msg": {"market_ticker": "K1", "yes": [[0.4, 10]], "no": [[0.5, 10]]}}, now=T)
    assert s.gaps == 1, "re-anchored, not a second gap"
    assert r.snapshot(T) is not None


def test_a_new_socket_restarts_the_sequence_baseline():
    s, _r, _ = wired()
    s.handle(SNAP, now=T)
    s.handle(delta(2), now=T)
    assert s.last_seq == {None: 2}
    s.last_seq.clear()                                  # what run() does on reconnect
    s.handle({"type": "orderbook_snapshot", "seq": 1,
              "msg": {"market_ticker": "K1", "yes": [[0.4, 10]], "no": [[0.5, 10]]}}, now=T)
    assert s.gaps == 0


# ── per-sid sequencing, server time, clock ───────────────────────────────────
def sid_frame(sid, seq, ticker="K1", kind="orderbook_delta", ts_ms=None):
    if kind == "orderbook_snapshot":
        msg = {"market_ticker": ticker, "yes_dollars_fp": [[0.40, 100]], "no_dollars_fp": [[0.55, 200]]}
    else:
        msg = {"market_ticker": ticker, "side": "yes", "price_dollars": "0.40", "delta_fp": "-1"}
    if ts_ms is not None:
        msg["ts_ms"] = ts_ms
    return {"type": kind, "sid": str(sid), "seq": str(seq), "msg": msg}     # strings, as on the wire


def test_two_subscriptions_on_one_socket_do_not_alias_each_others_sequence():
    """A second `subscribe` opens a second sid with its own 1,2,3. One socket-wide counter would
    hide the new sid under the old maximum and never see a gap on either."""
    s = KalshiStream(api_key="k", private_key=key())
    for t in ("K1", "K2"):
        s.register(t, BookReplica("kalshi", t, verification="stream"), "yes")
    s.handle(sid_frame(1, 1, "K1", "orderbook_snapshot"), now=T)
    for seq in (2, 3, 4):
        s.handle(sid_frame(1, seq, "K1"), now=T)
    s.handle(sid_frame(2, 1, "K2", "orderbook_snapshot"), now=T)     # the new subscription
    s.handle(sid_frame(2, 2, "K2"), now=T)
    s.handle(sid_frame(1, 5, "K1"), now=T)
    assert s.gaps == 0 and s.last_seq == {1: 5, 2: 2}
    s.handle(sid_frame(2, 4, "K2"), now=T)                            # 3 was lost on sid 2
    assert s.gaps == 1 and "sid 2" in s.last_error
    assert s.last_seq == {1: 5}, "only the sid that gapped is re-anchored"


def test_the_venue_timestamp_reaches_the_book_and_the_clock_monitor():
    s, r, _ = wired()
    s.handle(sid_frame(1, 1, "K1", "orderbook_snapshot"), now=T, mono=50.0)
    b = r.snapshot(T)
    assert b.source == "ws" and b.server_utc is None and b.received_mono == 50.0, "snapshots carry no ts"
    s.handle(sid_frame(1, 2, "K1", ts_ms=int((T - 0.07) * 1000)), now=T, mono=51.0)
    b = r.snapshot(T)
    assert b.server_utc == pytest.approx(T - 0.07) and b.received_mono == 51.0
    st = s.clock.stats()
    assert st["samples"] == 1 and st["offset_s"] == pytest.approx(0.07) and st["healthy"]


def test_a_clock_skew_of_seconds_is_unhealthy():
    s, _r, _ = wired()
    s.handle(sid_frame(1, 1, "K1", "orderbook_snapshot"), now=T)
    for seq in range(2, 60):
        s.handle(sid_frame(1, seq, "K1", ts_ms=int((T - 30.0) * 1000)), now=T)
    assert not s.clock.healthy and s.clock.stats()["worst_s"] == pytest.approx(30.0)
