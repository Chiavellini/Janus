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
python3 -m pytest                      # 393 tests, works from any directory, no network
python3 ops/watchdog.py                # is anything unhealthy?
python3 -m grids.live_stream.grid --leagues mlb --once     # one discovery pass, ~15 s of capture (--mode PAPER_EXECUTION runs the machine)
```

## State of the evidence — read this before trusting any number

- **Opportunities print; edge is not shown.** On clean data (since 2026-09-04 00:25Z) the lane
  recorded 292 profitable prints across MLB and college football. Under L36's SUSPECT label all
  but one were suspect; under L40's rule that can be false (a fault on a replica the print was
  priced from, in the minute before it) **15 are clean**: 12 college football in play at a 2.5%
  median locked return, 3 MLB. Three paper covers have settled (+$5.00 gross, +$0.75, and one
  PARTIAL at −$2.73 whose cause is fixed). A clean print is a priced book, not a fill.
- **The paper window is F5** (n = 37, from 2026-09-05 07:53Z). F3 stopped itself on its first
  unhedged paper leg — a design finding (the hedge limit was a VWAP budget sent as a per-level IOC
  limit), fixed at `30c8511` — and is void from a 24 h SIGBUS gap besides.
- **Fees come from the venues' own payloads** since 2026-09-02; the Kalshi curve is pinned from
  real fills (taker 0.07, maker 0.0175, unscaled); paper fills carry the pinned fee since
  2026-09-05. Every "cents from actionable" number before 2026-09-04 overstates the Kalshi fee.
- **Both proofs gate every cover.** `nodes/rules_exhaustive` proves the outcome set is complete;
  `nodes/settle_wedge` proves the two venues pay equivalently from their own rules text against
  reviewed templates (a venue rewording moves the hash and blocks the league — soccer, 2026-09-04)
  and prices the bounded residual from a registered measurement.
- **Coverage is 20 registered leagues, 11 enabled** (`nodes/entities/leagues.py`): mlb, nfl, epl,
  lal, bun, cfb, elc, el1, ita, atp, wta. Tennis prices on an upper-bound reserve (F4) until its
  forward row accrues. NBA/WNBA/NHL await the venues' listings; MLS and three soccer leagues await
  a postponement source (`nodes/watch_fd` is built and awaits a token); UFC, KBO, NPB await the
  census's fourth run. Golf has no head-to-head market on either venue.
- **The host is the weak part.** The lane's loop is prompt (L38); the Mac pages under load and
  killed the lane once with a SIGBUS. The Ashburn box (L34) is the fix and is the operator's.

## History

`CHANGELOG.md` — dated, append-only. What changed and why.

## Next

`NEXT.md` — one file, overwritten, explicitly an opinion. Never a second handoff document.
