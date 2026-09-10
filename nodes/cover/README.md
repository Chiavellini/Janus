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

`best_cover(offers, contracts, *, now_utc, max_leg_age_s, proof, top_k)` → `Cover`, where `proof`
is a `CoverProof` minted by `nodes/settle_wedge.certify_cover` from an `ExhaustiveOutcomeSet` and a
`SettlementEquivalence` — anything else is rejected with `cover_proof_missing`.
`edge_per_contract = 1.0 − cost_per_contract`. Return is on **capital deployed across both legs**.

Five named reject reasons — `stale_leg`, `shared_liquidity_source`,
`outcome_set_not_proven_exhaustive`, `insufficient_depth`, `quote_not_accepted`. They map onto
the `OpportunityStatus` enum (plan P0b) rather than a separate grid runtime.

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

**No leg-risk / slippage term.** Both legs are priced at simultaneous full VWAP fill. Kalshi leads
Polymarket by 5–10 s, with 36% of ≥10 bps jumps unrepriced on PM within 60 s. The buffer must be
*measured* from captured frames (plan P1/P4), never chosen. `GATE_TO_LIVE.md` already requires it.

**The settlement gate is the proof itself.** `price_combination` takes a `CoverProof` — the
exhaustiveness proof composed with `nodes/settle_wedge`'s equivalence proof — and rejects anything
else with `cover_proof_missing`. The proof also supplies the settlement-risk reserve (probability ×
worst-case loss on each bounded dimension, at the fill prices, Polymarket legs only), which is
inside `cost_per_contract` and reported as `settlement_buffer_per_contract`.

**Fees are only as good as the params on the `Leg`.** `Leg.fee_overrides` must carry the venue's
own schedule (Kalshi series `fee_type`/`fee_multiplier`, Polymarket `feeSchedule`); with an empty
dict the registry pin is charged, which for Kalshi sports is 2× the real fee. `nodes/game_poller`
refuses a leg without a schedule; a direct caller must not.

**The total-cost model (2026-09-03).** Fees are charged over one `Fill` per ladder level actually
consumed (a single VWAP fill overstated the concave p(1−p) fee). A size below any leg's
`min_order_contracts` (Polymarket's Gamma `orderMinSize`; Kalshi 1) is `below_min_order`, not a
cover. `frontier()` additionally takes per-venue `balances` (a rung whose venue capital exceeds
its balance stops the frontier with `balance`; absent means zero), `fixed_cost_usd`, and
`slippage_per_contract` with a `slippage_modelled` label that stays False until the buffer comes
from a registered measurement of captured frames — a False label caps the mode at PAPER.
`Leg.executable` remains a per-leg boolean for sportsbook acceptance, not per level.

Callers that require an execution shape pass `required_venues` and `leg_count`; filtering occurs
inside the exact combination search, so a cheaper same-venue or three-leg cover cannot mask the
best executable two-leg Polymarket+Kalshi alternative.

## Tests

`nodes/cover/tests/test_cover.py` (12) and `test_capacity.py` (11). Until 2026-09-02 the first
file was invisible to pytest.
