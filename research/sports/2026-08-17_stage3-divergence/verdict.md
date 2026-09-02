# Stage 3 — fee-net divergence. INTERIM.

**Date:** 2026-08-17 · **Track:** sports · **Ledger row:** L12 · **Spec:** `spec.yaml` (registered
before any price was joined to any pair) · **Status: PRELIMINARY — collection INTERRUPTED at 8 of 40 polls.**

> The registered design is 5-minutely polling for 7 days. The verdict is held at PRELIMINARY by a
> data-sufficiency guard until ≥168 polls and ≥5,000 observations at depth. **8 polls were
> collected.** Reaching the registered conclusion on ~30 minutes of one market state is exactly what
> the pre-registration exists to prevent, so the kill criterion **cannot fire yet by construction**,
> regardless of what the numbers say. Both of its tests currently fail; that is not a verdict.

---

## The preliminary finding

**Prices diverge. The fee floor eats it.**

| | |
|---|---|
| Gross cover (book prices alone) below $1.00 | **3.06%** of observations |
| Best gross cover seen | **0.98** — a real 2¢ divergence |
| …and it holds to | **500 contracts** |
| Median fee, reachable venue pair | **2.84¢** |
| Sample | 8 polls · 1,536 priced observations · 48 games · **0 rejects** |
| Cheapest fee-net cover observed | **1.0099** |
| Observations below the 0.995 arb threshold | **0**, at every size |

The single best case, live and fresh (leg age 0.77 s):

```
Kalshi  YES @ 0.4700  +  Polymarket YES @ 0.5100  =  0.9800 gross
                                            fees  =  0.0301
                                            cost  =  1.0101
```

A 2¢ arbitrage exists in the books and is destroyed by a 3¢ fee floor.

**This is a sharper statement than phase 1's.** Phase 1 concluded the venues were efficient. They
are not — they disagree by ~2¢ at real depth, several times a day. What is missing is not a
mispricing; it is a venue cheap enough to trade the mispricing on. Phase 1 could not distinguish
"the prices agree" from "the prices disagree by less than the fee floor", and those have completely
different implications for what to do next.

## Finding — the binding constraint is venue ACCESS, not market efficiency

L7 established that the two-leg fee floor is a venue-pair choice spanning 7.5×, from 3.75¢ down to
0.50¢. Stage 3 tried to use the cheap end and found it shut:

| Venue | k | Status |
|---|---|---|
| Smarkets | 0.02 | **HTTP 403**, three header variants |
| Sporttrade | 0.02 | no public API |
| Pinnacle | 0.00 (vig) | public API closed Jul 2025 |
| Betfair | 0.05 | deferred by operator decision (£499 key, read-only not permitted) |

**All three cheap legs behind L7's headline are unreachable.** L7's arithmetic is unchanged and
correct; its practical reach is narrower than it implied, and that is recorded here rather than
quietly dropped.

The consequence is precise and actionable: the measured **2¢ gross divergence would clear a 1.0¢
floor**. On the reachable pair (Kalshi+PM, ~3¢) it does not. So the next question for this track is
not "is there an edge" — there is, gross — but **"can we reach a venue cheap enough to keep it".**

Readable set as of today: Kalshi (0.07), Polymarket sports (0.05), SX Bet (**0.00 on singles**, the
cheapest coefficient in the registry, but thin — 100 active MLB markets, only 7 moneyline, 153
resting orders total). The cheapest readable pair is PM+SXBet at 1.25¢.

## Control — the pipeline is validated before its output is believed

**0 of 834 single-venue covers priced below 1.00.**

This is not a decoration. L1 measured 0 intra-venue no-arb violations in 124,437 markets, and the
complement identity (`yes_ask + no_ask = 2 − (yes_bid + no_bid) ≥ 1`) makes intra-venue arbitrage
structurally impossible rather than merely competed away. So a single-venue cover printing an edge
is a **bug signal first and a discovery second**. It printed none.

## Two collector bugs, found and fixed

Both are recorded because both would have produced confident wrong numbers.

1. **Misapplied `liquidity_source` guard.** Same-venue covers (Kalshi YES-A + Kalshi YES-B) were
   rejected as `shared_liquidity_source`. Those are legitimate covers — and per L7 the *cheap*
   structure, since net-winnings commission then applies to the arb edge alone rather than a full
   leg. The guard exists to stop treating two renderings of the **same outcome** (Kalshi and
   Robinhood are one book) as independent, and now checks exactly that.

2. **Fetch-all-then-price staleness.** The first version fetched every book, then took one clock
   reading, so early games were minutes stale — **93 of 192 observations**. The freshness check
   caught it, which is the system working as designed; the collector should not have created the
   condition. Books are now fetched and priced **per game**, so a cover's legs are seconds apart.

Both pre-fix runs are in `data/sports/stage3/quarantine/` with a README — kept, not deleted, so
the correction is auditable.

## What is built

| Module | Purpose |
|---|---|
| `screen/cover.py` | Fee-net cover cost. Depth-aware VWAP, worst-case settlement state, four hard rejects. |
| `collectors/sports_books.py` | Per-game book fetching for all three venues, with the 60s persistence recheck. |
| `screen/analyze_stage3.py` | Kill-criterion evaluation with the data-sufficiency guard. |
| `tests/test_cover.py` | 12 tests, all offline, all pass. |

Two design points in `cover.py` worth naming:

- **Worst-case settlement, not expected.** Commission on net winnings is charged only where you
  finish ahead, so a cover's total cost depends on *which* outcome wins. Taking the max over
  settlement states is what makes a reported edge a guarantee rather than an average — an "arb"
  that only pays when the favourite wins is a directional bet with extra steps. This matters
  precisely for the venues L7 called cheap, which charge nothing at entry and everything at
  settlement.
- **Greedy generates, exact re-prices.** `min` per outcome is only valid pre-fee; Kalshi's ceil is
  per *order* and commission aggregates per venue-market. So greedy produces a candidate list and
  every reported number is re-priced exactly over the enumerated combinations.

## Not done, and what would change the answer

- **The 7-day collection did not complete.** Forward polling ran **8 of 40** polls before the
  background process was reaped on session cleanup — the same thing that killed the IBKR gateway
  earlier in this project. Everything above rests on 8 polls / 1,536 priced observations / 48
  games, spanning roughly **30 minutes of one market state**. Treat every number as provisional.

  Figures were compared at 2 polls and at 8 polls (4× the data) and were stable — gross-below-1
  rate 3.13% → 3.06%, best gross 0.98 → 0.98, median fee 2.837¢ → 2.840¢, intra-venue violations
  0/204 → 0/834. That is a consistency check, **not evidence of sufficiency**: stability inside a
  single market state says nothing about behaviour across states, which is the entire reason the
  spec asks for seven days.

  Completing the registered collection needs a **launchd job under `com.janus.*`**. That is a
  persistent system change and has **not** been installed without approval.
- **SX Bet is parsed but not yet contributing legs.** Its size convention (`totalBetSize` in base
  tokens) is unverified against a real fill, so it is excluded from depth claims until reconciled.
  Since it is the only zero-commission venue reachable, wiring it in properly is the single highest
  -value next step for this track.
- Moneyline only. One league. Spreads and totals need exact line matching and are deferred.
- No settlement has been observed yet, so the Stage-4 wedge remains **unmeasured — which is a
  BLOCK, not zero**. Even a surviving candidate would not be a trade.

**0 test looks spent. No holdout touched. Nothing armed. `arming_allowed: false`.**

---

# ADDENDUM — execution style, and a correction to my own number

**Added 2026-08-17, after the operator pointed out that the strategy is eating the spread between
venues and that Stage 3 had only priced the expensive way of doing it.** That was right.

## The correction first

Earlier in this session I computed that the measured 2¢ dislocation, run through a maker/maker fee
floor of 0.44¢, nets **+1.56¢**. That number is real arithmetic but it is **cherry-picked**: it
pairs the *best observed* dislocation (0.98, the single widest of 1,536 observations) with the
*cheapest possible* fee treatment. The median tells a much more modest story, and the median is
what a strategy actually lives on.

## Dislocation, measured independently of execution

`cover_at_mid` — the sum of both legs' midpoints — asks whether the **venues disagree**, with no
assumption about how you trade:

| | |
|---|---|
| Median `cover_at_mid` | **0.99500** — half a cent of dislocation |
| Minimum | **0.96000** — 4¢ |
| Games below 1.00 | **27 / 48** |
| Median widest leg spread | 0.020 |

So the venues genuinely disagree, in most games, by about half a cent at the midpoint. That is the
real signal size — not 2¢.

## Cover cost by execution style, n=48 games, 200 contracts

The maker leg is priced at the **midpoint**, because to be filled you must quote a price someone
will hit. `at_bid` is shown only as an upper bound.

| Execution | Median cover | Median edge | Clears 0.995 | |
|---|---|---|---|---|
| taker / taker | 1.03390 | **−3.39¢** | 0/48 | **MEASURED** |
| maker / taker @ mid | 1.00860 | −0.86¢ | 5/48 | MODELLED |
| taker / maker @ mid | 1.00000 | 0.00¢ | 0/48 | MODELLED |
| **maker / maker @ mid** | **0.99925** | **+0.07¢** | **22/48** | MODELLED |
| *maker / maker @ bid* | *0.98208* | *+1.79¢* | *48/48* | *upper bound — not achievable* |

## What this actually says

**Execution style, not the fee floor, was the binding constraint — and fixing it moves the trade
from clearly-negative to roughly break-even, not to clearly-positive.**

Going taker→maker on both legs is worth about **3.5¢**, which is the entire gap. But it lands on a
median edge of **+0.07¢** — seven hundredths of a cent. In 22 of 48 games the modelled cover clears
0.995 (i.e. beats 0.5¢), versus 0 of 48 taking. That is a real change in kind, and a very thin
change in magnitude.

Against that ~0.07¢ median sit three unmodelled costs, all of which push the wrong way:

1. **Leg risk.** Two resting orders in two independent queues. One fills, you are naked directional
   on a $1 binary — not hedged, not arbitrage. A single unhedged leg can lose 50¢.
2. **Adverse selection.** Phase 1 measured maker-filled Polymarket windows settling **−22¢** while
   unfilled ones carried **+9.4¢**. That was a directional book so it does not transfer unchanged,
   but the covered case is **unmeasured**, and 0.07¢ of edge survives essentially no adverse
   selection at all.
3. **Queue position.** None of these numbers models depth ahead of you, cancellation, partial
   fills, or the fact that your own quote moves the touch.

## Verdict on this line

**A maker/maker cross-venue cover is not obviously dead, and is nowhere near obviously alive.** The
modelled median edge is smaller than any one of the three unmodelled costs above is likely to be.

This does *not* justify building queue infrastructure. It justifies one cheap next measurement: how
often does the dislocation persist long enough for a resting order to fill — measurable from the
existing 5-minutely tape with no orders placed, by checking whether a mid-crossing quote would have
been reachable in the following interval. If dislocation half-life is seconds, the line is dead and
we learned it for free.

**Evidence tier: MODELLED (MOD).** The `taker_taker` row is the only MEASURED one. No fill was
observed, none was assumed to be free, and nothing here may be promoted without measuring fills.

---

## ADDENDUM 2 — the median was diluted by a degenerate subgroup

**Same day, after asking whether the line is simply dead.** It is not, and the "+0.07¢ median" in
Addendum 1 is wrong for a specific, checkable reason.

That median pooled two populations that must not be pooled:

| Cheapest cover is… | n | Median edge | Exactly 0.00¢ |
|---|---|---|---|
| **CROSS-venue** | 25 | **+0.59¢** | 0 / 25 |
| SINGLE-venue | 23 | +0.00¢ | **21 / 23** |

The single-venue group is pinned at exactly zero **by arithmetic, not by market behaviour**:
Kalshi's complement identity forces `yes_mid + no_mid ≡ 1`, so a same-venue cover *cannot*
display dislocation. Including 23 structurally-zero observations in the denominator drags the
median to ~0 and understates the thing being measured. The correct denominator is games where the
venues actually differ.

**On that population:**

| | |
|---|---|
| Median cross-venue edge | **+0.59¢** |
| ≥ 0.5¢ | 21 / 25 (**84%**) |
| ≥ 1.0¢ | 12 / 25 (**48%**) |
| ≥ 2.0¢ | 3 / 25 (12%) |
| Max | +3.56¢ |

## Two errors in opposite directions, both now corrected

1. **+1.56¢** — cherry-picked: best-observed dislocation × cheapest fee treatment.
2. **+0.07¢** — diluted: median taken over a population half of which is zero by construction.

The defensible figure is **+0.59¢ median, fee-net, on the cross-venue subset**, MODELLED at
mid-quote execution. Both earlier numbers should be disregarded.

## Revised verdict on the line

- **Taker/taker cross-venue arbitrage: DEAD.** Measured, −3.39¢ median, 0 of 48 clearing, at
  depth. No ambiguity.
- **Maker/maker cross-venue cover: NOT dead.** ~0.6¢ fee-net median with roughly half the
  cross-venue games above 1¢ is not a rounding error. It is also not yet a strategy: it is
  MODELLED, assumes both legs fill at mid, and carries leg risk (one fill = naked directional on a
  $1 binary) and unmeasured adverse selection.

What it is worth is one specific, cheap measurement — **dislocation persistence**. If a
mid-crossing quote stays reachable long enough to fill, ~0.6¢ across ~25 games a day is a real if
modest business. If the half-life is seconds, it is unreachable and the line dies for free. That is
computable from the existing tape with no orders placed.
