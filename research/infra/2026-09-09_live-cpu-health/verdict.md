# L51 — CPU saturation and reader work

The live F15 event-loop thread is CPU-bound. A ten-second read-only procfs
sample ending 2026-09-09 08:45:56Z measured **97.59% of one vCPU** on Python's
main thread; the three workers used 0%, 0% and 1.90%. Lifetime process CPU was
97.3%, systemd showed no restart, and `nproc` was 1. Memory pressure was zero
and full I/O pressure was 0.24%, so neither paging nor disk waiting explains
the main-thread load. Exact observations are in `results_live_observation_01.json`.

At the same report, 216 pollers shared 454 Kalshi tickers and 438 Polymarket
assets. Kalshi's median venue-to-reader timestamp offset was 17.0231 seconds
(25.2476 in the preceding report); Polymarket's was 9.2831 seconds. The loop
overshoot was only 2.204 seconds. Kalshi's error count increased 86 to 87
between those reports with a keepalive ping timeout. A small *individual*
loop overshoot therefore does not establish a current socket: repeated slow
draining can accumulate a much longer receive backlog. Snapshot age measured
after `recv()` can remain near zero while the queued payload is old.

## Attribution and its limit

The production reader performs compression, parsing, ladder projection,
all-replica heartbeat propagation and synchronous poller callbacks on this
thread. When it drains below the incoming rate, WebSocket backpressure can
delay processing control frames and contribute to a keepalive timeout. This
is consistent with the observed CPU load, offsets and repeated timeouts;
L51 did not attach a live profiler or inspect the Python connection's internal
read-paused flag, so it does not independently prove that every timeout had
this cause.

An offline component profile used the first 10,000 intact raw frames from
each venue's copied 2026-09-09 04:00Z capture. Registrations matched the
observed counts: 454 Kalshi tickers with YES/NO replicas and 438 PM assets,
padding quiet registrations where the bounded prefix did not name them.
Network, poller callbacks and store writes were excluded. A cold prefix can
lack earlier snapshots, especially on PM, so this is not a full-lane profile
or a gate-4 trading replay. The copied local tuple database was malformed;
it was neither repaired nor used for any result.

Within this bounded reader workload, Kalshi projection is the largest
function family: **3.801 of 7.323 profiled CPU seconds** in `TickerBook.project`,
with approximately 1.45 million `Quote` constructions and validations for
19,998 YES/NO projections. There were also **9.08 million** heartbeat calls.
PM's all-replica `_beat` sweep consumed **1.490 of 2.130 profiled seconds**,
including 4.38 million heartbeat calls. These are useful optimization targets;
their shares must not be presented as measured shares of total live CPU.

## Local repairs and equivalence

1. Capture now uses gzip **level 3**, retaining the same gzip JSONL format,
   raw text, receive times, order, append behavior and hourly rotation.
   Across three repetitions, median compression CPU fell 0.323923 to
   0.133495 seconds for Kalshi and 0.458021 to 0.191566 seconds for PM
   (58.8% and 58.2%). Compressed bytes rose 342,494 to 457,245 (33.5%) and
   1,104,058 to 1,380,058 (25.0%). Every input frame and timestamp round-tripped
   exactly at all measured levels. The box had 37 GB free at observation;
   any eventual release must continue to watch retention and disk growth.
   Existing level-9 gzip members can be appended with new level-3 members,
   covered by a regression test.

2. `TickerBook.project` memoizes each ladder's validated `Quote` tuple and
   the existing kernel complement-fold result. Every call reconstructs the
   sorted content key and compares the identity of every immutable price and
   size object. This observes direct dictionary changes, new snapshots,
   same-sequence deltas, and partial failed snapshot parses. Identity also
   prevents signed zero or changed numeric rendering from aliasing under
   equality. Returned lists are always fresh. Validation, folding, sequence
   handling, callbacks, receive times and health checks retain their existing
   meaning.

The final implementation matched **all 19,998 projection outputs** over
10,000 actual Kalshi frames by digest. Every replica's final books, state,
fault, timestamps and counters, plus stream sequence state, also matched the
preserved uncached reference. Deterministic mutation tests make 8,000 further
reference comparisons and include invalid prices/sizes, signed zero,
caller-list mutation and partial parse failure. **109 tests passed** across
Kalshi stream, capture, book replica, replay and live-stream grid suites.

Three interleaved runs of the same reader fixture measured median
**5.261624 → 3.739283 CPU seconds**, a **28.9% reader CPU reduction** with the
final cache. Absolute timing differs from the earlier component run because
the laptop was under variable load; the paired before/after comparison is
the relevant result. `benchmark_projection.py` retains the original
uncached implementation, and `results_projection_final_01.json` pins the
tested production protocol source. The earlier experimental candidate and
its results are preserved separately; they are not the released algorithm.
The reachable cache object graph after this sample was 8,654,592 bytes across
820 cached sides on 410 books. That is an upper bound on incremental memory
because it includes price/size objects also held by the original dictionaries;
it is not a live RSS measurement. The cache trades this bounded observed
retention for reduced repeated allocation.

## Remaining work and expected EV effect

No repair in L51 has been deployed, and no live CPU or socket improvement is
claimed. Removing all-replica heartbeat sweeps would require representing
connection liveness once and preserving the public `heartbeat_utc` contract,
quiet-book freshness, reconnect/disconnect transitions, registration seeding,
REST reconciliation and replay behavior. Simply reducing heartbeat frequency
would change those semantics. That larger change is deferred until complete
lifecycle equivalence can be established; the sweeps remain intact.

After a separately reviewed, gated release, measure CPU deltas together with
frame rates, venue-to-reader age, queue/backpressure metrics, reconnect rate,
loop lag and disk trajectory under a comparable slate. If the loop remains
saturated, obtain a stable read-only slate snapshot and replay the complete
pipeline offline, including callbacks and store commits, before attributing
the residual to evaluation versus heartbeat work. Do not enlarge buffers or
keepalive thresholds and call the bottleneck solved.

Quoted EV, price selection, reserves, coverage and execution caps are
unchanged. Lower reader work may improve the fraction of fresh opportunities
and reduce hedge latency risk; realized EV improvement requires forward
evidence under the same gates. No outcome, holdout or strategy test look was
read or spent. No live mutation, profiler attachment, order, arm change,
watchdog weakening or cap change was performed.
