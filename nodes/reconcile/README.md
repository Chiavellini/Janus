# reconcile

**Kind:** `pure`
**Implements:** `reconcile.py`

The venue's word on every order, fill, fee and settlement, before any capital is released and
before any PnL is believed (spec §1.7, §10, GATE step 8 and standing requirements).

- `resolve_unconfirmed(journal, venues)` — every UNCONFIRMED or open order is asked about through
  `status()`; an unresolved poll stays UNCONFIRMED.
- `ingest_fills(journal, venues, since_utc)` — venue fills into the FIFO with their final flag
  (Polymarket: CONFIRMED on-chain only).
- `check_fees(journal, fills, fee_params)` — charged vs the pinned curve through the same models
  the cover used; an excess is a `FeeFinding.stop`, which the caller latches and re-pins.
- `settle(legs, winners, payouts=None)` — each venue's **own** settlement outcome (that is the
  point) → realized PnL per leg as `RealizedFill`s for the loss breaker. `payouts` is an optional
  exact outcome-id → payout map for scalar/half settlements; legacy binary `winners` remains
  supported. A missing or malformed payout for an owned leg is UNCONFIRMED.
- `releasable(realized)` — true only when no leg is UNCONFIRMED. Settlement timing differs between
  venues; capital availability on one side is never a proxy for the other.

Settlement-result ingestion accepts Kalshi binary results and finalized scalar
`settlement_value_dollars`, plus closed/resolved Polymarket `outcomePrices` mapped to CLOB tokens.
Maps are validated as complete finite values in [0,1], persisted in additive payout-evidence
tables (so historical settlement-row shapes remain unchanged), and reused by accounting refresh
after restart. A scalar/half result intentionally has no winner; it is settled directly from its
payout vector.

## Tests

`tests/test_reconcile.py`.

## Settlement results (`results.py`)

`kalshi_result(market)` remains the binary winner compatibility helper; `kalshi_payouts(market)`
also reads finalized scalar payouts. `polymarket_result(market)` remains a winner helper;
`polymarket_payouts(market)` reads a complete closed/resolved vector, so a 50-50 is final evidence
but not a winner. `winners_for_pair` retains its binary-only contract.
