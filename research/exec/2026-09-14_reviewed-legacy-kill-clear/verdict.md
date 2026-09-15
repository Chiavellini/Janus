# L122 verdict — exact reviewed legacy kill clear

Status: **PASS LOCALLY; OPERATOR RELEASE PENDING**.

The new helper accepts only the exact full SHA256 and reason of the retained flag-211 legacy
invalidation, plus the full deployed Git SHA. It revalidates `match_incident(211)`, required table
and column schema, both venues' journaled order state, all unreleased executions and reservations,
and every material unresolved flag including `GUARD_FAILED`. Missing schema is a stop.

The operator path stops the lane, runs a strict real Kalshi/Polymarket guard pass with the retained
kill and credential environment, warms all three sockets under that kill, stops again, and repeats
the strict guard. Exact resolution findings from the first pass are allowed, but incomplete fills,
unreadable venue positions, errors, orphans, mismatches, protection work, and active material
findings are not. Activation repeats the database/incident proof, verifies the opened kill inode
and digest across an atomic quarantine rename, and publishes exact bytes to a fresh exclusive audit
directory. Failure restores only into an absent live path, never over a new latch, and leaves the
lane stopped. A new process starts entry-unhealthy under L123 until its own complete guard pass.

The focused operator/box/guard suite passed **37/37**; shell syntax and `git diff --check` passed.
The full release baseline passed **1,642/1,642**, excluding only the two pre-declared FIFO races;
the one FIFO failure from the unfiltered run passed immediately in isolation. Replay over 20,000
frames kept 1,093 evaluation rows, zero selections, and exact digests
`13e4fb08a76c920f / 4f53cda18c2baa0c`.

No helper, kill clear, arm, mode, override, release, or order was run by an agent. Expected EV
effect is none per trade: this is the auditable transition needed before the already-signed q=10
economics cohort can collect evidence.
