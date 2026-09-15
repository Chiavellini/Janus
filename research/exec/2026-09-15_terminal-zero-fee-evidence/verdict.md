# L140 local verdict — PASS; production proof pending

The persistence path now writes `fee_usd=0.0` only when a Polymarket maker order has complete
terminal proof, zero filled quantity, `open=false`, and `settlement_pending=false`. A positive,
partial, open, pending, unknown, or otherwise incomplete order retains missing fee evidence and
cannot score as zero dollars. The stopped F22 rows are not edited.

F22 is closed in the capital-mode supervisor. The release and override default to the independently
registered F23 table/spec/assignment, and unknown or cross-cohort identities fail closed. F23's
report uses its registered caps, excludes F22, separates terminal completeness from the fixed
minimum sample, and cannot produce a scored verdict before that minimum.

The exact recovery route is pinned to the observed F22 kill SHA, reason, timestamp, decision IDs 1
and 3, their unchanged NULL-fee orders and maker proof, zero F23 rows, zero flight/unhedged/open
capital, two stopped complete guards, and a fresh retained-kill stream warmup. It has kill-first
rollback and cannot clear an unrelated or changed latch.

The final recovery proof also pins each source's event, experiment digest, sizing input and epoch,
quantity, execution, opportunity, first-leg client and venue-order identity; it requires an empty
hedge-client list and exactly one Polymarket order. Mutating linked rows together therefore cannot
make a different observation look like either registered source.

Local verification: 172 focused tests passed; all 1,766 collected tests in the full suite exited
zero; Python compilation, shell syntax and `git diff --check` passed. The registered replay remained exactly
`13e4fb08a76c920f / 4f53cda18c2baa0c` over 20,000 frames, 234 pollers, 5,858 evaluations and
1,093 evaluation rows.

Production release/recovery remains pending in this local verdict.
