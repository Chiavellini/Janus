# execute

**Kind:** `pure` (plus two tables on the Janus volume)
**Implements:** `plan.py`, `coordinator.py`, `records.py`, `venues.py`

The two-leg state machine (spec §10). One code path for every mode; `venues.py` is the only place
adapters are chosen, and the coordinator never branches on mode.

## Position in the grid

```
opportunity (PROFITABLE_UNEXECUTED) + priced books ──▶ plan_from_cover ──▶ Plan
risk.clear ──▶ RiskClearance ─────────────────────────────┐
                                                          ▼
                                   Coordinator.execute(plan, clearance)
                 DETECTED → VALIDATED → CAPITAL_RESERVED → LEG_A_SUBMITTED → LEG_A_FILLED
                          → LEG_B_SUBMITTED → LEG_B_FILLED | LEG_B_PARTIAL → HEDGED
                 failures: ORDER_REJECTED · ORDER_TIMEOUT · UNKNOWN_PROVIDER_STATE · PARTIAL_FILL ·
                           HEDGE_UNAVAILABLE · HEDGE_SLIPPAGE_EXCEEDED · MARKET_SUSPENDED ·
                           VENUE_DISCONNECTED · BALANCE_CHANGED
                                                          │
                              executions / execution_transitions (with the priced books)
                                                          ▼
                                              nodes/reconcile ──▶ ledger.release
```

## Leg order, fixed

**Polymarket first, FOK; Kalshi hedge, IOC, for exactly what leg A filled.** Kalshi leads
Polymarket by 5–10 s and a third of Polymarket reprices never happen, so the opportunity *is* a
stale Polymarket price and Polymarket is the less reliable executor: its ambiguity must land
where nothing is at risk. The hedge limit is the most a contract may cost for the cover still to
clear the execution threshold after what leg A actually paid; a book above it is
`HEDGE_SLIPPAGE_EXCEEDED`, never a chase. Never reversed at runtime.

## Rules, each with a test

An UNCONFIRMED leg is polled through `status()` and never resubmitted; still unknown at the
deadline is `UNKNOWN_PROVIDER_STATE` with the reservation kept. Whatever is unhedged after the
deadline is recorded (`executions.unhedged`, the watchdog's reservation alarm) and the
opportunity moves to `FAILED_HEDGE`. A kill switch or a disconnect before leg A aborts and
releases; after leg A fills the hedge is still sent. Capital is released only by
`nodes/reconcile`, after both venues reconcile.

An authoritative order fill above its request latches live entries immediately and records
`ORDER_OVERFILL`; the durable venue quantity is never clamped. The guard detects late overfills
from order totals too, even below protection dust. Protective requests floor share precision
and aggregate hedge buys cannot exceed the original plan's hedge quantity. Any remainder is
kept as held exposure; a request for 10 with a 10.166667 fill cannot authorize a 10.17 hedge.
The Polymarket transport currently blocks BUY entry because its wire cannot prove this share
bound (L53); these protections also cover orders from before that repair.

The guard checks existing overfills before syncing its trade FIFO. Partial FIFO coverage cannot
reduce a larger authoritative order quantity or replace its average/fee with the partial subset;
accounting stays pending until full fill coverage is available. Missing or shrinking FIFO totals
do not establish a reversal. A separately verified reversal must first be recorded explicitly
in the journal; reconciliation then uses that corrected total, preserving the historical alarm.

## Tests

`tests/test_coordinator.py` — the plan, the happy path with every transition persisted, an
unfilled FOK, an unconfirmed leg A (kept, then found filled and hedged), the partial hedge, the
slippage stop, kill/disconnect, shadow mode, the factory.

The guard aggregates `MIN(final)` across an order's fills: one provisional cash line keeps
`settlement_pending` set. Final price-only accounting corrections update execution averages
with a state-to-same-state audit entry, without reopening a released execution or changing
quantities/protection. Paid fees remain on the authoritative order rows; the existing settlement
revision path updates P&L and preserves old/new accounting. `test_guard_cash_finality.py`
checks these paths together using the Maximus cash values.
