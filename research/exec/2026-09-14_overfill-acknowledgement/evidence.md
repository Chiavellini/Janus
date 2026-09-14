# Frozen evidence for the historical order-overfill acknowledgement

Date: 2026-09-14. Read-only, from the box's own `orders`, `executions`, `execution_settlements` and
`capital_reservations` under the deployed sha `9387297`. This file is the immutable supporting
source cited by each acknowledgement entry; the binding snapshots are taken by
`nodes/execution/overfill_ack.py` from the database at prepare time, not from here.

## Why an acknowledgement is needed at all

`PositionGuard._overfill_candidates` scans `orders` for `filled_contracts > contracts` on every
pass, and its only dedupe is an in-memory set initialised empty at construction. So on **every
fresh process** it re-finds every historical overfill and re-latches `kill/live` within one pass.
A release paste therefore restarts the lane straight back into a halt, and has done repeatedly.
The acknowledgement row is the durable fix: it is append-only, digest-confirmed, and survives
restarts.

`prepare_from_database` refuses unless the proposal covers **every** candidate and **every**
unresolved `ORDER_OVERFILL` flag, which is why all seven appear below rather than only the two
named in earlier handoffs.

## What an overfill is here, and why it is not a defect to repair

The Polymarket CLOB BUY wire bounds **collateral, not received shares**
(`nodes/exec_polymarket/quantity.py`): `OrderArgsV2.size` becomes `takerAmount`, which the exchange
treats as a *minimum* at full maker-budget consumption. Price improvement therefore returns surplus
shares. F20 (GATE row 2026-09-10) records the operator accepting this limitation explicitly. The
quantity on the row is the venue's, and is authoritative; nothing below repairs a position or an
accounting figure.

## The seven candidates

Every one satisfies `settled_snapshot`: a single identified real order with a venue order id, not
open, cash accounting complete, owned by exactly one execution in state `RECONCILED` and released,
with a released reservation of matching identity and exactly one released settlement.

| client order id | asked | venue filled | excess | improvement | owning execution |
|---|---|---|---|---|---|
| `9d36d91cf99e46d3` | 10.00 | 10.175400 | 0.1754 | 1.75% | settled, reconciled |
| `17dd8b4ab307494f` | 10.00 | 10.156200 | 0.1562 | 1.56% | settled, reconciled |
| `40797bee0f17449c` | 10.00 | 10.166700 | 0.1667 | 1.67% | settled, reconciled |
| `e9a2cddfc6284424` | 5.00 | 5.241900 | 0.2419 | 4.84% | settled, reconciled |
| `a38ae7929a5a4fdd` | 5.00 | 7.769200 | 2.7692 | 55.38% | settled, reconciled |
| `7d6ecc39eeb7429a` | 25.00 | 26.562500 | 1.5625 | 6.25% | `770130525086456e`, RECONCILED |
| `0429ef246257415c` | 25.00 | 32.142858 | 7.1429 | 28.57% | `0dfc6df32bc646e9`, RECONCILED |

Four further overfilled orders — `b80fd489eba14f05`, `221d6cbab5554dc8`, `9aaeedd016444257`,
`580e967b31194f9d` — are **not** candidates: each is an operator-accepted bounded-taker residual
under one contract of excess (L65/F20/F21), which the guard exempts and
`bounded_taker_residual()` recognises. They are listed here only so the exclusion is on the record.

## The unresolved flag rows bound by this acknowledgement

Thirteen, all `ORDER_OVERFILL`, attributed by the client order id in their own detail text:

- `0429ef246257415c` — flag ids **544, 549, 550, 551, 552, 553, 560, 572, 575, 585** (ten; one per
  process restart that re-found it, which is the failure this acknowledgement ends)
- `7d6ecc39eeb7429a` — flag ids **578, 579, 586**

The other five candidates carry no unresolved flag: they were raised and resolved before the
current flag population, or arose on a path that recorded the residual without latching.

## What this does not do

It does not change a position, a balance, a fill quantity, an accounting figure, a cap or a
hurdle. It records that these settled overfills are known, attributed and accepted, so the guard
stops re-latching the live kill on them at every restart. Any *new* overfill after this row is
latched exactly as before.
