# ops — run accounting and the dead-man's switch

Not a node. Operational surface: it answers *"is this job healthy?"*, which nothing did before
2026-09-02.

| File | What it does |
|---|---|
| `run_index.py` | Append-only `runs/index.jsonl` on `/Volumes/Kilos`. Rows are immutable; corrections are new rows. |
| `watchdog.py` | SLA checks over that index. Detects `CRASH_LOOP`, `CRASHED`, `FAILED`, `STALE`, `HUNG`, `NEVER_RAN`, `UNREGISTERED`. |
| `run_node.sh` | Job wrapper: start row → run → finish row, plus stderr rotation at 32 MB. |
| `run_watchdog.sh` | Invoked by `com.janus.watchdog` every 5 minutes. |

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
