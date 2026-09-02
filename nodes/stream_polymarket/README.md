# stream_polymarket

**Kind:** `source` (transport) + `pure` (`protocol.py`)
**Implements:** `protocol.py` (wire format, offline), `stream.py` (socket, PING, drift detection)

One market-channel socket, many assets, feeding many replicas. Same shape as `nodes/stream_kalshi`,
different in three ways that matter.

## The integrity problem, and the answer the docs don't mention

Polymarket has **no sequence number**, no documented resynchronisation protocol, and a `hash` field
whose verification mechanism is undocumented. Taken at face value a replica here cannot prove it is
in sync — which is why `BookReplica` has an `external` mode at all.

**But every `price_change` entry carries `best_bid` and `best_ask` for its own asset.** That is a
per-message integrity check the documentation never advertises: recompute the local top of book
after applying the change and compare.

Measured live 2026-09-02:

| run | checks | agreement | drift |
|---|---|---|---|
| 4 assets, 40s | 1,426 | **100%** | 0 |
| 4 assets, 45s (with Kalshi) | 4,534 | **99.87%** | 6, all resynced |
| 6 assets, 45s | 7,460 | 97.5–99.9% | all genuine |

Every disagreement was investigated and **every one was a genuinely incomplete local book** —
one-sided ladders on settled markets (72 bids / 0 asks at 0.999/1.00) where the venue's stated best
referenced a level we had never been sent. The check reports real drift, not false alarms.

Its limit, stated plainly: **it verifies the top of book only.** A level drifting deeper in the
ladder is invisible to it, and `nodes/cover` walks the ladder — so a periodic REST reconciliation
(`BookReplica.reconcile`) remains the backstop for depth. It is no longer the primary defence.

On mismatch the replica is invalidated and a resnapshot forced. A resync is cheap; a fabricated
gap is not.

## Three more wire traps

1. **`size` is ABSOLUTE, not a delta** — the opposite of Kalshi's signed `delta`. Adding it instead
   of replacing silently doubles resting size.
2. **Best price is LAST in both ladders** of a `book` event: bids ran 0.01 → 0.19, asks 0.99 → 0.20.
   Indexing `[0]` for "best" prices every trade at the far end of the book.
3. **`side` is `"BUY"`/`"SELL"`**, not bid/ask, and a subscribe answers with a **list** of `book`
   events rather than one object.

## Two transport requirements

**The client must PING.** The venue wants a text `PING` every 10 seconds and answers `PONG`. Miss it
and the socket drops — which under the old polling design would have looked like a quiet market.
The websockets library's own protocol ping is not this.

**Subscriptions are mutable.** Assets can be added and removed mid-connection, so a game starting or
ending costs one small frame rather than a reconnect and fresh snapshots for everything else.

## Tests

`tests/test_polymarket.py` — 20 tests, including that a missing level is caught as drift, that
drift invalidates and forces a resnapshot, and that a slate change uses an operation frame rather
than a reconnect.
