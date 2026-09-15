# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-14 after L118–L120, on `claude/hedge-safety-and-speed`.

## Current state

`31e7a42` is deployed on the Mexico box. The lane and credentials are active, but `kill/live`
exists and entry is stopped. The lane is collecting market and refusal data; it is not placing
orders. Do not clear the kill until the exact disposition and legacy false-alarm rows below have
resolved under a complete guard pass.

The branch's functional candidate is `6bb2ebd` plus this handoff update. L118 adds an exact
append-only ownership disposition for the one operator-confirmed manual fill. L120 repairs one
schema-only invalidation of the historical legacy acknowledgement. The full suite is 1,601/1,601,
including the two previously flaky box tests on this run. Replay parity remains 1,093 rows at
`13e4fb08a76c920f` / `4f53cda18c2baa0c`.

No cap, hurdle, size, entry policy, protection decision, settlement rule, or kill condition changed.

## The Polymarket fill is operator-owned manual activity

The operator states verbatim:

- *"That position was placed manually on a hunch i got"*
- *"You should not worry about it"*

The exact fill remains:

- fill `99f8e62b-0684-446f-baa7-08bb785c3d30`
- order `0x32813cbb23731ca96e8830adb5118adb16367d4c0beecf2554040dec4eb3afa3`
- 666.666667 Yes shares at 0.1499999999
- token `5615282760875985231868508008056959876238536896643315063916840237042205273721`
- authoritative cash $104.25; confirmed taker trade; no Janus order or execution row

It is not a Janus cap breach, Janus P&L, or credential incident. It is still operationally relevant
because the correct guard treats every fill without Janus ownership as an orphan. Existing L56
dispositions required a settled archived proof and could not truthfully express an open manual
position.

L118's `open_external_manual` action binds every FillRecord field, the exact operator statements,
the authenticated cash-source hash and transaction, empty Janus order/event rows, and exact orphan
flag 587 to committed evidence at `5ca42d0`. Only that fill can match. A future fill sharing its
order, token, wallet, owner, price, side, or quantity remains an orphan. Confirmation appends
ownership only; it never changes the position, orders, P&L, accounting, flags, protection, or kill.

The prepared proposal is
`research/exec/2026-09-14_open-manual-fill-disposition/prepared.json`. The target-bound dry-run and
separate `--confirm` remain operator actions. After confirmation, a complete guard pass may resolve
only the exact ORPHAN_FILL flag; the retained kill is unchanged.

## The legacy alarm is a proved null-column migration

L119 compared the immutable acknowledgement for flag 211 to the current database field by field.
There is exactly one difference: `/settled/reservation/hedged_utc` is present now with `null` and
absent from the old snapshot. The acknowledgement record SHA verifies. No identity, quantity,
price, fee, cash, order/execution state, settlement, reservation value, flag, or violation changed.

The first ad-hoc classifier printed MATERIAL_STOP because it whitelisted the wrong path; the
registered criterion classifies the one null additive field as ADDITIVE_SCHEMA_ONLY. Both facts are
preserved in L119's result.

L120 accepts only stored-absent/current-null at that exact path, after recursive exact equality of
every other key, type, and value. A non-null `hedged_utc`, second added field, removal, type change,
or economic/incident change remains invalid and STOP. After deploy, a complete guard pass can close
the repeated exact migration false alarms. It never clears the kill or rewrites acknowledgement
evidence.

## Economics and the $100/day constraint

The operator now states verbatim: *"turnover is no constraint because we are specifically targeting
short horizon events (meaning 600 usd across both venues can probably result in turnovers over
10,000)"*.

That is the intended capital model, not current Janus behavior:

- The signed arm is $30/order, 25 contracts/leg, and $500 cumulative daily notional.
- `day_notional_usd()` counts filled-and-released reservations for the rest of the UTC day. Venue
  cash does not recycle under this cap today.
- Hedging ends only the per-event single-flight refusal. Capital remains committed until both
  venues are final and reconciliation releases the reservation.
- Open exposure is bounded more tightly by $250 unresolved/per-venue limits, and executions are
  globally serialized by one in-flight worker.

Do not change those semantics before positive q=10 unit economics and safe settlement release are
measured. If the evidence passes, a later dated GATE row can use the operator's words above and set
an explicit cumulative-turnover cap; the existing statement is not silently reinterpreted.

Economics remain unresolved:

- Twenty real covers: pooled P&L -$1.50, 10 losers; hedge slippage p50 3.04c/contract.
- Polymarket taker fee 0.828c and Kalshi hedge fee 1.187c against 0.67c median booked margin.
- No league has the 20 covers required for a defensible per-league reserve. ATP is 6/6 adverse;
  MLB has high slippage but positive realized P&L; pooling them is misleading.
- Maker entry might remove the PM fee, but it has one historical fill in seventeen attempts and
  needs L63's prospective 200-attempt cohort before any EV claim or policy change.
- The independently measured moneyline surface remains about $20/day gross. Reaching $100/day
  likely requires both positive unit economics and wider safe coverage, not only more capital.

The first post-`31e7a42` one-hour q=10 funnel reported 80 events seen, 72 co-listed, 74 games priced,
26 actionable prints, zero executions, and 31 KILL_SWITCH refusals. This is a short instrument check,
not a daily forecast. It proves the funnel recorder works while the retained kill prevents the real
conversion measurement.

## Immediate sequence

1. Push and operator-release the branch head once. The release is required because L118/L120 touch
   executable code; release remains the operator's paste.
2. On the deployed tree, operator runs the L118 disposition dry-run against
   `/srv/janus/tuples/tuples.sqlite`, reviews the exact facts/digest, then separately pastes the exact
   digest confirmation. The agent never runs `--confirm`.
3. Let one complete guard pass resolve exact ORPHAN_FILL 587 and the L120 migration false alarms.
   Inspect every unresolved flag, venue position, order, execution, reservation and stream before
   preparing any kill-clear line.
4. Only the operator clears the retained kill. The agent never clears, arms, changes mode, writes an
   override, or releases.
5. Resume the q=10 measurement cohort. Read L112 account-stream kinds, L113 funnel conversion, L114
   covers/event, and per-league net EV/Sharpe/slippage. Stop at the first registered safety STOP.
6. If unit economics are positive, decide maker-vs-taker and then design the explicit recyclable
   turnover policy. If they are not, exclude/reserve losing leagues before increasing turnover.

## Instrument traps that still apply

- `stages_json` `*_ms` are cumulative from `_t0`; difference per row. Exclude `guard_rerun` rows.
- `socket_health.frames` is cumulative; take deltas and treat decreases as reconnects.
- `BLOCKED_MATCH` is mostly the `single_venue` branch, not lost paired surface.
- `refusal_counts` is hot-path aggregation, not unique opportunities. An empty section means not
  yet ticked, not zero refusals.
- `PROFITABLE_UNEXECUTED` is material-change gated and per size rung. Always name the rung.
- The local archive DB is corrupt; replay uses the separate slate snapshot. Frames age out at seven
  days.
- Negative unconditional long-window hedge drift is not maker EV. L63 remains the maker authority.
