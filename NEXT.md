# NEXT

Current-state handoff, updated 2026-09-15. Evidence belongs in the linked registered rows; this
file is an opinionated map and may be overwritten.

## Production now

The Mexico box is still deployed at `59dd5ae2ce3619104aa95d127d1b115d7c0702a9`. The service is
active for streams/reconciliation but entry is blocked by `kill/live`; it is **not trading**. The
retained kill was latched at `1789504505.261733` with SHA-256
`d81bbfc267a235ca7f268e7317d77ee7e83c65f5263117590e4e86d1552b1636` and exact reason:

> F22 STOP: terminal maker zero-fill fee evidence is NULL; strict report classifies persistence_or_reconciliation_failure

At the latch there was zero flight and zero unhedged quantity. F22 is permanently closed. Its first
two maker decisions and orders remain unchanged evidence: authoritative terminal zero fills with
valid post-only proof, but `fee_usd=NULL`, so F22 correctly stopped rather than manufacturing a
zero-dollar observation.

The earlier scalar/cancelled cover is settled and released at `-$0.99357`. That economic loss did
not cause the current stop. The separately reported approximately $100 `ORPHAN_FILL` was operator
manual activity, not Janus, and the operator has asked that it not be pursued as a system incident.

The Polymarket redemption timer's rate-limited positions call remains an operating-cost issue. It
is distinct from order attempts and should stay bounded/quiet rather than retrying expensively.

## Release candidate in this tree

L140 fixes the F22 instrumentation defect prospectively: explicit `fee_usd=0.0` is persisted only
for complete terminal, non-open, non-pending, zero-fill maker proof. Ambiguous, partial and filled
orders retain blocking fee requirements. Historical F22 rows are not repaired.

F23 is a fresh event-randomized comparison of the same bounded immediate Polymarket taker entry
against the registered two-second post-only maker entry. It has a separate table, assignment
digest, authority and report. F22 cannot reactivate in capital mode. The fixed F23 end is 200
eligible decisions, at least 80 per arm, 50 events, five league-local days and three leagues; the
first three covers must reconcile before the fourth, but later fills are not serialized behind
settlement. Each F23 decision now persists its event start, league and canonical America/New_York
venue date before the wire; malformed or missing dates keep the five-day minimum unscored.

L142 closes a defect observed on both F22 maker orders. Their loop-owned safety callback went
unserviced for 1.62/1.75 seconds and timed out at nearly the full rest deadline. Each check is now
bounded by the existing poll interval; timeout/error cancels immediately and structured evidence
distinguishes responsive checks, timeout, refusal, fill and deadline.

The release/recovery route recognizes only the exact retained F22 kill, proves the complete
decision/execution/opportunity/client/order/digest identities of decisions 1 and 3 and their
unchanged NULL-fee orders, requires zero F23 rows and globally quiet capital, runs two
stopped complete guards around a retained-kill stream warmup, archives only that exact kill, and
restarts under exact F23 authority. A mismatch remains stopped and rollback restores the kill.

Local verification is green: 172 focused tests, all 1,766 collected tests in the complete suite,
compilation, shell syntax and
diff checks. Replay is unchanged over 20,000 frames, 234 pollers, 5,858 evaluations and 1,093 rows:
`13e4fb08a76c920f / 4f53cda18c2baa0c`.

## What the last live window actually proved

L141 fixed the denominator. In the registered 24-hour window, the included execution records span
15.34 wall-clock hours and reconcile exactly to:

- 95 `BOOK_MOVED` before wire;
- ten authoritative Polymarket terminal zero fills; and
- three complete covers, net `+$0.82908` after `$1.40092` fees.

The 95 declines were not 95 independent games: 35 event IDs and 49 opportunity IDs, with up to 13
attempts on one event. They do map to separate selected sizing windows, but none is proved safely
fillable. All have structured fresh confirmation: 90 failed Polymarket first-leg price/depth by
6c median and 10c p90; the other five passed leg A but the Kalshi hedge was above break-even by
1.88c median. Calling all 108 records “takeable prints” is therefore false.

The correct submitted-first-leg conversion was 3/13 = **23.1%**. The raw selected-window conversion
was 3/108 = 2.78%. Thirteen submitted orders are too few to distinguish a true one-third fill rate,
but one-third of all 108 is contradicted under the existing safe economics because no declined row
has a two-leg executable counterfactual.

The execution problem is nevertheless real. All eight eligible taker zero fills had sufficient
depth at the sent price immediately before submission and zero depth afterward: interim L102
classification `CONSUMED=8`, `STILL_THERE=0`, `PULLED=0`. Median REST confirmation was 180.74 ms,
confirmation-to-submit only 6.83 ms, and submit-to-ack 197.63 ms. This is latency-consistent but is
only eight observations, not L102's approximately 50-order final verdict.

For the 95 pre-wire declines, the Polymarket websocket book was already 548 ms old at median and
the fresh confirmation completed another 180 ms later. Ordinary machine dispatch is not the main
cost: frame-to-evaluation 1.66 ms, evaluation-to-executor 32.09 ms, worker hop 5.59 ms, clearance
5.55 ms and database work 8.14 ms at median. The direct target is the serial
websocket/venue-authority/network path while retaining a fresh hedge proof.

## Profit arithmetic

The recent three-cover mean was `$0.27636` net. Thirty-six covers at that mean produce `$9.95`, not
`$100`. The exact Polymarket fees on those covers were `$0.60932`; removing them raises 36 covers to
`$17.26`. Even removing **all** `$1.40092` of venue fees produces only `$26.76`.

At observed economics, `$100/day` requires about 362 covers. With only the Polymarket fee removed,
it still requires about 209. Therefore execution conversion plus the current maker saving are
necessary improvements but not sufficient. Reaching the goal also requires materially more
eligible surface, more dollars per cover within proven caps, a cheaper venue/mechanism, or some
combination. The high-evidence Kalshi MM-at-open lead remains untested in sports and avoids the
expensive two-venue fee pair, but it is a different mechanism and must be registered separately.

## Open questions that directly target the goal

1. Does F23's maker fee saving survive its lower fill probability, event-loop proof availability,
   waiting drift and hedge tail? Only the fixed forward cohort can answer.
2. Can taker entry remove one serial Polymarket confirmation round trip while preserving the fresh
   Kalshi hedge guarantee? The current data support testing a hedge-first strict-limit IOC arm, not
   blindly sending all 95 declined rows. That requires a new preregistered entry experiment and a
   dated GATE amendment before live use.
3. Why is the local Polymarket book commonly roughly 0.5–0.8 seconds old at selection, and can
   network placement or stream handling reduce the venue-authority gap? L141 says Python dispatch
   alone cannot supply the needed gain.
4. Can co-listed event coverage rise beyond the observed 35 `BOOK_MOVED` events without importing
   unmeasured settlement basis? Coverage and repeated covers are needed because current per-cover
   dollars cannot close `$100/day` alone.
5. Does the L102 `CONSUMED` split persist near 50 eligible taker zero fills? If it does, speed is the
   correct execution lever; if it reverses toward `STILL_THERE`, more speed will not fix the engine.

## Things that will mislead you

- `stages_json` stamps are cumulative from `_t0`; difference adjacent stamps per row.
- `socket_health.frames` is cumulative; use deltas and treat decreases as reconnects.
- `refusal_counts` are callback counts, not unique opportunities or stage conversion.
- `PROFITABLE_UNEXECUTED` is material-change gated and per size rung.
- `BOOK_MOVED` is a safe pre-wire terminal, not a submitted order and not proof the frozen print
  was still executable at the venue.
- A service can be active while `kill/live` blocks every entry.
- A provider response that is unresolved is not a zero fill.
- Negative unconditional hedge drift is not maker EV. The F23 randomized result governs.
