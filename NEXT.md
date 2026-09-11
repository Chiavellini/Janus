# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.*

Updated 2026-09-10 for the final F20 recovery/release candidate.

## Current state

Production runs `d3237fa` on the Mexico box in `LIMITED_LIVE`, but `/srv/janus/kill/live` remains
present and blocks new entries. The lane is active and all three streams are connected. There are
zero open, unconfirmed or cash-pending orders, zero unreleased executions/reservations, and no
execution after the single accidental F20 taker flight. That flight is fully RECONCILED/released at
-$0.014932. `ORDER_PERSISTENCE_FAILED` flag 530 remains unresolved until the new guard proves it.

The executable repair is `42ac10cd67af9b228930481ee3fd8ea4226f72ac`. It fixes the SQLite
writer-upgrade race, exact incident resolution, fail-closed retained-kill warm-up, SSM failure
propagation, redemption interpreter selection/error visibility, and the redemption watchdog cadence.
The candidate redemption SDK authenticated read-only on the box and sees two positive redeemable
conditions. No redemption was submitted during development.

The system is already taker-first under F20. The observed local execution stages were fast
(3.14 ms pre-machine, 33.22 ms database, 59.08 ms evaluation-to-execution); venue acknowledgement,
settled quantity and five missed Kalshi hedge IOCs dominated the 4.77-second completion. A C++
rewrite is not supported by this evidence.

Caps and policy remain unchanged: $12 combined stake, 10 requested contracts per leg, $250 daily
committed notional, $25 realized-loss breaker, $0.10 minimum net profit, 1% locked return, $1 maximum
protection loss, `protect_auto=true`, and `unwind_enabled=false`. The adverse first observation is
not evidence to lift them.

## Verification

The complete repository suite, focused execution/recovery/release tests, watchdog selftest,
compileall, YAML parsing, shell syntax and `git diff --check` pass. Actual-box read-only checks prove
the exact incident's seven terminal owned orders, two final FIFOs, bounded PM excess, released
settlement/reservation, current cash quiet, fresh streams, candidate unit syntax and pinned SDK.

## Immediate next step

Push the final documentation commit and have the operator run exactly one release paste with that
SHA and the existing `JANUS_ARM_CAPS='12 10 250 168'`. The release first restarts under the retained
kill, gives the fresh guard time to resolve only flag 530, refuses to proceed if any material flag
remains, then audits the original false-maker latch while stopped, warms all streams under that
same kill, and removes it only after a digest recheck. It then starts automatic redemption.

After the paste, verify absent kill, resolved exact persistence flag, active lane/timer, successful
redemption result, all streams/clocks green, and no watchdog alerts. F20 observation count is one;
reconcile observations two and three before permitting the registered fourth cover.
