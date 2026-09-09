# L42 — historical ITF settlement-delay enumeration

FAIL: enumeration incomplete. No ITF rate is registered from this row.

The 2026-09-09 07:21:22 UTC run read 2,100 closed tennis events in ascending event-id order.
Gamma refused offset 2,100 with HTTP 422 (`OffsetCap`), before the enumeration reached any ITF
event. Twenty-one raw pages remain at
`/Volumes/Kilos/janus/research/L42_itf_delay/20260909T072122Z/`; no page is silently treated as
the end of the catalog. The required empty terminal page was not reached.

The preregistered original-date, authoritative-close, parseability, and estimator criteria are
unchanged. A schema probe made after registration confirmed that current ITF descriptions carry
an explicit originally-scheduled timestamp and both event and market records carry `closedTime`.
The source can therefore support another historical attempt using complete pagination, subject
to a new row. There is no reason yet to conclude that only fourteen days of forward collection
can resolve this ingestion failure.

Eight focused measurement tests passed. They cover the authoritative close-field fallback,
rejection of `endDate` as a terminal timestamp, original ET date parsing, HALF/winner separation,
exclusion denominators, strict fourteen-day boundary, pagination past short pages, and failure
on duplicate ids.

This row establishes no delay frequency, settlement equivalence, tradeability or profitability.
