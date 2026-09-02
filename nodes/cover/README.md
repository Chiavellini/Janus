# cover

**Kind:** `pure`
**Implements:** `cover.py` (the price), `capacity.py` (the size frontier)

**The one number the whole system exists to compute.** A cover buys every outcome so exactly $1
arrives whichever way it settles. Cover for less than $1 and the difference is arbitrage.

This is the best-engineered module in the repo: it walks the ladder (never quotes the touch),
re-prices the exact cartesian product after greedy candidate generation, takes the WORST
settlement state rather than the expected one, hard-rejects stale legs, and dedupes by
`liquidity_source`.

## Position in the grid

```
[venue_kalshi]  ──┐
[venue_polymarket]├──▶ [fees] ──▶ [cover] ──▶ Cover(cost, edge, reject_reason) ──▶ [store_tuples]
[venue_sxbet]   ──┘
```

**Upstream:** `nodes/venue_*` (books), `nodes/fees` (curves).
**Downstream:** `nodes/store_tuples`, `nodes/analysis`.

## Contract

`best_cover(offers, contracts, *, now_utc, max_leg_age_s, exhaustive, top_k)` → `Cover`.
`edge_per_contract = 1.0 − cost_per_contract`. Return is on **capital deployed across both legs**.

Five named reject reasons — `stale_leg`, `shared_liquidity_source`,
`outcome_set_not_proven_exhaustive`, `insufficient_depth`, `quote_not_accepted` — which become
this node's fault vocabulary under the grid runtime.

## Capacity: how much it is worth, not whether an edge exists

`capacity.py`. The lane priced three fixed sizes and reported whether each cleared the hurdle. That
answers *is there an edge at 100 contracts*; it does not answer *how much does this make*.

A cover buys equal **payout** units, not equal dollars: N contracts of each complementary outcome,
each settling at $1, so exactly $N arrives either way. The cost of the Nth unit rises as both
ladders are eaten, so `profit(N) = N · (1 − cost(N))` rises then falls, and **two different sizes
matter**:

- **`N_max`** — the largest size still clearing the hurdle. The capacity of the opportunity.
- **`N_star`** — the size maximising total profit. Where you would actually trade.

`N_star ≤ N_max` always, and on a layered book they are far apart:

```
       N     cost     edge     profit    capital
    1000   0.8300  +0.1700     170.00     830.00
    8000   0.9213  +0.0787     630.00    7370.00   ← N_star  (8.5% on capital)
   18000   0.9928  +0.0072     130.00   17870.00   ← N_max   (0.7%)
```

Solved at the ladders' own **breakpoints** — the cumulative depths where `cost(N)` bends — which is
exact, where a binary search over a fee curve that steps (Kalshi's ceil is per *order*) can land
between steps and misreport the frontier by a level.

A rung must be **strictly** profitable. A cover priced at exactly 1.0000 locks nothing, and it is
the single most common state on a coherent market — admitting it would report a frontier on every
pair in the universe.

## Failure modes

**`exhaustive` is a caller-supplied `bool`, and `grids/live_sports` passes `True` for every
league** including `epl` (3-way) and `nfl` (regular-season ties). The module docstring states the
invariant this violates. An EPL match at home 0.46 / away 0.30 / draw 0.24 reports a cover cost of
~0.76 and a **+31% locked return** — a bet the match is not drawn. Fix: replace the bool with an
`ExhaustiveOutcomeSet` token only a citation-checked rule table can mint.

**No leg-risk term.** Both legs are priced at simultaneous full VWAP fill. Measured book RTT is
402–452 ms per venue and Kalshi leads Polymarket by 5–10 s, with 36% of ≥10 bps jumps unrepriced
on PM within 60 s. `GATE_TO_LIVE.md` already requires this term.

**No settlement gate.** `SettleRef`/`VoidPolicy`/`TiePolicy` exist in `kernel/schema.py` and are
never consulted; there is no `settlement` reject reason.

A cheaper same-venue cover can mask a real cross-venue one: `best_cover` returns the global
cheapest and the caller then filters for `cross`, reporting `NO_EDGE`.

## Tests

`nodes/cover/tests/test_cover.py` — 12 tests. Until 2026-09-02 these were invisible to pytest.
