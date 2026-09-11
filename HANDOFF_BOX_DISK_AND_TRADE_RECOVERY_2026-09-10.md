# Handoff — box disk exhaustion, live-trade audit, and safe recovery

## Read this first

This document is the shortest current source of truth for the next agent. It supersedes the
runtime-status claims in `NEXT.md` and the earlier handoff, but it does not supersede their design,
research, or safety history.

The production lane is **not currently trading**. At the read-only snapshot ending
`2026-09-11T04:45:37Z` (`2026-09-10 22:45` Mexico City), the 49 GB `/srv/janus` filesystem was full,
the live service was restart-looping, and automatic Polymarket redemption was stale. No production
files, services, orders, positions, cloud resources, or data were changed during this diagnostic.

## Initial project state for this session

- Local worktree: `/Users/bernardodelrio/Code/Janus/.codex/worktrees/ucl-coverage`
- Branch: `codex/ucl-coverage`
- Local HEAD: `5e5e54e6365f3fd249ada3e39785fa84970ed7e9` (`Record successful live recovery`)
- Deployed production SHA: `11b7f0a0c8d765e45772ad9d0f94ced0f900cd17`
- Box: region `mx-central-1`, instance `i-0a8c073c72dcdae11`
- Signed mode: `LIMITED_LIVE`, caps `$12 stake / 10 contracts / $250 daily notional`
- The local HEAD differs from production only by the documentation commit `5e5e54e`; it does not
  require deployment.
- The prior final audit had proved the lane and all three streams healthy, `kill/live` absent,
  material risk flags quiet, and Polymarket automatic redemption successful.

The user then asked whether there had been trades or failed trades. A fresh read-only box audit
found that live trading did occur, but a new storage failure has since stopped the lane.

## Work completed in this session

Only read-only diagnostics were performed:

1. Queried the box service state, kill files, signed override, disk space, watchdog, recent logs,
   execution journal, order journal, settlements, and unreleased exposure.
2. Distinguished actual fills from clean taker FAK no-fills and historical maker failures.
3. Identified the immediate outage as data-disk exhaustion rather than a kill relatch, credential
   failure, or execution crash.
4. Audited all filled executions in the last 24 hours and every execution since the latest release.
5. Attempted a read-only SQLite `dbstat` size aggregation. It was still scanning after 66 seconds,
   so the exact diagnostic processes (`81801`, `81802`, `81803`) were terminated. No database write
   occurred and those processes no longer exist.

No fix was applied because both available immediate remedies—deleting/pruning data or enlarging the
billable EBS volume—require explicit operator authorization. `AGENTS.md` also expressly prohibits
deleting data without approval.

## Current production state

### Immediate blocker

At `2026-09-11T04:44:45Z`:

- `/dev/nvme1n1`, mounted at `/srv/janus`: 49 GB size, 47 GB used, **0 available, 100%**.
- Root filesystem: 19 GB size, 15 GB available, 20% used.
- Inodes are not the problem: `/srv/janus` was only 1% inode-used.
- `/srv/janus/tuples/tuples.sqlite`: `27,362,127,872` bytes.
- `/srv/janus/frames`: approximately 21 GB total:
  - Kalshi frames: approximately 7 GB.
  - Polymarket frames: approximately 14 GB.
- Logs: approximately 14 MB.
- SQLite WAL: approximately 4.5 MB; the WAL itself is not the capacity problem.

The first observed fatal storage error was around `2026-09-11T04:40Z` (`22:40` Mexico City):

```text
[fatal] OperationalError: database or disk is full
```

The service then restarted once per minute and immediately failed because even the run marker could
not be written:

```text
/opt/janus/ops/run_node.sh:echo:45: write error: no space left on device
```

At the final snapshot:

- `janus-live-stream`: `activating (auto-restart)`, `Result=exit-code`, `ExecMainStatus=75`, at least
  seven restarts.
- `janus-pm-redeem.timer`: active.
- `janus-pm-redeem.service`: failed; watchdog reported redemption stale.
- `kill/live`: absent.
- `kill/all`: absent.
- The signed override still pinned the deployed tree and retained the approved caps.
- The lane is fail-closed because its process cannot start, despite no kill file.

Do **not** run the false-maker latch clearer. This outage is unrelated to the prior false maker
latch, and neither kill file exists.

### Money and exposure

The database showed no open venue orders. One execution remains unreleased only because its event
has not yet been settled:

```text
execution_id: 98376aa273244039bfd207db7c90af79
event: MORIYA V SHIMIZU (pm:atp:993325)
state: HEDGED
Polymarket: 10.107514 @ 0.929999998, fee $0.03289
Kalshi:     10.000000 @ 0.04,         fee $0.02690
bounded residual: 0.107514 Polymarket contracts
released: 0
```

All associated orders were terminal. Three Kalshi attempts at `0.03` and one at `0.04` filled zero;
the next `0.04` attempt filled all 10 contracts. Based on recorded cash and fees, the ordinary
two-outcome worst case is approximately `+$0.14022`; if the Polymarket side wins it is approximately
`+$0.24774`. Settlement-reference risk remains governed by the stored cover proof.

The last known position mismatch flag for the preceding trade was followed by
`POSITION_MISMATCH_RESOLVED`. The old persistence incident `530` was resolved by exact marker `533`.
The next agent must still obtain a fresh venue-authoritative position/cash snapshot after restoring
write capacity; do not infer current venue balances solely from the local database.

## Trade audit

Three filled executions existed in the audited 24-hour window.

### 1. JACQUEMOT V TIKHONOVA — settled `-$0.014932`

- Execution: `0b425cbe71cb4ca1a919fda622538a07`
- Started: `2026-09-10T21:26:34Z`
- This is the already-documented accidental release-transition execution.
- Polymarket filled `10.763158 @ 0.38`; Kalshi protection eventually filled `10 @ 0.64` after five
  misses.
- Settlement: cover `-$0.4775`, directional residual `+$0.4626`, total `-$0.014932`.
- State: `RECONCILED`, released, all orders terminal.

### 2. SEKULIC V MATSUDA — settled `-$0.095105`

- Execution: `73688bf3da174f33a22023b111411d20`
- Started: `2026-09-11T02:46:40Z` (`20:46` Mexico City).
- Polymarket filled `10.012485 @ 0.801`, fee `$0.07979`.
- Five Kalshi hedge attempts at `0.16` filled zero; protection then filled `10 @ 0.19`, fee
  `$0.1078`.
- Settlement: cover `-$0.0975`, directional residual `+$0.0024`, total `-$0.095105`.
- State: `RECONCILED`, released, all orders terminal.
- This is the most important execution-quality case to investigate: the detected opportunity was
  profitable at the frozen books, but the first leg filled and the Kalshi touch disappeared before
  protection completed, converting the trade to a small locked loss.

### 3. MORIYA V SHIMIZU — hedged and pending settlement

- Execution: `98376aa273244039bfd207db7c90af79`
- Started: `2026-09-11T04:22:31Z` (`22:22` Mexico City), after the latest release.
- Exact economics and status are recorded above.
- This confirms that the final taker-first system can fill; it is not categorically unable to trade.

### No-fills and apparent failures

Since the latest release completed at approximately `2026-09-11T03:20:54Z`, the database recorded:

- 19 execution attempts.
- 1 filled/hedged execution: MORIYA V SHIMIZU.
- 18 `ORDER_UNFILLED` taker FAK attempts, each with zero fill, zero position, and released capital.
- 0 genuine `ORDER_REJECTED` executions after that release.

Across the full 24-hour window there were 43 `ORDER_UNFILLED`, 5 `ORDER_REJECTED`, 2 `RECONCILED`,
and 1 `HEDGED` rows. The five apparent rejections were:

- Two old maker orders rejected because the post-only quote crossed the book.
- One old maker attempt whose quote proof expired or was missing.
- Two Polymarket FAK submissions that returned HTTP 400 `no orders found to match`; both filled zero
  and created no position. They were economically authoritative no-fills but were labeled
  `ORDER_REJECTED` by the then-running code.

The current deployed code subsequently recorded the same economic FAK no-match outcome as
`ORDER_UNFILLED` 18 times. Treat the two HTTP-400 rows as historical observability debt; verify the
current path with tests before changing it, and do not assume the bug still reproduces.

An `invalid amounts ... max accuracy` Polymarket error visible in stderr was traced to an order from
`2026-09-08T23:50:55Z`, not to the current 24-hour window. That order filled zero and has no owning
execution.

## Files changed

No existing file was modified in this session.

## Files created

- `HANDOFF_BOX_DISK_AND_TRADE_RECOVERY_2026-09-10.md` — this handoff. It records the current outage,
  exact trade audit, safety boundary, and prioritized continuation plan.

## Important files intentionally left untouched

- `NEXT.md` — its runtime statement is now stale, but it contains valuable design and verification
  history. This handoff explicitly supersedes runtime status without rewriting history.
- `HANDOFF_PROFIT_SIZING_COVERAGE_2026-09-09.md` — retained unchanged as the complete history of the
  sizing, taker restoration, kill-latch, persistence, and redemption work.
- `snooping_ledger.md` and all research specs — no empirical evaluation or code change was run, so no
  new row was registered.
- `ops/watchdog.py`, execution code, storage code, systemd units, and box scripts — reviewed only
  enough to diagnose; no untested fix was made.
- `/srv/janus/tuples`, `/srv/janus/frames`, `/srv/janus/logs`, kill files, and release audit files —
  no production data was deleted, truncated, compacted, or modified.
- AWS instance and EBS configuration — no resize, restart, snapshot, or paid resource mutation was
  performed.

## Sources of truth

Use these in this order:

1. `AGENTS.md` — sacred safety/design rules, especially no data deletion without explicit approval,
   pre-registration before empirical work, and pure executable two-leg arbitrage.
2. This handoff — freshest operational snapshot and shortest continuation context.
3. `HANDOFF_PROFIT_SIZING_COVERAGE_2026-09-09.md` — full prior implementation and release history.
4. `GATE_TO_LIVE.md` — operator-only live promotion and capital-safety boundary.
5. `NEXT.md` — design opinion and prior successful state; its claim that production is currently
   green is superseded by this handoff.
6. Production facts: exact deployed SHA, systemd state, read-only SQLite journal, venue-authoritative
   orders/positions/cash, signed override, kill files, and watchdog output.
7. `snooping_ledger.md` and immutable specs for any new empirical analysis.

## Immediate next steps, in order

### P0 — obtain explicit authority for the storage remedy

Ask the operator to choose between:

1. **Recommended: enlarge the EBS data volume first.** This preserves all evidence and is the
   fastest low-risk recovery. Resolve the exact EBS volume ID and filesystem type read-only before
   proposing commands. The operator must approve the new size and billable mutation.
2. Prune/archive data. This is destructive and requires the operator to approve the exact paths,
   age boundary, and recovery implications. Never delete the database wholesale, run `VACUUM`, or
   recursively remove `/srv/janus`.

The current 50 GB volume filled in roughly three days, so merely adding a few GB is not durable.
Expansion is an emergency runway, not the final retention fix.

### P0 — stabilize and verify money before restarting

After authority is granted:

1. Stop the restart churn for `janus-live-stream` while storage is repaired. Do not clear or create a
   kill file as a shortcut; document the exact service action.
2. Preserve the current database and raw frames. Prefer an EBS snapshot if the operator accepts its
   cost and time.
3. Restore substantial free capacity.
4. Check `df -h`, `df -i`, filesystem type, mount health, SQLite readability, and a bounded integrity
   check before starting writers.
5. Query both venues authoritatively for open orders, positions, recent fills, and cash. Reconcile
   execution `98376aa...` and confirm all its orders are terminal.
6. Confirm the signed override is still unexpired and pins SHA `11b7f0a...`; never silently re-sign or
   change caps.
7. Start the live lane and wait for Kalshi, Polymarket market, and Polymarket user streams to be
   connected and fresh.
8. Run automatic redemption once, verify its ledger, then run the watchdog. Do not call the system
   healthy until the lane, all streams, redemption, disk headroom, orders, positions, settlements,
   reservations, and material risk flags agree.

Useful first read-only command:

```bash
cd /Users/bernardodelrio/Code/Janus/.codex/worktrees/ucl-coverage
JANUS_BOX_REGION=mx-central-1 \
JANUS_BOX_ID=i-0a8c073c72dcdae11 \
bash ops/box/status.sh --since 86400
```

Use `bash ops/box/run.sh '<read-only command>'` for targeted inspection. Remember that it executes as
root on the box; use `sudo -u janus` for SQLite and repository-owned paths.

### P1 — identify and stop the storage growth

Before empirical testing, create a descriptive `research/exec/.../spec.yaml` and append its PENDING
ledger row. Then, with the lane stopped and adequate free space:

1. Determine exact table sizes. The live `dbstat` aggregation was too expensive during this session;
   run it offline or use a bounded alternative.
2. Quantify per-hour growth of `tuples.sqlite`, Kalshi frames, and Polymarket frames.
3. Identify which tables and frame writers lack retention/rollup.
4. Implement explicit retention that preserves execution, order, fill, settlement, risk, reservation,
   proof, research, and audit evidence.
5. Add a pre-full disk watchdog threshold with enough runway to stop writers safely before SQLite can
   fail. A 100%-full alert is too late.
6. Add tests for retention boundaries, disk-pressure fail-closed behavior, and restart recovery.

Expected EV effect: preventing another disk outage preserves opportunity coverage and avoids losing
all executable EV during downtime. It should not change trade selection or lower any profitability
gate.

### P1 — review hedge slippage without weakening safety

Pre-register a descriptive audit of the SEKULIC and MORIYA attempts. Compare frozen-book plan,
first-leg acknowledgement, hedge quote age, each IOC submission/acknowledgement, venue FIFO fills,
and the protective walk. Determine whether first-leg venue ordering, smaller initial quantity, or a
different bounded hedge schedule improves realized EV.

Do not remove protective hedging merely because SEKULIC locked a loss; once the first leg fills,
limiting unhedged exposure is the safety obligation. Any proposed change must preserve the pure
two-leg requirement and state expected EV and tail-risk effects.

### P2 — verify observability taxonomy

Add or confirm a regression test that Polymarket's HTTP-400 FAK `no orders found to match` response is
stored as an authoritative zero-fill `ORDER_UNFILLED`, not `ORDER_REJECTED`. Current production
behavior appears corrected, so make no code change unless the current path can still reproduce the
misclassification.

## Completion criteria for the next agent

The handoff is complete only when all of the following are true:

- Meaningful free disk headroom exists and a tested retention/alert path prevents recurrence.
- The live lane is active rather than activating/restart-looping.
- All three streams are fresh.
- Venue-authoritative open orders and unexpected positions are zero.
- MORIYA V SHIMIZU is either correctly pending settlement or fully reconciled/released.
- Automatic redemption is active and current.
- The watchdog has no actionable alert.
- `kill/live` has not been spuriously created or cleared.
- The signed caps remain exactly `$12 / 10 / $250` unless the operator separately authorizes a new
  capital decision.
- Full relevant tests pass, research/ledger rules are satisfied, and any executable release uses the
  operator boundary in `GATE_TO_LIVE.md`.
