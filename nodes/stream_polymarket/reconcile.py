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


@dataclass(frozen=True)
class FetchTarget:
    asset_id: str
    versions: tuple[tuple[int, float], ...]


@dataclass(frozen=True)
class FetchedBook:
    bids: list
    asks: list
    received_utc: float
    received_mono: float
    versions: tuple[tuple[int, float], ...]


@dataclass
class Reconciler:
    """Drives `due` on a period against a `fetch(asset_id) -> (bids, asks)` callable."""
    stream: object
    fetch: Callable[[str], tuple[list, list]]
    period_s: float = 5.0
    reconciles: int = 0
    rest_drift: int = 0
    errors: int = 0
    superseded: int = 0
    last_error: str = ""
    last_run_utc: float = 0.0
    drifted: list[str] = field(default_factory=list)

    def prepare(self, now: float | None = None) -> list[FetchTarget]:
        """Select work and snapshot replica versions on the event-loop thread."""
        t = now if now is not None else time.time()
        return [FetchTarget(asset_id, tuple((id(reg.replica), reg.replica.updated_utc)
                                            for reg in self.stream.regs.get(asset_id, ())))
                for asset_id in due(self.stream.regs, t)]

    def fetch_due(self, targets: list[FetchTarget], *, now: float | None = None,
                  mono: float | None = None) -> dict[str, FetchedBook]:
        """Network half. It receives immutable targets and never reads live replica state."""
        books: dict[str, FetchedBook] = {}
        for target in targets:
            try:
                bids, asks = self.fetch(target.asset_id)
                received_utc = now if now is not None else time.time()
                received_mono = mono if mono is not None else time.monotonic()
                books[target.asset_id] = FetchedBook(bids, asks, received_utc, received_mono,
                                                     target.versions)
            except Exception as exc:  # noqa: BLE001 -- one failed fetch must not stop the pass
                self.errors += 1
                self.last_error = brief_error(exc)
        return books

    def apply(self, books: dict[str, FetchedBook], *, now: float | None = None) -> list[str]:
        """The state half: adopt each fetched book and tell the poller. MUST run on the event-loop
        thread: `on_update` records to the tuple store, whose sqlite connection belongs to that
        thread (2026-09-03: run in the worker thread, every reconciled evaluation died on
        ProgrammingError and was lost)."""
        # L101 (2026-09-14): the replica keeps the stamp of when the book WAS TRUE
        # (`received_utc`), but the poller must be told the time it is being asked to price AT.
        # Passing the fetch stamp as "now" made every REST-reconciled evaluation compute
        # `now - as_of()` = 0.0, so `max_rest_book_age_s` (3.0 s) could not fire on this path at all.
        # And `fetch_due` fetches SEQUENTIALLY while the whole batch is applied afterwards, so the
        # first asset fetched was routinely seconds old by the time it priced: Polymarket-triggered
        # evaluations measured p90 3,543 ms, p99 6,341 ms, max 8,249 ms, on 10.7 % of all recorded
        # evaluations, every one of them reporting an age of zero.
        t_apply = now if now is not None else time.time()
        done = []
        for asset_id, fetched in books.items():
            versions = dict(fetched.versions)
            applied = False
            for reg in self.stream.regs.get(asset_id, ()):
                # A WS frame that landed while REST was in flight is strictly newer evidence.
                # Never let the delayed response overwrite it with an older ladder.
                if versions.get(id(reg.replica)) != reg.replica.updated_utc:
                    self.superseded += 1
                    continue
                fault = reg.replica.reconcile(fetched.bids, fetched.asks,
                                              now=fetched.received_utc, mono=fetched.received_mono)
                self.reconciles += 1
                applied = True
                if fault is Fault.HASH_MISMATCH:
                    self.rest_drift += 1
                    self.drifted.append(asset_id)
                    self.drifted = self.drifted[-20:]
                if reg.on_update:
                    reg.on_update(asset_id, t_apply)
            if applied:
                done.append(asset_id)
        self.last_run_utc = t_apply
        return done

    def once(self, now: float | None = None, mono: float | None = None) -> list[str]:
        """One pass, synchronous, on the calling thread. Returns the asset ids reconciled."""
        targets = self.prepare(now)
        books = self.fetch_due(targets, now=now, mono=mono)
        return self.apply(books, now=now)

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                targets = self.prepare()
                books = await asyncio.to_thread(self.fetch_due, targets)
                self.apply(books)
            except Exception as exc:  # noqa: BLE001
                self.errors += 1
                self.last_error = brief_error(exc)
            await asyncio.sleep(self.period_s)

    def stats(self) -> dict:
        return {"reconciles": self.reconciles, "rest_drift": self.rest_drift, "superseded": self.superseded,
                "errors": self.errors,
                "last_error": self.last_error, "last_run_utc": self.last_run_utc}
