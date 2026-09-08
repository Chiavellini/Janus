# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-08 23:18 UTC from the F12 box health pass. CHECKLIST.md is the state list;
CHANGELOG.md and the F rows in `snooping_ledger.md` are the append-only history.

## Where it stands

**The lane is LIMITED_LIVE and healthy on the Mexico box** (`i-0a8c073c72dcdae11`,
`mx-central-1a`) on executable commit `ca398be`. The service, credentials, census and watchdog
timer are enabled and active; the lane has zero systemd restarts. It has 82 co-listed pollers and
all required feeds are connected: Kalshi public, Polymarket public, and Polymarket's authenticated
account order/trade stream. The latest persisted account-stream row had 12 frames, zero errors and
sub-second age. The box watchdog says all registered jobs healthy. No laptop process or operator
connection is in the runtime path.

F12 keeps the existing arm: **$12 combined stake, 10 contracts per leg, $250 committed daily
notional, $25 realized-loss breaker, $0.10 minimum net profit, 1% locked return,
`protect_auto=true`, `unwind_enabled=false`**. The override expires 2026-09-15 23:12Z. There is no
live kill file. Real entry fails closed unless both public streams and the authenticated account
stream are connected; an unresolved submission still creates the box-local kill before a retry.

Today's authoritative execution record has 35 attempts and three executions with a real first
fill. The 01:39Z ATP fill was an unhedged F8 defect and later redeemed +$4.3754 by luck; it is not
an arbitrage result. Two later BUR @ WXM covers are fully paired: Polymarket 10.15625 @ 0.63 with
Kalshi 10.16 @ 0.19, and Polymarket 10 @ 0.78 with Kalshi 10 @ 0.01. Both have `unhedged=0`; their
two capital reservations remain open correctly while Polymarket resolution is pending. The latest
24-hour guard has zero unconfirmed orders, orphans, mismatches or positions to protect.

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

F12 is the fresh forward clock. Hand-reconcile its first three valid covers before the fourth and
stop on any fill not protected within 30 seconds, orphan, mismatch, missing reservation, store
error after submission, fee above pin or breaker. Do not raise a cap or weaken a price/settlement
hurdle without a new dated GATE row. The next useful economic evidence is the live fill rate and
realized net EV of these small entries; zero-fill FAKs are legitimate venue outcomes, not execution
failures.
