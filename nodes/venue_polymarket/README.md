# venue_polymarket

**Kind:** `source` (fetch) + `pure` (parse)
**Implements:** `books.py`

Polymarket CLOB books and the Gamma token map.

## Position in the grid

```
PM CLOB + Gamma ──▶ [venue_polymarket] ──▶ Book(asks), token map ──▶ [cover]
```

**Upstream:** `clob.polymarket.com`, `gamma-api.polymarket.com`.
**Downstream:** `nodes/cover` via a grid.

## Contract

`pm_book(payload, fetched_utc)`, `fetch_pm_books(token_map, client)`, `pm_token_map(slugs, client)`.

## Failure modes

**Both ladders put the BEST price LAST.** `bids[0]` is the worst bid, `asks[0]` the worst ask.
Indexing `[0]` for "best" silently prices every trade at the far end of the book.

**The rate limiter QUEUES rather than rejecting**, so a throttled response is a stale quote wearing
a fresh wall-clock timestamp. `fetched_utc` is stamped at receipt, so a 4 s RTT yields a
"0-second-old" book. Staleness is currently measured against the newest leg, not the wall clock.

Books come back empty often enough to matter — one of the two recorded sports sweeps failed with
`insufficient_depth` for exactly this reason.

## Tests

`nodes/cover/tests/test_cover.py` covers the reversed-ladder trap.
