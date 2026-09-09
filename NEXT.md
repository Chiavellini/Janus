# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-08 23:18 UTC from the F12 box health pass. CHECKLIST.md is the state list;
CHANGELOG.md and the F rows in `snooping_ledger.md` are the append-only history.

## Where it stands

**F13 is LIMITED_LIVE and healthy on the Mexico box** (`i-0a8c073c72dcdae11`,
`mx-central-1a`) on executable commit `3358411`, code tree `c37db15804f4abb5`. It started
2026-09-09 01:50:14Z after the full suite passed and the F12 STOP was repaired. The watchdog is
fully green; Kalshi public, Polymarket public and the authenticated Polymarket account stream are
connected with zero stream errors. Runtime, credentials, data, guard, kill sync, restart and
watchdog remain box-local; no laptop or operator connection is in the runtime path.

The arm is unchanged: **$12 combined stake, 10 contracts per leg, $250 committed daily notional,
$25 realized-loss breaker, $0.10 minimum net profit, 1% locked return, $1 maximum protection loss,
`protect_auto=true`, `unwind_enabled=false`**. It expires 2026-09-16 01:45Z. Local and SSM live
kills are absent. Real entry fails closed unless all three streams are connected; an unresolved
submission latches locally. A live latch blocks first legs but no longer prevents the authorized
guard process from restarting and protecting an already-held execution.

Authoritative real-money record: the historical ATP naked leg settled +$4.25074 after its actual
PM fee (directional luck, not arbitrage); BUR-WXM covers settled +$1.59954 and +$2.00720 after both
venue fees; MIN-DET settled +$1.11975. F12's ARI-KC first leg was protected after repair with PM
10 @ 0.63 and Kalshi KC-NO 10 @ 0.43; it is exactly paired and locks a $0.88815 cash loss
($0.94815 including the registered settlement reserve), still awaiting venue results. No other
Janus reservation is open. The latest 24-hour guard has zero unconfirmed orders, orphans,
mismatches or positions to protect.

## Why paper looked busy and live did not

Paper execution consumes the decision book synchronously, with no network arrival delay, venue
minimum rejection, CLOB `delayed` acknowledgement or eventual-consistency gap. Most paper covers
were also q=25 or q=100; the live $12 arm rejects those rungs before the wire and admits only the
smallest executable profitable size. Those are different fill populations, so paper's 34 hedged
covers are plumbing evidence, not a live fill-rate estimate.

F8's 19 failures separated into 10 legacy FOK no-fills, five FAK delayed/not-found zero-fills, two
manually reconciled zero-fill unknown/stuck rows, one Polymarket $1-minimum rejection and one
clearance expiry. The repairs now on the box remove entry-time balance round trips, keep
`not_found` ambiguous until durable order/trade proof, join exact client/order ids, rebuild lifetime
fills, reopen reservations on late fills, account committed notional correctly, persist each
venue's settlement separately, and latch locally on a remaining unknown. F12 closes the last
several-minute blind spot by consuming authenticated account events: MATCHED drives the exact-size
hedge immediately and a terminal immediate-order cancellation closes as zero-fill. Settlement now
also refreshes average price and fees from the durable venue-fill FIFO even when the acknowledged
quantity already agreed.

## What remains

F13 is the fresh forward clock (zero executions at start). Hand-reconcile its first three valid
covers before the fourth and stop on any fill not protected within 30 seconds, orphan, mismatch,
missing reservation, store error after submission, fee above pin or breaker. Do not raise a cap,
enable unwind or weaken a price/settlement hurdle without a new dated GATE row. The next useful
economic evidence is the live fill rate and realized net EV of these small entries; an
authoritative FAK zero-fill is a legitimate venue outcome, not an execution failure.
