# Janus F23 execution and fee handoff — 2026-09-15

## Initial project state

The working tree started at commit `fa00a8d98dc2ba4cf2e8b5c6cb0d9fdcaf95f7a2` on branch
`claude/hedge-safety-and-speed`. Production remained deployed at `59dd5ae2ce3619104aa95d127d1b115d7c0702a9`.
The service was active for polling and reconciliation, but `kill/live` blocked trading. The exact
retained kill has SHA-256 `d81bbfc267a235ca7f268e7317d77ee7e83c65f5263117590e4e86d1552b1636`
and reason:

> F22 STOP: terminal maker zero-fill fee evidence is NULL; strict report classifies persistence_or_reconciliation_failure

F22 had stopped on two legitimate maker terminal zero-fills whose order rows retained
`fee_usd=NULL`. There was no position, hedge, unhedged quantity, or realized loss in either row,
but a strict dollar report correctly refused to infer a zero fee. F22 is closed and its rows must
not be repaired or pooled.

The operator believed the recent funnel was three successful entries versus 105 execution
failures and asked that execution speed and fee reduction directly target the $100/day objective.
The first task was therefore to establish the correct denominator rather than assume all 108
records were simultaneously executable.

## What was learned

L141 reconciled the exact window to 108 execution records over 15.34 wall-clock hours:

- 95 `BOOK_MOVED` before any wire;
- ten authoritative Polymarket terminal zero-fills;
- three complete covers, net `+$0.82908` after `$1.40092` total fees.

The 95 pre-wire records were not 95 safely takeable trades. They represented 35 events and 49
opportunities. Fresh confirmation showed that 90 failed the Polymarket price/depth requirement by
6 cents median and 10 cents p90. Five passed Polymarket but failed the Kalshi hedge break-even by
1.88 cents median. None has a proved safe two-leg counterfactual under unchanged limits.

The correct submitted-first-leg conversion was `3/13 = 23.1%`, not `3/108`. Thirteen submitted
orders are too few to distinguish a true one-third conversion rate. All eight eligible taker
zero-fills had enough sent-size depth immediately before submission and zero depth after the
terminal answer: interim L102 classification `CONSUMED=8`, `STILL_THERE=0`, `PULLED=0`. That is
small-n observational evidence of a race. Median timings were:

- Polymarket REST confirmation: 180.74 ms;
- confirmation to submit: 6.83 ms;
- submit to acknowledgement: 197.63 ms;
- ordinary machine stages were only tens of milliseconds.

The direct speed target is therefore the serial venue confirmation/network path, while preserving
a fresh Kalshi exit proof. It is not safe to send the 95 already-invalid windows.

The profit arithmetic also contradicts a simple “36 fills = $100” thesis. The three-cover mean was
`$0.27636` net. Thirty-six covers at that mean are `$9.95`; removing the exact Polymarket fees
raises that to `$17.26`; removing all fees raises it to `$26.76`. At observed economics, `$100`
requires about 362 covers, or about 209 if only Polymarket fees disappear. Speed and PM maker fee
savings are necessary, but cannot alone prove the daily goal at the current surface and dollars
per cover.

## Work completed in the uncommitted tree

The tree contains a release candidate, but it was deliberately not committed, pushed, deployed,
armed, or used to clear the kill after the operator asked to stop and hand off.

L140 prospectively records `fee_usd=0.0` only for complete terminal, non-open, non-pending maker
zero-fill proof. Positive, partial, open, pending, or ambiguous states retain missing fee evidence
and remain blocking. Historical F22 rows remain unchanged.

F23 is a new, event-randomized two-arm cohort with a separate table, assignment version, authority,
and report. It compares the same bounded immediate Polymarket taker entry to a two-second post-only
maker entry. It has no crossover, replacement, or fallback. Caps and hurdles remain `$30` combined
planned stake, 25 contracts, `$500` committed daily notional, `$25` breaker, `$0.05`/0.5% entry,
and `$2.50`/`$0.10` per-contract protection. F22 is forcibly disabled in capital mode.

L142 bounds every maker safety callback by the smaller of the existing poll interval and remaining
rest deadline. Timeout/error cancels immediately. Structured evidence records checks, timeouts,
errors, duration, outcome, and reason. The F23 report refuses a maker observation that lacks valid
guard evidence.

The first-three-fill checkpoint validates the chronological first three fills, but no longer
serializes all later turnover behind settlement. F23 decisions persist event start, league, and
canonical America/New_York venue date so the registered five-day minimum can actually score.

The F22 recovery helper is pinned to the complete identities of the two source decisions,
executions, opportunities, clients, venue orders, assignment/sizing digests, quantities, empty
hedge lineage, exactly one Polymarket order, unchanged NULL fee, terminal maker proof, exact kill,
zero F23 rows, and globally quiet capital. It cannot generically clear another kill.

## Verification completed

- 172 focused F23/L140/L142/recovery tests passed.
- The complete 1,766-test suite passed once.
- A later repeat encountered only the two pre-existing flaky FIFO tests in
  `ops/box/tests/test_box.py`; the second repeat was manually interrupted near completion when the
  operator asked to stop.
- Python compilation, shell syntax, and `git diff --check` passed.
- Replay remained exact over 20,000 frames, 234 pollers, 5,858 evaluations, and 1,093 rows:
  `13e4fb08a76c920f / 4f53cda18c2baa0c`.
- A final independent fresh-eyes audit returned `RELEASE` with no hard blocker.

## Modified files

- `GATE_TO_LIVE.md`: appended the dated F23 authority with the operator's verbatim statement and
  unchanged limits.
- `NEXT.md`: replaced stale state with production halt, L141/L102 evidence, F23 candidate, profit
  arithmetic, and direct open questions.
- `snooping_ledger.md`: preregistered L140, F23, L141, and L142 before their runs/implementation;
  appended results without changing prior rows.
- `grids/live_stream/grid.py`: added F23 activation, assignment, persistence, fail-closed cohort
  handling, maker plan dispatch, audit date/league fields, and permanent live F22 disablement.
- `grids/live_stream/tests/test_grid_callbacks.py`: added F23 activation, cohort, production audit
  field, fallback date, and callback tests.
- `nodes/exec_polymarket/client.py`: added prospective explicit zero-fee persistence only for
  complete terminal maker zero-fills.
- `nodes/exec_polymarket/tests/test_post_only_lifecycle.py`: proves terminal zero gets explicit fee
  zero and maker fills do not.
- `nodes/execute/README.md`: documents the F23 cohort and maker evidence behavior.
- `nodes/execute/coordinator.py`: added bounded maker-guard waits and structured terminal evidence.
- `nodes/execute/entry_experiment.py`: added F23 assignment/table/activation/update paths and fixed
  the first-three checkpoint throughput bug.
- `nodes/execute/tests/test_entry_experiment.py`: tests F23 separation/activation and the one-time
  first-three gate.
- `nodes/execute/tests/test_maker_entry.py`: tests deadline, repeated checks, timeout/error,
  refusal, fill, and final maker evidence.
- `nodes/risk/health.py`: reports F23 persistence failures.
- `ops/arming_override.py`: permits a pinned F23 experiment authority.
- `ops/box/README.md`: documents F23 release/recovery behavior.
- `ops/box/clear_false_maker_latch.py`, `ops/box/clear_false_maker_latch.sh`,
  `ops/box/clear_guard_failure_latch.py`, and `ops/box/clear_legacy_incident_latch.py`: tightened
  routing/compatibility around exact experiment recovery.
- `ops/box/release.sh`: defaults to exact F23 authority and routes only the registered F22
  instrumentation kill to the new stopped-lane recovery.
- `ops/box/tests/test_box.py`: tests F23 release routing and complete F22 source identity proof.
- `ops/box/write_override.sh`: writes either explicit F22 legacy or default F23 pinned authority;
  production supervisor still hard-disables F22.
- `ops/f22_report.py`: generalized strict reporting for F23, added maker-guard proof enforcement,
  canonical local-day counting, fixed minimums, and clustered outcome analysis.
- `ops/tests/test_f22_report.py`: updated strict report and cohort tests.

## New files

- `ops/box/clear_f22_instrumentation_latch.py`: exact read/prove/archive/restore helper for the one
  retained F22 kill.
- `ops/box/clear_f22_instrumentation_latch.sh`: stopped-lane guard/recovery orchestration.
- `ops/box/f23_arm_statement.txt`: exact registered operator statement.
- `ops/box/write_f23_override.sh`: explicit F23 override wrapper.
- `ops/f23_report.py`: F23-only report entry point.
- `ops/tests/test_f23_report.py`: F23 separation, minimum, and clustered-outcome tests.
- `research/exec/2026-09-14_confirm-vs-engine/interim_20260915.md`: L102 interim evidence.
- `research/exec/2026-09-15_book-moved-execution-conversion/{spec.yaml,measure.py,results.json,verdict.md}`:
  L141 preregistration, read-only measurement, exact output, and verdict.
- `research/exec/2026-09-15_maker-guard-deadline/{spec.yaml,verdict.md}`: L142 registration/result.
- `research/exec/2026-09-15_terminal-zero-fee-evidence/{spec.yaml,verdict.md}`: L140 registration/result.
- `research/sports/2026-09-15_limited-live-f23-maker-vs-taker/spec.yaml`: immutable F23 protocol.
- `research/exec/2026-09-15_book-moved-execution-conversion/__pycache__/measure.cpython-314.pyc`:
  generated untracked bytecode; do not commit it.
- `HANDOFF_2026-09-15_F23_EXECUTION.md`: this handoff.

## Important files intentionally left untouched

- `nodes/risk/limits.toml` and `nodes/opportunity/thresholds.py`: no cap, hurdle, loss allowance,
  or size increase was authorized or needed for F23.
- Settlement matching and settlement-wedge policy: no basis or safety rule was weakened.
- The production SQLite database: read-only measurements only; historical F22 fee rows were not
  repaired.
- `/srv/janus/kill/live`: retained unchanged. No release, arm, mode switch, confirmation, or kill
  clear was executed.
- Production checkout: still `59dd5ae2ce3619104aa95d127d1b115d7c0702a9`, not this candidate.

## Sources of truth

- `AGENTS.md`: architecture, preregistration, executable-price, basis, and safety invariants.
- `NEXT.md`: current operational state and measured conclusions.
- `GATE_TO_LIVE.md`: exact capital authority and unchanged F23 limits.
- `snooping_ledger.md`: immutable registration/result chronology.
- `research/exec/2026-09-15_book-moved-execution-conversion/spec.yaml` and `verdict.md`: correct
  execution denominator and economics.
- `research/exec/2026-09-15_terminal-zero-fee-evidence/spec.yaml`: L140 constraints.
- `research/exec/2026-09-15_maker-guard-deadline/spec.yaml`: L142 constraints.
- `research/sports/2026-09-15_limited-live-f23-maker-vs-taker/spec.yaml`: fixed F23 population,
  arms, minimum sample, outcomes, stops, and analysis.
- `research/infra/2026-09-12_loop-waste/measure.py`: replay parity gate.

## What the next versions should target

1. **First decide whether to preserve and release this F23 candidate.** Re-audit the uncommitted
   tree rather than assuming this handoff is correct. If retained, remove only the generated
   `__pycache__`, rerun focused/full/replay gates, commit once, push, and use the exact recovery
   route. Do not reinterpret F23 as a proven improvement: it is an instrument to measure maker
   fee savings net of lower fill probability and hedge tails.
2. **Register a genuinely speed-directed successor before implementation.** The candidate should
   remove or overlap the approximately 181 ms Polymarket REST confirmation round trip, most likely
   by using a bounded fresh authenticated socket snapshot at the signing boundary or a registered
   hedge-first/strict-limit IOC design. Preserve an independently fresh Kalshi hedge proof,
   quantity/collateral ceilings, no retry after ambiguity, and every existing cap. This is an
   entry-policy change and needs its own spec, PENDING ledger row, and dated GATE amendment before
   live use.
3. **Use the right success denominator.** Primary outcome should be terminal realized dollars per
   eligible randomized decision, clustered by event. Report safe submitted-order conversion
   separately and explicitly test the operator's one-third target. Do not use all BOOK_MOVED rows
   as the denominator and do not score unresolved orders as zero. Require zero unknown provider
   states, zero unprotected fills, and unchanged replay unless the registered behavior change is
   deliberately named.
4. **Separate fee instrumentation from fee economics.** L140 fixes missing zero-fill fee evidence;
   it does not reduce trading fees. F23 measures whether post-only PM fee savings survive its fill
   loss. If F23 is not positive in realized dollars per eligible decision, stop optimizing that
   maker arm. The next fee mechanism should be a separately registered cheaper venue/pair or the
   inherited Kalshi MM-at-open lead in sports, which avoids the expensive two-venue pair. [Corrected
   2026-09-18: that lead's evidence is one Bitcoin market with simulated fills, and its derived dollar
   figures were withdrawn -- see AUDIT_2026-09-15_F23_RELEASE.md:435-461. Its sports test is L152.]
5. **Address scale only after speed and fee results are honest.** Even 36 covers at recent economics
   do not approach `$100`. The later version must increase safely co-listed surface or dollars per
   cover within signed caps, or adopt a cheaper mechanism. Coverage expansion must not import an
   unmeasured settlement basis.

## Immediate commands for the fresh agent

Start in this exact worktree and do not mutate production during the audit:

```bash
cd /Users/bernardodelrio/Code/Janus/.claude/worktrees/janus-arbitrage-trader-4e6d4d
git status --short
git diff --check
git diff --stat
```

Read `AGENTS.md`, `NEXT.md`, the four specs named above, and the tail of `snooping_ledger.md` before
choosing whether to keep or replace the candidate. Re-run:

```bash
python3 -m pytest -q nodes/execute/tests/test_entry_experiment.py nodes/execute/tests/test_maker_entry.py nodes/exec_polymarket/tests/test_post_only_lifecycle.py grids/live_stream/tests/test_grid_callbacks.py ops/tests/test_f22_report.py ops/tests/test_f23_report.py ops/box/tests/test_box.py
python3 -m pytest -q
mkdir -p /tmp/janus-f23-replay-results
python3 research/infra/2026-09-12_loop-waste/measure.py --label fresh-audit --runs 1 --frames 20000 --out /tmp/janus-f23-replay-results
```

Expected replay digests are `13e4fb08a76c920f / 4f53cda18c2baa0c`. The two known flaky tests are
`test_redemption_builder_cli_keeps_secure_value_off_argv` and
`test_redemption_secret_pipe_gives_one_payload_per_reader_open`; do not confuse those existing FIFO
races with a candidate regression, but do not hide any other failure.

Production box identifiers for read-only checks are:

```bash
JANUS_BOX_REGION=mx-central-1 JANUS_BOX_ID=i-0a8c073c72dcdae11 bash ops/box/status.sh
```

Do not release or clear the kill merely because the prior audit said `RELEASE`; independently prove
the exact stopped state first and follow the operator's newest instruction.
