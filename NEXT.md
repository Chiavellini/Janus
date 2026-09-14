# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-14 after the L116 confirmation and the 2026-09-14 orphan-fill investigation, on
`claude/hedge-safety-and-speed`.

## Current state

`5053154` is deployed on the Mexico box. The lane is active in `LIMITED_LIVE`, but `kill/live`
exists and entry is stopped. **Do not clear it.** Seven historical overfill acknowledgements still
validate, but a new, unrelated account incident now blocks relaunch.

The branch contains the already-pushed L104–L116 work plus a local L117 candidate. L117 makes kill
files first-writer-wins so a later alarm cannot erase the reason trading first stopped. It changes
no kill condition, cap, hurdle, size, allowance, protection decision, or order path. Focused tests
are 37/37, the full suite is 1,568/1,568 on this run, and replay parity remains
`13e4fb08a76c920f` / `4f53cda18c2baa0c` over 1,093 rows.

## The account incident — operator attribution required

At 2026-09-14 18:06:29Z the authenticated Polymarket account bought **666.666667 Yes shares at
$0.15** on *“Will there be no change in Fed interest rates after the September 2026 meeting?”*
Order `0x32813cbb23731ca96e8830adb5118adb16367d4c0beecf2554040dec4eb3afa3`, trade
`99f8e62b-0684-446f-baa7-08bb785c3d30`, authoritative cash **$104.25**. The guard flagged it as
`ORPHAN_FILL` 30 seconds later.

This is real quantity, not a decimal/display bug: `666.667` is only `:g` formatting. It is a taker
trade, on a non-sports token, with no matching `orders`, `order_events`, `pm_bounded_taker_orders`,
or post-only row. Current Janus code cannot create it: the live universe is sports and the only BUY
signer is hard-limited to 25 requested contracts / $30 collateral. The fill does share the account
and CLOB API-owner UUID used by Janus. The honest attribution is therefore **manual/shared-account,
another client using the account, or compromised credentials**; the database cannot choose among
those without the operator.

The public positions feed still showed all 666.6666 shares open, marked at $76.67 (about −$23.33
against the ~$100 token value before the separately recorded $4.25 cash residual/fee), end date
2026-09-16. Janus did not hedge, sell, or otherwise alter it. It is outside the sports execution P&L
breaker.

One further finding changes the interpretation of the “harmless” legacy alarm in the prior
handoff. `KillSwitches.latch()` unconditionally rewrote an existing file. Repeated
`LEGACY_INCIDENT_ACK_INVALID flag=211` latches replaced the orphan reason and timestamp in
`kill/live`; at inspection the file named the legacy alarm at 21:24:32Z although it was born the
previous day. `lane_flags` preserved the orphan, but the operator-facing first cause did not. L117
repairs that provenance loss with atomic exclusive creation. It deliberately does not suppress the
137/day legacy rows, which remain a separate cleanup.

## Economics — what survives confirmation

- Polymarket taker entry cost remains measured at 0.828c/contract; Kalshi hedge fee at
  1.187c/contract; median booked margin 0.67c. The fee problem is real.
- L116's 2026-09-11 result does **not** generalize as a pooled cents-per-second slope. That day,
  mean drift was 0.28c at 1.0 s and 0.78c at 2.5 s, implying +0.50c from speeding up.
- The owed 2026-09-13 confirmation read 2,797 actionable moments, 30,671 samples and 100,232,969
  frames with zero parse errors/corrupt files. Mean drift was **0.29c at 1.0 s and 0.19c at 2.5 s**:
  2.5→1.0 s was **−0.11c**, not +0.50c. By 20 s the pooled mean was −0.84c.
- The adverse tail still worsened with time on 09-13: p90 was 3c at 1 s, 5c at 2.5 s and 6c at
  20 s. Speed can improve tail risk even when the pooled mean does not.
- The sign is league-dependent. ATP/ELC/EPL got dearer between 1.0 and 2.5 s; La Liga/MLS/NFL/MLB
  did not. **Do not use “0.25c per second” for a blanket hurdle or $100/day forecast.** Measure EV
  per league and keep the Sharpe/tail benefit separate.
- Negative unconditional drift at long windows is not maker EV. A maker fills selectively when the
  market comes to it; L63's prospective cohort remains the authority. Nothing here re-enables maker.

The confirmation took about 35 minutes over 3.5 GB / 100.2 M frames on the one-vCPU box at
`nice -n 19`; the old “~10 minutes” estimate was false.

## What to do next

1. **Operator answer:** did the operator intentionally place the Fed-rate order above? If yes, a
   source-bound external-fill disposition can be prepared. If no, rotate/revoke the Polymarket
   trading credentials and investigate every client using the wallet before any kill clear.
2. Release L117 only through the operator's ordinary `ops/box/release.sh <sha>` paste. A release is
   required because `nodes/risk/kill.py` is in the executable-tree hash. The current genuine kill
   remains; never use the false-maker auto-clear path as a disposition for this fill.
3. After account attribution and a clean guard, decide whether to resume the 10-contract measurement
   run. Only real orders make L112 (account-stream kinds), L113 (post-kill refusal funnel), and L114
   (covers per event) answer their registered questions.
4. Treat latency as per-league/tail work. The remaining 366 ms and 306 ms segments are mostly durable
   pre-wire database work, not proven idle time. Instrument SQLite lock wait/serialization before
   scoping a rewrite. Racing the user stream against REST is plausibly ~350 ms, but L112 explicitly
   requires a real-order day before changing that path.
5. Clean up `LEGACY_INCIDENT_ACK_INVALID flag=211` only under a separate row. It is noisy but no
   longer able to overwrite a first latch after L117.

## Session delta and source of truth

Created: L116's `results_20260913.json` and `confirmation_20260913.md`; L117's immutable
`spec.yaml` and `verdict.md`. Changed: `nodes/risk/kill.py`, its focused risk tests,
`snooping_ledger.md` by append-only rows/notes, and this handoff. Intentionally untouched:
`GATE_TO_LIVE.md`, all caps/hurdles/limits, the maker/taker policy, box modes/overrides, the current
kill file, the open Polymarket position, and all user changes in the main checkout.

Sources of truth were `AGENTS.md`, `README.md`, `GATE_TO_LIVE.md`, L104–L117 and their immutable
specs, the box's read-only `venue_fills`/`pm_cash_sources`/`orders`/`lane_flags` rows, the public
Polymarket position feed, replay parity, and the test suite. The official Polymarket CLOB schema
confirms that `owner` is the API-key-owner UUID; it does not identify which human or client sent an
order sharing that owner.

## Instrument traps that still apply

- `stages_json` `*_ms` are cumulative from `_t0`; difference them per row. Exclude `guard_rerun`
  rows because `protect_existing` re-bases `_t0`.
- `socket_health.frames` is cumulative; take deltas and treat decreases as reconnects.
- `BLOCKED_MATCH` is mostly the `single_venue` branch, not lost paired surface.
- The local archive DB is corrupt; replay uses the separate slate snapshot.
- Frames age out at seven days.
