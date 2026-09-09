# L46 — PASS, main-draw ITF reserve registered

The fresh catalog completed both keyset chains: **33,295 closed and 531 open tennis events** in
339 requests/pages, with no retries, cache reuse, duplicate/state-transition events, or catalog
state mismatches. All raw request/cursor/response hashes are preserved under
`/Volumes/Kilos/janus/research/L46_itf_delay/20260909T075545Z`.

ITF main-draw population: 13,467 identified singles, all required fields parseable; 2,097 recent
original starts excluded from the mature denominator. Explicit qualifying excluded structurally
(2,222 events), never silently transferred into this population.

Among **11,370 mature singles**, 178 are conservatively adverse: 136 HALF, six winner resolutions
after fourteen days, 34 winner resolutions before the original start, and two still-open events.
The other 11,192 resolve to a winner within fourteen days. Any HALF is counted adverse even though
many are matched half-dollar payouts with no cross-venue loss.

The immutable always-one-sided-upper-bound estimator registers
**`tennis.itf.delayed_gt14d_rate = 0.01768867361249885`** (Wilson z=1.6449), not the
1.5655233069% point estimate. The policy charges this reserve once, using the existing worst-case
loss model. This expands safe eligibility; it does not establish profitable executable depth or
guarantee future settlement frequencies.

## Independent correction and replay

While the unmodified collector ran, independent review hardened the pure scorer so total
authoritative-close absence fails even for an all-open population. Offline cursor validation also
rejects false/zero/list/dict cursors and enforces the collector's strict event-ID types.
`replay.py` then re-read every saved raw page with no network, verifying exact requests, hashes,
cursor completion, IDs, classifications, and aggregate output. **Both result and full row files
are byte-identical** under the corrected code. `verification.json` records all hashes:

- Result SHA-256: `f89fcc3ae43539952960488d81a382176337da469d801bebf8993dc7d14060a9`.
- Rows SHA-256: `d3dc03be348a1ea223a84cb5070332afc866957801df9085c81353bcc6c95983`.
- 339-page manifest SHA-256: `0b68a7d4a646a030e18893494f94bc357fd19a0cdb80b2fd56537e35a30dd577`.

L42/L44 failures and all source pages remain untouched; L45 remains failed/unscored. This row is
not a repaired or reused L44 archive. No specification or old result was changed.

The ITF per-league **paper/demo** allowance is now $200, matching ATP/WTA. Outer event/day/live
caps, submission mode, orders, signed overrides and deployment were not changed by this row.
Qualifying requires its separate L47 result; tour evidence cannot satisfy either ITF key.
