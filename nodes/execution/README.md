# execution

**Kind:** `pure` + one journal (three tables) on the Janus volume
**Implements:** `journal.py`, `gate.py`, `paper.py` (`PaperVenue`, `RefusingVenue`), `testing.py`

What every execution venue shares, real or not. The contract is `kernel/execution_protocol.py`.

## Position in the grid

```
coordinator ──▶ ExecutionVenue.submit(req, RiskClearance)
                    │  gate.admit: mode ≥ needed, a live unused clearance for THIS opportunity, consumed
                    │  journal.pending BEFORE the wire            (UNCONFIRMED until the venue speaks)
                    ▼
        paper / refusing / exec_kalshi / exec_polymarket
                    │
                    ▼
                journal.record: FILLED | PARTIAL | UNFILLED | UNCONFIRMED | REJECTED, venue words kept
```

## Rules the journal enforces

A row exists before the POST; a process that dies between the two leaves `UNCONFIRMED`, which
`status()` resolves before any retry. A duplicate client order id is refused here, which is
what makes the id idempotent on our side of the wire. `venue_fills` is the FIFO the loss breaker
reads, with the venue-final flag.

## Paper and shadow

`PaperVenue` fills against the exact `Book` the opportunity was priced from, with a latency and
an adverse-move parameter (zero until the slippage buffer is measured). `RefusingVenue` is
SHADOW_LIVE: intent journaled, nothing sent. Both pass the same gate and write the same journal,
so the coordinator cannot tell them from a real venue — which is the point.

## Tests

`tests/test_execution.py`.
