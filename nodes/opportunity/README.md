# opportunity

**Kind:** `pure` (plus three tables on the Janus volume)
**Implements:** `status.py` (the classifier), `thresholds.py` (the two thresholds as importable
constants), `opportunity.py` (the record, its allowed transitions, the persisted frontier and
books), `record.py` (the one write path the supervisor and the replay share)

One evaluation → one `kernel.schema.OpportunityStatus`. Every writer uses it; no grid computes a
status from literals any more.

## Position in the grid

```
[game_poller] Evaluation ──▶ [opportunity.status_for] ──▶ OpportunityStatus ──▶ [store_tuples]
```

## Contract

`status_for(cover_ok, reject_reason, blocked_by, gross_per_contract, cost_per_contract,
single_venue, hurdle)`:

| condition | status |
|---|---|
| a replica fault (`…:SEQ_GAP`, `…:STALE`, `…:NOT_SYNCED`, …) | `BLOCKED_STALE` |
| `…:NO_ASKS`, `insufficient_depth`, `quote_not_accepted` | `BLOCKED_DEPTH` |
| `…:FEE_SCHEDULE_MISSING`; or gross < 1 but fee-net cost ≥ 1 | `BLOCKED_FEES` |
| `outcome_set_not_proven_exhaustive`, `settlement_not_equivalent` | `BLOCKED_RULES` |
| `shared_liquidity_source`, single-venue cover, unknown refusal | `BLOCKED_MATCH` |
| gross ≥ 1 | `NO_EDGE` |
| 0 < locked return < hurdle | `DISCOVERED` |
| locked return ≥ hurdle | `PROFITABLE_UNEXECUTED` |

The fine-grained reason (`blocked_by`, `reject_reason`) is still recorded beside the status.

## Failure modes

An unknown refusal string maps to `BLOCKED_MATCH`, the conservative bucket, never to a price
finding. Add the mapping when a new reject reason is introduced; `tests/test_status.py` pins the
table.

## Tests

`tests/test_status.py`.

## The record (2026-09-03)

One `Opportunity` per (event, quantity), created when an evaluation first reaches `DISCOVERED`
or `PROFITABLE_UNEXECUTED`, then carried through every status by `transition()`, which enforces
the machine (no DISCOVERED → HEDGED; terminals are terminal). `thresholds.py` holds the two
thresholds: discovery is gross edge > 0; execution is locked return ≥ 1% **and** net profit ≥
$0.50 — a cover that clears the return hurdle but not the dollar floor is `DISCOVERED`. Tables:
`opportunities` (the latest state, with `books_json`, the exact ladders the edge was priced from,
kept when the edge goes away), `opportunity_transitions` (append-on-change), `frontiers` (every
solved size curve: `n_max`, `n_star`, the rungs, the cost-model labels).
