#!/usr/bin/env python3
"""A live order book held in memory, and -- the point of this node -- whether it can be trusted.

A streaming replica fails differently from a polled book. A poll either returns a book or raises.
A replica drifts: you miss one delta and every quote after it is quietly wrong, in a way that
looks exactly like a real price move. For an arbitrage system that is the worst failure available,
because a desynced book does not merely go stale -- it MANUFACTURES gaps that were never there,
and it does so most often when the market is moving fastest and the deltas are densest.

So the replica does not expose prices. It exposes a STATE, and only one state yields a book:

    DISCONNECTED --> CONNECTING --> SNAPSHOT_PENDING --> SYNCED
                                          ^               |
                                          +-- RESYNCING <-+   seq gap, hash mismatch,
                                                              heartbeat loss, age bound

`snapshot()` returns a Book ONLY from SYNCED and only inside the freshness bound. Every other state
returns None, which callers must treat as a BLOCK rather than a stale price -- the same rule
screen/cover.py already applies to a stale leg.

THE TWO VENUES ARE NOT SYMMETRIC, and this is the single most important fact about streaming here.
Kalshi's orderbook_delta carries a monotonic `seq`, so a gap is detectable at the protocol level:
miss one and you KNOW. Polymarket's market channel has no sequence number at all -- its `book` and
`price_change` events carry a `hash` whose verification mechanism is undocumented, and there is no
documented resynchronisation protocol. A Polymarket replica therefore cannot prove it is in sync
from the stream alone; it needs a bounded-interval REST reconciliation as an outside check. That
asymmetry is expressed here as `max_unverified_s`: Kalshi can run on sequence alone, Polymarket
must be re-anchored on a timer or it decays to RESYNCING by construction.

LIVENESS IS NOT FRESHNESS. Under polling, an old timestamp means a stale book. Under streaming, a
book that has not updated in ten minutes may be perfectly current -- nothing happened -- or the
connection may have died silently. The book's own timestamp cannot tell those apart; only a
heartbeat can. That distinction is exactly the shape of the failure that let a collector crash-loop
for thirteen days looking like a quiet market, so liveness is tracked per CONNECTION and pushed in
via `heartbeat()`, never inferred from the age of the last book event.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from kernel.schema import Book, Quote


class ReplicaState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    SNAPSHOT_PENDING = "SNAPSHOT_PENDING"
    SYNCED = "SYNCED"
    RESYNCING = "RESYNCING"


#: States that can never yield a book. Anything not SYNCED is a BLOCK, not a stale price.
UNUSABLE = frozenset(ReplicaState) - {ReplicaState.SYNCED}


class Fault(str, Enum):
    SEQ_GAP = "SEQ_GAP"                    # kalshi: a delta was missed; the book is now fiction
    HASH_MISMATCH = "HASH_MISMATCH"        # polymarket: reconciliation disagreed with the stream
    HEARTBEAT_LOST = "HEARTBEAT_LOST"      # the connection is dead, not the market quiet
    UNVERIFIED_TOO_LONG = "UNVERIFIED_TOO_LONG"   # polymarket: no outside check within the bound
    STALE = "STALE"                        # SYNCED but known current longer ago than the caller's bound (see as_of)
    NOT_SYNCED = "NOT_SYNCED"              # never reached SYNCED
    CROSSED_BOOK = "CROSSED_BOOK"          # best bid >= best ask: the replica is incoherent


@dataclass
class BookReplica:
    """One venue's book for one market, plus the evidence that it is still real."""
    venue: str
    market_id: str

    #: HOW this replica proves it is still in sync. Measured against both venues, 2026-09-02:
    #:
    #:   "own_sequence" -- the venue sequences PER MARKET, so the replica can check its own seq.
    #:                     No venue here does this; kept because it is the natural default and a
    #:                     venue that behaves this way should not need a transport to help.
    #:   "stream"       -- the TRANSPORT verifies, and the replica trusts it. Kalshi: its `seq` is
    #:                     per SUBSCRIPTION, not per market. Four tickers on one socket produce a
    #:                     globally contiguous 1,2,3,4,5... so every individual ticker sees a
    #:                     legitimately non-contiguous subsequence. Checking seq per market would
    #:                     report a gap on essentially every message.
    #:   "external"     -- nothing in the stream proves anything; an outside REST check must land
    #:                     within `max_unverified_s`. Polymarket: no sequence number exists at all.
    verification: str = "own_sequence"
    #: "external" only: how long a replica may run without an outside REST check before it is no
    #: longer trusted.
    max_unverified_s: float = 30.0
    #: How long without a connection heartbeat before the venue is presumed dead.
    heartbeat_timeout_s: float = 15.0

    state: ReplicaState = ReplicaState.DISCONNECTED
    last_fault: Fault | None = None
    seq: int | None = None
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)

    updated_utc: float = 0.0        # last book mutation
    #: Provenance of the ladder currently held (kernel.schema.Book carries the same three).
    source: str = "ws"              # "ws" from the socket, "rest" after a reconcile adopted REST
    server_utc: float | None = None # the venue's own stamp on the last mutation, when it sends one
    received_mono: float | None = None  # local monotonic clock at the last mutation
    verified_utc: float = 0.0       # last snapshot or successful reconciliation
    heartbeat_utc: float = 0.0      # last sign of life from the CONNECTION

    resyncs: int = 0
    seq_gaps: int = 0
    applied: int = 0

    # ── connection lifecycle ────────────────────────────────────────────
    def connecting(self, now: float | None = None) -> None:
        self.state = ReplicaState.CONNECTING
        self.heartbeat_utc = now or time.time()

    def subscribed(self, now: float | None = None) -> None:
        """Subscribed, awaiting the first snapshot. Deltas before it MUST be discarded."""
        self.state = ReplicaState.SNAPSHOT_PENDING
        self.heartbeat_utc = now or time.time()

    def heartbeat(self, now: float | None = None) -> None:
        """Proof the CONNECTION is alive. Not proof the book changed."""
        self.heartbeat_utc = now or time.time()

    def disconnected(self, now: float | None = None) -> None:
        self.state = ReplicaState.DISCONNECTED
        self.seq = None
        self.bids.clear()
        self.asks.clear()
        self.updated_utc = self.verified_utc = 0.0

    # ── currency ────────────────────────────────────────────────────────
    def as_of(self) -> float:
        """The instant this book is known to be the venue's book.

        Under streaming the age of the last MUTATION is not the age of the KNOWLEDGE. A book that
        has not moved in a minute on a live, sequence-checked socket is the venue's book as of the
        last frame on that socket: every change would have arrived as a delta, and a lost one
        shows as a gap (Kalshi) or a top-of-book hash miss and a REST check (Polymarket). So
        currency is the latest of the last mutation, the last verification and the last sign of
        life from the connection, and `check()` measures its age bound from here.

        Measured 2026-09-05/06 (ledger F5): 331,743 college-football and 4,836 tennis evaluations
        were refused STALE on Kalshi books whose socket carried 250 frames a second -- quiet
        markets between plays and points, priced as if the feed had died. The hard bounds stay: a
        dead connection is HEARTBEAT_LOST at `heartbeat_timeout_s`, an externally verified replica
        decays to UNVERIFIED_TOO_LONG at `max_unverified_s`. A REST-adopted ladder counts the
        socket too: after the adoption the socket is the only source of change, the next
        top-of-book hash or REST check re-verifies it within the same bounds as any other book,
        and holding it STALE until a change arrived kept every quiet Polymarket draw and pre-game
        book blocked for hours (2026-09-07 14:00Z: 1,440 draw and ~2,500 MLB evaluations on the
        box). The `source` label stays on the Book so the provenance is visible downstream.
        """
        return max(self.updated_utc, self.verified_utc, self.heartbeat_utc)

    # ── data ────────────────────────────────────────────────────────────
    def _stamp(self, source: str, server_utc: float | None, mono: float | None) -> None:
        self.source = source
        self.server_utc = server_utc
        self.received_mono = mono

    def snapshot_in(self, bids, asks, *, seq: int | None = None,
                    now: float | None = None, server_utc: float | None = None,
                    mono: float | None = None) -> None:
        """Full book from the venue. The ONLY way into SYNCED."""
        t = now or time.time()
        self.bids = {float(p): float(s) for p, s in bids if float(s) > 0}
        self.asks = {float(p): float(s) for p, s in asks if float(s) > 0}
        self._stamp("ws", server_utc, mono)
        self.seq = seq
        self.state = ReplicaState.SYNCED
        self.last_fault = None
        self.updated_utc = self.verified_utc = self.heartbeat_utc = t

    def delta_in(self, changes, *, seq: int | None = None,
                 now: float | None = None, server_utc: float | None = None,
                 mono: float | None = None) -> Fault | None:
        """Apply incremental changes. `changes` is (side, price, size); size 0 removes the level.

        A sequence gap does NOT just drop the message -- it invalidates the whole book, because
        every level after the missed delta is now unverifiable. Returns the fault, if any.
        """
        t = now or time.time()
        if self.state is not ReplicaState.SYNCED:
            return Fault.NOT_SYNCED                  # deltas before the snapshot are discarded

        if self.verification == "own_sequence" and seq is not None and self.seq is not None:
            if seq <= self.seq:
                return None                          # duplicate or replay; ignore, stay synced
            if seq != self.seq + 1:
                self.seq_gaps += 1
                self._invalidate(Fault.SEQ_GAP)
                return Fault.SEQ_GAP

        for side, price, size in changes:
            book = self.bids if side == "bid" else self.asks
            p, s = float(price), float(size)
            if s <= 0:
                book.pop(p, None)
            else:
                book[p] = s
        if seq is not None:
            self.seq = seq
        self.applied += 1
        self._stamp("ws", server_utc, mono)
        self.updated_utc = self.heartbeat_utc = t
        if self.verification in ("own_sequence", "stream"):
            self.verified_utc = t
        return None

    def project_in(self, bids, asks, *, seq: int | None = None,
                   now: float | None = None, server_utc: float | None = None,
                   mono: float | None = None) -> Fault | None:
        """Full ladders derived from a venue delta: sequence-checked like a delta, applied whole.

        Kalshi needs this and `delta_in` cannot express it. Kalshi ships YES-bid and NO-bid
        ladders with a SIGNED per-level delta, and a YES ask exists only as a NO bid at 1-p -- so
        one delta message changes BOTH sides of the projected book at once. The caller owns the
        wire format and does the folding; the replica still owns the sequence check, because
        whether the book can be trusted is this node's job and not the transport's.
        """
        t = now or time.time()
        if self.state is not ReplicaState.SYNCED:
            return Fault.NOT_SYNCED
        if self.verification == "own_sequence" and seq is not None and self.seq is not None:
            if seq <= self.seq:
                return None                          # duplicate or replay
            if seq != self.seq + 1:
                self.seq_gaps += 1
                self._invalidate(Fault.SEQ_GAP)
                return Fault.SEQ_GAP
        self.bids = {float(p): float(s) for p, s in bids if float(s) > 0}
        self.asks = {float(p): float(s) for p, s in asks if float(s) > 0}
        if seq is not None:
            self.seq = seq
        self.applied += 1
        self._stamp("ws", server_utc, mono)
        self.updated_utc = self.heartbeat_utc = t
        if self.verification in ("own_sequence", "stream"):
            self.verified_utc = t
        return None

    def reconcile(self, bids, asks, *, now: float | None = None,
                  tolerance: float = 1e-9, server_utc: float | None = None,
                  mono: float | None = None) -> Fault | None:
        """Outside check against a REST snapshot. The only integrity proof Polymarket allows.

        Agreement re-verifies the replica. Disagreement is not repaired quietly -- the REST book
        is adopted and the divergence is reported, because a replica that silently self-heals
        hides the very drift this exists to catch.
        """
        t = now or time.time()
        want_b = {float(p): float(s) for p, s in bids if float(s) > 0}
        want_a = {float(p): float(s) for p, s in asks if float(s) > 0}
        agree = (self._close(self.bids, want_b, tolerance)
                 and self._close(self.asks, want_a, tolerance))
        self.bids, self.asks = want_b, want_a
        # Adopted from REST: the book is labelled so, and the caller holds it to the stricter
        # freshness bound a REST fallback gets (spec §8).
        self._stamp("rest", server_utc, mono)
        self.verified_utc = self.updated_utc = self.heartbeat_utc = t
        if agree:
            self.state = ReplicaState.SYNCED
            self.last_fault = None
            return None
        self.state = ReplicaState.SYNCED             # adopted truth, but the drift is recorded
        self.last_fault = Fault.HASH_MISMATCH
        self.resyncs += 1
        return Fault.HASH_MISMATCH

    @staticmethod
    def _close(a: dict, b: dict, tol: float) -> bool:
        if set(a) != set(b):
            return False
        return all(abs(a[k] - b[k]) <= tol for k in a)

    def stream_verified(self, now: float | None = None) -> None:
        """The TRANSPORT proved this replica is still correct, without a fresh snapshot.

        Polymarket needs this. It has no sequence number, so the replica is in "external" mode and
        decays to UNVERIFIED_TOO_LONG on a timer -- correct as a default, because nothing in the
        stream proves anything. But every price_change carries the venue's own best_bid/best_ask,
        and when the local top of book matches it, the replica HAS been verified from outside. The
        stream calls this on a passing check so an actively traded market stays alive on its own
        traffic, while a genuinely quiet one still decays and forces a resnapshot.

        This verifies the TOP of book only. A level drifting deeper is invisible to it, so a
        periodic REST reconcile remains the backstop for depth.
        """
        self.verified_utc = now or time.time()

    def invalidate(self, fault: Fault) -> None:
        """Public: the TRANSPORT found a problem this replica cannot see.

        Kalshi needs this. Its sequence is per subscription, so a gap means SOME message was lost
        and nothing says which market it belonged to -- every replica on that socket is suspect,
        and the one that can tell is the stream, not the book.
        """
        self._invalidate(fault)

    def _invalidate(self, fault: Fault) -> None:
        self.state = ReplicaState.RESYNCING
        self.last_fault = fault
        self.resyncs += 1
        self.seq = None
        self.bids.clear()
        self.asks.clear()

    # ── the gate ────────────────────────────────────────────────────────
    def check(self, now: float | None = None, *, max_age_s: float = 5.0) -> Fault | None:
        """Why this replica is unusable right now, or None if it is fine."""
        t = now or time.time()
        if t - self.heartbeat_utc > self.heartbeat_timeout_s:
            if self.state is ReplicaState.SYNCED:
                self._invalidate(Fault.HEARTBEAT_LOST)
            return Fault.HEARTBEAT_LOST
        if self.state is not ReplicaState.SYNCED:
            return self.last_fault or Fault.NOT_SYNCED
        if self.verification == "external" and (t - self.verified_utc) > self.max_unverified_s:
            return Fault.UNVERIFIED_TOO_LONG
        if t - self.as_of() > max_age_s:
            return Fault.STALE
        if self.bids and self.asks and max(self.bids) >= min(self.asks):
            return Fault.CROSSED_BOOK
        return None

    def snapshot(self, now: float | None = None, *, max_age_s: float = 5.0) -> Book | None:
        """A Book, or None. None is a BLOCK -- never substitute the last good book."""
        if self.check(now, max_age_s=max_age_s) is not None:
            return None
        return Book(
            bids=tuple(Quote(p, self.bids[p]) for p in sorted(self.bids, reverse=True)),
            asks=tuple(Quote(p, self.asks[p]) for p in sorted(self.asks)),
            fetched_utc=self.as_of(), source=self.source, server_utc=self.server_utc,
            received_mono=self.received_mono)
