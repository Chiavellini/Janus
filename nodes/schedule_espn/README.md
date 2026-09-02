# schedule_espn

**Kind:** `source` (fetch) + `pure` (parse)
**Implements:** `espn.py`

The external schedule spine. Every venue is anchored to ESPN independently, which turns an
O(n·m) fuzzy cross-venue matching problem into two O(n) exact joins. This node is the reason
`match_sports` can match on a canonical key instead of title similarity.

## Position in the grid

```
ESPN API ──▶ [schedule_espn] ──▶ ScheduledGame[] ──▶ [match_sports] ──▶ [venue_*]
```

**Upstream:** ESPN site API (`site.api.espn.com`). No Janus node.
**Downstream:** `nodes/match_sports` (canonical key), `grids/live_sports` (live/near-window filter).

## Contract

`fetch_range(league, start, end)` → `ScheduledGame[]`; `parse_scoreboard(payload, league)` is PURE.
`nearest_game` returns `None` on a tie and outside `DEFAULT_START_TOLERANCE_S` (5400 s) rather than
guessing — an ambiguous schedule anchor is a BLOCK, never a best effort.

## Failure modes

`HTTP_5XX` on one league must not kill the others — today it does, because `fetch_range` has no
`except` and the league loop is unguarded. This is the first thing the grid runtime fixes
(fan out on `league`).

`was_suspended` and `neutral_site` are parsed and **never consulted**, despite neutral-site games
being where venue rulesets diverge most.

## Tests

`tests/integration/test_spine.py` (shared with `entities` — the spine spans both nodes).
