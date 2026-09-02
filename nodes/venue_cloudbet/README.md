# venue_cloudbet

**Kind:** `source` (feed) + `execute` (trading) + `pure` (join)
**Implements:** `feed.py`, `trading.py`, `join.py`

Cloudbet sportsbook. **Currently parked** — the project pivoted its third venue to `venue_sxbet`.
Kept because `trading.py` is the reference implementation for the `execute` node kind.

## Position in the grid

```
Cloudbet Feed ──▶ [feed] ──▶ indicative quote ──╳ (non-executable)
Cloudbet Trading ──▶ [trading] ──▶ ACCEPTED ──▶ [join] ──▶ [cover]
```

**Upstream:** `nodes/entities`, `nodes/schedule_espn` (via `join.py`).
**Downstream:** `nodes/cover`.

## Contract

A feed quote is **indicative**. `Leg.executable` defaults `False` and only
`accepted_offer()` can set it. `join.py` additionally requires a terminal provider state
(`ACCEPTED`/`REJECTED`/`REDUCED`) before a leg reaches the cover screen.

`trading.py` is fail-closed and correct: `submit_enabled=False` by default, journal-before-POST,
no client-side retry after a timeout, idempotency by reference UUID, response identity verified.

## Failure modes

**The structural problem, and why the project moved to SX Bet.** Acceptance is a real,
irrevocable bet, and it must happen BEFORE `best_cover` can price the cover. So the mandated
sequence is: place the Cloudbet bet → then discover whether the arbitrage exists → then try the
CLOB leg. That is a naked directional position with hedge-completion risk, and there is no unwind
path anywhere in the codebase. `REDUCED` is a terminal accepted state, so a partial fill leaves a
thin leg that `best_cover` then rejects for depth — after you are filled.

No state machine removes this: it observes the book's option, it cannot take it away.

Secondary: the fee pin is `unverified`; the book is one synthetic ask level built from the
*displayed* max stake; entity resolution is text-only (no xref), unlike Kalshi/PM.

## Tests

`tests/test_feed.py`, `test_trading.py`, `test_fixtures.py`. Fixtures in `fixtures/` are
**hand-authored, not recorded** — see the replay-cassette work in the plan.
