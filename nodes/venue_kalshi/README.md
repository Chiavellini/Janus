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

`kalshi_book(payload, side, fetched_utc)` → `Book`; `fetch_kalshi_books(tickers, client)`;
`fetch_kalshi_series(ticker, client)` and `kalshi_fee_params(series)` → `{fee_type, fee_multiplier}`
or `None`. `adapter.py` registers the venue (`data_quality="live"`, `kalshi_clob`).

**The multiplier is per series and it is not 1.0 for sports.** KXMLBGAME: `quadratic_with_maker_fees`,
0.5 (2026-09-02). A `None` from `kalshi_fee_params` must block the leg, never fall back to the pin.

## Failure modes

**`orderbook_fp` carries `yes_dollars` AND `no_dollars`, and both are BID ladders.** There are no
asks in the payload. A YES ask at p exists only as a NO bid at 1−p; asks are synthesised with
`fold_complement_bids`. Read naively you see half the market.

`depth=20` is requested and `Book.depth_truncated` is never set, so a truncated ladder is
indistinguishable from an exhausted one.

## Tests

`tests/test_books.py` (the fold, the complementary NO ladder), `tests/test_series.py` (fee
params, registration), and `nodes/cover/tests/test_cover.py`.
