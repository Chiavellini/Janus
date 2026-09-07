# book_replica

**Kind:** `pure`
**Implements:** `replica.py`

A live order book held in memory, and — the point of this node — **whether it can be trusted right
now**. It does not expose prices; it exposes a *state*, and only one state yields a book.

## Position in the grid

```
[stream_kalshi]     ──▶ snapshot / delta ──▶ ┌──────────────┐
                                             │ book_replica │──▶ Book | None ──▶ [game_poller]
[stream_polymarket] ──▶ snapshot / delta ──▶ └──────────────┘
                    ──▶ REST reconcile ────▶        │
                                                    └── None = BLOCK, never a stale price
```

## The state machine

```
DISCONNECTED → CONNECTING → SNAPSHOT_PENDING → SYNCED
                                  ↑              │
                                  └── RESYNCING ←┘   seq gap · hash mismatch ·
                                                     heartbeat loss · age bound
```

`snapshot()` returns a `Book` only from `SYNCED`, inside the freshness bound, on a book that is not
crossed. The bound is measured from `as_of()` — the last proof the book is current (last mutation,
last verification, or last frame on a live socket, whichever is latest; a REST-adopted ladder
counts the socket too and keeps its `source` label) — not from the last mutation. A quiet in-play book on a
live socket is the venue's book; until 2026-09-07 it was refused `STALE` after 5 s. Everything else returns `None`, which callers treat as a BLOCK — the same rule
`nodes/cover` already applies to a stale leg.

## Why this node exists

A poll either returns a book or raises. **A replica drifts.** Miss one delta and every quote after
it is quietly wrong in a way that looks exactly like a real price move. For an arbitrage system
that is the worst failure available: a desynced book does not go stale, it **manufactures gaps that
were never there**, and it does so most often when the market is moving fastest and the deltas are
densest.

## The two venues are not symmetric

This is the single most important fact about streaming here.

| | Kalshi | Polymarket |
|---|---|---|
| Integrity | monotonic `seq`; a gap is detectable at the protocol level | **no sequence number**; a `hash` whose verification is undocumented |
| Resync | documented: stop, reconnect, resnapshot | **no documented protocol** |
| Consequence | sequence *is* the verification | needs a bounded-interval REST check, or it decays to unusable |

Expressed as `max_unverified_s`: Kalshi runs on sequence alone; Polymarket must be re-anchored on a
timer or `check()` returns `UNVERIFIED_TOO_LONG` by construction. A `reconcile()` that disagrees
adopts the REST book **and reports the drift** — a replica that silently self-heals hides exactly
what this exists to catch.

## Liveness is not freshness

Under polling, an old timestamp means a stale book. Under streaming, a book that has not updated in
ten minutes may be perfectly current — nothing happened — **or** the socket may have died silently.
The book's own timestamp cannot tell those apart; only a heartbeat can. So liveness is tracked per
*connection* and pushed in via `heartbeat()`, never inferred from the age of the last book event.

That distinction is the same shape as the failure that let a collector crash-loop for thirteen days
looking like a quiet market.

## Faults

`SEQ_GAP` · `HASH_MISMATCH` · `HEARTBEAT_LOST` · `UNVERIFIED_TOO_LONG` · `STALE` · `NOT_SYNCED` ·
`CROSSED_BOOK` (bid ≥ ask is a broken replica, not a 100% arbitrage).

## Tests

`tests/test_replica.py` — 17 tests, including that a quiet market and a dead socket are
distinguishable, that a sequence gap invalidates the whole book rather than one message, and that
deltas arriving before the snapshot are discarded rather than fabricating a one-sided market.

## Provenance and the clock (2026-09-02)

Every ladder the replica holds is stamped with where it came from and when: `source` (`"ws"`
from the socket, `"rest"` once `reconcile()` adopted a REST book), `server_utc` (the venue's own
timestamp when the frame carried one — Kalshi deltas `ts_ms`, Polymarket events `timestamp`;
None otherwise, never a local guess) and `received_mono` (the local monotonic clock). `snapshot()`
puts all three on the `Book`, so a REST fallback is visibly labelled downstream.

`clock.py` holds `ClockMonitor`: an EWMA of `received − server` per socket. Measured on both
venues the stamp runs 30–70 ms ahead of local receipt — the normal band. A skew of seconds is a
fault; the supervisor halts pricing on it, because every freshness bound is `now − updated_utc`
and a stepped clock makes every book fiction at once.
