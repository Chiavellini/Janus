# Stage 1 — entity + schedule spine

**Date:** 2026-08-17 · **Track:** sports · **Ledger row:** L8 (characterization, no test look)
**Checkpoint:** ≥99% of one league-week resolves to a `game_id` → **PASS at 100.0%**, 280/280
venue events across **four** leagues, **zero** failures.

---

## What was built

| Module | Purpose |
|---|---|
| `lib/schedule/espn.py` | The external anchor. `ScheduledGame`, pure `parse_scoreboard()`, `index_by_participants()`, `nearest_game()`. |
| `lib/entities/resolve.py` | `normalize()`, `Resolver` with an xref path and a text path, ambiguity refusal, miss log. |
| `lib/entities/seed.py` | Builds the three tables from ESPN + Kalshi + Polymarket. |
| `lib/entities/{teams,aliases,aliases_manual,xrefs}.csv` | 159 teams · 644 generated aliases · 70 curated · 191 venue-id cross-references. |
| `catalog/stage1_checkpoint.py` | The checkpoint runner. |
| `tests/test_spine.py` | 16 tests, all offline, all pass. |

Also fixed `lib/fetch.py`: the response-cache key was the request URL, built with
`urlencode(params)`, which preserves **dict insertion order** — so the same query written in a
different order was a different cache entry. The key is now canonicalized; the request URL is
untouched. `tests/test_lib.py` 13/13 unchanged.

---

## Result

| League | Scheduled | Kalshi resolved | Polymarket resolved | Failures |
|---|---|---|---|---|
| MLB | 99 | 41/41 (100%) — all via exact time | 100/100 (100%) | 0 |
| NFL | 16 | 16/16 (100%) — all via local date | 16/16 (100%) | 0 |
| WNBA | 20 | 7/7 (100%) — local date | 20/20 (100%) | 0 |
| EPL | 10 | 10/10 (100%) — local date | 70/70 (100%) | 0 |

**Resolution, not co-listing.** This measures whether a venue's own market can be landed on an
external `game_id`. What fraction of games *both* venues quote is Stage 2's pre-registered gate
and is deliberately not tuned against here.

---

## Finding 1 — both venues expose an exact, agreeing start time. The matcher problem is smaller than the plan assumed.

The plan budgeted for fuzzy participant matching. That turned out to be unnecessary on the two
venues that matter, because both hand out **stable structured team identifiers**:

- **Kalshi** puts a per-team UUID in `custom_strike.{sport}_team`. Measured: exactly **30 distinct
  UUIDs for 30 MLB teams**, 1:1 with names, **zero collisions**.
- **Polymarket** exposes `teams[].id`, `abbreviation`, `gameId`, `sport`, `eventDate` and
  `markets[].gameStartTime`.

Cross-references were built by **intersection, never by a single string match**: a row is accepted
only when two independent labels agree on one entity. First pass gave 25 conflicts; all 25 were
real and are described below. After fixing them: **191 xrefs, 0 conflicts.**

Where an xref exists there is no string matching at all, so no ambiguity is possible.

## Finding 2 — three time fields on each venue, and the obvious one is wrong

This is the single most expensive trap found.

**Kalshi.** `close_time`, `expiration_time` and `latest_expiration_time` are the scheduled start
**plus exactly three days** — a postponement buffer implementing the rules text *"will remain open
and close after the rescheduled game has finished (within two days)"*. `expected_expiration_time`
and `occurrence_datetime` are the expected **end**. The start appears only in the event ticker and,
in English, in `rules_primary`. Keying a join on `close_time` puts every game three days late and
matches nothing. Locked in as `close_time_is_start_plus_three_days_not_the_start`.

**Polymarket.** *The slug date is not the game date.* `mlb-stl-cin-2026-05-24` was **played
2026-08-17** — PM mints a slug once and keeps it when a game is postponed, while Kalshi re-mints on
the new date with a doubleheader marker (`...26AUG171340STLCING1`). The event's own
`eventMetadata` confirms it: *"The makeup game from May adds scheduling pressure."*

**Why this matters beyond hygiene.** A slug/ticker-date join would have dropped precisely the
**postponed** games. Postponement is the mode where venue rulesets diverge most — LFMP versus
void-at-par — so the dropped subset is exactly the highest-wedge subset. The bias would have been
invisible and would have pointed the wrong way, making the wedge look smaller than it is.

`markets[].gameStartTime` (PM) and the rules text (Kalshi) agree **exactly**: both give
`2026-08-17T17:40:00Z`. Once the right field is used, the join is exact.

## Finding 3 — MLB alone states a clock time, and that is exactly where it is needed

Kalshi's rules text carries a clock time **only for MLB** (*"Aug 17, 2026 at 1:40 PM EDT"*);
every other league gives a bare date (*"Aug 20, 2026"*). This is not an inconsistency — MLB is the
only league with **doubleheaders**, i.e. the only one where (team pair, date) is not unique.

So the resolver runs two paths: exact-time → `nearest_game()` within a 90-minute tolerance;
date-only → `games_on_local_date()`. Both **refuse rather than guess**: `nearest_game` returns
`None` on a tie, and `games_on_local_date` returns `None` when a date holds two games of the same
matchup. Dates are Eastern, not UTC — a 10pm-Pacific game is the next day in UTC but the same day
in Eastern, which is how Kalshi dates it, and matching on UTC would drop every West Coast night
game. Tested.

## Finding 4 — a false alias was auto-generated and caught

Missing aliases were derived by **co-occurrence**: when one label on a market resolves via the
exact venue id and the other does not, the unresolved label denotes the same entity. 64 candidates
came out. One was wrong:

> `nfl, "la" → Los Angeles Rams (n=4)`

It looked unambiguous only because the **Chargers had not yet appeared with that label**. "LA"
denotes either LA club. A wrong entity does not produce a slightly-wrong pair — it produces two
unrelated markets whose price gap reads as an enormous edge and sorts to the top of any ranked
list. That is the phase-1 "+97.94¢ golfer vs cyclist" failure exactly.

Rule now enforced by test: a short code (≤3 chars) is trustworthy only when its team's location is
**unique in the league**. Long forms ("LA Rams") are self-disambiguating; rows a human verified
against observed venue output are exempt and marked `manual_`.

The six genuinely ambiguous alias keys — `mlb/chicago`, `mlb/los angeles`, `mlb/new york`,
`nfl/los angeles`, `nfl/new york`, `nhl/new york` — all **refuse to resolve**, by test. This is not
hypothetical: Kalshi renders MLB teams by **location only** (`yes_sub_title` = "St. Louis"), so
"New York" arrives as a real query.

## Finding 5 — venue facts worth carrying forward

- **`no_sub_title` equals `yes_sub_title` on 82/82 MLB markets.** It is *not* the opposing team.
  Anything reading it as the opponent builds a team-against-itself pair.
- **Kalshi runs 3,414 sports series, with game-level `*GAME` series for ~250 leagues** — from
  KXMLBGAME to KXKBOGAME, KXEUROLEAGUEGAME, KXBRASILEIROGAME. The co-listing surface is far larger
  than the plan's two-league scope assumed.
- **EPL is three-way** (home/draw/away). "Tie" is an outcome, not a participant — 20 of the 25
  first-pass conflicts. It is now recognized as `NON_TEAM_OUTCOMES`, not filed as an unresolved
  entity.
- **EPL's own rules text states the soccer wedge**: *"after 90 minutes plus stoppage time (does not
  include extra time or penalties)"*. The plan predicted "OT included except soccer"; the venue
  says so itself. Stage-4 input, sourced.
- **ESPN is Kalshi's own primary settlement source** for MLB (`settlement_sources`: ESPN, Fox
  Sports, mlb.com), so the anchor is not a neutral third party we picked — it is the venue's
  reference. PM's `resolutionSource` is mlb.com. Residual ESPN/MLB disagreement is a Stage-4
  input and is **not** assumed zero.
- `site.api.espn.com` — the host every tutorial cites — is **403**. `site.web.api.espn.com` works.

---

## Correction to the approved plan

`state.yaml` declared `leagues_v1: [nfl, nba]`. Measured against the calendar on 2026-08-17:

| League | Games in an 8-day window |
|---|---|
| MLB | 99 |
| WNBA | 20 |
| NFL | 16 (**preseason only**) |
| EPL | 10 (season opens 08-21) |
| **NBA** | **0 — out of season** |
| **NHL** | **0 — out of season** |

**Stage 2 should run on MLB**, with NFL added when the regular season opens (~10 Sept) and NBA/NHL
when they resume in October. The plan's league choice was made without checking the calendar; the
spine itself is league-agnostic, so this costs nothing.

---

## Not done here

No prices were read. No orderbook was fetched. No market was matched to another market — only to
the schedule. The Stage-2 gate (coverage ≥ 0.80, precision ≥ 0.98 against hand-labelled pairs) is
**not yet registered** and nothing here was tuned against it; the co-listing counts in
`results.json` are context and must not be quoted as a Stage-2 result.

Kalshi lists fewer games than the schedule (41 of 99 MLB) because it opens markets closer to game
time. Whether that is a listing-horizon effect or a genuine coverage limit is a Stage-2 question
and is **not** answered here.

**0 test looks spent. No holdout touched.**
