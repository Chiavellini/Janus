# L138 verdict — STOPPED BEFORE IMPLEMENTATION; SUPERSEDED

The registered premise was contradicted by the next read-only measurement. Both Kalshi outcome
markets were already `finalized` with `result=scalar`, and the exact Polymarket moneyline was
`closed` with `umaResolutionStatus=resolved` and `outcomePrices=[0.5,0.5]`.

Janus's winner-only result representation returned null for both non-binary final results. The
cover was therefore not awaiting venue finality; it exposed a settlement-accounting defect.
Implementing coexistence would have hidden that defect, so L138 stopped before code, tests, box
writes, kill mutation, or restart. L139 preregistered the payout-aware correction instead.
