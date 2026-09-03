# nodes/cover_cost — the recorded cover-cost distribution

**Contract.** Reads `stream_evaluations`, `events`, `event_transitions` and `socket_health` from the
tuple store and returns, per (league, quantity, game phase, flapping-or-clean) cell: dwell-weighted
status shares, blocked-reason shares with the raw fault tail kept, the priced share, the share
within 1¢ of actionable, the profitable share, and dwell-weighted cost quantiles; plus an audit of
every `PROFITABLE_UNEXECUTED` row (phase, flapping, a stale-family fault on the same game within
60 s) and the `n` for the forward paper row (GATE step 7).

**Why dwell.** The store writes a row on a material change (status, 0.1¢ of cost, or a 15 s
heartbeat), so rows are a carried-forward series. Counting them would weight a jittery book over a
steady one. Each row holds until the next row of the same (game, quantity), capped at 60 s; the raw
row count is reported beside every weighted figure.

**Phases.** `pre` before `events.start_utc`; `end` the last 600 s before the game's end, where the
end is the first `post` transition in `event_transitions` or, when the slate reaped the game first,
its last evaluation row; `post` after a recorded post transition; `in` otherwise. Today's only
sub-par covers were closing books (HANDOFF 2026-09-03 §7), which is why `end` is its own cell.

**Flapping.** An interval between two consecutive `socket_health` rows of a venue where the later
row is disconnected or its error count rose, plus windows declared in the research row's spec for
loops that pre-date the reconnect counter. Rows inside are kept and reported apart, never dropped.

**Failure modes.** Rows outside the `OpportunityStatus` vocabulary (the retired REST lane's) are
excluded by definition and counted. A game with no `events` row has no `pre` phase. The `n` is
declared (30) when fewer than five in-play, clean actionable rows exist, and the verdict says so.

**Position in the grid.** A node. Driven by
`research/sports/2026-09-04_cover-cost-distribution/measure.py` (ledger L36); imports the kernel
and nothing above it. Reads no outcome, claims no edge.
