# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-14 ~22:00Z, on `claude/hedge-safety-and-speed` (pushed; branched from
`claude/hedge-ladder-speed-3b5042c`).

**This hand-off deliberately does not choose what to do next.** The operator asked that the next
agent make its own calls. What follows is state, evidence, and the open questions — not a plan.

## Where it stands

`5053154` deployed; lane active. **`kill/live` is still latched and nothing is trading.** The
overfill acknowledgement is done: all **7** candidates carry a fresh row (ids 6–12), every one of
the 20 flag ids is bound as evidence inside them, and `match_overfill_ack` answers for all seven —
verified read-only as *"would still latch on: NOTHING"*. So a restart no longer re-latches on the
historical overfills, and clearing the kill is now a live decision rather than a blocked one.

Suite green at 1,565 (two known-flaky `ops/box` FIFO tests deselected; they fail ~65% in isolation
and are pre-existing — a task is queued).

## The economics, as measured

Three numbers now exist that did not this morning, all from the box's own data:

- **The Polymarket entry fee on leg A is 0.828 c/contract** and a maker pays **zero** there
  (`taker_only: True`, from the venue's own pinned schedule). Kalshi's hedge fee, 1.187c, is not
  avoidable. Median booked margin is **0.67c** — smaller than the avoidable fee.
- **Execution latency is priced at roughly 0.25 c/contract per second** (L116). Hedge-book drift by
  elapsed time: 0.5 s → 0.18c, 1.0 s → 0.28c, 2.5 s → 0.78c, 5 s → 1.30c, 20 s → 3.36c. The drift
  over today's 2,480 ms path (0.78c) **exceeds the entire booked margin**.
- **A maker's rest is incremental to that drift**: +0.53c at a ~2.5 s rest against 0.828c saved
  (net +0.30c), +1.19c at ~5 s (net −0.36c), +2.59c at ~17.5 s. Of 17 post-only orders ever sent,
  the only one that filled rested 20.46 s.

Caveat carried in the row: L116 measures **book drift**, a lower bound. Realised `hedge_slippage_c`
also contains the chase up the ladder (median 3.0c against 0.78c of pure drift); post-L85 realised
p50 of 0.50c is the consistency check. One ITF-dominated day (2026-09-11, 674 prints, 16.7 M
frames). **The 2026-09-13 confirmation run is owed** — the harness is
`research/exec/2026-09-14_cost-of-waiting/measure.py`, it runs detached on the box in ~10 min for a
small day, and it is unrun for 09-13 only because I stopped it to answer a question.

## What landed today

L104 the protect flag that never wrote (3,373 of 3,373) · L105 the unbounded hedge submits (497
orders for 4,970 contracts, reproduced) · L106 the 10-contract ladder · L107 the first path
decomposition · **L108 correcting it**, plus the instruments that made it wrong · L109 the duplicated
orderbook read · L110 settlement holding the write lock on the loop · L111 loop lag wearing the
venues' name · L112 account-channel counters · L113 the refusal funnel · L114 one-cover-per-event ·
L115 the maker cost counterfactual · L116 the cost of waiting. Plus L88's owed verdict.

## Open questions, not answered here

- **Whether to clear the kill.** Nothing collects until it is cleared: L102's fill verdict, L112's
  stream counts, L113's refusal funnel, L114's extra covers per event all begin then.
- **Whether speed or the maker path is the better next investment.** L116 says they are substitutes
  and that speed gets relatively better as the taker gets faster; it does not say how much more
  speed is available. The remaining named targets are the ~366 ms coordinator tail, the ~306 ms
  protect preamble, and leg A's settle polling.
- **Whether the entry hurdle should move.** It admits covers at 0.5c against an all-in cost that
  L116 now prices. The slippage report's standing instruction is *not* to raise a blanket hurdle
  before per-league measurement exists; whether L116 changes that is a judgement.
- **Whether to widen the universe at all yet.** CFB is the largest competition in the census and is
  quarantined on evidence; fl1/por/scop/bel1 sit at `$0.00` caps that would refuse everything if
  enabled; spreads/totals need a market-identity axis the kernel does not have.

## Two things found late and not investigated

- **`ORPHAN_FILL`, 2026-09-14 18:06:59Z: `polymarket 5615282760875985 buy_yes 666.667 @ 0.15`,
  order `0x32813cbb23`** — a venue fill that no order row explains, about **$100** and **26× the
  25-contract cap**, while the kill was latched. Two earlier orphans on 09-09 were 5.13 contracts.
  This one is a different magnitude and I did not chase it.
- **`POST_ONLY_PERSISTENCE_FAILED` fires 126 times in 24 h and all 126 are the same thing**:
  `LEGACY_INCIDENT_ACK_INVALID flag=211`, a legacy acknowledgement of an old
  `database is locked` that can no longer validate. Harmless in itself, but it is 126 rows/day of
  noise in the table the watchdog reads.

## Things that will mislead you if you do not know them

- **The instruments lie at the read site.** `stages_json` `*_ms` are cumulative from `_t0` (difference
  them per row, never as medians); `socket_health.frames` is cumulative (take deltas, a decrease is a
  reconnect); `protect_existing` re-bases `_t0`, so exclude `guard_rerun` rows from any segment maths.
  `ops/latency_report.py` now prints a per-row SEGMENTS table first and takes `--since`.
- **The replay parity digest in the 2026-09-12 verdict (`9f41923b8cf055a1`) is stale** — it predates
  L95–L103. The `e297f7d` baseline is `738ef6b0fee1d25e` / 2,271 rows; this branch is
  `13e4fb08a76c920f` / 1,093 rows, moved by L106's ladder alone.
- **`BLOCKED_MATCH` is 64% of evaluations and is not lost surface.** 99.97% is the `single_venue`
  branch, meaning the cheapest cover of any shape cost at least a dollar. With `NO_EDGE` that is
  82.6% of rows correctly saying there was nothing there. It is a naming problem.
- **The local archive DB (`data/tuples/tuples.sqlite`) is corrupt beyond reading** — even
  `sqlite_master`. The box is unaffected and the replay harness uses a separate slate snapshot.
- **Frames age out at 7 days.** 2026-09-07 is rolling off now.
