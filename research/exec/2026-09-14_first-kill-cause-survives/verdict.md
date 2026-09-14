# L117 verdict — the first kill cause now survives

Date: 2026-09-14. PASS against the immutable criteria in `spec.yaml`.

## Box evidence

The confirmed Polymarket fill `99f8e62b-0684-446f-baa7-08bb785c3d30` was observed at
2026-09-14 18:06:29Z and flagged `ORPHAN_FILL` at 18:06:59Z. It is a 666.666667-share taker BUY
on a Federal Reserve market with authoritative cash of $104.25 and no matching Janus order row.

At inspection time `/srv/janus/kill/live` instead contained
`LEGACY_INCIDENT_ACK_INVALID flag=211` with `latched_utc=1789421072.5778997` and an mtime of
21:24:32Z. The file was born the previous day. `KillSwitches.latch()` had therefore rewritten an
already-present kill's reason and time; the append-only `lane_flags` row was the only surviving
operator-readable record of the orphan cause.

## Repair

`KillSwitches.latch()` now opens the target with exclusive creation. The first writer creates the
same JSON record as before. Every later writer receives the same path without changing the file.
This is atomic across concurrent callers and preserves an empty file created by the operator.

No kill condition or enforcement input changed: existence of the file is still the switch. No cap,
hurdle, size, allowance, protection decision, or order path changed.

## Verification

- Focused risk suite: 37 passed.
- Full suite: passed, including the two known-flaky box FIFO tests on this run.
- Replay: 1,093 evaluation rows; row digest `13e4fb08a76c920f`; selection digest
  `4f53cda18c2baa0c`.

The deployed `5053154` does not contain this repair. It requires the operator's next ordinary
release paste because `nodes/risk/kill.py` is inside the pinned executable tree. The current kill
was not edited or cleared.
