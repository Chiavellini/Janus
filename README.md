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
                    ┌──────────────────┐
   ESPN ───────────▶│  schedule_espn   │──┐
                    └──────────────────┘  │   canonical key,
                    ┌──────────────────┐  ├──▶ no title matching
   venue labels ───▶│     entities     │──┘
                    └──────────────────┘  │
                                          ▼
                                 ┌─────────────────┐
                                 │  match_sports   │  NO PRICES READ
                                 └────────┬────────┘
                                          │ matched pairs
              ┌───────────────────────────┼───────────────────────────┐
              ▼                           ▼                           ▼
     ┌─────────────────┐        ┌──────────────────┐        ┌─────────────────┐
     │  venue_kalshi   │        │ venue_polymarket │        │   venue_sxbet   │
     │   CLOB, 1¢ tick │        │  best price LAST │        │  zero-rake CLOB │
     └────────┬────────┘        └────────┬─────────┘        └────────┬────────┘
              └───────────────────────────┼───────────────────────────┘
                                          ▼  Book(asks)
                                   ┌─────────────┐
                                   │    fees     │  the only place a fee is defined
                                   └──────┬──────┘
                                          ▼
                                   ┌─────────────┐
                                   │    cover    │  walks the ladder, worst settlement state
                                   └──────┬──────┘
                                          ▼
                            ┌──────────────────────────┐
                            │       store_tuples       │──▶ analysis ──▶ research/
                            └──────────────────────────┘

   parked: venue_cloudbet (sportsbook — acceptance must precede pricing; see its README)
   missing: rules_exhaustive, settle_wedge  ── the two gates that make a cover claim honest
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
python3 -m pytest                      # 92 tests, works from any directory
python3 ops/watchdog.py                # is anything unhealthy?
python3 -m grids.live_sports.grid --leagues mlb --include-near
```

## State of the evidence — read this before trusting any number

- The live scanner has run **twice, ever**, on **one game**, inside a single seven-minute window.
  The "0 opportunities above 1%" result is n=1 at −1.6%, roughly 2.7 points from the hurdle.
- It is **MLB-only in practice**: `nodes/match_sports` hardcodes `^mlb-` in the Polymarket slug
  pattern and applies it to all six default leagues, so five of them emit zero pairs.
- The scan window is live plus ±30 minutes, against a registered universe of 30 days.
- So the null is a **coverage artifact**, not an economics finding. It says nothing about whether
  the edge exists.

Two correctness bugs are known and must be fixed **in this order** — fixing coverage first would
switch on a fake-arbitrage generator:

1. `nodes/cover` receives `exhaustive=True` for every league, including 3-way EPL and tie-capable
   NFL. Replace the bool with a token only a citation-checked rule table can mint.
2. Only then, per-league Polymarket slug patterns in `nodes/match_sports`.

## Next

`NEXT.md` — one file, overwritten, explicitly an opinion. Never a second handoff document.
