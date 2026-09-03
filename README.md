# Janus

Executable **two-leg pure arbitrage on sports** across independent venues.

Buy one outcome on venue A, buy the complementary outcome on venue B, and require the combined
cost — after fees, executable depth, quote freshness and settlement rules — to guarantee a return.
It is not a forecast of the winner, and it is not a one-legged convergence bet on midpoint
divergence.

**Nothing is armed.** No orders, no capital. Promotion is gated by `GATE_TO_LIVE.md` in full.

---

## The grid

Every unit of work is a **node**: its own directory, its own tests, and a `README.md` saying what
it owns and how it connects. A **grid** wires nodes into a runnable pipeline.

```
   ESPN ──▶ schedule_espn ─┐
   venue labels ─▶ entities ┼──▶ match_sports (NO PRICES) ──┐
   Kalshi series fees ──────┤                               ├──▶ discovery ──▶ slate + events table
   Gamma feeSchedule ───────┘                               │        (fee params per venue, per game)
                                                            ▼
                     stream_kalshi ───▶ book_replica ×4 ──▶ game_poller (one actor per live game)
                     stream_polymarket ▶ book_replica ×4 ──▶   │  rules_exhaustive proof at spawn
                                                               │  fees ──▶ cover ──▶ capacity
                                                               ▼
                                             opportunity.record ──▶ store_tuples ──▶ analysis ──▶ research/
   raw frames ──▶ capture ──▶ /Volumes/Kilos/janus/frames ──▶ replay ──▶ the same handlers, a parity check

   grids/live_stream composes all of it (the supervisor). grids/live_sports is the REST lane, disabled.
   parked:  venue_cloudbet (sportsbook; acceptance precedes pricing), venue_sxbet (size convention unverified)
   settle_wedge: reviewed venue templates + measured rates ──▶ CoverProof (exhaustive × equivalent) ──▶ cover
```

## Layout

| Path | What |
|---|---|
| `kernel/` | Contracts shared by every node: schema types, HTTP client, stats. Depends on nothing. |
| `nodes/<name>/` | One unit of work. `README.md`, implementation, `tests/`. |
| `grids/<name>/` | A composition of nodes into a runnable pipeline. |
| `ops/` | Run index and the watchdog. |
| `research/<track>/<date>_<slug>/` | Pre-registered `spec.yaml`, `results.json`, `verdict.md`. **Immutable.** |
| `snooping_ledger.md` | The multiple-testing ledger. **Append-only. No result exists outside it.** |
| `tests/integration/` | Cross-node tests that no single node owns. |

**Layering rule:** grids import nodes; nodes import the kernel; nodes never import grids and no
grid imports another grid. That is what keeps a failure attributable to one node.

## Run it

```bash
python3 -m pytest                      # 265 tests, works from any directory, no network
python3 ops/watchdog.py                # is anything unhealthy?
python3 -m grids.live_stream.grid --leagues mlb --once     # one discovery pass, ~15 s of capture
```

## State of the evidence — read this before trusting any number

- **No actionable cover has ever been observed.** The streaming lane (`grids/live_stream`) has run
  over a handful of MLB games at ~200–300 evaluations/s; the best cover cost seen is 1.0020, about
  1.2¢ from the 1% hurdle on a lopsided game, median ~1.02–1.03. Tennis: 13 co-listed pairs, zero
  actionable frontiers. Stage 3 (interim, 8 of 40 polls): prices diverge by ~2¢ several times a
  day and the fee floor eats it.
- **Fees were wrong on both legs until 2026-09-02.** Kalshi sports series report
  `fee_multiplier 0.5` (`quadratic_with_maker_fees`); the lane charged 1.0×. Polymarket's rate was
  hardcoded rather than read from the market's `feeSchedule`. Every "cents from actionable" number
  before this date overstates the Kalshi fee by 2×. Fees now come from the venues' own payloads,
  and a leg whose schedule was not fetched is blocked (`FEE_SCHEDULE_MISSING`), never defaulted.
- **Both proofs gate every cover.** `nodes/rules_exhaustive` proves the outcome set is complete;
  `nodes/settle_wedge` proves the two venues pay equivalently, from their own rules text against
  reviewed templates, and prices the bounded residual (MLB: a makeup more than two days out, a
  cancellation) from a registered measurement (ledger L26: 10 of 2,100 games, 0 cancellations).
  MLB certifies; NFL and NHL block until their Polymarket game text is harvested and reviewed.
- **Coverage is six leagues, live plus up to `--pre-hours` before start.** The `^mlb-` slug
  hardcode and the ±30 min window are gone (`f8a187e`).

## History

`CHANGELOG.md` — dated, append-only. What changed and why.

## Next

`NEXT.md` — one file, overwritten, explicitly an opinion. Never a second handoff document.
