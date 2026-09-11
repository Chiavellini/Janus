# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.*

Updated 2026-09-11 20:20Z after the disk-full recovery.

## Current state

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

The operator's release paste, `bash ops/box/release.sh <sha>` on this branch's head, when no
money is in flight (the paste checks). It re-signs the standing statement at the same caps; no
GATE row is needed because no cap, hurdle or hedge behaviour changes. After it: confirm
`[retain]` lines appear within 15 minutes, the watchdog is quiet on disk, and `df` stops
climbing. Then, at the operator's option, a one-off offline `VACUUM` to give back the 24 GB the
old sizing rows occupy (the file does not shrink on its own). L73's one supported candidate, a
one-tick-per-attempt hedge walk inside the unchanged budget and loss cap, is a separate
pre-registered row if pursued.
