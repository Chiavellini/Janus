# NEXT

An opinion, not a record. Overwrite this file; never append to it. What changed is git log.

Updated 2026-09-15 after L130 production confirmation on branch claude/hedge-safety-and-speed.

## Current state

The Mexico box is deployed at f7c9c1b177f757d6bfbc6e126eeb47bbb001c6eb. The lane service is
active/running in LIMITED_LIVE and `kill/live` is absent after exact reviewed recovery. Independent
read-only inspection found no current open or unconfirmed journal orders, unreleased executions,
material unhedged exposure, unreleased reservations, or unresolved ORPHAN_FILL, ORDER_OVERFILL,
POST_ONLY_PERSISTENCE_FAILED, or GUARD_FAILED flags. All three sockets were connected and fresh.

The candidate through L130 passed the integrated suite when the two documented pre-existing FIFO
flakes were excluded. The one FIFO failure seen in an earlier unfiltered run passed immediately
in isolation. Replay parity is unchanged: 1,093 rows and zero selections at
13e4fb08a76c920f / 4f53cda18c2baa0c. A fresh external audit returned RELEASE with no remaining
P0/P1 in the audited recovery and guard paths. L130 is production-confirmed.

One observability defect remains: `ops/box/status.sh` reports the persistent advisory file
`.legacy-incident-211.lock` as `KILL_FILE_PRESENT`. Runtime entry checks ignore arbitrary files and
look only for named all/live/venue/event/strategy switches, so this is not an entry block; it is a
false watchdog alert that could mask a later real kill and should be repaired separately.

No cap, hurdle, size, entry policy, settlement rule, or trading behavior changed. The changes make
restart recovery exact, make guard failure fail closed, preserve protection on incomplete guard
snapshots, and permit only a narrowly proved legacy-kill recovery during an operator-run release.

## Initial state and source of truth

The session began after release 31e7a42 stopped during legacy-latch recovery. The operator
cancelled that command after it printed a very long repeated flag list. Read-only inspection later
showed the box safely stopped by a retained kill, no live capital in flight, and deployment
8e7ab4a. A later operator attempt for 6a64561 exited before changing that checkout. Static review
then found and registered L124's fail-closed release-route validation defect. The authorized
3af2993 release deployed and re-signed the standing caps, then failed closed at L125's independent
helper digest validator. The 31f8b1d continuation deployed and failed locally before the helper's
first remote action at L126's heredoc boundary. The original kill remained exact and admitted no
entry throughout. NEXT.md, AGENTS.md, GATE_TO_LIVE.md, the L104-L126 ledger rows and registered specs,
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
- ops/box/clear_legacy_incident_latch.sh and ops/box/tests/test_legacy_incident_clear.py: preserve
  exact helper semantics while validating full digests and constructing remote shell variables
  and quotes correctly.
- snooping_ledger.md: register L121-L130 before their runs and record their immutable results.
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
- research/exec/2026-09-14_helper_digest_validator/spec.yaml and verdict.md: L125 registration and
  result.
- research/exec/2026-09-14_remote_heredoc_boundary/spec.yaml and verdict.md: L126 registration and
  result.
- research/exec/2026-09-14_post_ack_maker_history/spec.yaml and verdict.md: L127 read-only
  production classification.
- research/exec/2026-09-14_terminal_history_release_convergence/spec.yaml and verdict.md: L128
  registration and local result.
- research/exec/2026-09-15_recovery_cursor_boundary/spec.yaml, results.json, and verdict.md: L129
  read-only production boundary measurement.
- research/exec/2026-09-15_exact_recovery_convergence/spec.yaml and verdict.md: L130 registration
  and local result.

## Intentionally untouched

GATE_TO_LIVE.md, caps, hurdles, sizing, settlement templates, venue credentials, balances, venue
positions, and production database records were not directly changed. The user's manual
Polymarket position was not changed or attributed to Janus. The two known flaky FIFO tests were
not chased because they are pre-existing and separately queued. The operator explicitly
authorized the agent to execute this release; that authority does not permit bypassing any proof
or manually clearing a kill.

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

## L125: exact helper digest validators

research/exec/2026-09-14_helper_digest_validator/spec.yaml registers the proof. The helper itself
had independently malformed length patterns: 42 groups for the 40-character release SHA and 61
for the 64-character kill digest. Both now use anchored exact lowercase-hex expressions and reject
short, long, uppercase, or non-hex values before remote work. Forty-one focused tests, the
integrated suite, replay parity, and a separate audit passed.

## L126: local-to-remote heredoc boundary

research/exec/2026-09-14_remote_heredoc_boundary/spec.yaml registers the proof. The helper's
unquoted heredoc expanded remote STARTED and AUDIT locally and emitted backslash-quoted rather than
syntactic double quotes. The production-construction test now proves the complete boundary: five
reviewed values bind locally, every remote variable remains remote, STARTED is assigned before use,
and archive-dir receives the expanded quoted AUDIT path. Forty-two focused tests, integrated suite,
replay parity, and the final external audit passed.

## L127-L128: terminal history and exact release convergence

The read-only L127 production measurement verified the flag-211 acknowledgement, its sole bound
violation, 17 later terminal/unviolated maker attempts, an empty admission slot, and quiet current
capital. It also proved that 20 acknowledged overfill flags and the operator-disposed manual fill
still lacked append-only resolution markers, so its honest verdict was MATERIAL_STOP.

L128 changes only the exact recovery proof. It uses the existing settled-current predicate beside
the incident-only matcher and exact single-violation proof; every active or unknown current state
still blocks. The retained-kill wait is bounded at five minutes so the ordinary live guard—not the
helper—can append both ordered exact resolutions. Focused adversarial tests, integrated suite,
replay parity, and a fresh audit passed locally.

## L129-L130: measured recovery boundaries

The authorized a29a7c1 release failed closed after five minutes. L129 proved why. Polymarket's
authenticated integer `after` cursor excludes a fill at that exact second: the disposed fill was
absent at 1789409189 and the sole returned row one second earlier. It also proved that all twenty
unresolved overfill flags are covered, while four separate candidates legitimately pass the
existing bounded-taker-residual rule but caused the resolver to abort. Finally, systemd had zero
unit PIDs after killing the lane at its 30-second stop deadline, but the failed state label caused
cleanup to report a stop failure. The exact kill remained present throughout.

L130 crosses only the qualified disposition's one-second API boundary, applies the same bounded
residual predicate during overfill resolution while retaining exact unresolved-flag coverage, and
accepts/reset-failed only after MainPID and ControlPID both prove zero. Its 182 focused tests,
integrated suite, exact replay, shell syntax, and independent audit passed.

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

1. Observe the production-confirmed lane and resume the registered q=10 prospective cohort;
   measure per-league net EV, Sharpe, slippage,
   fill conversion, and covers per event. Do not pool leagues to hide adverse selection.
2. Repair the watchdog's advisory-lock false positive without changing runtime kill semantics.
3. If taker unit economics remain negative, test the registered maker cohort and/or exclude losing
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
