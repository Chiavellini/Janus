# NEXT

An opinion, not a record. Overwrite this file; never append to it. What changed is git log.

Updated 2026-09-15 for the F22 maker-versus-taker release candidate on branch
`claude/hedge-safety-and-speed`.

## Current production state

The Mexico box is deployed at `f7c9c1b177f757d6bfbc6e126eeb47bbb001c6eb`. The lane service was
last observed active in `LIMITED_LIVE`, but `kill/live` is retained, so new entry is blocked. Do not
describe the lane as trading merely because systemd is active.

The current kill is bound to SHA-256
`dcc4c761ee8fb5f903475e0400b54a0ef57db8246cd7d378d4846cf181c96d83` and the first guard failure
at UTC `1789484735.5242064`. A fresh read-only query found exactly two unresolved `GUARD_FAILED`
rows: 1169 (Polymarket balance/trade-batch failure) and 1170 (missing complete fills/positions
proof). L132 required only row 1169 and therefore stopped. L133 preregisters exact recovery for the
pair `{1169,1170}` without weakening L132.

The Polymarket redemption timer is failing while `data-api.polymarket.com/positions` returns a rate
limit error. This is an unresolved operating-cost/reliability issue, not evidence of runaway order
submission. It must not be confused with the entry-attempt volume in the lane.

## F22 release candidate

F22 is the registered event-randomized comparison between:

- the existing bounded immediate Polymarket taker entry; and
- a reviewed short-rest Polymarket post-only maker entry, followed by the same Kalshi hedge.

Assignment is a stable SHA-256 parity of canonical `event_id`. It is persisted before any provider
wire action, with the complete sizing, opportunity, book-epoch, order, execution, fee, hedge and
settlement lineage needed to score an observation. Arms cannot cross, fall back, or replace one
another. The maker arm must remain post-only and the taker arm remains immediate.

F22 is default-off unless the signed override pins the exact F22 spec digest, assignment algorithm,
unchanged caps, `LIMITED_LIVE` mode and the operator's exact statement:

> proceed with the experiment; consider todays goal (reach 20 usd profit)

The first three actual F22 fills form an online safety gate: no later admission is allowed until
each is uniquely linked, reconciled, settled as a released COVER, and proves zero unhedged and zero
directional quantity. Any persistence or lineage failure stops F22 entry and latches a kill.

`ops/f22_report.py` fails closed on incomplete or contradictory assignment, order-role, fill, fee,
hedge or settlement evidence. A no-wire outcome cannot score if it has an order, settlement,
first-order id, hedge id or nonzero fill.

## Verification

The release candidate has zero live F22 observations. It is locally ready, not economically
validated.

- Focused F22/grid/report tests: 65 passed; the final combined F22/recovery selection passed 87.
- Integrated suite: the only failure in the final run was the documented pre-existing box FIFO
  flake; it passed immediately in isolation.
- Replay: stable over 20,000 frames, 234 pollers, 5,858 evaluations and 1,093 rows.
- Replay digests: `13e4fb08a76c920f / 4f53cda18c2baa0c`, unchanged.
- Shell syntax, Python compilation and `git diff --check`: passed.
- Final independent Luna safety audit: RELEASE after its last no-wire reporting blocker was fixed.

No agent ran `--arm`, `--confirm`, `ops/box/write_override.sh`, `ops/box/mode.sh`, the L133 helper,
or `ops/box/release.sh`; no kill, mode, override, account state or production database was mutated.

## Economic truth

The most recent measured pre-F22 12/24-hour funnel had 107 execution attempts, 16 submitted orders,
8 filled orders and 3 completed covers for `+$0.8291` realized. Ninety-five attempts ended
`BOOK_MOVED`; of the remaining Polymarket orders, eight had zero fill and four filled. The current
route therefore has neither a proved `$20/day` floor nor evidence supporting `$100/day`.
The current watchdog independently reports the latest ten completed covers at `-$2.37`, with four
losses and four hedges above their own break-even. That is adverse historical entry economics; it
is not new PnL earned while the retained kill blocks entry.

F22 directly targets the avoidable Polymarket taker fee, but it tests a tradeoff rather than a free
improvement: maker entry saves the fee only when it fills quickly enough to avoid losing more edge
to waiting and adverse selection. Historical maker evidence is one fill in seventeen attempts.
The registered cohort must reach its fixed minimums before any profitability claim: 200 decisions,
80 per arm, 50 events, five days and three leagues, unless a registered STOP occurs first.

The `$20` target is a goal for measurement, not a daily constraint the code may chase. The signed
limits remain $30 combined planned stake, 25 contracts, $500 daily notional, $25 breaker,
$0.05/0.5% hurdle and $2.50/$0.10-per-contract protection. There is no authority here to increase
turnover, loosen safety, or stop early after a favorable result.

## Release boundary and immediate continuation

The next production action is one operator-pasted `ops/box/release.sh <commit>` command after this
candidate is committed and pushed. The release must classify the exact retained kill before it
changes checkout or restarts anything. For the exact L133 route, the helper stops the lane, proves
the registered two-row set and global quiet money state, runs two stopped credentialed guards with
a retained-kill three-stream warm-up between them, appends one exact joint resolution, archives only
the unchanged kill and restarts. Any mismatch restores the kill and leaves the lane stopped.

After a successful release, use `ops/f22_report.py` and the production funnel to observe:

1. whether the first three fills reconcile exactly;
2. maker versus taker fill conversion and time-to-fill;
3. net realized EV and Sharpe per trade after both venues' fees and hedge slippage;
4. `BOOK_MOVED`, authoritative zero-fill and unresolved outcomes separately; and
5. whether rate-limited redemption calls are consuming avoidable AWS/API work.

Do not pool leagues to hide adverse selection, do not treat an unresolved provider response as a
no-fill, and do not infer profitability from attempts, theoretical edges or midpoint movement.

## Files in this release candidate

- `nodes/execute/entry_experiment.py` and tests: exact assignment, authority, persistence and
  first-three-fill gate.
- `grids/live_stream/grid.py` and tests: pre-wire assignment, arm construction, lifecycle linking,
  hard stop and board visibility.
- `ops/f22_report.py` and tests: strict prospective scoring and audit report.
- `ops/arming_override.py`, `ops/box/write_override.sh`, and risk reporting: exact signed F22 pins.
- `ops/box/clear_guard_failure_latch.py/.sh` and tests: exact L133 recovery, rollback and retry.
- `ops/box/release.sh` and tests: pre-mutation kill classification and helper-owned guard route.
- `research/exec/2026-09-15_f22-entry-arm-instrumentation/`: L131 spec and local verdict.
- `research/exec/2026-09-15_guard-failure-recovery/`: L132 spec and STOP.
- `research/exec/2026-09-15_guard-failure-pair-recovery/`: L133 spec and local verdict.
- `research/sports/2026-09-15_limited-live-f22-maker-vs-taker/`: immutable F22 forward spec.
- `GATE_TO_LIVE.md` and `ops/box/arm_statement.txt`: exact operator statement, unchanged caps.
- `snooping_ledger.md`: immutable registrations and results.

## Instrument traps

- `stages_json` timing values are cumulative from loop start; difference adjacent stages and
  exclude guard-rerun rows.
- `socket_health.frames` is cumulative; take deltas and treat decreases as reconnects.
- `BLOCKED_MATCH` is mostly the single-venue branch, not lost paired surface.
- `refusal_counts` is hot-path callback aggregation, not unique opportunities.
- `PROFITABLE_UNEXECUTED` is material-change gated and per size rung; always name the rung.
- An active service plus `kill/live` means polling may continue while entry remains blocked.
- The status script's execution field can include historical untimestamped repeated lines. Use the
  production database for actual unresolved execution, reservation and PnL state.
- Negative unconditional hedge drift is not maker EV. L63 remains the maker authority.
