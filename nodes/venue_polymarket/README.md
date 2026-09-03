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

`pm_book(payload, fetched_utc)`, `fetch_pm_books(token_map, client)`, `pm_token_map(slugs, client)`,
`pm_market_for_slug(event, slug)`, `pm_fee_params(market)` → `{fee_rate, fee_exponent, taker_only,
rebate_rate}` or `None`, `pm_order_limits(market)` → `{min_order_contracts, tick}`. `adapter.py`
registers the venue (`pm_clob`).

**The fee is per market.** Gamma carries `feeSchedule` on each market (`sports_fees_v2`, rate 0.05
on game markets, 0.03 on a futures market, 2026-09-02). A `None` must block the leg.

## Failure modes

**Both ladders put the BEST price LAST.** `bids[0]` is the worst bid, `asks[0]` the worst ask.
Indexing `[0]` for "best" silently prices every trade at the far end of the book.

**The rate limiter QUEUES rather than rejecting**, so a throttled response is a stale quote wearing
a fresh wall-clock timestamp. `fetched_utc` is stamped at receipt, so a 4 s RTT yields a
"0-second-old" book. Staleness is currently measured against the newest leg, not the wall clock.

Books come back empty often enough to matter — one of the two recorded sports sweeps failed with
`insufficient_depth` for exactly this reason.

## Tests

`tests/test_books.py` (the reversed ladders, the fetch path that used to raise `NameError`, the
fee schedule, order limits, registration) and `nodes/cover/tests/test_cover.py`.
