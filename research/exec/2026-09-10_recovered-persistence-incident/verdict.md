# L69 verdict — recovered order-persistence incident

Status: **LOCAL AND ACTUAL-BOX READ-ONLY PASS; LIVE RESOLUTION PENDING**.

The immediate cause of flag 530 was an explicit deferred `BEGIN` in the Polymarket cash/fill
bundle. That overrode the execution worker's configured IMMEDIATE transaction and allowed a
read-snapshot-to-writer upgrade to fail immediately when the loop owned the database writer lock.
The candidate uses `BEGIN IMMEDIATE`; a two-connection concurrency regression proves it waits for
the other writer and commits the final cash source/fill atomically without latching.

The recovery is exact-ID and append-only. It accepts only the strict database-lock detail, then
requires a real identified terminal order, complete exact execution ownership, final authoritative
FIFO for every positive order, matching cash/fees, bounded authorization for any accepted PM
excess, a unique released RECONCILED execution, complete final released settlement, and matching
released reservation. A fresh error-free two-venue guard with no orphan, mismatch or protection
work must pass twice, including under the writer lock. The false-maker clear independently refuses
every unresolved material risk flag.

The candidate proof was executed read-only against production flag 530 and exact CID
`b80fd489eba14f05a3e6a9031e7d6a0c`. It found seven owned terminal orders, two final venue FIFOs,
one valid bounded-taker overfill, execution `0b425cbe71cb4ca1a919fda622538a07`, and matching released
settlement/reservation timestamps. All negative and race regressions pass.

No production row or kill was changed. The operator release must deploy the guard, allow it to
append the exact resolution after its fresh venue pass, and only then may the digest-bound
false-maker clear continue.
