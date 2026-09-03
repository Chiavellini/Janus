# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-03, after P9 of the v1 plan.

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
`nodes/reconcile`; `grids/live_stream --mode PAPER_EXECUTION` runs the machine against live books;
offline execution over captured frames; settlement-result ingestion; the 48 h registry with tiers,
wake/drain and a registry alarm. Everything in the plan that code alone can deliver is delivered.

## Now — the operator's steps, in order (BATTERY.md has the detail)

1. **Merge and restart the lane** so capture, the new vocabulary and fee-correct rows start
   accruing: `git merge --ff-only claude/janus-arbitrage-trader-4e6d4d` on main, then
   `launchctl kickstart -k gui/$(id -u)/com.janus.live-stream`. Watch `python3 ops/watchdog.py`.
2. After a day of capture: register and run the **slippage measurement** (Kalshi best-ask moves
   inside the hedge window) as a descriptive row; fill `Frontier.slippage_modelled`.
3. **Kalshi demo credentials** → `DEMO_EXECUTION` round-trip (place → poll → cancel → settle),
   then wire real-order modes into the grid (they are refused there until this is done once).
4. **Polymarket**: `pip install py-clob-client`, a 600-mode wallet key file, then the $5
   `LIMITED_LIVE` fill under a signed `kill/arming_override.json`; `nodes/reconcile.check_fees`
   against the charged fee on both venues.
5. Harvest and review the Polymarket **NFL and NHL** game templates when they list.
6. P10 Ashburn only after all of the above, and only on explicit approval to start the instance.

## Not now, deliberately

Any order path before `nodes/risk` exists. Ashburn/EC2 before everything is proven locally.
`venue_cloudbet` (acceptance before pricing makes its leg a naked directional bet) and
`venue_sxbet` (size convention unverified against a fill). Makers on Polymarket (`rebateRate`
semantics unverified). The `kernel/grid.py` typed-faults runtime: dropped in favour of the enums.

## The question that actually matters

Unchanged: **what is the distribution of cover cost**, per league and quantity, with every blocked
reason kept distinct. Capture, replay and a CDF answer it, under a new pre-registered row.
