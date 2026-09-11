# L73 verdict — hedge slippage, SEKULIC V MATSUDA (73688bf3) and MORIYA V SHIMIZU (98376aa2)

Read-only from the box's journal on 2026-09-11 (`timelines.txt`, wallet and order identifiers
shortened). Times are seconds after `executions.started_utc`.

## Timelines

| | SEKULIC (02:46:40.207Z) | MORIYA (04:22:31.615Z) |
|---|---|---|
| Plan Kalshi book stamp (books_json) | -0.673 s (0.16 × 56.66, 0.17 × 40, 0.18 × 102, 0.19 × 10) | -0.373 s (0.03 touch; hedge budget 0.0442) |
| Plan Polymarket book stamp | -1.107 s | -0.605 s |
| Leg A (Polymarket FAK) submit / ack / settled | +0.042 / +0.616 / +0.963 | +0.007 / +0.213 / +0.557 |
| Leg A fill | 10.012485 @ 0.801 (limit 0.802), fee $0.0798 | 10.107514 @ 0.93 (limit 0.94), fee $0.0329 |
| Kalshi book age at first hedge submit | 1.64 s | 0.94 s |
| Hedge IOCs (limit → result, submit time) | 0.16 → 0 (+0.965), 0.16 → 0 (+1.259), 0.16 → 0 (+1.598), 0.16 → 0 (+2.037, phase budget), 0.16 → 0 (+2.823, budget), **0.21 → 10 @ 0.19** (+3.697, phase loss_cap, ceiling 0.27) | 0.03 → 0 (+0.567), 0.03 → 0 (+0.999), 0.03 → 0 (+1.313), 0.04 → 0 (+1.699, budget), **0.04 → 10 @ 0.04** (+2.301, budget) |
| Each Kalshi IOC ack latency | 181–230 ms | 80–306 ms |
| Result | HEDGED at +3.817 s, ABOVE_BREAK_EVEN (budget 0.1622, paid 0.19): cover -$0.0975, settled **-$0.0951** | HEDGED at +2.511 s inside budget (0.0442): **+$0.14** worst case, pending settlement |
| Residual | 0.012485 PM contracts (bounded taker residual) | 0.107514 PM contracts |

## What the slippage is attributed to

1. **Book movement between plan and first-leg fill, on the Kalshi side.** In both executions the
   Kalshi ask that priced the plan (0.16 with 56.66 displayed; 0.03) answered the first IOC with
   `fill_count 0.00` 0.94–1.64 s after its stamp. The IOC round trips themselves were fast
   (80–306 ms) and the venue answered definitively every time; the FIFO at an unchanged touch is
   not the cause, the touch was gone. On SEKULIC not only 0.16 but 0.17 and 0.18 (142 displayed
   contracts) were gone by +3.7 s: the fill came at 0.19, the fourth level of the plan book.
2. **First-leg latency is the exposure window, and Polymarket's settle is the larger half of it.**
   Leg A took 0.96 s and 0.56 s from submit to settled (ack 0.62 s / 0.21 s, then one status poll to
   confirm size). Plan-to-first-hedge was 1.64 s and 0.94 s. Nothing in the journal shows the lane
   idle; the time is the venue's.
3. **The walk, not the retries, closed both.** Five retries at the plan price in 2.1 s bought
   nothing on SEKULIC; the first tick up (0.04) closed MORIYA on its second try; the loss-cap phase
   closed SEKULIC one tick above the budget. Retrying an untouched price is where the seconds went.

## Would a different choice have changed these two results?

- **First-leg venue ordering (Kalshi first).** Both Kalshi touches were gone within a second, so a
  Kalshi-first IOC would have zero-filled both: SEKULIC's -$0.0951 avoided, MORIYA's +$0.14 never
  taken. Net on these two: $0 instead of +$0.045. Kalshi's IOC answer is definitive in ~200 ms,
  whereas the Polymarket FAK acks `delayed` and needs a status poll (the coordinator's stated reason
  for its order: "ambiguity here costs nothing" when it is the first leg). Putting Polymarket second
  would move that ambiguity onto the hedge, where an unconfirmed answer is exposure. Not
  recommended on this evidence; the tail risk (an unconfirmed hedge) is worse than the loss it
  avoids.
- **Smaller initial quantity.** Neither Kalshi zero fill was depth-limited: 10 contracts against
  56.66 and (MORIYA) a touch that then filled all 10 one tick up. Size would not have changed
  either result.
- **A different bounded hedge schedule.** The plan-price retries (three "walked" plus two "budget"
  attempts at the same price on SEKULIC, three on MORIYA) consumed 1.9 s and 1.1 s for nothing.
  Walking one tick per attempt from the second attempt, inside the same budget and loss cap, would
  have reached 0.17/0.18 by +1.3–1.6 s on SEKULIC, when at most those levels were still there
  (unknowable from the journal; the raw Kalshi frames for 02:46:39–45Z under
  `frames/kalshi/2026-09-11/02.jsonl.gz` hold the answer and are the next descriptive row), and
  0.04 by +1.0 s on MORIYA instead of +1.7 s. Expected EV effect: a cent or two per hedged
  contract on the fraction of covers that walk, no change to which opportunities are taken; tail
  risk unchanged (the loss cap and budget are the same, reached sooner). This is the only change
  the two executions support, and it is a candidate for its own pre-registered row, not a change
  made here.

Protective hedging stays as it is: once leg A is filled, limiting the unhedged window is the
safety obligation, and both executions show it working (hedged at +3.8 s and +2.5 s).

## Status

L73 PASS as a description. Nothing was changed. The taxonomy debt the handoff named (HTTP-400
"no orders found to match" journaled as ORDER_REJECTED) reproduced in code and is fixed with a
regression test in the same branch, separately from this row.
