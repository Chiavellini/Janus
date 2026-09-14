# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-14 ~05:30Z, on `claude/hedge-ladder-speed-3b5042c`.

## Where it stands

**Trading is stopped and should stay stopped until the release below is pasted.** `kill/live` is
latched (the guard, on `77013052`'s unprotected residual — correctly). The lane process is up and
pricing; it is entering nothing. **No open positions**; the Dolphins/Raiders position settled
**−$1.1392**, the worst-case branch.

The box runs **`9387297`** (L96–L100). **Pushed and NOT deployed: `a213130` (L101), `49b8e79`
(L102/L103), `c5f6da4`.** Suite green at **1,547 tests, zero skips**.

Box health is good and that is new: **load 0.46, loop lag 0.32 s**, down from 4.8 and rising before
L100 landed. The runaway protect loop was most of the saturation.

## The honest position on the money

Six days live, and the number that matters is not the headline:

- **The arbitrage business made $0.98 in total — $0.14/day.** The +$4.34 headline is **77%
  `directional_usd`**: money made on contracts that were never hedged, and **$4.25 of it is one
  accident** (`789ad9b2`, ten contracts left naked with no hedge ever placed, which happened to win).
  Strip it and 20 covers netted **+$0.09 on $286 of turnover**.
- **Four consecutive losing days** since 09-10. Median cover realises **−$0.0149**; 11 of 21 lost.
- **Fees are 2.05c/contract** (PM taker 0.855c + Kalshi 1.199c) against a **median booked margin of
  0.67c**.
- **Hedge slippage median 3.0c, p90 14c, adverse on 14 of 20.** `margin − slippage` predicts the sign
  of the outcome on **16 of 19** covers. Nothing else does.
- **$100/day is ~208x away** at today's expectancy. The defensible target is **$3–19/day once the sign
  is positive, and $0/day until it is.** Scaling a negative-EV cover scales the loss.

## What this session found, by theme

Row numbers are what nobody remembers, so: themes first, rows in the next section.

**1. The book may be advertising liquidity the engine will not honour.** Of 141 Polymarket taker BUYs,
**118 zero-filled and exactly ONE partially filled.** Losing a race yields crumbs; all-or-nothing does
not. The pre-send confirm has **no discriminating power** — 15 of 16 confirmed zero-fills *and* 6 of 6
confirmed fills showed full size at or below the limit, with identical confirm latency. Orders the
engine `matched` at receipt filled **5 of 5**; orders routed `delayed` filled **13 of 107 (12%)**.
This is the open question the whole strategy turns on, and L102 is the instrument for it.

**2. Fees eat the edge, and half of that is optional.** `PM_MAKER_RATE = 0.0` — *"takerOnly: makers pay
nothing."* The 0.855c is the cost of *crossing*, not of trading. Credited back across 201,870
evaluations it makes **+1,084 more rows actionable (+188%)**, and — the certain, fill-independent half
— every executed cover earns **+0.855c**, which more than doubles a 0.67c cushion.

**3. We are ~10x slower to act than to look.** Observation (book change → decision) is **~200 ms
median**; execution (decision → hedge ack) is **2,480 ms**. Of leg A's 564 ms, **354 ms is a cold
metadata cache** paid by 56% of orders. Signing is 6.8 ms. **Mexico is already optimal** — every cloud
region closer to Kalshi is geoblocked by Polymarket; Dublin is the trap the latency guides recommend.

**4. Structural safety gaps, all live.** 11 of 21 leg-A fills **overfilled** (the order is
collateral-denominated, so price improvement returns extra shares), leaving naked residuals the hedge
never covers. **25 contracts already exceeds the $2.50 protection cap** at p90 slippage ($3.16), so a
p90 event *necessarily* ends in a naked position and a halted lane — which is exactly what `77013052`
did. Aggregate hedge submits are **unbounded**: one execution fired **511 orders for 12,775 contracts**
to hedge 25. And **3,373 of 3,373** protect kill latches failed to write their audit flag.

**5. Corrections to my own earlier claims — do not re-inherit them.**
- The **"207 ms edge life" was my sampling floor**, not the market. It was `heartbeat_s = 15.0` in the
  recording gate and the 200 ms coalescing cap, divided two different ways. The true lifetime is
  **unmeasured**.
- **Depth is a median 30 contracts, p25 zero** — not "plausibly hundreds". Only 52% of attempts hold 25
  on both legs. `frontiers.n_max` (median 588) is ~20x what real attempts support; it is not capacity.
- The **root-disk diagnosis was wrong**. The box wedged from **single-vCPU starvation**, itself largely
  caused by L100's own retry loop. Root was 24% full.
- Every latency stage figure above was measured while that loop had the box at load 4–5. **Re-measure
  before scoping latency work.**

## What landed (L95–L103)

| row | what | deployed |
|---|---|---|
| L95 | a pre-send read that cannot fill the planned size takes what the book has | yes |
| L96 | a padded order the venue's own floors make illegal; entry reprices to the venue's ask | yes |
| L97 | two stage clocks measured the wrong interval; `worker_hop_ms` added | yes |
| L98 | distance-to-actionable was measured on an unroutable cover, **sign reversed** | yes |
| L99 | the entry limit reached the venue off tick and the wire re-priced it *downward* | yes |
| L100 | a residual the quantity cap cannot hedge re-ran **2,840 times**; the row blamed the wrong constraint | yes |
| L101 | the REST reconciler priced books up to **8 s old** and computed their age as 0.0 | **no** |
| L102 | record the confirm's ladder, and re-read the book after the venue's terminal answer | **no** |
| L103 | 56% of orders paid **354 ms** for metadata the SDK fetches before signing | **no** |

## What to do next, in order

1. **Deploy `c5f6da4` and clear the kill.** *(operator — the release and the clear are both blocked for
   me by the permission classifier.)* Note the kill re-latches on every restart until item 5 is done.
2. **Let ~50 orders accumulate, then run the L102 verdict query.** Among zero-fills whose confirm showed
   full size: **STILL_THERE ≥ 60%** means the published book is not honoured and speed cannot fix it;
   **CONSUMED ≥ 60% with STILL_THERE < 20%** means an honest race and latency is the answer; a high
   **PULLED** fraction means the resting size was never committed liquidity. *Threshold set before
   seeing the data, deliberately.* **This decides the strategy. Everything below waits on it.**
3. **Verify L103** — the first-vs-repeat submit→ack split, scoped to a single process run (the cache is
   per-process, so a restart re-colds every token and would mute the result).
4. **Owed safety work:** bound aggregate hedge submits per execution; fix the flag write; bring the
   contract cap to ~20 *or* raise the protection budget above measured p90 slippage. *(The cap is
   operator-signed — needs a dated GATE row.)*
5. **The overfill acknowledgement row** for `0429ef24`. This is why every release re-latches the kill.
   Needs frozen evidence and an operator `--confirm`.
6. **Redemption** is failing on a Polymarket rate limit with no backoff, with capital stuck in an
   unredeemed position.
7. **Deferred, pending item 2:** the **maker path** (complete, 279 tests, live-proven, switched off by a
   two-line revert on 2026-09-10; its guard timed out on 8 of 10 rests on a box that was *starved* —
   worth re-testing now load is 0.5; needs a GATE row, F20 says taker). And **widening to
   spreads/totals** (~10x the contract pairs per event, blocked on two matcher defects:
   `CanonicalKey.line_abs` has zero producers so legs on different lines would pair, and a middle
   prices as a cover while paying nothing).

## What not to do

- **Do not raise caps or size** until per-cover EV is measurably positive. At p90 slippage, 700
  contracts is a $98 single-cover loss against a $25 daily breaker.
- **Do not scope latency work off the pre-L100 numbers.** The box was starved by a bug when they were
  taken.
- **Do not read a fall in actionable prints after L101 as a regression.** Those evaluations were pricing
  stale books while reporting perfect freshness. A fall is the fix working.
- **Do not cite `frontiers.n_max` as capacity.** It is replica-priced, slippage-free and unfiltered by
  executable shape.
- **Do not treat a pre-send confirm as evidence** either way. It cannot discriminate; that is measured.
