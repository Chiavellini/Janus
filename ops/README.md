# ops — run accounting and the dead-man's switch

Not a node. Operational surface: it answers *"is this job healthy?"*, which nothing did before
2026-09-02.

| File | What it does |
|---|---|
| `run_index.py` | Append-only `runs/index.jsonl` on `/Volumes/Kilos`. Rows are immutable; corrections are new rows. |
| `watchdog.py` | SLA checks over that index. Detects `CRASH_LOOP`, `CRASHED`, `FAILED`, `STALE`, `HUNG`, `NEVER_RAN`, `UNREGISTERED`. |
| `run_node.sh` | Job wrapper: start row → run → finish row, plus stderr rotation at 32 MB. |
| `run_watchdog.sh` | Invoked by `com.janus.watchdog` every 5 minutes. |
| `arming_override.py` | Writes the signed arming override (GATE step 9): the operator's verbatim statement, runner and limits sha pins, caps, expiry. Refuses to overwrite without `--force`. |
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

## Host hygiene while the lane is live on the Mac (2026-09-04)

The lane's books are only as fresh as its event loop is prompt, and this Mac is starved
(swap in use, other agents, collectors). Ledger L37 and L38: a test suite or a capture analysis
run beside the lane shows up as seconds of receive lag on both sockets. Until the box exists:

- Run `python3 -m pytest` and any `research/**/measure.py` under `nice -n 19`, one at a time, and
  never inside a window a research row is reading from the capture.
- Watch `loop` on the lane's report line and `socket_health.loop_lag_s`; a `[clock] HALT STALL`
  line means the lane fell behind real time, and every book it priced in that tick was that old.
- `launchd` cannot raise the lane's priority without root; `Nice` stays at 0.
