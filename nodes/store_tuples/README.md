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
`__init__`, because the root disk has ~10 GB free.

## Failure modes

`sweep_runs.error` is written as a hardcoded `None` by `grids/live_sports`, so a failed sweep
records `status='ERROR'` with the exception discarded.

`status` values mix casing — `ACTIONABLE`/`NO_EDGE` (literals) vs `insufficient_depth` (a
`reject_reason`), so a downstream `== "INSUFFICIENT_DEPTH"` filter silently misses rows.

The table has **three sweep rows, ever**.

## Tests

No direct tests — a gap. Exercised incidentally by `venue_cloudbet/tests/test_fixtures.py`.
