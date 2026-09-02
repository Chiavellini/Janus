# analysis

**Kind:** `pure`
**Implements:** `execution_styles.py`, `analyze_stage3.py`

Offline analysis over cover output: what a cover costs under each EXECUTION STYLE (not just the
expensive one), and the pre-registered Stage-3 kill criterion.

## Position in the grid

```
[cover] ──▶ [analysis] ──▶ research/sports/**/results.json
```

**Upstream:** `nodes/cover`, `nodes/venue_*`.
**Downstream:** `research/` artifacts only. Nothing downstream in the live path.

## Contract

`analyze_stage3` evaluates the registered kill criterion for ledger L12: *fewer than 0.5% of
observations below 0.995 at ≥ $200 depth*. Criteria are immutable.

## Failure modes

Timestamped outputs (unlike `grids/live_sports`, which overwrites), so this lane does keep history.

## Tests

None. A gap.
