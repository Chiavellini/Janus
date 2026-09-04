# replay

**Kind:** `pure` (given captured frames)
**Implements:** `replay.py`

Captured frames → the same stream handlers → the same pollers → the same record path → a scratch
database, then a row-for-row comparison against what the live lane wrote. This is GATE_TO_LIVE
step 4 made mechanical: the offline path *is* the live path minus the socket.

## Position in the grid

```
[capture] frames ──▶ [replay.Harness] ──▶ stream_kalshi.handle / stream_polymarket.handle
                                              └▶ book_replica ▶ game_poller ▶ opportunity.record_evaluation ▶ scratch store
                                                                                       │
                                            live stream_evaluations ◀── compare() ────┘
```

**Upstream:** `nodes/capture`, `nodes/discovery.load_specs` (the slate the supervisor spawned
from, persisted as `events.spec_json`). **Downstream:** the faithfulness check, the
reconnect/gap/partial-fill battery (plan P8), the slippage measurement (plan P4).

## Contract

`Harness(store)` — `spawn(game_id, spec)`, `feed(frame)`, `stats()`. `replay(harness, frames)`.
`compare(live, replayed, start_utc=, end_utc=)` → `{live_rows, replay_rows, mismatches, only_live,
only_replay}`; the bar is `mismatches == 0`.

The receive timestamp captured with each frame is the clock: the streams' `handle(..., now=)`
and the pollers' `evaluated_utc` see the same instant live and offline, so the change gate in
`store.evaluation` fires on the same rows.

## Failure modes

**`Harness.spawn` mirrors `grids/live_stream.Supervisor.reconcile`.** A node may not import a
grid, so the spawn branch is duplicated and must stay line-for-line identical until plan P7 moves
the supervisor's spawn into a node. A drift here is exactly the class of bug the parity check
exists to catch, and it will show up as mismatches.

`latency_ms` is a timing measurement (event arrival → decision) and is not comparable under
replay; `compare()` ignores it.

A frame that is not valid JSON on the Kalshi side is counted (`parse_errors`) and skipped; the
Polymarket handler already counts non-JSON as an error frame.

## Tests

`tests/test_replay.py` — a captured pair of games replays to rows, replay is deterministic, the
parity check reports zero mismatches against itself and names a mismatch when there is one.

## Offline execution (2026-09-03)

With `mode=PAPER_EXECUTION` (CLI `--mode OFFLINE_REPLAY`) the harness also runs the paper
coordinator: every `PROFITABLE_UNEXECUTED` evaluation is planned, cleared through `nodes/risk`
(with the harness's own kill directory and ledger) and executed against the replayed books on
the replayed clock, so `executions` / `orders` rows are reproducible row for row. This is the
pre-capital battery's substrate: a captured day replays into a full paper trading record.

**Coalescing boundary (2026-09-04).** The poller prices a game at most once per
`eval_interval_s` on quiet books (mirrored between the grid and this harness). A capture recorded
before the sha that introduced the window replays to different rows than the lane wrote then;
parity is claimed only across captures and rows produced under the same interval.
