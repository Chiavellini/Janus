# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.*

Updated 2026-09-10 for the final F20 recovery/release candidate.

## Current state

Production runs `11b7f0a0c8d765e45772ad9d0f94ced0f900cd17` on the Mexico box in
`LIMITED_LIVE`. `kill/live` is absent, the lane and redemption timer are active, all three streams
are fresh, all material risk flags are resolved, current money state is empty, and the watchdog is
green. Exact marker 533 closes only persistence incident 530. The single accidental F20 taker
flight remains fully RECONCILED/released at -$0.014932; no later execution existed at final audit.

The base executable repair is `42ac10cd67af9b228930481ee3fd8ea4226f72ac`. It fixes the SQLite
writer-upgrade race, exact incident resolution, fail-closed retained-kill warm-up, SSM failure
propagation, redemption interpreter selection/error visibility, and the redemption watchdog cadence.
The candidate redemption SDK authenticated read-only on the box and sees two positive redeemable
conditions. No redemption was submitted during development.

The d864447 release deployed that base but failed closed before lane stop or kill handling. Its
fresh logs proved the current adapter error was gone; exact recovery was blocked only because an
already-resolved historical checker repeated a one-time terminal-zero proof against unrelated
shared-account positions and emitted `LEGACY_POSITION_EVIDENCE_BLOCKED`. L71 makes that checker
quiet only when its own exact unresolved flag set is empty, after validating acknowledgements and
migration alarms. The final `11b7f0a` release passed this boundary and safely cleared the kill.

Automatic redemption is operational. It submitted two eligible conditions, stored transaction
identities, observed fresh position disappearance, and marked both COMPLETE. Nothing eligible,
pending, unknown or failed remains.

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

No operational action is required. Let F20 run under the unchanged caps. Reconcile observations two
and three before permitting the registered fourth cover, with special attention to first-fill-to-
hedge latency, missed IOC levels, locked cover P&L and residual P&L. Do not lift caps or begin a C++
rewrite from the first adverse observation alone. The laptop may be powered off; runtime,
credentials, monitoring, redemption and restart behavior are box-local.
