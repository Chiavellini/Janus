# L25 — does edge live where size lives?

**Verdict: `NOT_SIGNIFICANT` — no evidence of the hazard at this power. Explicitly NOT proof of
absence.** Executed 2026-08-20 against the immutable spec. `test_looks_spent: 1` — the project's
first. No outcome and no settlement were read.

## Result

Population: 509 unique Kalshi markets from L24's verified pairs; 494 scored (15 excluded, all
`pm_one_sided`, counted not dropped). Significance bar `p < 0.0040` (BH-FDR q=0.10, m=25).

| | primary (all, n=494) | robustness \|edge\| ≤ 20¢ (n=193) |
|---|---|---|
| decile cut | $18.15 | $15.16 |
| median edge, top decile | 43.758¢ | 2.358¢ |
| median edge, rest | 24.471¢ | 0.299¢ |
| **difference** | **+19.287¢** | **+2.059¢** |
| permutation p | 0.128 | 0.365 |
| Spearman rho | −0.0646 | −0.1128 |
| rho p | 0.154 | 0.120 |
| significant | **no** | **no** |

Per the registered decision rule this is the `not_significant` branch: **no evidence that edge is
anti-correlated with capacity.** The top decile does not show a detectably smaller edge.

## What the numbers actually say — read this before believing the headline

**The two statistics disagree in SIGN.** The decile difference is *positive* (+19.3¢: the big
markets look better) while Spearman rho is *negative* (−0.065: edge mildly decreasing in size).
A monotone relationship cannot do that. Whatever is driving the decile split is not a clean
size effect.

**The population is heavily contaminated, and the run quantified it.** A median apparent edge of
**24.5¢ across all markets** is not a plausible cross-venue number — it implies two legs costing
75.5¢ for a $1 payoff, a 32% riskless return, on contracts that are supposedly the same question.
`match/screen.py`'s own docstring states the rule: *"A large nominal edge on an unverified pair is a
red flag, not an opportunity: it usually means the two markets are NOT the same question."*

The trim is the measurement: **61% of markets (494 → 193) carry |edge| > 20¢.** That is the
false-pair rate showing through, and it is far higher than the population can absorb. In the trimmed
sample the medians fall to plausible magnitudes (2.36¢ / 0.30¢) and the test is still null.

So the honest summary is not "the hazard is absent". It is: **this test was largely uninformative,
because the variable it correlates against is dominated by pairs that are not real pairs.**

## What this cost and what it bought

It cost the project's first test look. It bought three things:

1. The hazard flagged on 2026-08-20 — that capacity might be anti-correlated with edge — is **not
   confirmed**. It cannot be ruled out either; the sign disagreement and the contamination both
   bound what can be claimed.
2. A **quantified contamination indicator**: 61% of scored markets carry an implausible edge.
3. A consequence that is now unavoidable: **`match/gold/nonsports.csv` is the binding constraint on
   everything downstream.** This was pre-registered as the largest threat before the run
   (*"verifier precision is unmeasured and the false-pair share is unknown"*), and the result
   converted it from a caveat into the critical path.

## What must NOT be concluded

- Nothing here says an edge exists, is real, or is harvestable. No settlement was read.
- Nothing here licenses scaling the cross-venue program. A null on a contaminated population is
  not a green light.
- The +19.3¢ decile difference must not be quoted as a finding. It is not significant, it disagrees
  in sign with the rank correlation, and it sits on a population where the median edge is itself
  implausible.

## Next, in order

1. **Label `match/gold/nonsports.csv`** (144 blind pairs, key withheld). Until verifier precision is
   known, no cross-venue statistic on this corpus can be interpreted.
2. Re-run this row's statistics on the surviving high-precision population **as a new row** — the
   criteria above are immutable and must not be re-fitted (rule 6).
3. L24 capture continues regardless; it is unaffected by this result.
