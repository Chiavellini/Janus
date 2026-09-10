#!/usr/bin/env python3
"""One authenticated Kalshi socket, many markets, feeding many replicas.

ONE CONNECTION, NOT ONE PER GAME. Kalshi authenticates at the HTTP upgrade and multiplexes by
`market_ticker`, so a socket per game would mean one RSA handshake per game and N connections
against whatever the venue's limit is, for no gain. The connection is shared infrastructure;
`nodes/game_poller` registers its replicas and is fed.

WHAT THIS NODE OWNS AND WHAT IT DOES NOT. It owns the wire format, the connection, and the
subscription set. It does NOT decide whether a book is usable -- `nodes/book_replica` does, and it
does the sequence check even though this node could, because "can this book be trusted" must have
exactly one home and it must not be the transport.

SEQUENCE IS PER SUBSCRIPTION, NOT PER MARKET. Measured against the live socket on 2026-09-02 with
four tickers on one subscription: snapshots arrived as seq 1,2,3,4 and deltas continued 5,6,7,...
globally contiguous, interleaved across tickers. Each individual ticker therefore sees a
legitimately non-contiguous subsequence -- ATH got 1,10,11,13,15,17 -- so a per-market seq check
reports a gap on almost every message. This node owns the check because the sequence is a property
of the CONNECTION, and the replicas are told.

The consequence is blunt and deliberate: a gap means some message was lost and nothing identifies
which market it belonged to, so EVERY replica on that subscription is invalidated and a resubscribe
is tripped, which makes the venue resend snapshots for all of them. A cleverer partial recovery
that is subtly wrong is indistinguishable from one that works.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from kernel.redact import brief_error
from nodes.book_replica.clock import ClockMonitor
from nodes.book_replica.replica import BookReplica, Fault
from nodes.stream_kalshi.protocol import (TickerBook, parse, subscribe_frame,
                                          unsubscribe_frame, update_subscription_frame)

KALSHI_WS = "wss://api.elections.kalshi.com/trade-api/ws/v2"
WS_PATH = "/trade-api/ws/v2"


def ws_headers(api_key: str, private_key: Any, now_ms: int | None = None) -> dict[str, str]:
    """RSA-PSS SHA-256 headers for GET /trade-api/ws/v2.

    Every Kalshi socket is authenticated at the upgrade, even for public market data. The key
    object is injected rather than read here, so the signing input is fixture-testable without
    touching a credential.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    timestamp = str(int(time.time() * 1000) if now_ms is None else int(now_ms))
    message = (timestamp + "GET" + WS_PATH).encode()
    signature = private_key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
        hashes.SHA256())
    return {"KALSHI-ACCESS-KEY": api_key,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode()}


def load_private_key(path: Path):
    from cryptography.hazmat.primitives import serialization
    return serialization.load_pem_private_key(Path(path).read_bytes(), None)


@dataclass
class Registration:
    replica: BookReplica
    outcome: str                 # "yes" | "no" -- which side of the Kalshi market this replica is
    on_update: Callable[[str, float], None] | None = None


@dataclass
class KalshiStream:
    """Shared socket + subscription set. Transport around `protocol`."""
    api_key: str = ""
    private_key: Any = None
    url: str = KALSHI_WS

    books: dict[str, TickerBook] = field(default_factory=dict)
    regs: dict[str, list[Registration]] = field(default_factory=dict)   # ticker -> registrations
    connected: bool = False
    resubscribe_needed: bool = False
    #: A `nodes/capture.FrameWriter`, or None. Raw frames go here before they are parsed.
    capture: Any = None
    #: Last seq seen on the subscription. Not per ticker -- see the module docstring.
    #: Last seq PER SID. A second `subscribe` on one socket opens a second subscription with
    #: its own sequence; one socket-wide counter would alias the new sid's 1,2,3 under the
    #: old one's maximum and never see a gap on either. Keyed on sid; None for frames
    #: that carry none (a venue change, and a loud one).
    last_seq: dict[int | None, int] = field(default_factory=dict)
    clock: ClockMonitor = field(default_factory=ClockMonitor)
    #: The live subscription id from the venue's `subscribed` reply; None until acked or after
    #: a full resubscribe. Slate changes go through update_subscription on this sid.
    sid: int | None = None
    #: ticker -> the sid whose snapshot the stream's folded book for that ticker descends from.
    #: Cleared with every new socket, resubscribe and gap: after any of those the folded book
    #: is not a seed until the venue snapshots it again.
    snapshotted: dict[str, int | None] = field(default_factory=dict)
    _msg_id: int = 1

    frames: int = 0
    snapshots: int = 0
    seeded: int = 0
    deltas: int = 0
    gaps: int = 0
    errors: int = 0
    last_frame_utc: float = 0.0
    last_error: str = ""

    # ── subscription set ────────────────────────────────────────────────
    def register(self, ticker: str, replica: BookReplica, outcome: str = "yes",
                 on_update: Callable[[str, float], None] | None = None,
                 now: float | None = None) -> None:
        self.regs.setdefault(ticker, []).append(Registration(replica, outcome, on_update))
        # A slate change is a DIFF the run loop sends as update_subscription. Only a sequence
        # gap sets `resubscribe_needed`, which tears the subscription down instead.
        #
        # A ticker the socket ALREADY carries gets no second snapshot: the venue snapshots a
        # market once per subscription, and the diff above only adds what is new. Tennis lives
        # on the capture watchlist from discovery, hours before its match goes live, so the
        # poller's replica registered at first serve waited NOT_SYNCED for a reconnect that
        # never came -- 25,563 tennis evaluations across every match that went live after the
        # lane started (2026-09-05/06, ledger F5). The stream's own folded book IS that snapshot
        # plus every sequence-checked delta since, so the late replica is seeded from it at the
        # subscription's current seq. Not after a gap or on a fresh socket: then nothing is a
        # seed until the venue snapshots the ticker again.
        book = self.books.get(ticker)
        if (book is not None and self.connected and self.sid is not None
                and not self.resubscribe_needed and ticker in self.snapshotted
                and self.snapshotted[ticker] == self.sid):
            bids, asks = book.project(outcome)
            replica.snapshot_in(bids, asks, seq=self.last_seq.get(self.sid), now=now or time.time())
            self.seeded += 1

    def unregister(self, ticker: str) -> None:
        self.regs.pop(ticker, None)
        self.books.pop(ticker, None)
        self.snapshotted.pop(ticker, None)

    @property
    def tickers(self) -> list[str]:
        return sorted(self.regs)

    # ── the message path (pure, testable without a socket) ──────────────
    def handle(self, msg: dict, *, now: float | None = None, mono: float | None = None) -> str:
        """Fold one frame into the books and push the result into every registered replica."""
        t = now or time.time()
        self.frames += 1
        self.last_frame_utc = t
        p = parse(msg, self.books)
        if p.kind == "delta":
            self.clock.observe(t, p.server_utc)

        # ANY frame proves the SOCKET is alive, so it refreshes liveness for every replica on it --
        # not just the ticker that moved. The connection is shared; a market with no activity is
        # quiet, not disconnected, and conflating the two is what makes a streaming collector
        # refuse to serve a perfectly good book. Liveness is per connection; freshness
        # (`updated_utc`) stays per market and is only touched by that market's own events.
        for regs in self.regs.values():
            for reg in regs:
                reg.replica.heartbeat(t)

        if p.kind == "subscribed":
            if p.sid is not None:
                self.sid = p.sid
            return p.kind
        if p.kind in ("error", "ignored"):
            self.errors += 1
            self.last_error = f"{p.kind}: {p.detail}"
            return p.kind

        # Subscription-level gap check, BEFORE anything is applied. A lost message may have
        # belonged to any ticker on this socket, so the whole set is suspect. An `ok` reply to
        # update_subscription CONSUMES a seq (probed live), so it is counted here too.
        if p.seq is not None:
            last = self.last_seq.get(p.sid)
            if last is not None and p.seq > last + 1:
                self.gaps += 1
                self.last_error = (f"subscription seq gap on sid {p.sid}: expected {last + 1}, "
                                   f"got {p.seq} (on {p.ticker})")
                self.resubscribe_needed = True
                for regs in self.regs.values():
                    for reg in regs:
                        reg.replica.invalidate(Fault.SEQ_GAP)
                # Re-anchor rather than hold the old baseline. Everything is already invalidated
                # and a resubscribe is tripped; the next frames re-establish the sequence, and
                # holding a stale baseline would report a second gap for the same loss.
                self.last_seq.pop(p.sid, None)
                self.snapshotted.clear()
                return "gap"
            if last is None or p.seq > last:
                self.last_seq[p.sid] = p.seq
        if p.kind == "heartbeat":
            return p.kind

        book = self.books.get(p.ticker)
        if book is None:
            return "ignored"
        if p.kind == "snapshot":
            self.snapshotted[p.ticker] = p.sid
        projected: dict[str, tuple] = {}
        callbacks = []
        for reg in self.regs.get(p.ticker, ()):
            if reg.outcome not in projected:                  # two registrations per ticker: sort once
                projected[reg.outcome] = book.project(reg.outcome)
            bids, asks = projected[reg.outcome]
            if p.kind == "snapshot":
                reg.replica.snapshot_in(bids, asks, seq=p.seq, now=t, server_utc=p.server_utc, mono=mono)
                self.snapshots += 1
            else:
                reg.replica.project_in(bids, asks, seq=p.seq, now=t, server_utc=p.server_utc, mono=mono)
                self.deltas += 1
            if reg.on_update and all(reg.on_update is not callback for callback in callbacks):
                callbacks.append(reg.on_update)
        # One ticker can feed both the primary YES and complementary NO replicas for a game.
        # Apply the complete frame to every registration before any callback may freeze/price it.
        for callback in callbacks:
            callback(p.ticker, t)
        return p.kind

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def stats(self) -> dict:
        return {"connected": self.connected, "tickers": len(self.regs), "frames": self.frames,
                "snapshots": self.snapshots, "seeded": self.seeded, "deltas": self.deltas, "seq_gaps": self.gaps,
                "sid": self.sid, "sids": sorted(k for k in self.last_seq if k is not None),
                "errors": self.errors, "last_error": self.last_error, "clock": self.clock.stats(),
                "age_s": round(time.time() - self.last_frame_utc, 2) if self.last_frame_utc else None}

    # ── transport ───────────────────────────────────────────────────────
    async def run(self, stop: asyncio.Event, *, connect=None, recv_timeout: float = 30.0,
                  on_state: Callable[[str, str], None] | None = None) -> None:
        """Connect, subscribe, pump. Reconnects with backoff until `stop` is set.

        `connect` is injectable so the loop can be driven by a fake in tests -- the reconnect and
        resubscribe logic is exactly the part that is never exercised by a happy-path integration
        test and is where a streaming collector actually fails.
        """
        import websockets
        connect = connect or (lambda url, headers: websockets.connect(
            url, additional_headers=headers, ping_interval=20, max_size=2 ** 23))
        backoff = 1.0
        while not stop.is_set():
            if not self.regs:
                await asyncio.sleep(1.0)      # nothing to subscribe: no handshake, no idle socket
                continue
            try:
                headers = ws_headers(self.api_key, self.private_key)
                async with connect(self.url, headers) as ws:
                    self.connected = True
                    self.last_seq.clear()         # a new socket restarts every sequence
                    self.snapshotted.clear()      # and nothing folded before it is a seed
                    backoff = 1.0
                    if on_state:
                        on_state("connected", f"{len(self.regs)} tickers")
                    subscribed: set[str] = set()
                    self.sid = None
                    while not stop.is_set():
                        want = set(self.tickers)
                        if self.resubscribe_needed and subscribed:
                            # A gap: every replica is already invalidated. Tear the
                            # subscription down and open a fresh one -- fresh snapshots, fresh seq.
                            self.resubscribe_needed = False
                            if self.sid is not None:
                                await ws.send(json.dumps(unsubscribe_frame([self.sid], self._next_id())))
                            self.sid = None
                            self.snapshotted.clear()
                            subscribed = set()
                        if not subscribed and want:
                            self.resubscribe_needed = False
                            await ws.send(json.dumps(subscribe_frame(want, self._next_id())))
                            subscribed = set(want)
                        elif not want:
                            await asyncio.sleep(0.5)
                            continue
                        elif want != subscribed and self.sid is not None:
                            # A slate change costs one frame on the existing sid (probed live);
                            # a second `subscribe` would open a second sid and duplicate frames.
                            added, gone = want - subscribed, subscribed - want
                            if added:
                                await ws.send(json.dumps(update_subscription_frame(
                                    self.sid, added, "add_markets", self._next_id())))
                            if gone:
                                await ws.send(json.dumps(update_subscription_frame(
                                    self.sid, gone, "delete_markets", self._next_id())))
                            subscribed = set(want)
                        raw = await asyncio.wait_for(ws.recv(), timeout=recv_timeout)
                        t_recv, m_recv = time.time(), time.monotonic()
                        if self.capture is not None:
                            # BEFORE parse: a parse bug is what you most want to replay. The
                            # same timestamp feeds handle(), so a replay reproduces the row.
                            self.capture.write(raw, received_utc=t_recv, received_mono=m_recv)
                        self.handle(json.loads(raw), now=t_recv, mono=m_recv)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 -- reconnect is the whole job
                self.connected = False
                self.errors += 1          # a reconnect is an error: socket_health.errors must climb with it
                self.last_error = brief_error(exc)
                if on_state:
                    on_state("reconnect", self.last_error)
                # Replicas stop serving books on heartbeat timeout; make it immediate and explicit.
                for regs in self.regs.values():
                    for r in regs:
                        r.replica.disconnected()
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 2)
        self.connected = False
