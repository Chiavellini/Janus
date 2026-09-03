# match_sports

**Kind:** `pure`
**Implements:** `sports_match.py`, `stage1_checkpoint.py`

Cross-venue matching on a canonical key. **NO PRICES ARE READ HERE.**
Key = `league + {sorted participants} + start_time(±window) + market_type + period + line + side`.
Jaccard/title similarity is anti-correlated with truth in sports — "Lakers vs Celtics Nov 3" and
"Lakers vs Celtics Nov 17" share nearly every token — so it is used for candidate generation only,
never as proof.

## Position in the grid

```
[schedule_espn] ──┐
                  ├──▶ [match_sports] ──▶ matched pairs ──▶ [venue_*] ──▶ [cover]
[entities] ───────┘
```

**Upstream:** `nodes/schedule_espn`, `nodes/entities`.
**Downstream:** `nodes/discovery` (and through it both grids), `nodes/venue_cloudbet/join.py`.

## Contract

`kalshi_markets(...)`, `pm_markets(...)`, `pair(...)`. Both venues resolve onto ESPN
**independently**, then join on an exact index key — no similarity score, no threshold.

## Failure modes

**The slug is per league** (`_fullgame_slug`). It was `^mlb-` for every league until `f8a187e`,
which starved five of six leagues of Polymarket pairs under a benign-looking reason code. Sampled
2026-09-02: the convention is identical across leagues.

**Period vocabulary.** This module emits `"full_game"`; `kernel/schema.PERIODS` and
`nodes/rules_exhaustive` use `"game"`. Unified in plan P0b.

**`CanonicalKey` is not yet constructed here.** The join tuple is
`(espn_game_id, market_type, period, entity_id)`, with participants and start time consumed
upstream when both venues resolve onto the schedule. Plan P3 builds the kernel's `CanonicalKey`
and records key provenance per venue.

## Tests

`tests/test_match.py` — the per-league slug, the exact join, determinism, no prices.
`tests/integration/test_spine.py` covers `stage1_checkpoint`.

## The key (2026-09-02)

Every `VenueMarket` carries the kernel's `CanonicalKey` — league, sorted ESPN participant ids,
external start time, market type, period — built from the schedule game the venue resolved onto,
and `pair()` joins on `(key, entity_id)`. A market that resolved onto no game has no key and pairs
with nothing. `key_provenance` records how the start time was obtained: Kalshi from rules text
(`ticker_parse`), Polymarket from `gameStartTime` (`api_structured`). Rules text rides on
`rules` for `nodes/settle_wedge`.
