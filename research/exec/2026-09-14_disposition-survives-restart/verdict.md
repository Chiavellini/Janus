# L121 local verdict — PASS; deployment confirmation pending

The measured deployed sequence contradicted L118's handoff claim. The manual fill occurred at
`1789409189`; the released process started at 2026-09-15 01:27:52 UTC, about seven hours later; the
exact disposition was appended as row 4 at `1789436244.278682`. After normal guard cycles,
ORPHAN_FILL 587 and its twenty already-acknowledged ORDER_OVERFILL companions remained unresolved.
The deployed guard's cursor starts only 120 seconds before its process, so it never re-read the
FillRecord required by `match_disposition`.

`recovery_fill_since` now examines only current disposition heads, fully revalidates each through
`match_disposition`, requires an exact snapshot match to a currently unresolved ORPHAN_FILL row,
and accepts only a fill older than the ordinary cursor and no more than 24 hours old. It changes
only the lower bound passed to both venue fill readers. The disposition is never substituted for
venue evidence; the venue must still return the exact FillRecord and the existing complete guard
pass must still resolve the exact cited IDs.

The first implementation was not releasable: an independent review reproduced
`sqlite3.ProgrammingError` because the loop-owned store connection was read inside
`asyncio.to_thread`. Recovery now uses the journal's worker-owned connection and the integration
test crosses the real thread boundary. Non-finite, negative, and over-24-hour window overrides are
rejected; candidate rows are filtered by exact unresolved incident IDs; and recovery stops
fail-closed above a hard 500-incident work bound rather than repeatedly scanning an unbounded
backlog. Malformed flags and database errors remain visible and latch live entry; corrupt,
revoked, stale, wrong-target, and cited-incident-mismatch evidence is ignored without authority.

Focused disposition and guard tests are 100/100. The integrated release baseline passed
1,642/1,642 excluding only the two pre-declared FIFO races; the one FIFO failure in an unfiltered
run passed immediately in isolation. Replay over 20,000 frames kept 1,093 evaluation rows, zero
selections, and exact digests 13e4fb08a76c920f / 4f53cda18c2baa0c. No box write, kill clear, arm,
mode, override, release, cap, hurdle, size, entry or accounting change occurred.
