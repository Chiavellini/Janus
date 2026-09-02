# stream_kalshi

**Kind:** `source` (transport) + `pure` (`protocol.py`)
**Implements:** `protocol.py` (wire format, offline), `stream.py` (socket, auth, recovery)

**One authenticated socket, many markets, feeding many replicas.**

## Position in the grid

```
Kalshi WS ──▶ [protocol] ──▶ TickerBook (yes/no bid ladders)
                                  │ project + fold
                                  ▼
              [stream] ──▶ book_replica × N ──▶ [game_poller]
                  │
                  └── subscription seq gap ──▶ invalidate ALL ──▶ resubscribe
```

**Upstream:** `wss://api.elections.kalshi.com/trade-api/ws/v2`. **Downstream:** `nodes/book_replica`.

## One connection, not one per game

Kalshi authenticates at the HTTP upgrade — RSA-PSS SHA-256 over `timestamp + "GET" + path` — and
multiplexes by `market_ticker`. A socket per game would mean one RSA handshake per game and N
connections against the venue's limit, for nothing. `nodes/game_poller` registers replicas and is
fed.

## Measured against the live socket, 2026-09-02

**2,544 frames in 20s, 84.5 replica updates/second, zero sequence gaps.** The REST poller it
replaces managed one sample per 17 seconds.

Two findings from that session, both now pinned by tests:

**1. `seq` is per SUBSCRIPTION, not per market.** Four tickers on one subscription produced
snapshots at seq 1,2,3,4 then deltas 5,6,7… globally contiguous and interleaved. Each individual
ticker sees a legitimately non-contiguous subsequence — ATH got 1,10,11,13,15,17. A per-market seq
check therefore reports a gap on almost every message, which is what the first live run did.

So this node owns the check, because the sequence is a property of the *connection*. And the
recovery is blunt on purpose: a gap means some message was lost and **nothing says which market it
belonged to**, so every replica on the socket is invalidated and a resubscribe is tripped. A
cleverer partial recovery that is subtly wrong is indistinguishable from one that works.

**2. Any frame proves liveness for every replica on the socket.** Two quiet tickers went
`HEARTBEAT_LOST` on a healthy socket carrying 2,500 frames, purely because no event named *them*.
Liveness belongs to the connection; freshness belongs to the market.

## The three wire traps

All produce a confident wrong number rather than an error, which is why `protocol.py` is split out
and tested offline:

1. **Both ladders are bids.** Kalshi ships `yes` and `no` bid ladders and no asks. A YES ask at p
   exists only as a NO bid at 1−p. Read them as bid/ask and you see half the market.
2. **Deltas are signed changes, not sizes.** `delta` is added to the level's current size.
3. **One message moves both sides.** Because YES asks fold from NO bids, a `no`-side delta changes
   the YES book's *asks* — so an update cannot be expressed as `(side, price, size)` edits. That is
   what `BookReplica.project_in` exists for.

Prices are probabilities in [0,1]; a `40` is rejected as an API change, not read as 40¢.

## Tests

`tests/test_protocol.py` (12) + `tests/test_stream.py` (17), including the interleaved-subscription
case that the naive per-market check fails, reconnect marking every replica disconnected, and that
the signing input verifies against `timestamp + GET + path`.
