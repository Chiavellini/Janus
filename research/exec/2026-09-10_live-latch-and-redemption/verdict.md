# L64 verdict — terminal repair and redemption pass; maker-rest branch superseded

Date: 2026-09-10

## Result

The registered terminal-reconciliation repair and independent Polymarket redemption service pass
their offline criteria. The proposed 15-second maker-rest policy was superseded before deployment
or observation by L65/F20 and is not present in the release candidate. L64 therefore makes no claim
about longer-rest maker fill probability or EV.

The coordinator now budgets the adapter-declared two-second stable-terminal window plus one poll
after cancel. A deterministic regression reproduces proof maturing just after the former deadline
without a latch, while a truly unresolved order still latches. Cancel dispatch timing is unchanged.

The redemption state machine filters to positive-value `redeemable=true` conditions, journals
PREPARED before the relayer wire, recovers the post-wire/pre-journal window by exact metadata, and
requires confirmed transaction plus fresh disappearance of positive redeemable value before
COMPLETE. Unknown and failed outcomes remain durable and make the systemd oneshot fail for watchdog
visibility. Zero-value remnants are untouched. The service uses a separate pinned
`polymarket-client==0.9.0` venv and ten-minute timer.

## Validation

- Complete repository test suite: PASS at 100%.
- Focused terminal, redemption, credential, systemd, watchdog and release tests: PASS.
- Watchdog self-test, Python compilation, shell syntax and diff check: PASS.
- Official 0.9.0 wheel interfaces and official relayer recent-transaction metadata contract:
  inspected and consistent with the adapter.

## Boundary

No box release, order, redemption transaction, credential write, restart, or live observation was
performed while producing this verdict. The later F20 gate separately authorizes an exact,
digest-bound false-maker-latch clear during the operator release; no generic or changed kill can be
cleared by that path.
