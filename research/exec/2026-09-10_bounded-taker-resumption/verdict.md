# L65 local verdict — bounded taker resumption passes offline

Date: 2026-09-10

## Result

The local release candidate restores immediate executable-price taker entry in capital-risking
mode. It does not restore a generic Polymarket BUY signer: only a dedicated FAK/FOK method can sign,
and that method is hard-limited to ten requested contracts, twelve dollars collateral, and
cent-exact collateral independently of the signed override.

The durable bounded-taker authorization is committed before the wire. Authoritative actual fill
quantity is never clamped. Price-improvement excess strictly below one contract is preserved,
hedged and audited as `BOUNDED_TAKER_RESIDUAL`; excess at or above one contract retains the existing
quantity stop and live latch. Unknown wires and every other protection remain unchanged.

## Validation

- Generic BUY block, dedicated wire bounds, pre-wire persistence and refusal tests: PASS.
- Coordinator and guard sub-one acceptance / at-least-one STOP regressions: PASS.
- Live grid and exhaustive sizing select the taker plan with executable-price economics: PASS.
- Complete repository suite, watchdog self-test, Python compilation, shell syntax and diff check:
  PASS.

## Boundary

This is a local implementation verdict, not live profitability evidence. F20 has not begun; no
fill-rate or realized-EV inference is made from the prior maker cohort. Caps and profit/return
hurdles are unchanged.
