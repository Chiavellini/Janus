# rules_exhaustive

**Kind:** `pure`
**Implements:** `rules.py`

The gate between a 3-way market and a two-leg "cover". A cover is only a cover if the outcome set
**partitions the sample space** — otherwise you are not holding arbitrage, you are holding a bet
that the uncovered outcome does not happen.

## Position in the grid

```
[match_sports] ──▶ outcome set ──▶ [rules_exhaustive] ──▶ ExhaustiveOutcomeSet ──▶ [cover]
                                          │
                                          └── NotExhaustive ──▶ BLOCK (never priced)
```

**Upstream:** `nodes/match_sports` (the matched outcome set), the league from `nodes/schedule_espn`.
**Downstream:** `nodes/cover` — which cannot price without the token.

## Contract

`prove(league, market_type, period, outcome_ids)` → `ExhaustiveOutcomeSet | NotExhaustive`.

**The proof is a type, not a flag.** `ExhaustiveOutcomeSet.__post_init__` refuses direct
construction, so `prove()` is the only mint and `nodes/cover` requires the token. A caller cannot
assert exhaustiveness; it can only obtain it.

A rule needs a **citation**. A rule with `citation=None` is *asserted*, not proven, and blocks.
Adding a league is deliberately annoying: you must name the sporting rule that makes its outcome
set complete.

| League | Outcomes | Status |
|---|---|---|
| mlb, nba, wnba, nhl | 2 | Cited — extra innings / overtime / OT+shootout always produce a winner |
| **nfl** | 2 | **BLOCKED** — regular-season games can tie after one overtime period |
| **epl** | 3 | **BLOCKED** — home/draw/away; a two-leg cover pays nothing on a draw |
| anything else | — | **BLOCKED** — `NO_RULE_FOR_LEAGUE` |

NHL's citation covers the **full-game** period only. NHL "regulation time" markets are 3-way and
sit under a different period key, so they do not inherit it.

## Failure modes

`NO_RULE_FOR_LEAGUE` · `RULE_UNCITED` · `OUTCOME_COUNT_MISMATCH` · `DUPLICATE_OUTCOME`.

All are BLOCKs. None is a zero-risk shrug.

## Why this node exists

`grids/live_sports` used to pass `exhaustive=True` for every league in its default list
(`mlb,nfl,nba,wnba,nhl,epl`), including 3-way EPL. An EPL match quoted home 0.46 / away 0.30 with
an invisible 0.24 draw priced as a 0.76 cover returning **+31%**. It never fired only because a
hardcoded `^mlb-` slug pattern in `nodes/match_sports` starved the other five leagues of pairs —
so fixing coverage first would have switched on a fake-arbitrage generator.

## Tests

`tests/test_rules.py` — including `test_the_proof_cannot_be_forged` (the design rests on it) and
`test_the_epl_bug_end_to_end`.
