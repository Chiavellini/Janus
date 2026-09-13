# Hedge slippage, not the edge, decides whether a cover makes money (2026-09-13)

Read-only, from the box's own settled covers: `ops/slippage_report.py --hours 168 --rows`, 19 real
covers with a hedge fill. No code change proposed here; this is the measurement that should govern
the next one.

## The result

| | median margin entry priced | median hedge slippage | ratio |
|---|---|---|---|
| all 19 covers | **0.67c** | **3.00c** | **4.5x** |
| entered before the pre-send hedge check (15) | 0.72c | 5.00c | 6.9x |
| entered after it (4) | 0.30c | **0.50c** | 1.7x |

Pooled: slippage p50 3.0c, p90 **14.0c**, max 15.75c, min −15.0c, adverse on 13 of 19. Net
**−$0.55** across the 19, with 9 losers.

**`margin − slippage` predicts the sign of the outcome on 16 of 19 covers.** All three misses
(`548a0a6d` +$0.03, `0dfc6df3` +$0.38, `d10f3475` +$0.02) are near-zero outcomes, and two of them
carry an overfill that muddies the attribution. Nothing else in the data predicts the sign this well
— not league, not size, not the entry price, not the gross sum.

So the lane is not harvesting a measured edge. It is accepting a roughly symmetric ±15c execution
risk in exchange for a median 0.67c of priced margin, and the outcome is the slippage draw. That is
the arithmetic reason nine of nineteen covers lost money while every one of them was "an arbitrage"
at entry.

## The registered hurdle is set an order of magnitude below the risk it has to cover

`EXECUTION_MIN_LOCKED_RETURN` is 0.5%, which on a $1 contract is **0.50c** of required margin,
against a measured slippage p50 of 3.0c and p90 of 14.0c. Only **3 of 19** covers were entered with a
margin exceeding even the median slippage.

This is the quantitative answer to "are we being too conservative?", and it inverts the question.
The lane is far too *loose* in the one place that decides the P&L — the margin it will accept against
unmodelled hedge risk — while being needlessly tight in places that cost surface and no money
(the venue size floors of L96, the off-grid limits of L99, the phantom `BLOCKED_MATCH` telemetry of
L98). Loosening the hurdle to take more orders would buy more of a coin flip.

## What already worked, and it is the only lever that helps

The four covers entered after L85's pre-send hedge-book confirmation show slippage p50 **0.50c** and
max **3.08c**, against 5.00c and 15.75c before it. Median down ~10x, tail down ~5x. **n=4 is far too
small to be a claim**, but the mechanism is not in doubt: confirming the hedge's own book before leg
A commits removes exactly the case where the hedge had already walked away. The report itself refuses
to publish a reserve for any league under 20 covers ("not assumed zero"), and that discipline should
hold here too.

## The tension that has to be resolved, and it is strategic

There is currently **no margin threshold that is both safe and permits volume**:

- Require margin > the pooled median slippage (3.0c) and the lane admits 3 of 19 covers.
- Keep the hurdle at 0.50c and roughly half of all covers lose money.

Both eras are still slightly net-negative (−$0.29 pre, −$0.26 post, the latter on four covers and
dominated by one −$0.48). So volume is not the constraint and the hurdle is not tunable into
profitability. **The only path to more orders is lower slippage**, which then makes low margins
survivable. L85 is evidence that path is real.

## What to do next, in order

1. **Let n grow under L85/L96/L99 and re-run this report.** The single number that matters is
   post-fix slippage p50 and p90 per league. Twenty covers per league is the report's own bar.
2. **Then** gate entry on `margin > measured slippage p90 for THIS league` rather than on a blanket
   return hurdle. Per-league, from data, refusing where there is no measurement — never a global
   constant, which is what 0.5% is.
3. **Do not raise the blanket hurdle in the meantime.** At 3c it admits almost nothing, and it would
   destroy the surface the L96/L98/L99 work just recovered before the measurement exists to set it
   properly.
4. The remaining slippage sources worth attacking, in the order the data supports: the hedge's
   own ladder chase (`b_attempts` of 2-6 on every pre-L85 loser, 1-2 after), and the
   entry-to-hedge interval, which L97's repaired clocks can now measure honestly for the first time.

## Caveat on this document

19 covers, 7 leagues, 5 of them with n<=2. Every per-league number here is descriptive, not a
reserve, and the report labels them `unmodelled` for that reason. The pooled numbers are the only
ones with enough weight to argue from, and even they rest on a single week that contains the
−$2.00 `64d6925e` incident the pre-send checks were built to prevent.
