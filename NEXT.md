# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-10 for the F20 bounded-taker release candidate.

## Where it stands

The Mexico box (`i-0a8c073c72dcdae11`, `mx-central-1a`) still runs production commit `6c694f1`
under `LIMITED_LIVE`, but a false maker-terminality `kill/live` currently blocks new orders. A
fresh read-only audit found zero open Polymarket orders, zero unresolved maker markers, zero active
unreleased executions, and zero material unhedged exposure. All three live streams were connected.
The lane was evaluating opportunities; its 13 current-day execution attempts were maker orders that
either rested without filling or were rejected for crossing, and none filled.

F18's maker-entry policy is superseded by the operator's 2026-09-10 instruction to restore taker
entry. F19 (a proposed longer maker rest) was preregistered but closed without deployment or data.
The local F20 candidate uses the immediately executable two-leg plan again. The Polymarket entry is
signed only through a dedicated FAK/FOK path hard-bounded to 10 requested contracts and $12
collateral, even if a future signed arm is larger. A price-improvement excess strictly below one
contract is retained as the actual fill, hedged, and explicitly audited; an excess of one contract
or more keeps the old fail-closed overfill stop. The generic immediate BUY signer remains blocked.

The repeated false kill race is repaired by honoring the Polymarket adapter's stable-terminal proof
window after cancel. The release path can clear only the exact maker false-latch whose digest it
captured at the start, and only while the lane is stopped after terminal-zero and global-money-quiet
proof. It archives the original kill and proof before removal, verifies three fresh post-start
streams, and restores the kill and restarts the lane if any later step fails. It cannot clear an
operator stop, changed kill, fill, open order, unresolved marker, or exposure.

Automatic Polymarket redemption is included. A separate pinned `polymarket-client==0.9.0` runtime
runs every ten minutes, selects only positive-value `redeemable=true` positions, persists PREPARED
before submission, recovers an ambiguous wire by exact relayer metadata, and requires both onchain
confirmation and fresh position disappearance before COMPLETE. Zero-value remnants are untouched.
The local operator release provisions the builder credential into SSM if and only if the complete
set is absent; partial credentials fail closed and secrets are never printed.

The arm remains **$12 combined stake, 10 contracts per leg requested, $250 committed daily
notional, $25 realized-loss breaker, $0.10 minimum net profit, 1% locked return, $1 maximum
protection loss, `protect_auto=true`, `unwind_enabled=false`**. This release changes execution
urgency, not the outer capital envelope.

## Verification

The complete repository suite passes at 100%. Focused bounded-taker, coordinator, guard,
redemption, false-clear, release, credential, watchdog, and grid tests pass. Shell syntax,
`compileall`, watchdog self-test, and `git diff --check` pass. The official Polymarket 0.9.0 wheel
was inspected for the `SecureClient.create`, `redeem_positions`, position pagination, and relayer
transaction polling contracts; the public relayer documentation confirms that recent transactions
are returned with caller metadata for crash recovery.

## Immediate next step

Commit and push the F20 candidate, then have the operator run the one release paste printed by the
committing task. That paste provisions redemption authority, checks out the exact SHA without an
early restart, installs the pinned redemption runtime and timer, re-signs the unchanged arm,
restarts `LIMITED_LIVE`, performs only the exact false-maker-latch recovery, verifies fresh market
and user streams, and immediately runs redemption.

After release, verify the command ends with `LIVE_CLEAR_COMPLETE`, an active redemption timer, and
a successful redemption summary. Then inspect the first bounded-taker cover for decision-to-order,
first-fill-to-hedge, exact venue fills, fees, and locked/realized P&L. C++ is not the next change:
the observed missed fills came from the maker-rest policy and network/order lifecycle, not measured
Python compute in the order path. Optimize or rewrite only the stage that fresh F20 latency evidence
shows is actually limiting execution.
