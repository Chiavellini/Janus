# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-03, after P7 of the v1 plan.

## Done

Substrate (git, watchdog, visible suite, node grid). The streaming lane: two shared sockets, book
replicas with liveness ≠ freshness, one actor per game, the size frontier. Exhaustiveness as an
unforgeable proof. **P0–P3 of the v1 plan** (2026-09-02/03): fees from the venues' own payloads;
the vocabulary enums; raw-frame capture and a replay whose parity against live is zero mismatches
on real traffic; provenance and server time on every book; one Kalshi subscription per socket
with per-sid sequencing; a REST backstop for quiet Polymarket books; the complementary NO ladder
streamed; `nodes/settle_wedge` — settlement equivalence as a second proof, priced from a measured
rate (ledger L26), certified live on real MLB text; `CanonicalKey` as the join key; `nodes/risk` —
limits, kill files, the latching breaker, the exposure ledger, the `RiskClearance` token and the
mode gate, with three watchdog alarms; the total-cost model (per-level fills, min order, balance,
fixed cost, a labelled slippage term) and the `Opportunity` record with persisted frontiers; the
order path (`kernel/execution_protocol`, `nodes/execution`, `exec_kalshi`, `exec_polymarket`), disarmed:
journal before the wire, no retry after an ambiguous send, a `RiskClearance` on every submit; the
coordinator (`nodes/execute`, Polymarket first, Kalshi hedge, every transition persisted) and
`nodes/reconcile`; `grids/live_stream --mode PAPER_EXECUTION` runs the machine against live books.

## Now

1. **P8 the pre-capital battery**: replay a captured day through the paper coordinator; injected
   gap / reconnect / heartbeat loss; partial fill on leg A; ambiguous order recovered only via
   `status()`; kill file mid-execution; balance change between VALIDATED and CAPITAL_RESERVED; fee
   reconciliation against captured fill payloads; settlement-result ingestion from both venues into
   `reconcile.settle`; the slippage measurement (registered row) once a day of capture exists.
2. P9 control-plane polish (48 h horizon, priority tiers, wake/drain), P10 Ashburn (gated), P11
   promotion (Kalshi demo round-trip, $5 fills, arming by signed override). Before any DEMO run: demo credentials for Kalshi; before any
   LIMITED_LIVE Polymarket leg: `pip install py-clob-client` and a 600-mode wallet key file.

Harvest and review the Polymarket NFL and NHL game templates when they list; until then those
leagues block at `TEMPLATE_UNKNOWN`, which is correct. Measure the slippage buffer (the distribution
of Kalshi best-ask moves inside the hedge window) from captured frames under a registered row once
the live lane runs this tree and a day of capture exists; until then `slippage_modelled=False`.

## Not now, deliberately

Any order path before `nodes/risk` exists. Ashburn/EC2 before everything is proven locally.
`venue_cloudbet` (acceptance before pricing makes its leg a naked directional bet) and
`venue_sxbet` (size convention unverified against a fill). Makers on Polymarket (`rebateRate`
semantics unverified). The `kernel/grid.py` typed-faults runtime: dropped in favour of the enums.

## The question that actually matters

Unchanged: **what is the distribution of cover cost**, per league and quantity, with every blocked
reason kept distinct. Capture, replay and a CDF answer it, under a new pre-registered row.
