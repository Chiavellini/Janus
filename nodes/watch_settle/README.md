# nodes/watch_settle — settlement timing for capture-only events

**Contract.** `record_watch(store, events, now)` upserts one `watch_events` row per Polymarket
event the capture-only watchlist sees: `first_seen_ts` and `start_utc` are written once and never
overwritten; `start_utc_last` and `last_seen_ts` refresh every pass. `resolve_pending(store, cl,
now)` asks Gamma about unresolved events whose start is at least an hour old and records the
winning label, `HALF` (closed at 0.5/0.5: a walkover or a match not played inside the venue's
window), or leaves the row open with a note. `delay_rows(store)` is what the forward row reads.

**Why forward.** No results archive keeps a match's scheduled date (ledger L39), so
`tennis.delayed_gt7d_rate` can only accrue from what the lane itself saw: the start time at first
sight against the time the market resolved.

**Caveats, stated here and in every row that reads the table.** `start_utc` is the first-seen
`gameStartTime` because Polymarket rewrites it in place on the same slug when a match moves.
`resolved_seen_ts` is the poll time, not the venue's resolution time; the daily cadence puts a
±24 h box around it.

**Position in the grid.** Written by `grids/live_stream` (`apply_watch`, on the loop, same
transaction as the slate); resolved by the daily oneshot
`research/sports/2026-09-04_tennis-delay-forward/measure.py` under `com.janus.watch-settle`.
Reads no price, claims no edge.
