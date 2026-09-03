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
- `settle(legs, winners)` — each venue's **own** settlement outcome (that is the point) → realized
  PnL per leg as `RealizedFill`s for the loss breaker; a leg whose venue has not settled, or a
  fill not yet final, is UNCONFIRMED, which keeps the day's PnL unknown.
- `releasable(realized)` — true only when no leg is UNCONFIRMED. Settlement timing differs between
  venues; capital availability on one side is never a proxy for the other.

Settlement-result ingestion from the venues (Kalshi market `result`, Polymarket resolution) is
plan P8/P11 work; `settle` takes the outcomes as input.

## Tests

`tests/test_reconcile.py`.
