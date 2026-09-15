# L123 verdict — guard failure fails closed

Status: **PASS; DEPLOYMENT PENDING**.

`Supervisor.guard_pass` now treats an unexpected `fetch` or `apply` exception, including an
incomplete `GuardSnapshot` (requiring `fills_read_complete is True`, no errors, and non-`None`
positions for every configured venue), as an unhealthy pass. Capital-risking Supervisors start
unhealthy until that first complete proof. A failure preserves the first live-kill writer, appends
`GUARD_FAILED` through the grid's thread-correct flag connection,
invalidates balance and fill snapshots, and leaves the process alive for protective handling. A
failure of either durable alarm path retains an in-memory entry stop; new entries are refused before
balance reads, clearance, and venue helpers. Even an incomplete pass queues any already-open naked
execution it found for protection before refusing new capital. A complete later pass restores only that in-memory
gate and never clears the kill or resolves the append-only flag evidence. Non-capital modes keep the
failure observable without acquiring live kill authority.

The focused callback suite passed **42/42**, including the real `asyncio.to_thread` fetch boundary,
fetch and apply failures, first-writer provenance, failed kill/flag persistence, stale snapshot
invalidation, startup refusal until a complete `GuardSnapshot` proof, incomplete-without-exception
handling, recovery, and protection hand-over. `git diff --check` passed.

The integrated release baseline passed **1,642/1,642**, excluding only the two pre-declared FIFO
races; the one FIFO failure in the unfiltered run passed immediately in isolation. Replay over
20,000 frames kept 1,093 evaluation rows, zero selections, and exact digests
`13e4fb08a76c920f / 4f53cda18c2baa0c`.

The pre-existing L121 grid hunk was retained and folded into the L123 handler: its direct live-kill
latch is now paired with durable `GUARD_FAILED`, independent alarm-failure handling, and the
in-memory gate. No kill was cleared, no live helper or order ran, and no capital or production state
was changed. The registered economics, eligibility, settlement, protection policy, and replay
digests (`13e4fb08a76c920f` / `4f53cda18c2baa0c`) are unchanged.

Expected EV effect: none per trade; the lane may refuse turnover while guard health is unavailable.
