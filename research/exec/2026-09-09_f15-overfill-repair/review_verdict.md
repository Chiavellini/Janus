# L53 — independent-review correction

The partial-FIFO defect is repaired locally. **Live BUY entry remains blocked.** The earlier
124-test result remains preserved, but its local-completeness claim was incomplete: the guard
could shrink an authoritative 10.166667-share order to the 6-share FIFO subset before checking
for an overfill.

The guard now checks existing order-level overfills before `_row_for()` can sync any fills.
Its post-sync check remains for newly adopted late fills. When FIFO quantity is smaller than
the known order quantity, it preserves the known quantity, average, fee, and state, and marks
accounting pending. Available fills being final does not establish that the absent remainder
has final cash accounting. An append-only `guard_fill_coverage` event records both quantities.

Once the remaining fill arrives, full FIFO coverage can replace average and fee; settlement
stays pending until every constituent fill is final. Missing, reduced, zero, or provisional
FIFO amounts never imply a reversal. The explicit-reversal regression models a separate,
authoritative reversal already accepted and recorded in the journal with source identity;
only then does the guard reconcile the reduced order total. This repair does not create an
automatic reversal workflow or authorize one. The historical overfill event and live stop
remain after such a correction.

The exact 10.166667-order/6-FIFO fixture asserts the kill is already latched when sync begins,
that all authoritative order fields survive, and that the execution retains 10.166667. The
late-completion fixture passes through complete-but-pending to full cash finality. Further
fixtures cover shrinking/zero FIFO without reversal and the explicitly audited reversal case.

Combined execution, Polymarket, account-ledger, reconciliation, and risk tests: **194 passed**
in 1.72 seconds. `git diff --check` passed. No source venue read or live mutation was needed;
all new fixtures are offline. Expected EV effect is avoiding understated exposure and partial
cash being used as whole-order cost, with no measured profitability claim.
