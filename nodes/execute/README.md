# execute

**Kind:** `pure` (plus two tables on the Janus volume)
**Implements:** `plan.py`, `sizing.py`, `maker.py`, `coordinator.py`, `records.py`, `venues.py`

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
                 failures: ORDER_UNFILLED · ORDER_REJECTED · ORDER_TIMEOUT · UNKNOWN_PROVIDER_STATE · PARTIAL_FILL ·
                           HEDGE_UNAVAILABLE · HEDGE_SLIPPAGE_EXCEEDED · MARKET_SUSPENDED ·
                           VENUE_DISCONNECTED · BALANCE_CHANGED
                                                          │
                              executions / execution_transitions (with the priced books)
                                                          ▼
                                              nodes/reconcile ──▶ ledger.release
```

## Leg order, fixed

**Polymarket first; Kalshi hedge, IOC, for the authorized quantity leg A filled.** Live and paper
entry are immediate under F20. Kalshi leads
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

An authoritative order fill above its request is never clamped. Under the durable L65 bounded-
taker authorization only, price-improvement excess strictly below one contract is recorded as an
accepted protection-dust residual without a kill. Every other overfill latches live entry and the
guard detects it from late order totals. Protective requests floor share precision
and aggregate hedge buys cannot exceed the original plan's hedge quantity. Any remainder is
kept as held exposure; a request for 10 with a 10.166667 fill cannot authorize a 10.17 hedge.
The generic Polymarket transport still blocks immediate BUY signing; only the fixed $12/10 F20
entry method may sign one. L54's separate post-only route remains for historical reconciliation.

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

## Live bounded-taker entry (L65/F20); retained maker reconciliation (L54)

Live execution now selects `plan_from_cover` exactly like paper/replay: Polymarket first as an
immediate FAK/FOK at the walked executable ceiling, then Kalshi as the hedge. The dedicated PM
wire remains hard-limited to $12 collateral and 10 requested shares even if an outer arm grows.

The older maker route is retained for its durable journal and restart reconciliation. If used by
historical tests/tools, its original quote deadline and cancel-first lifecycle still apply.

Known fill deltas are journaled and protected after cancel dispatch, before slow terminal
reconciliation. Cumulative observations are monotonic and cent-floored; a 2→2→5 stream hedges 2
then only 3. No replacement is attempted; terminal zero fill is `ORDER_UNFILLED`, not rejection.
The PM adapter owns the durable singleton, original cancel deadline, terminal/late-fill proof and
restart cancellation. Guard cash finality does not close a maker order with a resting remainder.

Every order journal row carries its exact execution id because opportunity ids are reused. If the
execution-row write fails after a confirmed maker fill, that failure latches entry but cannot stop
the deterministic protective hedge request; the adapter journal remains the pre-wire authority.
On restart the guard repairs execution ownership from those exact rows and will not submit another
hedge or unwind while any owned protective order is unresolved. Balanced recovered fills move both
the execution and its opportunity (with a transition row) to `HEDGED`.

If reconciliation is still ambiguous after its bounded attempt, new entry is latched, reservation
and maker admission stay held, and known exposure still enters protection. Synchronous network
calls may delay terminal reconciliation after cancel dispatch; restart recovery uses the durable
cancel intent, order journal and position guard. L63 prospectively measures maker fill selection,
realized-EV and Sharpe inputs; conditional-fill sizing is not claimed realized-EV optimal.
