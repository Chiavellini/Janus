# discovery

**Kind:** `source` (fetch) + `pure` (select, join, slate)
**Implements:** `discovery.py`, `census.py`

The event registry. Turns the ESPN schedule into the set of games that are live (or about to be)
**and** co-listed on both venues, with the four market ids and the fee params each venue reported
for them. Runs on the slow clock; everything downstream is fast.

## Position in the grid

```
schedule_espn ─┐
entities ──────┼──▶ [discovery] ──▶ slate {game_id: spec} ──▶ game_poller (via a grid)
match_sports ──┤                └─▶ events table (this node's own DDL)
venue_kalshi ──┤   series fee_type / fee_multiplier
venue_polymarket ┘ Gamma feeSchedule, token map, order limits
```

**Upstream:** the nodes above. **Downstream:** `grids/live_stream` (the supervisor) and
`grids/live_sports`. No grid imports another grid any more; this node is why.

## Contract

- `select_live(schedule, now_ts, include_near, pre_hours)` — PURE window filter.
- `live_games(leagues, now, include_near, pre_hours)` — per-league ESPN fetch, failures named.
- `match_live(league, games, now)` — both venues onto the schedule, exact join.
- `kalshi_league_fees(leagues, client)` — `fee_type`/`fee_multiplier` per league series.
- `discover(...) -> Discovery` — the frozen answer, with `fee_params` and `fee_errors`.
- `co_listed(d) -> (slate, blocked)` — PURE. A spec is
  `{league, short_name, state, start_utc, outcomes, fee_params, pm_slug, kalshi_event, pm_limits}`.
- `record_events(store, d, slate, blocked)` — upserts `events`, appends `event_transitions` on change.

## Failure modes

**A venue's fee schedule is absent, not defaulted.** `fee_params` only carries venues whose
schedule was actually fetched. `nodes/game_poller` blocks the other leg with
`FEE_SCHEDULE_MISSING`. Measured 2026-09-02: KXMLBGAME is `quadratic_with_maker_fees` at **0.5×**
and an MLB Gamma market carried **rate 0.03** — the lane had hardcoded 1.0× and 0.05.

**ESPN state lags.** A game can be "pre" for a minute after first pitch; `select_live` keeps games
that started up to `DEFAULT_LEAD_S` ago.

**One league's failure is recorded, never fatal.** ESPN 500s, a matcher exception, a missing
series: each lands in `schedule_failures` / `fee_errors` and the other leagues proceed.

## Tests

`tests/test_discovery.py` — window selection, the slate from a frozen Discovery, fee params reaching
the spec and their absence being visible, the events table and its change-gated transitions.

## Settlement (2026-09-02)

Each spec carries both venues' raw rules text (`rules`) — Kalshi `rules_primary`/`rules_secondary`
with the league's series record, Polymarket `description`/`resolutionSource` — plus the
participant names the normaliser strips, and `settlement`, the verdict `nodes/settle_wedge`
reached from exactly those words. `record_events` writes the `settlement_records` (the text, by
hash) and `equivalence_records` (the verdict, append-on-change). The supervisor and the replay
re-certify from the same spec, so what was priced and what was recorded cannot diverge.

The spec also preserves `game_id` and `schedule_population` (source, league, game ID and season
slug). L43 MLS evidence is regular-season-only; losing this tag would otherwise allow a
league-level template to transfer the measured reserve to unmeasured postseason games. MLS
recertification requires an ESPN `regular-season` tag bound to this exact slate game; old specs
without the tag fail closed until fresh discovery rebuilds them.

## The co-listing census (2026-09-03, ledger L28)

`census.py` answers a different question from the slate: not *which games are watchable now* but
*which competitions are worth the work of a citation, harvested templates and measured rates*.
Both venues enumerate themselves — Kalshi `/series?category=Sports` then every game-class series'
open markets; Polymarket `/sports` (its own league table, with the settlement source and tag)
then each tag's events with a `moneyline` market carrying `gameStartTime` — and the two are joined
per event on the calendar date and both participants (abbreviation equal, or a name token shared).
The join is a counting device with declared looseness: the unmatched remainder is reported per
competition, and the Kalshi ↔ Polymarket competition mapping is learned from the pairs, never
hand-seeded. `summarize` scores each competition by co-listed capacity at the touch over contract
life. `research/sports/2026-09-03_co-listing-census/measure.py` runs it daily; the rank is read
from the seven-day median. `tests/test_census.py` covers ticker parsing, both venues' shapes as
captured on 2026-09-03 (three-way soccer included), the join and the ranking.
