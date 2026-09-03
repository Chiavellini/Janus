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

## Now — what is left, and whose it is

Done since the merge: NFL templates reviewed and the tie rule cited; slippage measured (L27) and
registered; the Polymarket client installed; real-order modes wired into the grid.

**Yours, because I am not permitted to place orders:**
1. **The Kalshi proof on the production account** (demo waived, your decision, logged in GATE):
   write the override with `ops/arming_override.py`, dry-run `ops/kalshi_live_proof.py --ticker …`,
   then `--arm`. Two contracts by default. `--settle` after the game reconciles PnL and balance.
2. **A funded Polymarket wallet.** Its private key in a 600-mode file named by
   `JANUS_PM_WALLET_KEY_PATH` (never in `JANUS_CREDS`); `JANUS_PM_FUNDER` / `JANUS_PM_SIGNATURE_TYPE`
   if a proxy wallet.
3. **The $5 fills and the arming override** (`kill/arming_override.json`: your verbatim statement,
   `signed_by`, mode, runner and limits shas, caps, expiry). Real-money orders are yours to
   authorise; the coordinator then runs them under `LIMITED_LIVE`.
4. **Approval to start Ashburn** (billable). Another agent has begun provisioning in `infra/`.

**Time:** shadow evidence accrues under launchd; re-run L27 after a week of NFL traffic.
**Code, when data allows:** an NFL postponement/cancellation rate (a registered row) unblocks NFL;
NHL waits for Kalshi to list.

## Not now, deliberately

Any order path before `nodes/risk` exists. Ashburn/EC2 before everything is proven locally.
`venue_cloudbet` (acceptance before pricing makes its leg a naked directional bet) and
`venue_sxbet` (size convention unverified against a fill). Makers on Polymarket (`rebateRate`
semantics unverified). The `kernel/grid.py` typed-faults runtime: dropped in favour of the enums.

## The question that actually matters

Unchanged: **what is the distribution of cover cost**, per league and quantity, with every blocked
reason kept distinct. Capture, replay and a CDF answer it, under a new pre-registered row.
