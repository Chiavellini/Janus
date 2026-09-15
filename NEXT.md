# NEXT

An opinion, not a record. Overwrite this file; never append to it. What changed is git log.

Updated 2026-09-15 for the F22 maker-versus-taker release candidate on branch
`claude/hedge-safety-and-speed`.

## Current production state

The Mexico box is deployed at `c65d6206eb2a3b91569fda8fc8af06c716c671b8`. The lane service is
stopped (`inactive`, `MainPID=0`, `ControlPID=0`) and `kill/live` is retained, so neither polling nor
new entry is running. Do not describe the lane as trading.

The current kill is bound to SHA-256
`dcc4c761ee8fb5f903475e0400b54a0ef57db8246cd7d378d4846cf181c96d83` and the first guard failure
at UTC `1789484735.5242064`. The exact unresolved `GUARD_FAILED` rows remain 1169 (Polymarket
balance/trade-batch failure) and 1170 (missing complete fills/positions proof). L132 required only
1169 and stopped. L133 registered the pair, but its production run stopped at the first static proof
because an exact real cover remained unsettled. It appended no resolution and archived no kill.

The Polymarket redemption timer is failing while `data-api.polymarket.com/positions` returns a rate
limit error. This is an unresolved operating-cost/reliability issue, not evidence of runaway order
submission. It must not be confused with the entry-attempt volume in the lane.

L134 repaired the SSM transport-newline bug, after which release `1be680b` checked out and re-signed
the unchanged F22 authority. L133 then stopped safely. L135 proved its four nonquiet counters were
not one stale identity: execution `17077a35` / reservation `b292be2a` is a real 25-contract ATP
cover with both owned IOC legs filled, zero unhedged quantity and no settlement row. Its $24.49357
reservation must remain held until both venues finalize. The admission is canonically empty despite
its retained timestamp; historical persistence flag 211 has valid exact resolution marker 215 but
no lifecycle row because that incident was itself a persistence failure.

L136's winner-only provider read returned `null` from both venues, but that did **not** mean venue
finality was pending. L138's fresh raw read contradicted that interpretation: both Kalshi markets
were already finalized with scalar payouts (`SHA=0.44`, `IVA=0.56`), and Polymarket was closed and
resolved at `0.50/0.50`. L138's proposed coexistence route was stopped before implementation.

L139 is the corrected release candidate. It represents complete authoritative per-outcome payout
maps without manufacturing a winner, stores them in additive tables that preserve historical exact
evidence, settles complementary NO and sell legs, and lets the guard recognize a paid scalar leg.
The exact stopped-lane helper binds the measured maps and the cover's `-$0.99357` realized PnL in
addition to every prior L136 identity, economics, kill, unit and atomic rollback proof. Production
has not received L139 yet; it remains stopped with no settlement row and the reservation unreleased.

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
validated. Production is blocked on the unshipped L139 payout-aware settlement correction, not on
venue finality.

- Focused F22/grid/report tests: 65 passed; the final combined F22/recovery selection passed 87.
- L139 focused reconcile/helper/guard/legacy selection: 167 passed.
- Integrated suite after the additive-table correction: exit zero.
- Replay: stable over 20,000 frames, 234 pollers, 5,858 evaluations and 1,093 rows.
- Replay digests: `13e4fb08a76c920f / 4f53cda18c2baa0c`, unchanged.
- Shell syntax, Python compilation and `git diff --check`: passed.
- Final independent Luna L139 safety audit: RELEASE.

The agent ran the operator-authorized release route. It checked out `1be680b` and re-signed the
unchanged standing limits, then failed closed in L133. No kill archive, entry, account mutation,
guard resolution or F22 observation occurred. The one already-held cover is unchanged.

## Economic truth

The most recent measured pre-F22 12/24-hour funnel had 107 execution attempts, 16 submitted orders,
8 filled orders and 3 completed covers for `+$0.8291` realized. Ninety-five attempts ended
`BOOK_MOVED`; of the remaining Polymarket orders, eight had zero fill and four filled. The current
route therefore has neither a proved `$20/day` floor nor evidence supporting `$100/day`.
The current watchdog independently reports the latest ten completed covers at `-$2.37`, with four
losses and four hedges above their own break-even. That is adverse historical entry economics; it
is not new PnL earned while the retained kill blocks entry.

The held cancelled cover adds a directly measured `-$0.99357` settlement-basis loss: Polymarket
paid `0.50` on the owned token while Kalshi paid `0.44` on the owned ticker. The existing entry had
priced this dimension probabilistically through its settlement buffer; it did not guarantee a
positive realized return in this cancellation state. That contradicts any claim that every admitted
two-leg position is outcome-by-outcome riskless and must be addressed separately from parser
correctness after the lane is recovered.

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

L139 is release-ready. The operator has authorized the agent to run the exact release route. It must
atomically settle only the registered cover at `-$0.99357` before L133's static proof; then the
unchanged two stopped guards, retained-kill stream warm-up, exact joint resolution, exclusive kill
archive and restart requirements apply. Any mismatch retains/restores the kill and leaves the lane
stopped.

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
- `ops/box/settle_held_cover.py` and tests: exact atomic L136 settlement convergence while stopped.
- `ops/box/release.sh` and tests: pre-mutation kill classification and helper-owned guard route.
- `research/exec/2026-09-15_f22-entry-arm-instrumentation/`: L131 spec and local verdict.
- `research/exec/2026-09-15_guard-failure-recovery/`: L132 spec and STOP.
- `research/exec/2026-09-15_guard-failure-pair-recovery/`: L133 spec and local verdict.
- `research/exec/2026-09-15_release-kill-reason-newline/`: L134 measured transport fix and verdict.
- `research/exec/2026-09-15_l133-nonquiet-identity/`: L135 exact read-only diagnosis.
- `research/exec/2026-09-15_stopped-lane-settlement-convergence/`: L136 immutable recovery spec.
- `research/exec/2026-09-15_l136-direct-script-import/`: L137 direct-invocation packaging fix.
- `research/exec/2026-09-15_exact-held-cover-coexistence/`: L138 superseded premise and STOP.
- `research/exec/2026-09-15_scalar-half-settlement/`: L139 payout-aware settlement spec/verdict.
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
