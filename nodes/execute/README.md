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

## Tests

`tests/test_coordinator.py` — the plan, the happy path with every transition persisted, an
unfilled FOK, an unconfirmed leg A (kept, then found filled and hedged), the partial hedge, the
slippage stop, kill/disconnect, shadow mode, the factory.
