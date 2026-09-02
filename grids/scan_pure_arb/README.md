# grids/scan_pure_arb — bounded family scanner

`python3 -m grids.scan_pure_arb.grid`

Scans a bounded market family for complementary covers. **A parallel implementation**: it computes
its own cover economics rather than calling `nodes/cover`, so it has no staleness check, no
`Leg.executable` gate and no exhaustiveness proof.

It does one thing better than `live_sports`: it reads the Polymarket fee rate from the payload
(`feeSchedule.rate`) instead of hardcoding it, and it records the real exception on a failed sweep.

Reconcile onto `nodes/cover` or retire it. Two cover implementations is one too many.
