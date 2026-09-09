# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-09 03:43 UTC from the F15 box health and account-reconciliation pass. CHECKLIST.md is the state list;
CHANGELOG.md and the F rows in `snooping_ledger.md` are the append-only history.

## Where it stands

**F15 is LIMITED_LIVE and healthy on the Mexico box** (`i-0a8c073c72dcdae11`,
`mx-central-1a`) on executable commit `64f54c7`, code tree `0fd7f6eae72cfb98`. It started
2026-09-09 03:42:30Z after the full suite passed and the quantity-preserving order repair was registered. The watchdog is
fully green; Kalshi public, Polymarket public and the authenticated Polymarket account stream are
connected with zero stream errors. Runtime, credentials, data, guard, kill sync, restart and
watchdog remain box-local; no laptop or operator connection is in the runtime path.

The arm is unchanged: **$12 combined stake, 10 contracts per leg, $250 committed daily notional,
$25 realized-loss breaker, $0.10 minimum net profit, 1% locked return, $1 maximum protection loss,
`protect_auto=true`, `unwind_enabled=false`**. It expires 2026-09-16 03:39Z. Local and SSM live
kills are absent. Real entry fails closed unless all three streams are connected; an unresolved
submission latches locally. A live latch blocks first legs but no longer prevents the authorized
guard process from restarting and protecting an already-held execution.

Authoritative real-money record: the historical ATP naked leg settled +$4.25074 after its actual
PM fee (directional luck, not arbitrage); BUR-WXM covers settled +$1.59954 and +$2.00720 after both
venue fees; MIN-DET settled +$1.11975. F12's ARI-KC cover settled -$0.88815 after protection at
PM 10 @ 0.63 and Kalshi KC-NO 10 @ 0.43. F14's one CHC-MIL cover settled +$0.116065; its
collateral-sized PM order requested 5 but bought 7.769231 after price improvement, so F14 stopped
and F15 restored a share-sized wire order before resuming. F13's one
STL-SF cover holds PM 5.241936 @ 0.62 and Kalshi 5.24 @ 0.40; it locks at least a $0.25585 loss,
with 0.001936 share below the registered venue dust. Combined corrected live P&L is +$8.20515
settled and +$7.94929 including the one open minimum outcome; +$3.95441 is settled hedged-cover
P&L and +$4.25074 is the historical ATP directional exception. Latest direct cash is Kalshi
$266.9893 and Polymarket $310.08128; BUR and MIN claims are redeemed. Cash plus STL's conservative
$5.24 guaranteed payout is $582.31058, +$0.09182 from the comparable Sep 8 close.
The guard has zero unconfirmed orders, orphans, mismatches, material unhedged exposure or positions
to protect. Actual daily committed notional is $32.91819 with $5.49585 still open; zero-fill rows contribute $0.

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
quantity already agreed. F14 additionally encodes immediate PM BUYs as cent-exact collateral
market orders, grows open reservations to authoritative chased cost, restates released fills to
exact spent capital and revises already-settled P&L through an append-only audit row. F15 keeps
the FAK/FOK share-sized: wire quantity and price can only move down to a cent-exact maker pair,
so price improvement cannot increase contracts beyond the request.

## What remains

F15 is the fresh forward clock (zero executions at its 03:42:30Z start). Hand-reconcile its first three valid
covers before the fourth and stop on any fill not protected within 30 seconds, orphan, mismatch,
missing reservation, store error after submission, fee above pin or breaker. Do not raise a cap,
enable unwind or weaken a price/settlement hurdle without a new dated GATE row. The next useful
economic evidence is the live fill rate and realized net EV of these small entries; an
authoritative FAK zero-fill is a legitimate venue outcome, not an execution failure.
