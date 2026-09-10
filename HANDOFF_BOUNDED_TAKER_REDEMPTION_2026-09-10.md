# Handoff — bounded taker restoration, exact false-latch recovery, and PM redemption

Date: 2026-09-10 America/Mexico_City

Branch: `codex/ucl-coverage`

Worktree: `/Users/bernardodelrio/Code/Janus/.codex/worktrees/ucl-coverage`

Production before this release: `6c694f1320459b590809f4de7496415d0a748d0e`

## Initial project state

The supplied 2026-09-09 handoff ended with F18 live on the Mexico box using Polymarket post-only
maker entry. On the current box day, thirteen attempts produced no fills: accepted maker orders
rested briefly and canceled at zero, crossed maker orders were rejected, and one final terminal-zero
order caused `kill/live` to latch about 0.05 seconds before its already-observed two-second stable
terminal proof matured. Read-only production evidence showed zero open PM orders, zero unresolved
maker markers, zero active unreleased executions, zero material unhedged exposure, and fresh
connected Kalshi, Polymarket market, and Polymarket user streams. The lane remained active but the
kill prevented new orders.

The PM account also exposed one positive-value redeemable win and many zero-value token remnants.
There was no automatic redemption job. The user explicitly directed a return to taker entry under
the existing small caps and asked that the false maker latch stop recurring, redemption become
automatic, and the box be restarted through the normal operator release boundary.

## Work completed

1. Restored the live grid and exhaustive sizing path to the executable-price taker plan. The PM
   first leg uses a dedicated FAK/FOK signer hard-limited to 10 requested contracts and $12
   collateral; the generic immediate BUY signer remains blocked.
2. Persisted bounded-taker authority before the wire. Actual venue quantity is preserved. A
   price-improvement excess strictly below one contract is hedged and explicitly audited; one
   contract or more keeps the existing overfill stop and latch.
3. Fixed the false maker-terminal race by extending only post-cancel reconciliation through the
   adapter's declared stable-terminal proof grace plus one poll. Cancel timing is unchanged and a
   genuinely unknown order still latches.
4. Added a release-only exact false-latch recovery. It captures the original kill digest, stops the
   lane, proves the named maker order terminal-zero and all execution state quiet, archives the kill
   and proof, restarts, requires all three streams to reconnect freshly, and restores the kill plus
   lane on any failure. No generic, changed, operator, filled, open, or exposed kill is clearable.
5. Added automatic PM redemption using the official `polymarket-client==0.9.0` in an isolated venv.
   The durable state machine filters valuable redeemable positions, records PREPARED before submit,
   recovers an ambiguous submission through exact relayer metadata, waits for confirmation, and
   requires fresh position disappearance before COMPLETE. A systemd timer runs every ten minutes;
   watchdog alerts after thirty minutes without a successful pass.
6. Added idempotent local provisioning of a complete builder-key triple into encrypted SSM. Partial
   credentials fail closed; values are neither printed nor written outside SSM and box tmpfs.
7. Preregistered L64/F19 before their tests, then L65/F20 before taker tests. F19 was closed with no
   data when the user superseded the maker-rest proposal. F20 remains the pending live cohort.
8. After the first candidate stopped at release step zero because local Python lacked `boto3`, L66
   replaced that undeclared dependency with a minimal AWS CLI SSM adapter. SecureString JSON enters
   through stdin, not argv or output. The failed paste performed no checkout, restart, or clear.
9. The installed CLI rejected whole JSON from `/dev/stdin`; the second paste also stopped before
   checkout. L67 now streams JSON twice through a short-lived mode-600 FIFO, matching the actual
   CLI's observed parser behavior without a regular file or secret-bearing argv. Benign local parser
   validation passes and read-only SSM inspection confirms source 3/3, builder 0/3.

Expected EV effect: immediate entry should recover executable first-leg fills lost to the recent
short-lived maker policy, at the known cost of taker fees. The magnitude is deliberately unclaimed
until F20 produces prospective fills. Redemption improves collateral availability, not trading EV.

## Files changed

- `GATE_TO_LIVE.md` — appended F19 and the superseding F20 operator authority without changing
  earlier gates.
- `CHANGELOG.md` — appended the execution, latch-recovery, redemption and validation history.
- `NEXT.md` — replaced stale F15/F18-maker status with the F20 release state and next action.
- `snooping_ledger.md` — appended L64, F19, L65, F20 and append-only local verdict notes.
- `grids/live_stream/grid.py` — capital mode now constructs the taker plan.
- `grids/live_stream/tests/test_grid_callbacks.py` — asserts the taker fill model.
- `nodes/exec_polymarket/client.py` — adds bounded-taker constants/table/signer/submit path and
  exposes terminal-proof grace.
- `nodes/exec_polymarket/README.md` — documents the new narrow taker contract and retained blocks.
- `nodes/exec_polymarket/tests/test_pm_exec.py` — covers pre-wire bounded authorization.
- `nodes/exec_polymarket/tests/test_quantity_cap.py` — covers dedicated signer bounds and generic
  BUY refusal.
- `nodes/execute/sizing.py` — sizes the same executable taker plan sent by the grid.
- `nodes/execute/coordinator.py` — accepts only durable sub-one bounded residuals and budgets the
  adapter's terminal-proof grace.
- `nodes/execute/guard.py` — recognizes the same durable accepted residual without weakening other
  overfill findings.
- `nodes/execute/protect.py` — records bounded residuals distinctly in the reconciled result.
- `nodes/execute/README.md` — updates execution policy and failure semantics.
- `nodes/execute/tests/test_maker_entry.py` — proves late-maturing terminal-zero does not latch and
  true unknown still does.
- `nodes/execute/tests/test_quantity_caps.py` — proves sub-one acceptance and at-least-one STOP.
- `nodes/execute/tests/test_sizing.py` — asserts taker plan selection and label.
- `ops/box/creds.py` — materializes the optional all-or-none builder credential group.
- `ops/box/release.sh` — composes provisioning, checkout, runtime sync, unchanged arm, restart,
  exact false-latch recovery, and immediate redemption into one operator paste.
- `ops/box/user-data.sh` — bootstraps redemption directories, isolated venv, SDK, unit and timer.
- `ops/box/README.md` — documents release and redemption operation.
- `ops/box/tests/test_box.py` — covers credentials, provisioning, SDK/unit installation and release
  composition.
- `ops/watchdog.py` — registers and self-tests the box-only thirty-minute redemption SLA.

## Files created

- `nodes/redeem_polymarket/__init__.py`, `redeem.py`, `run.py`, `README.md` — redemption node,
  durable state machine, oneshot entry point and contract.
- `nodes/redeem_polymarket/tests/__init__.py`, `test_redeem.py` — filtering, idempotency, crash
  recovery, confirmation, failure and no-blind-retry tests.
- `ops/box/clear_false_maker_latch.py`, `clear_false_maker_latch.sh` — exact stopped-lane proof,
  recoverable archive/clear, restart and fresh-stream check.
- `ops/box/provision_redemption.py` — local, secret-redacted builder credential provisioning using
  the existing AWS CLI and stdin-only SecureString payloads, with no laptop `boto3` dependency.
- `ops/box/sync_runtime.sh` — release-time pinned SDK/units/credentials/timer installation.
- `ops/box/systemd/janus-pm-redeem.service`, `janus-pm-redeem.timer` — isolated redemption job and
  ten-minute schedule.
- `ops/box/tests/test_live_clear.py` — exact clear success/restore and refusal regressions.
- `research/exec/2026-09-10_live-latch-and-redemption/spec.yaml`, `verdict.md` — immutable L64 and
  its partial-pass/superseded-maker verdict.
- `research/exec/2026-09-10_bounded-taker-resumption/spec.yaml`, `verdict.md` — immutable L65 and
  local implementation verdict.
- `research/sports/2026-09-10_limited-live-f19-maker-rest/spec.yaml`, `verdict.md` — immutable F19
  and no-data closure.
- `research/sports/2026-09-10_limited-live-f20-bounded-taker/spec.yaml` — pending forward cohort.
- `research/exec/2026-09-10_redemption-provision-cli/spec.yaml`, `verdict.md` — immutable L66 local
  release-compatibility repair and passing verdict.
- `research/exec/2026-09-10_redemption-provision-pipe/spec.yaml`, `verdict.md` — immutable L67
  pipe-transport repair and actual installed-CLI passing verdict.
- `HANDOFF_BOUNDED_TAKER_REDEMPTION_2026-09-10.md` — this continuation record.

## Files intentionally left untouched

- `ops/box/limits.toml`, the signed arming statement, and all capital/profit/return/protection
  limits: the user authorized execution urgency, not larger capital or lower hurdles.
- `nodes/execute/maker.py` and its historical journals: retained for reconciliation and historical
  evidence; the live grid simply no longer selects maker entry.
- Settlement, canonical matching, liquidity-source, fee, balance, breaker, reservation, and hedge
  clearance logic: all remain required and fail closed.
- Existing executions, orders, flags, account rows, cash/P&L, and kill evidence: no source or
  accounting row was rewritten or deleted. The operator release archives only the exact current
  false latch after re-proving it.
- The main checkout `/Users/bernardodelrio/Code/Janus`: all work stayed in the supplied isolated
  `ucl-coverage` worktree.

## Sources of truth

- `AGENTS.md` supplied architectural, safety, preregistration, executable-price and objective
  invariants.
- `GATE_TO_LIVE.md` supplied the append-only operator authority and unchanged live envelope.
- `research/exec/2026-09-10_bounded-taker-resumption/spec.yaml` is the immutable execution policy
  implemented in the candidate; the F20 spec defines the live observation boundary.
- The production SQLite journals, kill file, service state and socket-health rows were treated as
  operational truth; operator summaries were not substituted for them.
- The downloaded official `polymarket-client==0.9.0` wheel and Polymarket's official relayer and
  redemption documentation supplied the SDK and transaction contracts.

## Current project state

The local tree is a fully tested release candidate. The complete repository suite passes at 100%,
as do focused execution/redemption/release tests, shell syntax, `compileall`, watchdog self-test and
diff checks. Production is unchanged until the operator runs the release paste: it remains on
`6c694f1`, active but unable to enter because the current false maker latch is present. F20 has not
started and no taker fill-rate, live-latency or realized-EV claim has been made.

The remaining uncertainty is venue/runtime integration of the first real redemption and the first
F20 taker cover. Both are made visible and fail closed. C++ is not currently justified by evidence:
the observed no-fill mechanism was policy/order lifecycle and network interaction, not measured
Python execution-path compute.

## Immediate next steps

1. Commit and push this exact candidate; record the full SHA.
2. The operator runs `JANUS_BOX_REGION=mx-central-1`, the known box ID, unchanged
   `JANUS_ARM_CAPS='12 10 250 168'`, and `bash ops/box/release.sh <full-sha>` from this worktree.
3. Require the paste to report exact clear success, three green post-start streams, active
   redemption timer, and a non-error redemption summary. A refusal is evidence to inspect, not a
   reason to delete the kill manually.
4. Read back exact deployed SHA/override, watchdog, flight/unhedged/open-order state, redemption
   journal, and any first F20 execution. Reconcile nominal versus actual quantity, both venue fills,
   fees, hedge latency and P&L before drawing a speed or profitability conclusion.
