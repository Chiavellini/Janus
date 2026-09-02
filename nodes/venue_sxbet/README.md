# venue_sxbet

**Kind:** `source` (fetch) + `pure` (parse)
**Implements:** `books.py`

SX Bet — a **zero-rake CLOB**, 0% commission on singles, the cheapest screening coefficient of any
two-sided venue in `nodes/fees/registry.py`.

This node is the intended third venue. Unlike a sportsbook it has two-sided depth, a real NO side,
and no counterparty discretion to reject a bet after seeing your stake.

## Position in the grid

```
SX Bet API ──▶ [venue_sxbet] ──▶ Book(asks) ──▶ [cover]
```

**Upstream:** `api.sx.bet` (V3).
**Downstream:** `nodes/cover` via a grid.

## Contract

`sx_book(orders, want_outcome_one, fetched_utc)`, `fetch_sx_mlb(client)`.

## Failure modes

**Not a ladder at all** — a list of resting maker orders. `percentageOdds` is the MAKER's implied
probability scaled by 1e20, and a taker buying outcome ONE lifts orders whose maker took outcome
TWO. So the taker pays `1 − makerOdds`, and `isMakerBettingOutcomeOne` selects the side. Getting
this backwards inverts every price and produces beautiful nonsense.

**Not yet wired into `grids/live_sports`** — only `grids/sports_books_poll` uses it.

## Tests

`nodes/cover/tests/test_cover.py` covers the maker/taker inversion.
