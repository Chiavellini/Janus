# L72 verdict — box disk retention and pre-full alert

## Criterion 1 — size breakdown and growth (read-only, 2026-09-11 17:31–17:43Z, lane stopped)

`dbstat` over the 27,362,902,016-byte `tuples.sqlite` (6,680,396 pages of 4,096 bytes, 734 s):

| object | bytes | share |
|---|---|---|
| sizing_decisions | 24,693,407,744 | 90.2 % |
| stream_evaluations (+ its two indexes) | 1,887,842,304 (+ 434,745,344) | 8.5 % |
| sizing_decisions_epoch (index) | 203,649,024 | 0.7 % |
| frontiers | 51,748,864 | 0.2 % |
| opportunity_transitions (+ index) | 33,943,552 (+ 27,811,840) | 0.2 % |
| everything else (orders, fills, executions, settlements, flags, reservations, events, …) | < 35 MB total | 0.1 % |
| quote_history, opportunity_history, latest_* | 4,096 each (empty) | 0 |

Rates in the 24 h before the lane died (rowid bounds by binary search): sizing_decisions
~1,949,906 rows (~21 GB/day at 10.8 KB average, 98 % the `candidates` array);
stream_evaluations ~1,890,683 rows (115-char legs, ~0.5 GB/day with indexes); socket_health
3,933 rows; order_events 534; execution_transitions 279. Frames per day (directory sizes):
Kalshi 1.74 → 2.28 → 2.52 GB, Polymarket 4.01 → 4.25 → 5.12 GB; Polymarket bytes are 96 %
`price_change`; the top 20 markets carry 82 % (Kalshi) and 92 % (Polymarket) of an hour's bytes;
capture-only tennis is 58 Kalshi + 26 Polymarket markets. Total ≈ 28 GB/day at the end, not the
15 GB/day estimated from the first three days.

Attribution: 99 % of the database growth is one table, and 97 % of its rows belong to blocked or
no-edge epochs. The four tables this row's criteria name are 8.6 % of the file. Retention of them
(criterion 2) is correct and cheap but would not have prevented the outage; the gate on
sizing_decisions is L74.

## Criteria 2–5

- Retention (`TupleStore.retain`, `capture.prune_days`, `Supervisor.retain_once`) deletes only
  rows/day-directories older than the window from the named series; the count test over a
  populated fixture shows every other table unchanged and a foreign table refused.
- Watchdog `disk_alerts`: PRESSURE at 80 % or under three days of projected runway from a 24 h
  sample file, CRITICAL under 5 GiB, root disk on the critical floor only; measured on a real run
  and skipped when the job-branch tests turn risk off.
- `Supervisor.on_report_tick` raises `DiskPressure` under the JANUS_MINFREE_KB floor (the runner's
  own 2 GB) and `main()` exits 75; tested with a stubbed usage reading, including an unreadable
  volume that is not a verdict.
- No VACUUM, no cap or hurdle change. Expected steady state after L74 at the 7-day window chosen
  by the operator: ~1 GB/day database, ~7 GB/day frames, ~55 GB resident on the 200 GB volume.

## Status

L72 PASS. Recovery on 2026-09-11 (operator-authorized): units stopped 17:15:55Z, snapshot
`snap-0cdf81181eae376ef` completed, volume `vol-0551c767981c71d03` 50 → 200 GB at 18:07Z,
`resize2fs` clean, 142 GB free. Nothing pruned; caps, kill files and the override untouched. The
code is committed on the branch and not deployed; the release is the operator's paste.
