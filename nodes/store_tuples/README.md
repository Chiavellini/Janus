# store_tuples

**Kind:** `sink`
**Implements:** `store.py`

Sparse, change-only SQLite storage. Latest state plus material quote/opportunity transitions and
one aggregate row per sweep — never repeated full-universe snapshots.

## Position in the grid

```
[cover] ──▶ [store_tuples] ──▶ /Volumes/Kilos/janus/tuples/tuples.sqlite
```

**Upstream:** `nodes/cover`, `nodes/venue_*`.
**Downstream:** Research artifacts; `ops/watchdog.py` reads run rows.

## Contract

`market()` upserts; `quote()` appends only on ≥1 tick, ≥10% depth change, or state change;
`opportunity()` appends only on an actionability/return transition; `sweep()` writes one row per run.
**Raw venue payloads are never retained.** Data must live on `/Volumes/Kilos` — enforced in
`__init__`, because the root disk has ~10 GB free. `ensure_ddl(fragment)` lets a node own its
tables (idempotent); `nodes/discovery` uses it for `events`.

## Failure modes

`status` is a `kernel.schema.OpportunityStatus` value as of 2026-09-02 (`nodes/opportunity`
classifies every evaluation). Rows written before that date mix `ACTIONABLE`/`NO_EDGE`/`NO_PRICE`
with lowercase reject reasons and replica fault strings; read them with that in mind.

**Sub-tick drift can accumulate unrecorded.** `latest_quotes` is updated on every call, but a
history row lands only when the move from the *last stored* value is ≥ 1 tick — so a run of
sub-tick moves that sum to several ticks writes nothing. Pinned by `tests/test_store.py`.

`sweep_runs.error` now carries the exception text (was a hardcoded `None`).

## Tests

`tests/test_store.py` — the volume guard, the material-change gates on quotes, opportunities
and evaluations, `ensure_ddl`, and that a failed sweep keeps its error.
