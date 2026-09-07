# ops — run accounting and the dead-man's switch

Not a node. Operational surface: it answers *"is this job healthy?"*, which nothing did before
2026-09-02.

| File | What it does |
|---|---|
| `run_index.py` | Append-only `runs/index.jsonl` on `/Volumes/Kilos`. Rows are immutable; corrections are new rows. |
| `watchdog.py` | SLA checks over that index. Detects `CRASH_LOOP`, `CRASHED`, `FAILED`, `STALE`, `HUNG`, `NEVER_RAN`, `UNREGISTERED`. |
| `run_node.sh` | Job wrapper: start row → run → finish row, plus stderr rotation at 32 MB. |
| `run_watchdog.sh` | Invoked by `com.janus.watchdog` every 5 minutes. |
| `arming_override.py` | Writes the signed arming override (GATE step 9): the operator's verbatim statement, the code-tree pin (`kernel/code_sha`: nodes, grids, kernel, the runner, the box units; the whole-checkout HEAD beside it for the record) and the limits sha, caps, expiry. Refuses a dirty or unknown tree, and refuses to overwrite without `--force`. |
| `box/kill_sync.py`, `box/kill.sh` | The cross-host kill: `kill.sh all\|live [--clear]` sets or clears `/janus/kill/{all,live}` in SSM from the Mac; the box's watchdog job mirrors them into its local kill files every five minutes and never lifts a file the breaker or a human latched. |
| `box/release.sh`, `box/arm_statement.txt` | The operator's daily paste: checkout without restart, re-sign the override for the new tree, restart under `LIMITED_LIVE`. Refuses while a co-listed game is in play unless `--now`. |
| `kalshi_live_proof.py` | GATE step 8 on Kalshi, tiny, through the same nodes a trade uses: dry run, `--arm`, `--settle`, `--check`. The operator runs it; the agent never passes `--arm`. |
| `polymarket_live_proof.py` | GATE step 8 on Polymarket, tiny, the venue's first real order (no demo exists): dry run, `--arm`, `--settle`, `--check`. Needs the wallet key file (600) named by `JANUS_PM_WALLET_KEY_PATH` and an override whose statement names Polymarket. Matched is not settled: the fill counts once the trade is CONFIRMED on-chain. |
| `kalshi_shards.py` | Kalshi exchange shards: `--show` prints the balance per shard and which shard each registered game series is on; `--move --to N --usd X` plans an intra-account transfer and sends it only with `--confirm` (the operator's). Collateral lives per shard since 2026-08-24; an order on an unfunded shard is refused `user_not_found`. |
| `proof_check.py` | The post-proof checklist as code, shared by every venue's proof script: resting → canceled, IOC final, fees at the pin, balance delta, settled PnL arithmetic, reservation released. Reads the ledger read-only; never echoes an ack. |

## Why the start row exists

It is written **before the interpreter is invoked**. A crash at import, argparse or config time —
exactly what `com.janus.convergence` did every 30 seconds for thirteen days, unnoticed — still
leaves a durable trace. A design that only logged completions could not have seen that failure at
all, because a crash loop does technically keep running. `CRASH_LOOP` (restart *rate*) is the check
that catches it, and it needs no cooperation from the collector.

The old `collectors/run_*.sh` wrappers `exec`'d into Python, which replaces the shell and makes
recording an outcome structurally impossible. `run_node.sh` deliberately does not `exec`.

## Alarm discipline

Per `GATE_TO_LIVE.md` step 2 — *"every alarm demonstrated firing against a fake target; a monitor
that has never emitted is untested"* — `watchdog.selftest()` drives all seven branches against
synthetic input and asserts each fires, **and** asserts the healthy case stays silent. A monitor
that always fires is what trains an operator to ignore it. Do not add a check without adding its
firing test.

`DISABLED` holds deliberately-stopped jobs (reported as info, never as alerts) so an unloaded lane
does not alarm forever.

## Releases under the arm (2026-09-07)

The arming override pins the **executable tree**, not the checkout: `kernel/code_sha.code_tree_sha`
hashes the git tree ids of `nodes`, `grids`, `kernel`, `ops/run_node.sh` and `ops/box/systemd`.
A docs, research or ops-script commit deployed to the box leaves the arm valid; a change under any
of those paths does not (`OVERRIDE_CODE_SHA` at start). The whole-checkout `runner_sha` is still
written and logged, for the record. The operator's choice: "Pin the code tree, one daily paste".

The lane no longer trusts the override it read at start. `Supervisor.check_arm()` re-reads it on
every report tick (`nodes/risk/gate.override_state`); in a capital-risking mode an override that has
expired, gone missing, or pins another tree or other limits sets `arm_stale`, prints
`[arm] STALE <why>` once, and `_execute` refuses every real order at the door (`ARM_STALE`) while
pricing continues. A matching override lifts it without a restart. The watchdog says the same from
outside: `OVERRIDE_EXPIRING` (under 24 h left) and `OVERRIDE_STALE`, both only where the box's
systemd drop-in says `LIMITED_LIVE` (the Mac has no drop-in and never alarms).

The daily paste is `ops/box/release.sh <sha>`: checkout without restart, re-sign at the F8 caps
from `ops/box/arm_statement.txt`, restart under `LIMITED_LIVE`. `ops/box/update.sh` refuses to
check out under a `LIMITED_LIVE` drop-in without `--no-restart`, because the restart it would do
crash-loops until the override is re-signed. The cross-host kill is `ops/box/kill.sh all|live`
(an SSM parameter the box mirrors within five minutes; `--clear` lifts only what SSM latched).

## Host hygiene while the lane is live on the Mac (2026-09-04)

The lane's books are only as fresh as its event loop is prompt, and this Mac is starved
(swap in use, other agents, collectors). Ledger L37 and L38: a test suite or a capture analysis
run beside the lane shows up as seconds of receive lag on both sockets. Until the box exists:

- Run `python3 -m pytest` and any `research/**/measure.py` under `nice -n 19`, one at a time, and
  never inside a window a research row is reading from the capture.
- Watch `loop` on the lane's report line and `socket_health.loop_lag_s`; a `[clock] HALT STALL`
  line means the lane fell behind real time, and every book it priced in that tick was that old.
- `launchd` cannot raise the lane's priority without root; `Nice` stays at 0.

Measured 2026-09-04 01:00Z: a full `pytest` run under `nice -n 19` still stalled the lane 10.9 s and
7.3 s on consecutive ticks (the host pages, and nice does not help paging). Run the full suite only
when the lane's stall does not matter (no game in play) or on another machine; run targeted test
directories otherwise.
