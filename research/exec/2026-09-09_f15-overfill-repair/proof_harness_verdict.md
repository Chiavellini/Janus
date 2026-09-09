# L53 offline proof follow-up

The four full-suite failures were stale offline harness assumptions, not justification to
relax the production BUY block. The in-memory `FakeTransport` now explicitly declares its
test-only exact-share contract: it fills precisely the submitted size without a signer,
network, exchange contract or price-improvement mechanism. Real `PyClobTransport` is untouched
and still refuses every BUY without a proved maximum received-share bound.

The fake also reports matching synthetic trade/cash identities and the same Decimal debit
used to update its simulated balance. This retains the independent adapter cash-finality
boundary while preserving the existing success, chain-failure, excessive-fee kill and settled
win/loss arithmetic assertions. A new test removes the fake's cap contract and proves that
the adapter journals `QUANTITY_CAP_UNPROVEN` without reaching its post operation.

Validation: all 38 registered ops proof and PM/coordinator/guard quantity tests passed in
14.02 seconds; `git diff --check` passed. The seven ops proof tests include all six original
tests unchanged in their assertions. Production behavior and expected EV are unchanged; this
restores offline coverage only. No venue access, live mutation, deployment or new look.
