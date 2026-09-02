# venue_kalshi

**Kind:** `source` (fetch) + `pure` (parse)
**Implements:** `books.py`

Kalshi CLOB books. Prices are **probabilities in [0,1], not cents**, in 1¢ ticks — so the project's
1% return hurdle is exactly **one tick wide**.

## Position in the grid

```
Kalshi API ──▶ [venue_kalshi] ──▶ Book(asks) ──▶ [cover]
```

**Upstream:** `api.elections.kalshi.com`.
**Downstream:** `nodes/cover` via a grid.

## Contract

`kalshi_book(payload, side, fetched_utc)` → `Book`; `fetch_kalshi_books(tickers, client)`.

## Failure modes

**`orderbook_fp` carries `yes_dollars` AND `no_dollars`, and both are BID ladders.** There are no
asks in the payload. A YES ask at p exists only as a NO bid at 1−p; asks are synthesised with
`fold_complement_bids`. Read naively you see half the market.

`depth=20` is requested and `Book.depth_truncated` is never set, so a truncated ladder is
indistinguishable from an exhausted one.

## Tests

`nodes/cover/tests/test_cover.py` covers the parser (the bids-only fold).
