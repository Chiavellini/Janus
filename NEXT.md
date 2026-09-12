# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-12 ~20:00Z, on `claude/hedge-ladder-speed-3b5042c` (off `3b5042c`).

## Where it stands

**Trading is stopped and should stay stopped.** The operator latched `kill/live` at ~19:30Z after
two of the three covers taken in the sixteen minutes following the 18:47Z clear lost money. The box
(`i-0a8c073c72dcdae11`, mx-central-1) is up and healthy — lane active, loop lag 0.2–0.3 s, 32
pollers, all three sockets connected — and still runs `3b5042c`. Nothing on this branch is deployed.

**Why it is stopped, in one line: the lane books about half a cent of edge per contract and accepts
ten to fifteen cents of hedge-price movement.** Seven days, 15 real covers (`ops/slippage_report.py
--hours 168 --rows` on the box): hedge slippage min −15.0c, p50 5.0c, max 15.75c, mean 3.47c,
adverse 11 of 15; pooled P&L **−$0.28**, 8 of 15 losing money. The entry margin on the losers was
0.05, 0.11, 0.22, 0.26, 0.33 and 0.46 cents. Flat only because the two sides cancel.

By league it is not uniform, and that matters for what to do: `mlb` **+$0.92** on 1.89c median
margin *despite* 11c median slippage; `atp` **−$3.29**, 5 of 5 adverse, 0.46c median margin; `elc`
+$3.00 on favourable slippage (luck, n=2); `ita` and `wta` one cover each, both losers.

**The cause is structural and old.** Entry charges nothing for the hedge moving.
`Plan.holding_reserve_per_contract` is fee + settlement buffer only, and the reserve that exists is
zero *and* inert: `44045ff` (2026-09-08) set `SLIPPAGE_PER_CONTRACT` 4.0c → 0 and says in its own
message that `slippage_for` "never gated an order". The only production caller is `grid.py:535`,
into `frontier()` for reporting. So no version of this lane has ever priced hedge slippage.

This morning's hurdle cut (1 % → 0.5 %, `41cb151`) halved the margin that was absorbing it. The
operator's read that the lane is "too conservative" is the opposite of what the data says: the
profit hurdle refuses almost nothing (`MIN_PROFIT` appears on 39 `[risk] refused` lines ever), and
what refuses covers is operational — `ARM_STALE` 8,022, `KILL_SWITCH` 3,924, `CAP_STAKE` 1,736,
`IN_FLIGHT` 594.

## On this branch, green, not deployed

Full suite green (1,509 tests). Three rows registered: **L85, L86, L87**.

- **L85** (`research/exec/2026-09-12_hedge-leg-book-confirmation/spec.yaml`) — entry walks the
  *hedge* leg's book before leg A is sent and declines `BOOK_MOVED` above **break-even**. Not the
  walked limit, not the hurdle budget: both refuse covers that still make money (MORIYA hedged 0.04
  against a 0.0342 budget for +1.44 %). VWAP against VWAP (`plan.vwap_for_size`), short depth
  declines, a failed read is not a verdict. Plus: the layer no longer spends a walked send the entry
  reading already proved dead, bounded by `entry_book_trust_s` so a guard re-run never skips on a
  stale row. Would have declined `64d6925e` (settled **−$1.9979**) outright.
- **L86** (`.../2026-09-12_hedge-slippage-measurement/spec.yaml`) — `ops/slippage_report.py`, plus
  `stages_json.hedge_slippage_c` per cover. Read-only, and it **refuses a per-league reserve under
  `--min-samples`**: no league has 20 covers, so all five print UNMEASURED rather than get a number.
- **L87** — the guard and the acknowledgement exporter now share one `bounded_taker_residual`
  predicate, so the ack proposal covers **one** order (`0429ef24…`) instead of ten; and an invalid
  acknowledgement surfaces once per change instead of on each of three detections per 30 s pass
  (that bug wrote **280 of the 291** `ORDER_OVERFILL` rows on record, on 2026-09-10). No latch
  condition narrowed — `test_no_blanket_released_skip` and the sixteen mutation cases are untouched.

## Now — and the sequencing is not optional

**Mine, in order:**

1. **Do not resume trading on L85 alone.** L85 catches a hedge that is *already* gone at entry
   (DJERE's 10c gap) but not Atalanta's 2.2c of intra-flight slippage against 0.11c of margin. The
   thing that decides whether this strategy is viable is the reserve, and the reserve needs samples.
2. **Get samples without risking money: run the measurement on paper.** The lane prices and records
   covers it does not send. That is how `atp`, `ita`, `wta` reach 20 covers without paying for them.
3. **Then charge `slippage_for(league)` in the plan's required margin** — the term missing from
   `holding_reserve_per_contract` — behind a flag, with the gate itself a dated GATE row quoting the
   operator. On the measured numbers `mlb` would keep trading and `atp`/`wta`/`ita` would stop.
4. **Then reduce slippage, so trades come back.** Measured windows on `64d6925e`: the walked send
   L85 removes (~355 ms), the leg-A settle still polling once after the ack despite L84
   (`a_polls=1`, `a_settled` 748 vs `a_ack` 394 — ~354 ms, unexplained, look here next), the L77
   read (188 ms, leave alone — removing it needs the signer L53/L54/F18/L65/F20 blocked, and that
   reopens the overfill). **Leg inversion is not the lever**: Polymarket is the slow venue (L34:
   box→Kalshi 51 ms p50, box→CLOB 184 ms), so leading with Kalshi would lengthen the exposure window
   and break the property that makes the current order safe.
5. **The overfill acknowledgement** (one order now, thanks to L87): fetch and commit the venue
   activity evidence for `0429ef24…`, then `--prepare`, then the dry run, then hand the operator the
   `--confirm <digest>`. Evidence must be committed *before* the release, because `--prepare`
   resolves sources from `/opt/janus`.

**Yours:** the release paste, the kill, and any GATE row. A release will re-latch the kill once more
until step 5's acknowledgement exists.

## Not now, deliberately

Spreads and totals. `STRATEGY_VERSION = "v1-taker-taker-moneyline"`; nothing but moneyline is
modelled, and each new family needs its own settlement-equivalence template pair and fee model. The
alpha argument (thinner books) cuts the wrong way while slippage is the binding problem — thinner
books slip more, and slippage is what is eating the edge.

Lowering the hurdle further, or widening any cap, to take more covers. On these numbers that buys
more variance, not more profit.

## The open data-quality bug worth its own row

The richest `PROFITABLE_UNEXECUTED` rows are three-leg soccer/MLS covers whose legs sum to **0.31
raw against a 1.00 payout** (one MLS row: kalshi 0.17 + polymarket 0.09 + kalshi 0.05, reported
201 % locked return). A genuine three-way partition must sum to ≈1.00, so those legs are stale or
mis-paired. None executed, but they are in the evaluation stream and on the board — this is the
operator's "the dashboard's raw is buggy", and they are right. First fix is that
`stream_evaluations.legs_json` records only venue and vwap, no `outcome_id` and no `covers`, so the
partition cannot be checked after the fact. Record those, then audit. Draw *modelling* is sound
(`best_cover` requires the covered sets to partition the proven outcome set, so a draw is never
silently uncovered); draw *availability* is the operational problem —
`polymarket:draw:HASH_MISMATCH` 14,028 blocks in 24 h and `kalshi:draw:NOT_SYNCED` 4,228.

## The question that actually matters

Whether a hedge can be had, at size, at a price close enough to the one the cover was priced at for
half a cent of edge to survive. Seven days say not reliably on tennis. `mlb` says sometimes. Until
the reserve is measured per league, every resumed cover is a coin flip with a rounding error of edge.
