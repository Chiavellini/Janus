# game_poller

**Kind:** `pure` (event-driven actor)
**Implements:** `poller.py`

**One live game, four books, re-priced on every event.** The unit of work is a *game*, not a sweep.

## Position in the grid

```
              ┌──────────────┐
   slate ────▶│  supervisor  │ spawn on live, reap on settle
              └──────┬───────┘
                     ▼
  venue events ─▶ ┌──────────────────────────────────┐
   (routed)       │ game_poller                      │
                  │  4 × book_replica                │──▶ Evaluation[] ──▶ store / execution
                  │  rules_exhaustive proof (once)   │
                  │  fees + cover on every event     │
                  └──────────────────────────────────┘
```

**Upstream:** `nodes/book_replica`, the stream routers, `nodes/slate` (lifecycle).
**Downstream:** `nodes/store_tuples`, and eventually the execution path.

## Why it does not own its sockets

Kalshi authenticates one connection and multiplexes by `market_ticker`; Polymarket takes an
`assets_ids` list on one socket and supports mid-connection subscribe/unsubscribe. A socket per game
would mean fifteen authenticated connections *per venue*, wasting every handshake and hitting
connection limits for no gain.

Connections are shared infrastructure owned by the stream nodes. The poller **subscribes and is
fed**. It is still an actor — it owns state and a lifecycle — it simply is not a connection.

## Contract

`on_event(venue, market_id)` → one `Evaluation` per tested quantity, **including blocked ones**.
"We could not price this, and here is why" is the observation that separates *no edge* from
*no data*; a binary actionable/no-edge collapses them. `nodes/opportunity` maps each one to an
`OpportunityStatus`.

Nothing runs on a timer. A timer samples a market, and a market that moves 28¢ between samples
cannot be sampled into an answer.

## The three refusals

1. **Every replica must be SYNCED and fresh.** Three good replicas do not make a fourth
   trustworthy — one drifted book blocks the whole cover.
2. **Exhaustiveness is proven once, at spawn.** A game whose outcome set cannot be proven complete
   never gets a poller at all, so no subscription is spent on it. An EPL poller is `BLOCKED` before
   it opens a single book.

3. **A leg without its venue's fee schedule is blocked** (`FEE_SCHEDULE_MISSING`). `fee_params`
   comes from `nodes/discovery` — Kalshi's series multiplier and Polymarket's `feeSchedule` —
   never a constant. The lane charged 1.0× and 0.05 for a month; the venues said 0.5× and 0.05.

These are the ways a streaming arbitrage system lies to itself: a drifted replica invents a gap,
an incomplete outcome set turns "the draw is invisible" into a 31% return, and a fee constant
moves the hurdle without anyone noticing.

## States

`WARMING` (replicas syncing) → `WATCHING` (all four synced, pricing per event) → `DRAINING`.
`BLOCKED` is terminal and structural.

## Tests

`tests/test_poller.py` — 14 tests, including that a 3-way league never gets a poller, that one
desynced replica blocks the cover, that a same-venue cover is not counted as an opportunity,
and that a missing fee schedule blocks rather than defaults.

## Halt

`halt` is set by the supervisor for a reason the poller cannot see — an unhealthy clock today, a
kill switch or a venue disconnect later. Evaluations are still emitted, blocked as
`supervisor:halt:<reason>`, so an outage is recorded rather than silent.

## The complementary NO ladder (streaming lane, 2026-09-02)

A Kalshi event carries one market per participant, and NO on the other participant's market is
the same exposure as YES on this one — a different order book with its own depth and price,
carried in the same frames. Measured +67% to +563% takeable depth on live MLB; until now only
the retired REST lane read it. Each outcome gets a `("kalshi_no", outcome)` replica registered
on the *other* ticker with side `"no"`, offered as a third leg with `outcome_id "<ticker>:NO"`.
It is **extra depth, never a requirement**: a fault on it drops the leg and does not block the
cover the four primary books can price. `registrations()` is the one place the set of books a
game is priced from is defined; the supervisor and the replay harness both register through it.

REST-sourced books (after a Polymarket reconcile) are held to `max_rest_book_age_s`, stricter
than `max_book_age_s`.
