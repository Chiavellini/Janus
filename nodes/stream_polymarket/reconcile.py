#!/usr/bin/env python3
"""The REST backstop: an outside check on a Polymarket replica that nothing else is verifying.

The per-message top-of-book check keeps an ACTIVELY traded market verified on its own traffic. A
quiet market gets no price_change frames, so nothing verifies it, and it decays to
UNVERIFIED_TOO_LONG -- correctly, and permanently. `BookReplica.reconcile` has existed for this
since the replica was written; it had no production caller. This is the caller.

Selection is deliberate: only replicas that are SYNCED and past half their unverified budget are
fetched. Reconciling a busy market against REST would report timing skew as drift every few
seconds; the busy market is already verified by the stream and needs nothing from here. A
disagreement is adopted from REST and REPORTED (`HASH_MISMATCH` on the replica, `rest_drift` in
the stats) -- the book is then labelled `source="rest"` and `nodes/game_poller` holds it to the
stricter REST freshness bound.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable

from kernel.redact import brief_error
from nodes.book_replica.replica import Fault, ReplicaState


def due(regs: dict, now: float, *, fraction: float = 0.5) -> list[str]:
    """PURE. Asset ids whose replicas are SYNCED and past `fraction` of their unverified budget."""
    out = []
    for asset_id, rs in regs.items():
        for reg in rs:
            r = reg.replica
            if r.state is ReplicaState.SYNCED and (now - r.verified_utc) > fraction * r.max_unverified_s:
                out.append(asset_id)
                break
    return sorted(out)


@dataclass
class Reconciler:
    """Drives `due` on a period against a `fetch(asset_id) -> (bids, asks)` callable."""
    stream: object
    fetch: Callable[[str], tuple[list, list]]
    period_s: float = 5.0
    reconciles: int = 0
    rest_drift: int = 0
    errors: int = 0
    last_error: str = ""
    last_run_utc: float = 0.0
    drifted: list[str] = field(default_factory=list)

    def fetch_due(self, now: float | None = None) -> tuple[float, dict[str, tuple[list, list]]]:
        """The network half: fetch every due replica's book. Safe in a worker thread; touches no
        replica and no callback."""
        t = now or time.time()
        books: dict[str, tuple[list, list]] = {}
        for asset_id in due(self.stream.regs, t):
            try:
                books[asset_id] = self.fetch(asset_id)
            except Exception as exc:  # noqa: BLE001 -- one failed fetch must not stop the pass
                self.errors += 1
                self.last_error = brief_error(exc)
        return t, books

    def apply(self, books: dict[str, tuple[list, list]], *, now: float, mono: float | None = None) -> list[str]:
        """The state half: adopt each fetched book and tell the poller. MUST run on the event-loop
        thread: `on_update` records to the tuple store, whose sqlite connection belongs to that
        thread (2026-09-03: run in the worker thread, every reconciled evaluation died on
        ProgrammingError and was lost)."""
        m = mono if mono is not None else time.monotonic()
        done = []
        for asset_id, (bids, asks) in books.items():
            for reg in self.stream.regs.get(asset_id, ()):
                fault = reg.replica.reconcile(bids, asks, now=now, mono=m)
                self.reconciles += 1
                if fault is Fault.HASH_MISMATCH:
                    self.rest_drift += 1
                    self.drifted.append(asset_id)
                    self.drifted = self.drifted[-20:]
                if reg.on_update:
                    reg.on_update(asset_id, now)
            done.append(asset_id)
        self.last_run_utc = now
        return done

    def once(self, now: float | None = None, mono: float | None = None) -> list[str]:
        """One pass, synchronous, on the calling thread. Returns the asset ids reconciled."""
        t, books = self.fetch_due(now)
        return self.apply(books, now=t, mono=mono)

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                t, books = await asyncio.to_thread(self.fetch_due)
                self.apply(books, now=t)
            except Exception as exc:  # noqa: BLE001
                self.errors += 1
                self.last_error = brief_error(exc)
            await asyncio.sleep(self.period_s)

    def stats(self) -> dict:
        return {"reconciles": self.reconciles, "rest_drift": self.rest_drift, "errors": self.errors,
                "last_error": self.last_error, "last_run_utc": self.last_run_utc}
