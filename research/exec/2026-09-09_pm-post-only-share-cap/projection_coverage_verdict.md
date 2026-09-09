# L54 projection-coverage review repair

Local repair PASS for the registered maker-accounting subtask. This is not a
deployment, live-entry approval, current-account total, or EV result.

Registration: `projection_coverage_followup.yaml`, appended L54 PENDING before
running any new regression. The earlier criteria and results remain unchanged.

## RED and GREEN

The first exact selected run failed all six cases:

- Guard received no fills for owned taker quantity 4 followed by an unattributable
  maker row, despite the role STOP having latched.
- Guard received quantity 6 instead of observed quantity 11 after a cash timeout.
- A malformed trade neighbor or raising trade iterator discarded the valid maker
  prefix, both with and without previously proved cash.

After repair, all six passed. Extended tests cover a within-cap increase to 8 as
well as the cap violation at 11, restart, a repeated smaller trade, and both failed
and successful-but-stale cash reads. A source-proved $0.12 fee for six shares is
preserved in the original SHA-backed source, not presented as the complete fee
for eight or eleven. The guard persists the actual quantity, marks settlement
pending, updates execution exposure, and hands it to protection on that pass.

Final focused run: **67 passed** across maker fills, L52 cash accounting, guard
cash finality, and guard quantity coverage. `git diff --check` passes.

An intermediate shared combined run passed 452 tests and failed two newly
registered singleton-admission tests still being implemented by the lifecycle
owner. That run is not claimed as a combined PASS; the overall L54 verdict must
record the stable combined rerun after that independent work finishes.

## Contract

Observed exposure and cash-covered quantity are separate facts. The mutable fill
projection retains the larger observed quantity across cash failures, smaller
stale reads and adapter restart. Durable cash fallback can replace complete
price/fee/finality only when its quantity and order/asset/side identity cover the
entire projected fill. Smaller cash authority remains in the append-only source
table; it cannot clamp or finalize the larger held quantity.

Trade iteration/projection is now failure-isolated by source row. Validated fills
are returned and recorded even when another row fails. The adapter separately
sets `projection_batch_error`; every fill in that incomplete batch is provisional,
and fresh cash I/O is skipped because uniqueness cannot be proved. Existing
SHA-backed cash source rows are unchanged. The separately owned guard/status
integration reports the error without discarding those fills and prohibits
terminal lifecycle proof from that pass.

L52's fresh activity index remains atomic: a malformed/raising activity batch
publishes no valid prefix, while a complete prior source remains usable when the
trade projection itself is complete and cash covers the full quantity.

## Files and authority

This follow-up edits only `nodes/exec_polymarket/client.py` (projection batch and
cash coverage regions), `nodes/exec_polymarket/tests/test_maker_fills.py`, this
registration/verdict, and appended ledger notes. Guard, lifecycle, admission,
socket-role, sizing, and README integrations belong to the parallel L54 owner.
Everything remains local and unstaged. No venue reads, venue/live mutation,
deployment, live restart, arm/cap change, or kill clearing occurred.
