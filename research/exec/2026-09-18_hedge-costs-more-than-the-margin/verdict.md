# L151 verdict — `SLIPPAGE_EXCEEDS_MARGIN`: the hedge costs four times the margin entry requires

Read-only. Nothing was traded, armed, deployed or written. `measure.py` ran on the box against
`/srv/janus/tuples/tuples.sqlite` in `mode=ro`; its output is `results_20260918.json`.

## The number

Over **every real-money Kalshi hedge order the lane has sent**, comparing the fill average with the
plan's own hedge VWAP — the price entry charged it:

| | |
|---|---|
| Filled hedges carrying a plan VWAP | **17** |
| Median realised slippage | **+1.98c per contract** |
| p90 | **+10.00c** |
| Worst | **+15.75c** |
| Adverse | **15 of 17** |
| Margin entry requires (`EXECUTION_MIN_LOCKED_RETURN` 0.005 on a $1 contract) | **0.50c** |

**The hedge costs about four times the margin the lane demands before trading**, and it is adverse
almost every time. That is the whole of L150's finding: the arbitrage earned +$0.812 over 25 covers
while unhedged remainders earned +$3.365, because the margin being selected cannot survive the hedge.

## Per league (every figure with its sample size)

| league | hedge orders | filled | zero-fill | slippage median | p90 | worst |
|---|---|---|---|---|---|---|
| mlb | 511 | 1 | 510 | +15.75c | +15.75c | +15.75c |
| atp | 26 | 7 | 19 | +3.00c | +5.00c | +10.00c |
| wta | 6 | 1 | 5 | +12.20c | +12.20c | +12.20c |
| itf | 5 | 4 | 1 | +0.50c | +1.96c | +1.96c |
| ita | 3 | 2 | 1 | +2.98c | +3.98c | +3.98c |
| lal | 1 | 1 | 0 | 0.00c | 0.00c | 0.00c |
| nfl | 1 | 1 | 0 | +6.00c | +6.00c | +6.00c |

Read these as orders of magnitude, not as registerable values: only atp has more than four fills, and
the spec forbids registering a per-league reserve from this sample. **itf is the one league whose
median slippage (0.50c) sits at the required margin**; every other measured league is above it.

The mlb row is one execution on 2026-09-12 that sent **511 hedge IOCs in 14 minutes** and still left
7.14 contracts naked. That is history: L105 (2026-09-14) added `max_protect_submits_total = 60` and
`protect_total_window_s = 600`, and no execution after that date shows more than two attempts.

## Why this was not caught earlier

The machinery to charge it exists and is switched off:

- `nodes/cover/capacity.py:49-50` — "this constant has never gated an order: `slippage_for` is read
  only by `frontier()`, for the reported N_max/N*, and never by `best_cover` / `plan_from_cover` /
  `clear`." So **entry charges the hedge its walked VWAP and nothing for what it actually pays.**
- The pooled 4c reserve was set to 0.0 by operator decision on **2026-09-08** — the last day the lane
  made money — because it was measured at a 3 s horizon the box does not run and "priced out nearly
  every cover the lane printed". That reasoning was sound; the replacement never arrived.
- **L41** (2026-09-07) was registered to produce measured per-league values and **never ran**.
  **L86** (2026-09-12) measured realised slippage per league, already recorded `atp −3.29, adverse
  5 of 5, on a 0.46c margin`, and is still PENDING with no verdict. A 2026-09-13 analysis found that
  `margin − slippage` predicts a cover's sign on **16 of 19** covers and recommended gating on it.
  None of the three was actioned.

So this row is the fourth time the same thing has been measured. It is the first time it has been put
next to the number entry actually requires.

## The fix, and why it is not a small wiring change

I implemented the obvious change — charge `slippage_for(league)` in `plan_from_cover`'s `clears()` —
and **reverted it, because it does not bind**. `clears()` is consulted only when the entry limit is
snapped up to the venue tick (plan.py:390) and when the one-tick pad is applied; the cover's
acceptance is decided earlier, by `best_cover` and then authoritatively by
`nodes/risk/clearance.py:205` on `cand.locked_return`. A charge in `clears()` would tighten two
narrow decisions and look like a fix. Sweeping the fixture space (every hurdle from 0 to 0.40)
produced **no case where the charge changed accept to refuse**.

**Where it must bind:** the locked return itself — the quantity `clearance` compares against
`min_locked_return` — so that a cover's stated margin is net of the hedge's measured cost. That
changes what every recorded evaluation says, and therefore the replay rows digest, so it needs its
own registered row, a dated GATE amendment and an operator release. It is not a worktree tweak.

**And it will not create profit.** With a median slippage of 1.98c against a 0.50c requirement,
charging the measured cost prices out essentially every cover the lane currently takes — which is
exactly what the 4c pooled reserve did before it was removed. The honest statement of the position:

> At current thresholds and current hedge quality, this lane has no edge. Its apparent profit came
> from unhedged remainders. Charging the hedge honestly does not make it profitable; it stops it
> paying for trades whose margin was never large enough to survive the hedge.

Profit requires one of: materially **lower hedge slippage** (faster hedging, or only books deep
enough to absorb the size), materially **larger margins** (a higher hurdle, which means far fewer
covers), or a **different mechanism**. Which of those to pursue is the operator's decision, and the
evidence for it is now on one page.

## What this does not establish

- No per-league reserve is registered from these 17 fills; L41's frame-based row, or L86's 20-cover
  bar, is what can carry a value.
- Slippage here is measured against the plan's own walked VWAP. It therefore includes the book moving
  between decision and send, thin depth, and chasing across phases, without separating them. L73
  (2026-09-11) found the walk, not the retries, closed both covers it examined.
- Fees are reported per league but are not part of the verdict's arithmetic.
