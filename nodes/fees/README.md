# fees

**Kind:** `pure`
**Implements:** `registry.py` (pins), `models.py` (curves), `targeting.py` (the hurdle curve), `venue_costs.py` (frozen anchor)

**The single place a fee is defined.** A charged fee above the pinned curve is a STOP-grade event,
not a rounding note.

## Position in the grid

```
[venue_*] ──▶ Book ──┐
                     ├──▶ [fees] ──▶ fee-net cost ──▶ [cover]
market payload ──────┘
```

**Upstream:** Per-market fee params from venue payloads (`NormMarket.fee_params`).
**Downstream:** `nodes/cover` — the only consumer that matters.

## Contract

`model_for(venue)`, `params_for(venue, overrides)`, `screening_coeff(...)`.
**Per-market payload values ALWAYS win over the pins.** The pins are a discovery-time fallback.

Kalshi is `ceil(0.07·C·p(1−p))` with the ceil applied PER ORDER (taker; maker 0.0175, 4× cheaper).
The fee collapses in the wings — 0.63¢ at p=0.90 vs 1.75¢ at p=0.50 — so **lopsided games are ~3×
cheaper to cover than coin-flips**, which nothing currently exploits.

`venue_costs.py` is FROZEN. `models.py` reproduces it digit-for-digit as the regression anchor.

## The hurdle is a curve, not a constant

`targeting.py`. Both legs of a cover sit at `p` and `~(1-p)`, and `p(1-p)` is symmetric, so the
combined fee is about `(k_kalshi + k_pm) * p * (1-p)` -- the SAME point on the curve for both legs.

| favourite price | combined fee | asks must total | gap needed |
|---|---|---|---|
| 0.50 | 3.00c | <= 0.9601 | **3.99c** |
| 0.75 | 2.26c | <= 0.9675 | 3.25c |
| 0.90 | 1.08c | <= 0.9793 | 2.07c |
| 0.95 | 0.58c | <= 0.9843 | 1.57c |
| 0.99 | 0.12c | <= 0.9889 | **1.11c** |

A coin-flip needs a ~4c cross-venue divergence to clear 1%; a heavy favourite needs ~1.1c. That is
why the lane ranks by distance-to-actionable rather than by price.

Measured on the first fee-aware run: **BAL @ COL sat at gross 1.0000 -- exact cross-venue parity --
and was further from actionable than ATH @ TEX at gross 1.0060**, because the coin-flip fee was 14x
larger. Ranking on price alone picks the wrong game.

This says how large a divergence a game NEEDS, never how likely that divergence is. Whether
lopsided games actually diverge more is an empirical question the recorded distribution answers.

## Failure modes

`registry.py` documents that hardcoding a Polymarket rate was a real live bug — and
`grids/live_sports/grid.py` hardcodes `{"fee_rate": 0.05}` anyway instead of reading `feeSchedule`.
The measured distribution is 0.04 → 1,262 markets, 0.07 → 372, 0.05 → 336.

`models.py` says a missing `fee_multiplier` "is an error, not a default" and then silently defaults
it to 1.0.

`carry_credit` (Kalshi pays 4.05% APY) is implemented and has **zero call sites**. Over a 240-day
hold that is 2.7 points — larger than the whole 1% hurdle.

Unmodelled entirely: gas/bridge (Polygon), FX and crypto spread, deposit/withdrawal, min stake.

## Tests

`nodes/fees/tests/test_fees.py`.
