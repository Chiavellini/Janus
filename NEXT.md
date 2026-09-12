# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.*

Updated 2026-09-11 21:40Z after the F21 release.

## Current state

**F21 is live.** The operator pasted `release.sh 3a05bc1` at 21:29Z: the box runs `3a05bc1`, the
override is re-signed at 25 contracts / $30 per order / $500 a day (expires 2026-09-18T21:29Z), the
taker wire's ceiling is 25 / $30, all three sockets connected, 35 pollers. First three F21 covers
are reconciled to venue cash before a fourth; the row closes at ten covers or the first STOP.

**Box CPU is the next constraint, not new.** The c7g.medium (1 vCPU) runs the lane at ~80 % CPU
in busy hours; `socket_health.loop_lag_s` averaged 2–4 s with spikes to 10–30 s through Sep 9–10
and HALT STALL (> 5 s) fires and recovers on its own (twice in the 21:00Z hour today). Each stall
is pricing time lost. Every SSM diagnostic adds load on that one core, so box reads should be
sparse while games are in play. A larger instance (c7g.large, 2 vCPU, ~2× the hourly price) is a
billable operator decision, and the L37/L51 CPU-health rows are the prior work.

### Earlier state (20:20Z)

Production runs `11b7f0a0c8d765e45772ad9d0f94ced0f900cd17` on the Mexico box in `LIMITED_LIVE`,
restarted 2026-09-11T20:17:57Z after 15.6 hours down. The 50 GB data volume filled at 04:40Z; the
operator authorized a snapshot (`snap-0cdf81181eae376ef`) and an enlargement to 200 GB (142 GB
free after `resize2fs`). Nothing was pruned; `kill/live` and `kill/all` are absent; the override
is unchanged (caps $12 / 10 / $250, expires 2026-09-18T01:20:54Z). All three streams are connected
and fresh, the guard raised and resolved one POSITION_MISMATCH at start (Kalshi had finalized
MORIYA V SHIMIZU `yes` at 06:52Z), the redemption timer is active with a clean run (nothing
eligible), and the watchdog's only alert is the daily census past its SLA because it could not
run on the full disk; it clears at its next scheduled run. A `quick_check` of `tuples.sqlite`
(27.4 GB) was still running detached in the background at restart; `redemptions.sqlite` and
`proofs.sqlite` pass. Execution `98376aa2` (MORIYA) is HEDGED and awaits the lane's settlement
poller: Kalshi paid the cover, the Polymarket leg expired, ~+$0.14.

Read `HANDOFF_BOX_DISK_AND_TRADE_RECOVERY_2026-09-10.md` (its appended recovery record) for the
exact timeline and the venue snapshot.

## Why it filled, and what is on the branch (not deployed)

`sizing_decisions` was 24.69 of 27.36 GB: an 11 KB candidate ladder per book epoch per poller,
~1.95 M rows a day, 97 % for blocked or no-edge epochs. Frames were 21 GB in four days with no
retention. Branch `claude/handoff-box-disk-trade-recovery-47d67a` (fast-forwarded from
`codex/ucl-coverage`) carries:

- L72 `c245e53`: `TupleStore.retain` (rowid-bounded, batched, refuses evidence tables),
  `capture.prune_days`, `Supervisor.retain_once` every 15 min at `--retain-days 7`,
  `watchdog.disk_alerts` (PRESSURE at 80 % or < 3 days runway, CRITICAL < 5 GiB), and
  `DiskPressure` → exit 75 on the report tick under the runner's own floor.
- L74 `b135265`: a sizing decision is recorded only when it selects something or ends an
  executable run; the single-flight guard is unchanged; the table joins retention.
- `68d3c65`: a Polymarket FAK answered HTTP 400 "no orders found to match" is an UNFILLED zero.
- L73 `45c4d18`: descriptive hedge-slippage audit of SEKULIC and MORIYA (report only).

Full suite green. Expected steady state after release: ~1 GB/day database, ~7 GB/day frames,
~55 GB resident at the 7-day window. Without the release the volume refills in about a week.

## Immediate next step

**kill/live is latched again since 2026-09-12 01:19Z** (LAA @ WSH: 25 requested at 0.18, filled 32.14
at 0.14 because the venue sizes an immediate BUY by collateral; 7.14 unhedgeable, -$0.45). L83 on
the branch caps the order's collateral at contracts x the venue's own ask (from the L77 read), so a
fill at the ask is exactly the request and a walk up under-fills. Paste the branch head, then clear
the latch by hand: `bash ops/box/run.sh 'sudo -u janus rm /srv/janus/kill/live; ls /srv/janus/kill'`.
Also observed on that trade: the first leg's status took 6.4 s to resolve and the 25-contract hedge
found no Kalshi depth under its loss cap for 38 minutes (chased every 3 s, then every 30 s).

**L79–L81 (loop waste) are on the branch, not deployed.** L78 profiled the live loop: the sizing
sweep was 55 %, ladder work 21 %, and the heartbeat sweep grows with the slate. Offline on the
234-poller Sep 9 slate the full pipeline went 23.1 → 3.8 CPU s with identical evaluation rows and
selections. One paste covers L77 (first-leg confirmation) and L79–L81; it also installs orjson
into the lane venv: `bash ops/box/release.sh <branch head>`. Then L82: the same py-spy sample and
loop-lag p50/p99 on the next busy slate vs the L78 baseline. The instance size question is closed
unless L82 still shows saturation.

### Earlier (2026-09-12 01:06Z): the allowance + L76 paste landed (`c03033c`) and the operator cleared the
latch; the lane trades at 25 / $30 / $500 with a $2.50 allowance and a 3 s re-protect cadence.
`python3 ops/launchpad.py` is the dashboard (opens locally; the agent republishes the hosted copy).
L77 is on the branch and NOT deployed: one read of the venue's own book before a FAK send;
above the plan limit or without depth, nothing is sent (BOOK_MOVED, released). Paste
`bash ops/box/release.sh <branch head>` when no money is in flight; evaluate after 50 attempts
(fill rate among sends vs 2/30, BOOK_MOVED share, median a_confirm_ms). Then the instance size
(c7g.large) as the operator's billable call.

### Earlier (01:00Z): kill/live is latched since 2026-09-11 21:37Z** (VARILLA V WILD, genuine: 39 s unprotected at 25
contracts under a $1 allowance = four Kalshi ticks). Two changes are on the branch for one paste:
the allowance scales to $2.50 so $0.10 a contract binds at 25 (GATE row 2026-09-12), and L76,
the fast re-protect cadence (3 s for 60 s instead of the 30 s guard pass). Paste
`bash ops/box/release.sh <branch head>`, then clear the latch by hand:
`bash ops/box/run.sh 'sudo -u janus rm /srv/janus/kill/live; ls /srv/janus/kill'`.
Hedge-on-ack was NOT done: Polymarket acks a FAK as "delayed", so an ack proves no position.
The `pre_machine` stage swung 4-885 ms tonight: event-loop contention on the one vCPU, the
strongest case yet for c7g.large (operator's billable call).

### Earlier: F21, the size step the operator ordered (*"do it; 25 contracts, $30 per order, $500 a day"*):
`bash ops/box/release.sh <this branch's head>` from the operator's checkout of this branch. The
paste's default caps are now 30 / 25 / 500 / 168 h and the standing statement carries the new
numbers, so the re-signed override arms them; the taker wire's own ceiling moved to 25 / $30 in
lockstep. Breaker $25, hurdles, the $1 protection allowance (four Kalshi ticks at 25) and the
capital limits are unchanged. First three F21 covers are reconciled to venue cash and fills
before a fourth; the row closes at ten covers or the first STOP. One known flaky test
(`test_redemption_builder_cli_keeps_secure_value_off_argv`, a FIFO handshake race on macOS,
unrelated) is deselected when running the suite until it is fixed.

### Earlier: two pastes, in order. First `bash ops/box/release.sh 35d1171` (disk retention, sizing gate, disk
alert, FAK taxonomy). Second, L75 on the same branch: the hedge stops re-sending a price the
venue has answered zero at (one fresh-book read after a walked zero fill and before a budget
stall retry; no ceiling, cap, window or loss allowance moves; GATE_TO_LIVE 2026-09-11 row). Paste
the branch head once both are reviewed; one paste covers both if the first has not happened yet.

### Earlier note

The operator's release paste, `bash ops/box/release.sh <sha>` on this branch's head, when no
money is in flight (the paste checks). It re-signs the standing statement at the same caps; no
GATE row is needed because no cap, hurdle or hedge behaviour changes. After it: confirm
`[retain]` lines appear within 15 minutes, the watchdog is quiet on disk, and `df` stops
climbing. Then, at the operator's option, a one-off offline `VACUUM` to give back the 24 GB the
old sizing rows occupy (the file does not shrink on its own). L73's one supported candidate, a
one-tick-per-attempt hedge walk inside the unchanged budget and loss cap, is a separate
pre-registered row if pursued.
