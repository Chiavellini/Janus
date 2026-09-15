# NEXT

An opinion, not a record. Overwrite this file; never append to it. What changed is git log.

Updated 2026-09-14 after L121-L123 on branch claude/hedge-safety-and-speed.

## Current state

The Mexico box is still deployed at 8e7ab4a. The lane service is active but kill/live remains
present with exact SHA a9613b6dff2499e3da6fe4aa2b872fa02f955aaefb043e60725f289603c249f6
and reason LEGACY_INCIDENT_ACK_INVALID flag=211. Nothing is trading. Read-only inspection found no
current open or unconfirmed journal orders, cash-pending orders, unreleased executions, or
unreleased reservations. The production database has every table and column required by L122.

The candidate through L124 passed the integrated suite when the two documented pre-existing FIFO
flakes were excluded. The one FIFO failure seen in an earlier unfiltered run passed immediately
in isolation. Replay parity is unchanged: 1,093 rows and zero selections at
13e4fb08a76c920f / 4f53cda18c2baa0c. A fresh external audit returned RELEASE with no remaining
P0/P1 in the audited recovery and guard paths.

No cap, hurdle, size, entry policy, settlement rule, or trading behavior changed. The changes make
restart recovery exact, make guard failure fail closed, preserve protection on incomplete guard
snapshots, and permit only a narrowly proved legacy-kill recovery during an operator-run release.

## Initial state and source of truth

The session began after release 31e7a42 stopped during legacy-latch recovery. The operator
cancelled that command after it printed a very long repeated flag list. Read-only inspection later
showed the box safely stopped by a retained kill, no live capital in flight, and deployment
8e7ab4a. A later operator attempt for 6a64561 exited before changing that checkout. Static review
then found and registered L124's fail-closed full-SHA validation defect. NEXT.md, AGENTS.md,
GATE_TO_LIVE.md, the L104-L124 ledger rows and registered specs,
git history, the production database, and exact kill/deployment hashes were treated as sources of
truth. Status log counters were not treated as authoritative execution state.

## Files changed

- grids/live_stream/grid.py and grids/live_stream/tests/test_grid_callbacks.py: recover exact
  dispositions after restart and make every guard failure an entry stop without suppressing
  protection.
- nodes/execute/guard.py and ops/guard_once.py, with ops/tests/test_guard_once.py: expose and require
  a complete, quiet guard proof for stopped-lane release checks.
- nodes/execution/dispositions.py and nodes/execution/tests/test_dispositions.py: add bounded,
  target-bound, venue-authoritative restart recovery.
- nodes/execution/README.md and ops/box/README.md: document the recovery and operator contracts.
- ops/box/release.sh and ops/box/tests/test_box.py: route only the exact reviewed retained kill
  through the bounded proof helper and validate the full deployed Git SHA.
- snooping_ledger.md: register L121-L124 before their runs and record their immutable results.
- NEXT.md: replace the stale deployed-state handoff with this release state and economic truth.

## Files created

- ops/box/clear_legacy_incident_latch.py: exact evidence validator, quarantine, archive, and rollback
  engine for the one reviewed legacy kill.
- ops/box/clear_legacy_incident_latch.sh: stopped-lane two-pass guard and verified cleanup wrapper.
- ops/box/tests/test_legacy_incident_clear.py: adversarial tests for mismatch, race, archive, stop,
  and rollback behavior.
- research/exec/2026-09-14_disposition-survives-restart/spec.yaml and verdict.md: L121 registration
  and result.
- research/exec/2026-09-14_reviewed-legacy-kill-clear/spec.yaml and verdict.md: L122 registration
  and result.
- research/exec/2026-09-14_guard-failure-fails-closed/spec.yaml and verdict.md: L123 registration
  and result.
- research/exec/2026-09-14_full-deployed-sha-validator/spec.yaml and verdict.md: L124 registration
  and result.

## Intentionally untouched

GATE_TO_LIVE.md, caps, hurdles, sizing, settlement templates, venue credentials, balances, venue
positions, and production database records were not changed. No arm, confirm, mode, override,
kill-clear, release, or order command was run by the agent. The user's manual Polymarket position
was not changed or attributed to Janus. The two known flaky FIFO tests were not chased because
they are pre-existing and separately queued.

## L121: exact restart-safe disposition recovery

research/exec/2026-09-14_disposition-survives-restart/spec.yaml registers the proof. Recovery uses
the worker-owned database connection, accepts only an active target-bound disposition, requires
the venue to return the exact fill, and has a 24-hour window plus a 500-row work bound. Corrupt,
revoked, expired, wrong-target, or unverifiable evidence cannot gain authority. Recovery errors
remain visible and latch the kill. The exact operator-owned manual Polymarket fill is the only
intended match.

## L122: exact reviewed legacy-kill recovery

research/exec/2026-09-14_reviewed-legacy-kill-clear/spec.yaml registers the proof. The helper is
reachable only from the operator release path and only when the full deployed SHA, full current
kill SHA, exact flag/reason, incident acknowledgement, schema, all material flags, every venue
journal state, executions, and reservations match the reviewed state.

Before removal it waits boundedly for L121 recovery, runs two strict complete-and-quiet
stopped-lane venue guards with retained-kill socket warmup between them, and preserves an
independent fsynced exact archive. Cleanup restores and verifies the original kill before
attempting to stop the lane; rollback failures are explicit hard failures. A changed or new kill
is preserved.

## L123: guard failure is an entry stop

research/exec/2026-09-14_guard-failure-fails-closed/spec.yaml registers the proof. A process starts
guard-unhealthy and cannot enter capital until one complete guard pass. Fetch, apply, or
incomplete-snapshot failure clears cached authority, appends GUARD_FAILED, and first-writer latches
the kill. If persistence itself fails, the in-memory entry stop remains. Existing findings and
required protection are processed before an incomplete snapshot is rejected, so fail-closed entry
does not suppress protection.

## L124: full deployed SHA reaches the exact helper

research/exec/2026-09-14_full-deployed-sha-validator/spec.yaml registers the proof. The L122
release route previously matched only twenty hex characters after reading a full forty-character
Git SHA, so a valid release failed closed before recovery. It now accepts exactly forty lowercase
hexadecimal characters. A harness executes the real shell route, proves the exact SHA reaches the
helper untruncated, and rejects abbreviated, overlong, uppercase, and non-hex values. A separate
audit returned RELEASE.

## What is and is not proved toward $100/day

These changes have zero claimed EV uplift per trade. They remove ways that a restart, stale guard
state, or failed cleanup could make the prospective profit measurement unsafe or ambiguous. They
are necessary measurement infrastructure, not proof of profitability.

The economic evidence is still adverse: twenty real covers produced pooled P&L of -$1.50, and the
latest ten were net -$3.96. Median booked margin was below combined realized fee/slippage. No
league has the twenty covers required for a defensible per-league reserve. Maker entry remains an
unproved lead with one historical fill in seventeen attempts; its registered prospective cohort
is still owed. The independently measured moneyline surface remains about $20/day gross.

The operator's short-horizon turnover thesis may eventually make $600 recycle above $10,000/day,
but current signed behavior still caps cumulative daily notional at $500 and keeps event capital
reserved until settlement/reconciliation. Do not increase turnover or loosen entry until q=10
unit economics are positive and settlement release is proved. Any later increase requires a dated
GATE_TO_LIVE.md amendment using the operator's verbatim authorization.

## Immediate sequence

1. Push branch head and have the operator run one release command. The agent never releases,
   confirms, clears a kill, arms, changes mode, or writes an override.
2. Verify the deployed full SHA, exact kill transition, lane state, complete guard result, fresh
   sockets, and zero open/unreleased material state. Stop on any mismatch.
3. Resume the registered q=10 prospective cohort and measure per-league net EV, Sharpe, slippage,
   fill conversion, and covers per event. Do not pool leagues to hide adverse selection.
4. If taker unit economics remain negative, test the registered maker cohort and/or exclude losing
   leagues. Only after positive unit economics should wider coverage and recyclable turnover be
   considered.

## Instrument traps that still apply

- stages_json timing values are cumulative from the loop start; difference adjacent stages and
  exclude guard_rerun rows.
- socket_health.frames is cumulative; take deltas and treat decreases as reconnects.
- BLOCKED_MATCH is mostly the single_venue branch, not lost paired surface.
- refusal_counts is hot-path aggregation, not unique opportunities.
- PROFITABLE_UNEXECUTED is material-change gated and per size rung; always name the rung.
- The status script execs field can include historical untimestamped repeated lines. Use the
  production database to decide whether an execution or reservation is actually unresolved.
- The local archive database is corrupt; replay uses the separate slate snapshot.
- Negative unconditional hedge drift is not maker EV. L63 remains the maker authority.
