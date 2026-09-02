# entities

**Kind:** `pure`
**Implements:** `resolve.py`, `seed.py`, `*.csv` (teams, aliases, xrefs)

Canonical team identity. Maps a venue's own rendering of a participant ("STL", "Cardinals",
"St. Louis Cardinals") onto one entity id, so two venues can be compared without ever comparing
their titles.

## Position in the grid

```
venue label ──▶ [entities] ──▶ entity_id ──▶ [match_sports]
                    │
                    └── unresolved ──▶ BLOCK (never a guess)
```

**Upstream:** Called by `match_sports` and `venue_cloudbet/join.py`.
**Downstream:** `nodes/match_sports`.

## Contract

`Resolver.resolve(league, text=..., venue=..., venue_team_id=...)` → `Resolution`.
Resolution order is **xref first, alias second**. `Resolution.ok` is the only valid success test.

## Failure modes

**`resolve()` signals failure by RETURNING `Resolution(entity_id=None)`. It does not raise.**
A `try/except` around it catches nothing. Wrapping this misunderstanding is what crash-looped
`com.janus.convergence` every 30 s for thirteen days (15,207 tracebacks, undetected) — a `None`
reached `sorted()` in a key function several frames away. Always check `.ok`.

Ambiguity resolves to unresolved, never to a pick: "New York" → `Yankees|Mets` is a BLOCK.

`seed.NON_TEAM_OUTCOMES = {tie, draw, no winner}` deliberately drops the draw leg. That is correct
here and **dangerous downstream** — see `nodes/cover` and `nodes/rules_exhaustive` (not yet built).

## Tests

`tests/integration/test_spine.py`.
