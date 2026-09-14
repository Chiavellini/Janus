# L116 confirmation — the pooled latency slope does not replicate

Date: 2026-09-14. Data day: 2026-09-13 UTC.

The registered harness completed one unchanged streaming pass over all 24 Kalshi hour files:
2,797 actionable moments, 30,671 priced samples, 100,232,969 frames, zero parse errors, zero
corrupt files, and 2–14 short-depth observations depending on the window. Runtime was about
35 minutes on the one-vCPU box at `nice -n 19`, not the ~10 minutes estimated in `NEXT.md`.

## Pooled hedge-book drift (cents/contract, positive = dearer)

| elapsed | mean | p50 | p90 | mean vs 2.5 s |
|---|---:|---:|---:|---:|
| 0.5 s | 0.217 | 0.000 | 2.200 | +0.030 |
| 1.0 s | 0.294 | 0.000 | 3.000 | +0.107 |
| 1.5 s | 0.272 | 0.000 | 4.000 | +0.085 |
| 2.0 s | 0.203 | 0.000 | 4.317 | +0.015 |
| 2.5 s | 0.187 | 0.000 | 5.000 | 0.000 |
| 5.0 s | -0.025 | 0.000 | 5.000 | -0.212 |
| 7.5 s | -0.192 | 0.000 | 5.298 | -0.379 |
| 10.0 s | -0.542 | 0.000 | 5.879 | -0.730 |
| 12.5 s | -0.886 | 0.000 | 5.000 | -1.073 |
| 20.0 s | -0.844 | -0.665 | 6.000 | -1.031 |
| 22.5 s | -0.829 | -0.410 | 7.000 | -1.016 |

This is not the monotone ~0.25 c/contract/second curve from 2026-09-11. Moving from 2.5 s to
1.0 s changes the pooled mean from 0.187c to 0.294c: **−0.107c of mean benefit**, rather than the
prior day's +0.50c. The adverse tail still improves: p90 is 3.0c at 1.0 s and 5.0c at 2.5 s.

## Mechanism heterogeneity

The pooled reversal is composition, not a universal favorable-wait result. Mean drift at
1.0 s → 2.5 s was ATP 1.067c → 1.907c, ELC 1.077c → 2.282c, and EPL 2.969c → 4.066c, but
La Liga −0.051c → −0.629c, MLS 0.003c → −0.421c, NFL 1.079c → 0.617c, and MLB 0.251c → 0.162c.
Filters do not transfer across these mechanisms; a pooled cents-per-second value is not a safe
entry-policy input.

## Verdict

The first day's claim that each second costs about 0.25c and that 2.5 s → 1.0 s is worth 0.50c
**fails confirmation**. Speed may still reduce adverse tails and materially helps some leagues,
but its expected-EV value must be measured per league over more than one day before it is used to
justify an entry hurdle or profit forecast.

The negative long-window pooled means are unconditional book drift, not maker EV. A maker fills
selectively when the market comes to it; L63's prospective cohort remains the authority for fill
selection. This result does not authorize or support re-enabling maker entry.
