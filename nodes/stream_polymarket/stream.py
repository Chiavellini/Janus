#!/usr/bin/env python3
"""One Polymarket market-channel socket, many assets, feeding many replicas.

Same shape as `nodes/stream_kalshi` and different in three ways that matter.

NO SEQUENCE, SO THE TOP OF BOOK IS THE PROOF. There is no seq and no documented resync. What there
is -- undocumented -- is `best_bid`/`best_ask` on every `price_change`. This node recomputes the
local top after applying each change and compares. A mismatch is drift, not a price move, so the
replica is invalidated and a resnapshot is forced. Measured live over 7,460 checks the agreement
was 97.5-99.9% and every disagreement was a genuinely incomplete local book, so the check earns
its keep rather than crying wolf.

Its limit, stated plainly: it verifies the TOP of the book only. A level that drifts deeper is
invisible here and the cover engine walks the ladder, so a periodic REST reconciliation remains
the backstop for depth -- `BookReplica.reconcile` exists for exactly that and is driven from
outside this node.

THE CLIENT MUST PING. The venue requires a text `PING` every 10 seconds and answers `PONG`. Miss it
and the socket is dropped, which under the old polling design would have looked like a quiet market.

SUBSCRIPTIONS ARE MUTABLE. Assets can be added and removed mid-connection, so a game starting or
ending costs a small frame rather than a reconnect and a fresh set of snapshots for everything.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Callable

from nodes.book_replica.replica import BookReplica, Fault
from nodes.stream_polymarket.protocol import (AssetBook, PING, PONG, events_in, operation_frame,
                                              parse_event, subscribe_frame)

PM_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
PING_INTERVAL_S = 10.0


@dataclass
class Registration:
    replica: BookReplica
    on_update: Callable[[str], None] | None = None


@dataclass
class PolymarketStream:
    url: str = PM_WS

    books: dict[str, AssetBook] = field(default_factory=dict)
    regs: dict[str, list[Registration]] = field(default_factory=dict)     # asset_id -> regs
    connected: bool = False
    resubscribe_needed: bool = False

    frames: int = 0
    snapshots: int = 0
    changes: int = 0
    drift: int = 0
    errors: int = 0
    checks: int = 0
    agreed: int = 0
    last_frame_utc: float = 0.0
    last_error: str = ""

    # ── subscription set ────────────────────────────────────────────────
    def register(self, asset_id: str, replica: BookReplica,
                 on_update: Callable[[str], None] | None = None) -> None:
        self.regs.setdefault(asset_id, []).append(Registration(replica, on_update))
        self.resubscribe_needed = True

    def unregister(self, asset_id: str) -> None:
        self.regs.pop(asset_id, None)
        self.books.pop(asset_id, None)
        self.resubscribe_needed = True

    @property
    def asset_ids(self) -> list[str]:
        return sorted(self.regs)

    @property
    def agreement(self) -> float | None:
        return None if not self.checks else self.agreed / self.checks

    # ── the message path (pure, testable without a socket) ──────────────
    def handle(self, raw, *, now: float | None = None) -> list[str]:
        """Fold one frame into the books and push the result into every registered replica."""
        t = now or time.time()
        self.frames += 1
        self.last_frame_utc = t

        if isinstance(raw, str):
            if raw.strip() in (PONG, PING):
                self._beat(t)
                return ["pong"]
            try:
                raw = json.loads(raw)
            except ValueError:
                self.errors += 1
                self.last_error = "non-JSON frame"
                return ["error"]

        # Any frame proves the SOCKET is alive for every replica on it. A market with no activity
        # is quiet, not disconnected -- the same rule as the Kalshi stream.
        self._beat(t)

        kinds: list[str] = []
        for ev in events_in(raw):
            for p in parse_event(ev, self.books):
                kinds.append(p.kind)
                if p.kind == "error":
                    self.errors += 1
                    self.last_error = p.detail
                    continue
                if p.kind not in ("book", "change"):
                    continue
                book = self.books.get(p.asset_id)
                if book is None:
                    continue
                bids, asks = book.ladders()

                if p.kind == "book":
                    self.snapshots += 1
                    for reg in self.regs.get(p.asset_id, ()):
                        reg.replica.snapshot_in(bids, asks, seq=None, now=t)
                else:
                    self.changes += 1
                    # THE integrity check. Polymarket offers nothing else.
                    if p.claimed_bid is not None or p.claimed_ask is not None:
                        self.checks += 1
                        if book.agrees_with(p.claimed_bid, p.claimed_ask):
                            self.agreed += 1
                        else:
                            self.drift += 1
                            self.last_error = (
                                f"top-of-book drift on {p.asset_id[:12]}…: venue says "
                                f"{p.claimed_bid}/{p.claimed_ask}, local {book.best_bid}/{book.best_ask}")
                            self.resubscribe_needed = True
                            for reg in self.regs.get(p.asset_id, ()):
                                reg.replica.invalidate(Fault.HASH_MISMATCH)
                            continue
                    for reg in self.regs.get(p.asset_id, ()):
                        reg.replica.project_in(bids, asks, seq=None, now=t)

                for reg in self.regs.get(p.asset_id, ()):
                    if reg.on_update:
                        reg.on_update(p.asset_id)
        return kinds

    def _beat(self, t: float) -> None:
        for regs in self.regs.values():
            for reg in regs:
                reg.replica.heartbeat(t)

    def stats(self) -> dict:
        return {"connected": self.connected, "assets": len(self.regs), "frames": self.frames,
                "snapshots": self.snapshots, "changes": self.changes, "drift": self.drift,
                "errors": self.errors, "checks": self.checks,
                "agreement": None if self.agreement is None else round(self.agreement, 5),
                "last_error": self.last_error,
                "age_s": round(time.time() - self.last_frame_utc, 2) if self.last_frame_utc else None}

    # ── transport ───────────────────────────────────────────────────────
    async def run(self, stop: asyncio.Event, *, connect=None, recv_timeout: float = 30.0,
                  on_state: Callable[[str, str], None] | None = None) -> None:
        import websockets
        connect = connect or (lambda url: websockets.connect(url, ping_interval=None,
                                                             max_size=2 ** 23))
        backoff = 1.0
        while not stop.is_set():
            ping_task = None
            try:
                async with connect(self.url) as ws:
                    self.connected = True
                    backoff = 1.0
                    if on_state:
                        on_state("connected", f"{len(self.regs)} assets")

                    async def pinger():
                        # The venue requires this; websockets' own protocol ping is not it.
                        while True:
                            await asyncio.sleep(PING_INTERVAL_S)
                            await ws.send(PING)

                    ping_task = asyncio.create_task(pinger())
                    subscribed: set[str] = set()
                    while not stop.is_set():
                        want = set(self.asset_ids)
                        if self.resubscribe_needed or want != subscribed:
                            self.resubscribe_needed = False
                            if not want:
                                subscribed = set()
                                await asyncio.sleep(0.5)
                                continue
                            if not subscribed:
                                await ws.send(json.dumps(subscribe_frame(want)))
                            else:
                                added, gone = want - subscribed, subscribed - want
                                if added:
                                    await ws.send(json.dumps(operation_frame(added, "subscribe")))
                                if gone:
                                    await ws.send(json.dumps(operation_frame(gone, "unsubscribe")))
                            subscribed = want
                        raw = await asyncio.wait_for(ws.recv(), timeout=recv_timeout)
                        self.handle(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 -- reconnect is the whole job
                self.connected = False
                self.last_error = f"{type(exc).__name__}: {exc}"
                if on_state:
                    on_state("reconnect", self.last_error)
                for regs in self.regs.values():
                    for r in regs:
                        r.replica.disconnected()
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 2)
            finally:
                if ping_task:
                    ping_task.cancel()
        self.connected = False
