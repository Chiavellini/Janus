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

Focused disposition and guard tests are 92/92. The combined execution and guard test directories
are green. Mutation coverage includes revoked, corrupt, wrong-target and cited-incident mismatch,
plus no flag/table, out-of-window, and an integration-style restart fetch. Full-suite and replay
parity checks are pending until L122 is integrated into the same release candidate. No box write,
kill clear, arm, mode, override, release, cap, hurdle, size, entry or accounting change occurred.
