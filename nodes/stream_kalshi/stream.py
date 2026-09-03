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
from nodes.book_replica.replica import BookReplica, Fault
from nodes.stream_kalshi.protocol import (TickerBook, parse, subscribe_frame)

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
    on_update: Callable[[str], None] | None = None


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
    #: Last seq seen on the subscription. Not per ticker -- see the module docstring.
    last_seq: int | None = None

    frames: int = 0
    snapshots: int = 0
    deltas: int = 0
    gaps: int = 0
    errors: int = 0
    last_frame_utc: float = 0.0
    last_error: str = ""

    # ── subscription set ────────────────────────────────────────────────
    def register(self, ticker: str, replica: BookReplica, outcome: str = "yes",
                 on_update: Callable[[str], None] | None = None) -> None:
        self.regs.setdefault(ticker, []).append(Registration(replica, outcome, on_update))
        self.resubscribe_needed = True

    def unregister(self, ticker: str) -> None:
        self.regs.pop(ticker, None)
        self.books.pop(ticker, None)
        self.resubscribe_needed = True

    @property
    def tickers(self) -> list[str]:
        return sorted(self.regs)

    # ── the message path (pure, testable without a socket) ──────────────
    def handle(self, msg: dict, *, now: float | None = None) -> str:
        """Fold one frame into the books and push the result into every registered replica."""
        t = now or time.time()
        self.frames += 1
        self.last_frame_utc = t
        p = parse(msg, self.books)

        # ANY frame proves the SOCKET is alive, so it refreshes liveness for every replica on it --
        # not just the ticker that moved. The connection is shared; a market with no activity is
        # quiet, not disconnected, and conflating the two is what makes a streaming collector
        # refuse to serve a perfectly good book. Liveness is per connection; freshness
        # (`updated_utc`) stays per market and is only touched by that market's own events.
        for regs in self.regs.values():
            for reg in regs:
                reg.replica.heartbeat(t)

        if p.kind == "heartbeat":
            return p.kind
        if p.kind in ("error", "ignored"):
            self.errors += 1
            self.last_error = f"{p.kind}: {p.detail}"
            return p.kind

        # Subscription-level gap check, BEFORE anything is applied. A lost message may have
        # belonged to any ticker on this socket, so the whole set is suspect.
        if p.seq is not None:
            if self.last_seq is not None and p.seq > self.last_seq + 1:
                self.gaps += 1
                self.last_error = (f"subscription seq gap: expected {self.last_seq + 1}, "
                                   f"got {p.seq} (on {p.ticker})")
                self.resubscribe_needed = True
                for regs in self.regs.values():
                    for reg in regs:
                        reg.replica.invalidate(Fault.SEQ_GAP)
                # Re-anchor rather than hold the old baseline. Everything is already invalidated
                # and a resubscribe is tripped; the next frames re-establish the sequence, and
                # holding a stale baseline would report a second gap for the same loss.
                self.last_seq = None
                return "gap"
            if self.last_seq is None or p.seq > self.last_seq:
                self.last_seq = p.seq

        book = self.books.get(p.ticker)
        if book is None:
            return "ignored"
        for reg in self.regs.get(p.ticker, ()):
            bids, asks = book.project(reg.outcome)
            if p.kind == "snapshot":
                reg.replica.snapshot_in(bids, asks, seq=p.seq, now=t)
                self.snapshots += 1
            else:
                reg.replica.project_in(bids, asks, seq=p.seq, now=t)
                self.deltas += 1
            if reg.on_update:
                reg.on_update(p.ticker)
        return p.kind

    def stats(self) -> dict:
        return {"connected": self.connected, "tickers": len(self.regs), "frames": self.frames,
                "snapshots": self.snapshots, "deltas": self.deltas, "seq_gaps": self.gaps,
                "errors": self.errors, "last_error": self.last_error,
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
            try:
                headers = ws_headers(self.api_key, self.private_key)
                async with connect(self.url, headers) as ws:
                    self.connected = True
                    self.last_seq = None          # a new socket restarts the sequence
                    backoff = 1.0
                    if on_state:
                        on_state("connected", f"{len(self.regs)} tickers")
                    subscribed: set[str] = set()
                    while not stop.is_set():
                        if self.resubscribe_needed or set(self.tickers) != subscribed:
                            subscribed = set(self.tickers)
                            self.resubscribe_needed = False
                            if subscribed:
                                await ws.send(json.dumps(subscribe_frame(subscribed)))
                            else:
                                await asyncio.sleep(0.5)
                                continue
                        raw = await asyncio.wait_for(ws.recv(), timeout=recv_timeout)
                        self.handle(json.loads(raw))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 -- reconnect is the whole job
                self.connected = False
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
