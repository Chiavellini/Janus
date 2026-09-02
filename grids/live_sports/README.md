# grids/live_sports — the product

`python3 -m grids.live_sports.grid --leagues mlb --include-near`

Composes: `schedule_espn` → `entities` → `match_sports` → `venue_kalshi` + `venue_polymarket`
→ `fees` → `cover` → `store_tuples`.

Books for all four legs of a game are fetched concurrently (4 workers) so a cover never mixes a
minute-old leg with a live one; measured quote skew is ~49 ms against 402–452 ms per-book RTT.

## Known defects, in fix order

1. **`exhaustive=True` is passed unconditionally** for every league in the default list
   (`mlb,nfl,nba,wnba,nhl,epl`). EPL is 3-way and NFL can tie. See `nodes/cover/README.md`.
2. **`{"fee_rate": 0.05}` is hardcoded** for Polymarket instead of read from `feeSchedule`; the
   Kalshi leg passes no `fee_multiplier` at all. See `nodes/fees/README.md`.
3. **`try/finally` with no `except`**, and `sweep_runs.error` written as a literal `None`, so a
   failed sweep discards its exception. `write_artifacts()` runs *after* `scan()` returns, so a
   crashed run leaves the previous run's "Status: OK" verdict in place, indistinguishable from a
   fresh one. Fixed archive-wide by the grid runtime.
4. **Fixed output filenames** — every run overwrites `results.json` and `verdict.md`. There is no
   scan history.
5. **`venue_sxbet` is not wired in**, though its parser exists and it is the cheapest venue in the
   census.

Only 1 and 2 are correctness bugs; 3–5 are why failures are invisible.
