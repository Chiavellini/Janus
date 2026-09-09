# entities

**Kind:** `pure`
**Implements:** `resolve.py`, `seed.py`, `leagues.py`, `*.csv` (teams, aliases, xrefs)

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

Tennis players are seeded in memory from Polymarket's current singles slate before Kalshi is
resolved. A verified venue spelling difference belongs in `aliases_manual.csv`, with both venue
identifiers and the observed date in its note; do not replace that audit trail with a fuzzy
middle-name rule.

An audited venue UUID exception belongs in `xrefs_manual.csv`, with the observed date, exact
venue identifier, ESPN club identity and reason. `load_xrefs()` merges this overlay with generated
`xrefs.csv` and rejects every disagreement; manual rows never override generated identities.
Scoped seeding writes only the generated file, preserving the overlay and retaining the underlying
label disagreement in `xref_conflicts.csv`. For example, Kalshi's Manchester United UUID is exact
even though its `MUN` ticker abbreviation is ESPN's Bayern Munich abbreviation in UCL.

## Failure modes

**`resolve()` signals failure by RETURNING `Resolution(entity_id=None)`. It does not raise.**
A `try/except` around it catches nothing. Wrapping this misunderstanding is what crash-looped
`com.janus.convergence` every 30 s for thirteen days (15,207 tracebacks, undetected) — a `None`
reached `sorted()` in a key function several frames away. Always check `.ok`.

Ambiguity resolves to unresolved, never to a pick: "New York" → `Yankees|Mets` is a BLOCK.

Soccer club identity is independent of competition: seeding reuses the existing entity for the
exact ESPN soccer team ID, preserving audited historical IDs such as `epl:eng.arsenal`. New clubs
use `soccer:espn-<id>`. `Team.league` is the identity's scope/original league, not a membership
claim. Aliases remain competition-scoped, and game keys still include the competition. Thus an
Arsenal UCL alias and domestic alias point to the same club, while their matches remain distinct.
Conflicting existing identities for one ESPN soccer ID stop seeding; global venue xref collisions
still stop loading. A roster refresh upserts identities without deleting shared clubs, and replaces
only the selected competitions' generated aliases/xrefs. UCL registration cannot bypass settlement
certification: L58 evidence applies only when the exact ESPN schedule population is `league-phase`.

`seed.NON_TEAM_OUTCOMES = {tie, draw, no winner}` deliberately drops the draw leg. That is correct
here and **dangerous downstream** — see `nodes/cover` and `nodes/rules_exhaustive` (not yet built).

## Tests

`tests/integration/test_spine.py`.

## The league registry (2026-09-03)

`leagues.py` is the one table for what a competition is called on each venue and how it is
anchored: code, Kalshi game series, Polymarket tag and slug prefix, ESPN path (or none, for a
`venue_structured` anchor), outcome cardinality. `seed.py`'s `SEED_LEAGUES` / `KALSHI_GAME_SERIES` /
`PM_TAG`, `schedule_espn.LEAGUE_PATHS`, the grid's `--leagues` default and the proof script all read
it. A row buys nothing on its own: `enablement(code)` lists what the league still lacks before it may
trade — a cited rule in `nodes/rules_exhaustive`, reviewed templates for both venues in
`nodes/settle_wedge/policy.py`, and a registered measurement for every BOUNDED dimension — and
`default_leagues()` is the rows that lack nothing (MLB alone on 2026-09-03; NFL waits on its rates).
`tests/test_leagues.py` pins that every consumer reads the table and that an unregistered league
still blocks at `NO_RULE_FOR_LEAGUE`.
