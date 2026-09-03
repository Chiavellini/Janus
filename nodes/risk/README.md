# risk

**Kind:** `pure` (plus two state files and one journal table on the Janus volume)
**Implements:** `limits.py` + `limits.toml`, `kill.py`, `breaker.py`, `ledger.py`, `clearance.py`,
`gate.py`, `health.py`

**No order can be sent without a `RiskClearance`, and only `clear()` mints one.** This node
lands before any execution adapter exists so that an adapter with submit capability never exists
without its gate. A bool such as the parked Cloudbet client's `submit_enabled` can be flipped by
any caller; a clearance cannot be forged, is consumed by exactly one submit, expires in
`clearance_ttl_ms`, and carries the reservation it was cleared against and the sha of the limits
it was cleared under.

## Position in the grid

```
limits.toml (sha-pinned) ─┐
kill files ───────────────┼──▶ [risk.clear] ──▶ RiskClearance ──▶ exec adapter .submit(order, clearance)
loss breaker (latching) ──┤            │
exposure ledger ──────────┘            └──▶ Refused(code, detail) ──▶ opportunity record
                                                                     (BLOCKED_BALANCE, …)
mode gate: --mode + env + kill + creds + signed override ──▶ Mode, decided once at start
health: kill-file-present / breaker-latched / unreconciled-too-long ──▶ ops/watchdog
```

## The fail-closed order in `clear()`

MODE (below PAPER executes nothing) → KILL_SWITCH (all / live / venue / event / strategy) →
BREAKER (latched, breached now, or PnL unknown because a fill is UNCONFIRMED) → CLOCK_UNHEALTHY →
FEE_SCHEDULE → VENUE_DISCONNECTED → STALE_BOOK → MIN_PROFIT → MIN_RETURN → BALANCE (real-order
modes only; unconfirmed is a refusal) → the ledger's caps (single-flight per event, simultaneous
events, per-event notional, per-league, per-venue, total, unresolved). The first failure is the
answer; nothing is partially reserved.

## Limits

`limits.toml`, checked in. Absent is zero, never unlimited. LIMITED_LIVE caps come from the
signed override and may only be lower. The sha of the loaded bytes is pinned into every
clearance and must match the override's pin.

## Kill switches

Files under `/Volumes/Kilos/janus/kill/`: `all`, `live`, `venue-<v>`, `event-<id>`,
`strategy-<version>`. `touch` and `rm` are the whole interface. The breaker latches `live`; a
human deletes it.

## The breaker

Daily realized PnL over a FIFO of venue-authoritative fills. Any UNCONFIRMED fill makes the day's
PnL unknown, and unknown is closed until the fill is re-polled. A breach latches — across
restarts, in `kill/breaker.json` — and only `reset(by=<name>)` clears it.

## The ledger

Reservation before submission, release only after both venues reconcile, cross-venue exposure in
one place. Journaled to `capital_reservations`; open reservations reload at start, so
single-flight per event survives a restart. The watchdog alarms when one stays open too long.

## The mode gate

`resolve_mode()` decides once. `LIVE=1` in the environment of a non-live mode refuses to start;
`all` refuses anything ≥ PAPER; `live` refuses anything that risks capital; real-order modes need
credentials; capital-risking modes need `kill/arming_override.json` with the verbatim operator
statement, `signed_by`, the mode, the runner and limits shas, positive caps and an unexpired
`expires_utc`. No mode ever escalates.

## Tests

`tests/test_risk.py` — every refusal code reachable in order, the token's single use and expiry,
the breaker's unknown-is-closed and latch-across-restart, the ledger's caps and restart, the gate.
`ops/watchdog.selftest` drives the three risk alarms and asserts the quiet case stays quiet.
