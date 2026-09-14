# L116 verdict — latency is priced, and it is expensive

Date: 2026-09-14. 2026-09-11, 674 actionable prints, 7402 samples,
16,730,092 Kalshi frames, 0 parse errors, 0 corrupt files, 0 short-depth.

## Hedge-book drift from the moment a cover was priced (cents/contract, + = dearer)

| elapsed | p50 | mean | p90 | vs the 2.5 s baseline |
|---|---|---|---|---|
| 0.5s | 0.00 | 0.18 | 0.31 | -0.60 |
| 1.0s | 0.00 | 0.28 | 1.98 | -0.50 |
| 1.5s | 0.00 | 0.57 | 3.95 | -0.20 |
| 2.0s | 0.00 | 0.66 | 5.00 | -0.12 |
| 2.5s | 0.00 | 0.78 | 5.82 | +0.00 |
| 5.0s | 0.00 | 1.30 | 7.00 | +0.53 |
| 7.5s | 0.00 | 1.97 | 9.00 | +1.19 |
| 10.0s | 0.24 | 2.35 | 9.00 | +1.57 |
| 12.5s | 0.68 | 2.83 | 10.00 | +2.05 |
| 20.0s | 1.00 | 3.36 | 11.00 | +2.59 |
| 22.5s | 2.00 | 3.53 | 11.59 | +2.75 |

The taker's own exposure today is the **2.5 s** row: L108 measured decision to hedge-ack at
2,480 ms p50, and the hedge is only priced when it acks.

## Answer 1 — each second of execution latency costs about 0.25 c/contract

Between 1.0 s and 2.5 s the mean drift runs 0.28c → 0.78c. **The median booked margin on a cover is
0.67c.** So the drift over today's path is **larger than the entire margin**, which is the
arithmetic reason half of all covers lose money while every one of them was an arbitrage at entry.

Cutting the path from 2.5 s to 1.0 s is worth **0.50 c/contract** — against a 0.67c margin, that is
a three-quarters improvement in what a cover keeps, and it flips the sign: 0.67 − 0.78 = −0.11c
becomes 0.67 − 0.28 = **+0.39c**.

L103 and L109 have already taken roughly 390 ms out of that path and are now deployed, which on this
curve is about **0.12 c/contract** already banked.

## Answer 2 — and it makes the maker path *less* attractive, not more

A maker saves the 0.828c Polymarket entry fee but pays drift for the length of its rest, **on top of
the drift a taker already pays**. Incrementally, against the 2.5 s baseline:

- rest ~2.5 s → +0.53c of extra drift against 0.828c saved → **net +0.30c**
- rest ~5 s → +1.19c → net −0.36c
- rest ~17.5 s → +2.59c → net −1.76c

So the maker case closes only with a **very short** rest — and a short rest is exactly where the
fill rate was zero: of the 17 post-only orders ever sent, the **only** one that filled rested
20.46 s, where the incremental cost is +2.75c against 0.828c saved. Short rest, no fills; long rest,
no economics.

**And the faster the taker gets, the worse the maker looks**, because the maker's cost is measured
incrementally against a shrinking baseline. The speed work and the maker path are substitutes, and
the speed work is the safer one: it improves the path already running, needs no GATE row, does not
contradict F20, and depends on no fill-rate assumption.

## What this does not say

This is **book drift**, a lower bound on realised slippage. The live `hedge_slippage_c` is measured
against the realised fill average, so it also contains the cost of chasing up the ladder — its
median is 3.0c against the 0.78c of pure drift here. Post-L85 realised slippage is p50 0.50c, close
to these numbers, which is the consistency check.

It is also one day and one slate, ITF-dominated. The second day (2026-09-13, 2,314 prints) is the
confirmation and is still owed.
