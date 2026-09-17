# L144 verdict — joint selection is excluded; the defect is Polymarket-side, and it is two mechanisms

**Registered verdict: `MIXED_OR_INCONCLUSIVE`.** No branch was widened to reach anything stronger.
But the registered rule *does* affirmatively exclude one hypothesis, and the data is one-sided enough
that the practical conclusion is not in doubt.

**The reconciliation gate passed first, as required:** over the 202 Polymarket-only rows this
extractor reproduces L143 exactly — **155 adverse / 46 zero / 1 favourable**. The instrument agrees
with the prior result before any new number is read.

169 executions carry a frozen ladder *and* a fresh confirmation for **both** legs. Both legs are
confirmed concurrently on the same clearance window (`coordinator.py:205-215`) off the same
`books_json` snapshot, so the comparison is symmetric in timing by construction.

## The two histograms, same 169 executions

```
KALSHI      -5:1  -4:2  -3:7  -2:5  -1:30 │ 0:102 │ +1:13 +2:3 +3:1 +5:1 +7:1 +8:1 +10:1 +14:1
POLYMARKET              -1:1             │ 0:40  │ +1:1 +2:2 +3:6 +4:9 +5:16 +6:27 +7:10 +8:12
                                                   +9:15 +10:5 +11:11 +12:4 +13:3 +14:2 +15:1
                                                   +16:1 +30:1 +32:1 +51:1
```

| | favourable | zero | adverse | median | mean |
|---|---|---|---|---|---|
| **Kalshi** | **45** | 102 | 22 | **0.0c** | **−0.05c** |
| **Polymarket** | **1** | 40 | 128 | +6.0c | +6.10c |

Conditional on the price moving at all — the scale-free symmetry statistic, **not pre-registered**:

- **Kalshi: 67.2% favourable** (45 of 67 moves)
- **Polymarket: 0.78% favourable** (1 of 129 moves)

## Joint selection is excluded — and that *is* a registered conclusion

`JOINT_SELECTION` required Kalshi favourable fraction < 0.30 **and** Kalshi median gap ≥ 1.5c. The
median is **0.0c**. The branch is definitively not satisfied, by the rule as written, before any
reinterpretation.

If the pair had been selected on combined noise, the Kalshi leg would regress too. It does not. On
the same rows, in the same windows, Kalshi is symmetric and if anything tilts *in our favour*
(mean −0.05c). **The defect is on the Polymarket side.**

## Why the verdict is still `MIXED_OR_INCONCLUSIVE`

`VENUE_SPECIFIC_POLYMARKET` required Kalshi favourable fraction ≥ 0.30. Observed: **0.2663** — short
by 0.034.

That threshold was mis-specified, and the reason is visible in the data: **102 of 169 Kalshi rows are
exactly unchanged.** With 60% zeros, the favourable fraction over *all* rows is mechanically capped
near 0.40 even under perfect symmetry, so 0.30 was never the right bar for "symmetric." The correct
symmetry statistic conditions on the price having moved, and on that basis Kalshi is 67% favourable.

I am reporting the registered verdict rather than the one I would now prefer. This is the second
threshold I have mis-specified in two rows (L143's was a pooled rho that turned out confounded by
outcome), and the pattern is worth naming: I have twice chosen a statistic that was correct in spirit
and wrong in its denominator. The pre-registration is doing its job — it is stopping me from
upgrading a verdict after seeing the number — but the thresholds themselves need more care before
the next row.

## Both secondary mechanisms are load-bearing, and they interact

Polymarket-only, per the registered secondary rule (marginal |rho| ≥ 0.25 holding sign at |rho| ≥ 0.15
in at least two of three strata of the other predictor):

| Predictor | marginal rho | low | mid | high | load-bearing |
|---|---|---|---|---|---|
| **apparent edge** (stratified by book age) | 0.3648 | 0.1674 | 0.2982 | **0.6542** | ✅ 3/3 |
| **frozen book age** (stratified by edge) | 0.3337 | 0.2305 | 0.4587 | 0.3802 | ✅ 3/3 |

**Both qualify**, and the registered rule says to state that plainly rather than choose. Each survives
stratification on the other, so neither is merely a proxy for the other: the gap grows both with how
good the deal looked *and* with how stale the book was.

The interaction is the informative part. The apparent-edge effect is weak in the freshest books
(rho 0.167) and **strongest in the stalest** (rho 0.654). The reading most consistent with that: a
stale Polymarket ladder is what *makes* a deal look good, the entry screen selects on the fiction, and
the confirmation reveals it was never there. Staleness and selection are not competing explanations
here — staleness manufactures the apparent edge that selection then chases.

## What bounds this

- **Taker arm only.** Both confirmations are gated on `not plan.first.post_only`. 132 executions
  carried no Polymarket confirmation and 33 more carried no Kalshi confirmation; all are counted and
  named, never imputed. Nothing here describes the maker arm.
- **The Kalshi leg is a weaker control than it first appears.** Both legs are screened, but not
  equally hard: L141 found 90 of 95 declines failed the *Polymarket* price/depth check and only 5
  failed the Kalshi break-even check. The first leg is where the screen binds, so it is also more
  heavily selected on. Asymmetric selection pressure could produce asymmetric regression on its own.
  What argues against that being the whole story is the book-age correlation surviving within edge
  strata (0.231 / 0.459 / 0.380) — selection alone does not predict a staleness gradient.
- **Venue microstructure differs.** Kalshi's asks are synthetic folds of NO bids and both ladders are
  truncated to 25 levels. Polymarket's book is also older (p50 356ms vs 188ms). Age alone cannot
  produce one-sidedness — a random walk is symmetric at any age — but the venues are not identical
  instruments and the median-gap comparison in cents is scale-dependent.

## Recommended next row

The target is now specific: **the Polymarket websocket book's fidelity**, not the lane's speed.

The cheapest decisive follow-up is to compare the websocket ladder against a REST read on the *same
market at the same instant*, on markets the lane did **not** select. That removes selection entirely
and measures feed fidelity directly. If the ws ladder is systematically optimistic on unselected
markets too, the fix is in how the lane sources or ages that book — and it is an engineering problem
with a bounded scope, which is the best news this line of work has produced.

No production state, order, kill, override, cap, hurdle or entry policy was changed. Raw extractor
output is retained verbatim at `results_20260916.json`, schema `janus.l144.venue_gap_asymmetry.v1`,
matching `measure.py`.
