# L113 verdict — the current bottleneck is before the first fill

Date: 2026-09-15. Read-only from the Mexico box on deployed SHA
`f7c9c1b177f757d6bfbc6e126eeb47bbb001c6eb`, using the registered
`ops/funnel_report.py`. No order, policy, cap, hurdle, mode, database, or service was changed.

## Post-release hour

At q=10 the last hour contained 199 events seen, 184 co-listed, 191 games priced, six materially
distinct `PROFITABLE_UNEXECUTED` episodes, four execution attempts, one submitted order, zero
filled orders, and zero covers. The one submitted order was venue-authoritatively `UNFILLED`; the
other executions stopped before a fill. At q=25 there were three actionable episodes, the same
four executions and one order, and again zero fills.

The q=10 row also recorded 447 `supervisor:halt` episodes. This is not 447 missed arbitrages: while
halted the lane does not price the counterfactual cover, so the report deliberately cannot say
which would have been actionable. It is nevertheless the dominant directly observed loss of
evaluation availability in this hour and deserves a separate measured attribution before any
entry-policy change.

## Twenty-four-hour context

The 24-hour q=10 view contained 540 events seen, 202 co-listed, 435 actionable episodes, eleven
execution attempts, five submitted orders, zero fills, and zero covers. The execution journal
classifies the eleven as six `BOOK_MOVED` and five `ORDER_UNFILLED`. The q=25 view contained 310
actionable episodes and the same downstream counts. This window spans older releases and a retained
kill, so it diagnoses the inherited funnel but is not a clean estimate of the new release.

Refusal counters are event-callback counts, not actionable episodes, and therefore are not valid
stage ratios. Their largest codes were `below_min_order`, `MIN_PROFIT`, `MIN_RETURN`, and `BALANCE`;
they identify where a dedicated join should look, not how many independent trades were lost.

## Verdict

L113 passes as a descriptive instrument. The released lane is safe and evaluating, but it has not
demonstrated first-fill conversion or positive money. The immediate profit question is the exact
timeline from an actionable print through `BOOK_MOVED` or the venue-authoritative zero fill,
separated from halt time and repeated event callbacks. The present data cannot support a daily
profit floor, and loosening a hurdle or size from these aggregate counts would be post-hoc and is
not authorized.
