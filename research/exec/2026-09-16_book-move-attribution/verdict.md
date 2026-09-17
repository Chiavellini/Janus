# L143 verdict — the first-leg gap is one-sided, and speed cannot recover it

**Registered verdict: `MIXED_OR_INCONCLUSIVE`.** No branch of the registered `decision_rule` was
satisfied, and none was widened to reach one. The substantive finding below is nonetheless strong and
points away from latency.

Read-only over the whole `executions` table (`max_rowid = 335`, so this is every execution ever
recorded, not a window), excluding the registered scalar cover. 334 executions in scope; **202 carry
both a frozen plan ladder and a fresh confirmation ladder.**

## Why the registered rule returned inconclusive

`ADVERSE_SELECTION_DOMINATES` required three conditions. Two were met decisively and one was not:

| Registered condition | Observed | Met |
|---|---|---|
| all-rows signed gap ≥ 1.5c against us | median **+6.0c**, mean +6.37c | ✅ |
| favourable fraction < 0.40 | **0.005** | ✅ |
| Spearman rho(elapsed, \|gap\|) < 0.20 | **0.3068** (95% CI 0.12–0.47, n=106) | ❌ |

`LATENCY_DOMINATES` failed on the first two by enormous margins. `PHANTOM_DEPTH_DOMINATES` failed
outright: **0 of 161 declines** held the planned price with insufficient depth. So the rule lands in
`MIXED_OR_INCONCLUSIVE`, exactly as registered.

## The rho that blocked the verdict is confounded by outcome

Pre-specified in `measurements` ("rank correlation... with n reported for each"), computed *within*
each terminal state rather than pooled:

| State | n | median elapsed | rho(elapsed, \|gap\|) |
|---|---|---|---|
| `BOOK_MOVED` | 95 | 737.6 ms | **0.1646** |
| `ORDER_UNFILLED` | 8 | 321.2 ms | **0.0825** |
| `RECONCILED` | 3 | 627.6 ms | — (n too small) |

**Both within-state correlations fall below the registered 0.20 threshold.** The pooled 0.3068 arises
because declines take roughly twice as long *and* move much further — the correlation is carried by
the between-group difference, not by elapsed time moving the price within a group.

This is a limitation of how the rule was written, not of the data: I registered the threshold on a
pooled statistic without anticipating the outcome confound. **The verdict stands as
`MIXED_OR_INCONCLUSIVE` regardless** — the branch is not being re-opened after the fact. What follows
is reported as a diagnostic, and any decision resting on it needs its own registered row.

## The distribution is one-sided in a way diffusion cannot produce

Signed gap in cents across all 202 rows:

```
 -1: 1
  0: 46
  1: 2   2: 3   3: 8   4: 11   5: 19   6: 30   7: 10   8: 12   9: 17
 10: 6  11: 12  12: 7  13: 4   14: 6  15: 1  16: 2
 22: 1  23: 1   30: 1  32: 1   51: 1
```

**155 adverse, 46 exactly zero, 1 favourable.** A latency or diffusion process over a ~700 ms window
is symmetric: if we were merely slow, roughly half of these moves would have gone *in our favour* and
we would have captured them. The observed favourable fraction is **0.005**. Every value is an integer
number of cents, consistent with venue tick moves rather than continuous drift.

The gap is also bimodal by outcome, not continuous:

| State | n | median gap | p90 | max |
|---|---|---|---|---|
| `RECONCILED` (filled) | 10 | **0.0c** | 0.0 | **0.0** |
| `ORDER_REJECTED` | 7 | **0.0c** | 0.0 | **0.0** |
| `ORDER_UNFILLED` | 24 | 0.0c | 0.0 | 10.0 |
| `BOOK_MOVED` (declined) | 161 | **+7.0c** | +13.0 | +51.0 |

**Every row that reached a fill saw the book not move at all.** There is no middle. The lane does not
lose a race by a little; it either sees a stable book and trades, or sees a price that was never
there.

The single favourable row is itself instructive: `5355ccd1`, ITF, 25 contracts, frozen marginal 0.24
against **45,179 contracts of displayed depth**, confirmed at 0.23 with `frozen_price_still_present:
false` and **zero** confirmed depth at the frozen price. Forty-five thousand contracts of displayed
liquidity that did not exist.

## What this does and does not license

**It argues against spending the live window on latency work for the taker first leg.** Removing or
shortening the confirmation cannot recover rows whose price was already wrong when we selected them —
it would convert a safe pre-wire decline into a fill at a price 6c worse than planned. This is
consistent with L141's own caution and with the inherited Polymarket control (filled windows settling
−22c against +9.4c unfilled).

**Two caveats bound it, and neither is minor.**

1. **This is a taker-path result only.** The confirmation block is gated on `if not
   plan.first.post_only` (`coordinator.py:207`), so maker rows carry no confirm ladder. 132 of the 334
   executions lacked one and are reported as missing, not imputed. Nothing here describes the maker arm.

2. **Selection at execution creation is not removed.** This row fixed the conditioning on
   `BOOK_MOVED` that L141 suffered, but an execution only *starts* when the frozen book passes the
   entry screen — so the frozen marginal is selected to look favourable, and regression toward the
   true price would also produce one-sided gaps. **A winner's-curse mechanism is not excluded by this
   row.** Two observations sit awkwardly with a pure winner's-curse story — the 46 exact zeros and the
   fact that all 10 filled rows show exactly 0.0c rather than partial regression — but that is
   suggestive, not dispositive. Discriminating properly requires relating gap magnitude to the size of
   the edge the screen saw, which is a separate registered measurement.

## Recommended next row

A follow-up L-row testing winner's curse directly: does gap magnitude scale with the apparent edge at
selection? If it does, the entry screen is selecting stale ticks and the fix is in what we screen on —
the websocket ladder's fidelity — not in how fast we act on it. If it does not, the ladder is
systematically misreporting executable depth, which is a venue-data problem and a different fix again.

Either way, **no speed successor should be registered on this evidence**, and the registered
`prohibited` clause of this row already forbids reading it as authority to remove the confirmation.

No production state, order, kill, override, cap, hurdle or entry policy was changed. Raw extractor
output is retained verbatim at `results_20260916.json`, schema `janus.l143.book_move_attribution.v1`,
matching `measure.py`.
