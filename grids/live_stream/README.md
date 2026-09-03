# grids/live_stream — the supervisor

```bash
python3 -m grids.live_stream.grid --leagues mlb --pre-hours 2
python3 -m grids.live_stream.grid --self-test          # how many co-listed live games right now
```

**One poller per live co-listed game, fed by two shared sockets.** This is the thing that decides
what exists: it rebuilds the slate on a slow clock, spawns a `nodes/game_poller` for every game
live and co-listed on both venues, registers that poller's replicas with the sockets, and reaps the
poller when the game settles.

## Shape

```
   slate (nodes/discovery: schedule + match + tokens + each venue's fee schedule)
                        │  spawn / reap
                        ▼
   ┌──────────────────────────────────────────────┐
   │  Supervisor                                  │
   │    live: game_id -> GamePoller               │
   └───────┬──────────────────────────────┬───────┘
           │ register replicas            │
           ▼                              ▼
   [stream_kalshi]  one socket    [stream_polymarket]  one socket
           └──────────► book_replica ◄────┘
                            │ on every event
                            ▼
                    fees → cover → capacity
                            │
                            ▼
                 store.evaluation()  (change-gated)
```

Connections are **infrastructure**; pollers are **actors**. Kalshi authenticates one socket and
multiplexes by `market_ticker`, Polymarket takes an `assets_ids` list and supports mid-connection
subscribe/unsubscribe — so a game starting or ending costs a subscription frame, not a reconnect.

## What it writes, and what it deliberately does not

Every evaluation is offered to `stream_evaluations`, which gates on a **material** move in cover
cost (0.1¢, a tenth of a Kalshi tick) or a heartbeat. At ~200 evaluations a second across a handful
of games, writing all of them would cost a gigabyte a day of near-identical rows and answer nothing
that carrying the series forward does not.

**Blocked evaluations are written too**, with the reason. That is what separates *no edge* from
*no data* — and it is the channel that was a header-only CSV all August. A first run over 9 games
recorded 162 priced rows alongside `HASH_MISMATCH` (Polymarket drift, correctly blocking),
`NOT_SYNCED`, `HEARTBEAT_LOST` and `STALE`. Since 2026-09-02 the `status` column is a
`kernel.schema.OpportunityStatus` (`nodes/opportunity.status_for`) and `blocked_by` keeps the
fine-grained reason: `BLOCKED_STALE`, `BLOCKED_DEPTH`, `BLOCKED_FEES`, `BLOCKED_RULES`, `NO_EDGE`,
`DISCOVERED` (positive but under the hurdle) and `PROFITABLE_UNEXECUTED` are never collapsed.

When a cover is `PROFITABLE_UNEXECUTED`, the size frontier is solved **on the same books that
produced the edge** — computing it from the replicas a moment later would price a different instant, because the
books move in milliseconds.

## Refusals inherited from the nodes

A game whose outcome set cannot be proven exhaustive never gets a poller, so no subscription is
spent on it. A cover is never priced unless all four replicas are `SYNCED` and inside the freshness
bound. Neither is re-implemented here.

## Operational

Start/finish rows to `runs/index.jsonl` (deferring to `JANUS_RUN_ID` when `ops/run_node.sh` set
it), SIGTERM drains rather than dying mid-write, and a failed discovery pass is reported and
retried rather than taking the loop down.

## Health and the clock

On every report tick the supervisor writes both sockets' `stats()` to `socket_health` and checks
each socket's clock monitor. If either venue's stamps run more than the bound away from local
receipt, every poller is halted (`supervisor:halt:CLOCK_UNHEALTHY`) until the skew clears.

## Depth backstop

A `nodes/stream_polymarket.Reconciler` task runs beside the sockets (`--reconcile-period`),
fetching `/book` for quiet Polymarket replicas and reconciling them. Its counters
(`reconciles`, `rest_drift`) ride along in the Polymarket `stats()` and so in `socket_health`.
