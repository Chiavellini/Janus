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
**Downstream:** `grids/live_sports`, `grids/scan_pure_arb`, `nodes/venue_cloudbet/join.py`.

## Contract

`kalshi_markets(...)`, `pm_markets(...)`, `pair(...)`. Both venues resolve onto ESPN
**independently**, then join on an exact index key — no similarity score, no threshold.

## Failure modes

**`PM_FULLGAME_SLUG` is hardcoded to `^mlb-` and applied to EVERY league** (`sports_match.py:56`).
NFL, NBA, WNBA, NHL and EPL therefore emit zero Polymarket pairs, bucketed as the benign reason
`derivative_event_not_full_game_moneyline`. The scanner is MLB-only in practice while its default
league list names six leagues.

This coverage bug is the ONLY thing masking the exhaustiveness bug in `nodes/cover`. Fixing it
first switches on a fake-arbitrage generator. Per-league slug patterns must land **after**
`rules_exhaustive` exists.

## Tests

`tests/integration/test_spine.py` covers `stage1_checkpoint`. `sports_match.py` itself has **no
direct tests** — a gap.
