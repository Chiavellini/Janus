# L148 verdict — FAILED its registered criterion; the write-through is withdrawn

**Outcome: `FAILED`.** The change was implemented, tested and put through two rounds of adversarial
review. The second round showed the registered success criterion — *"an independent adversarial
review of the diff finds no way for the write-through to overwrite newer websocket state"* — does not
hold. The change is reverted. Nothing was deployed.

The attempted code is kept verbatim in `attempted_write_through.patch`, with both review reports in
`review_round1.json` and `review_round2.json`.

## What was tried

When the Reconciler's REST read disagreed with a quiet replica, also write the REST ladder into the
stream's own ladder, `PolymarketStream.books`, so the correction would survive the next websocket
update (L146 R3).

## Round 1 — four defects in the first version, all introduced by it

Found by three reviewers and confirmed by two independent skeptics each, all by driving the real
classes:

| | Severity | Defect |
|---|---|---|
| **WT-1 / B1 / F2** | major | A second owner of the same token that never received a `book` stays unsynced, is never superseded, and always mismatches, so the write-through overwrote *newer* websocket depth. This is the normal production shape (capture watchlist plus game poller). |
| **WT-2** | minor | A replica invalidated for HEARTBEAT_LOST during the REST flight, likewise. |
| **M1** | minor | A malformed `book` after a drift recreates an *empty* ladder, defeating a presence-only check. |
| **F1** | minor | A REST read ahead of queued frames causes false top-of-book drift. It fails closed, but it is new noise. |

A corrected version then required three conditions before writing: no registration superseded, the
disagreement coming from a replica that was synced, and the stream's ladder still equal to what that
replica held. It closed WT-1, WT-2 and M1. Regression tests were shown to fail against the first
version and pass against the correction.

## Round 2 — the approach itself is unsound

The in-process guard held. One reviewer traced every path that can change the stream's ladder and
found each either supersedes the fetch or leaves no synced replica. The fix worked in every realistic
production shape, and the concern that it was too strict was refuted.

But two reviewers independently found the same failure, and both skeptics reproduced it (N1 /
WT-3): **the guard proves the stream's ladder did not change during the flight; it cannot prove the
REST response is newer than the websocket state already in it.** If REST lags the websocket, a level
the websocket already removed is written back. It is then relabelled `"ws"`, re-verified by every
agreeing update, and never re-checked because busy books are not due. Before the change, that stale
level lasted one message. After it, it lasts until a full websocket `book` event.

The trigger requires Polymarket's REST endpoint to lag its own websocket by roughly 15 s or more,
which has not been measured. But Polymarket's own client code says a throttled REST response is "a
stale quote wearing a fresh wall-clock timestamp" (`nodes/venue_polymarket/books.py:8-9`), and REST
carries no sequence number that would let the two be ordered. **So the write-through turns the L146
defect inside out rather than removing it.**

Round 2 also found (T1) that deleting any single one of the three guards left all 18 tests passing:
each regression test was caught by the superseded guard alone, not by the path its docstring named.

## Why this is withdrawn rather than patched again

Any write-through has to decide which of REST and the websocket is newer, and Polymarket gives no way
to decide. The follow-up, L149, stops making that decision. When REST disagrees with a synced replica,
it asks the websocket for a fresh full book — the same recovery the stream already uses for a
top-of-book drift. A websocket snapshot and the updates after it arrive in order on one stream, so
they cannot conflict, whichever way REST was wrong.

## What held, and is reused

- The regression scenarios WT-1, WT-2, M1 and F1 remain useful as tests of *any* fix.
- The confirmation that realistic formatting and size filtering never break ladder equality.
- The scope point from the spec: this is a data-integrity defect, not a profitability lever.

No change to `nodes/`, `grids/`, `kernel/` or `ops/` remains from this row. Nothing was deployed.
L146's recorded evidence was never edited, and its living test is back to its recorded state.
