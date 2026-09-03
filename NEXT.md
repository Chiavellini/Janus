# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-02, after P0a of the v1 plan.

## Done

Substrate (git, watchdog, visible suite, node grid). The streaming lane: two shared sockets,
book replicas with liveness ≠ freshness, one actor per game, the size frontier, the
complementary NO ladder (REST lane only so far). Exhaustiveness as an unforgeable proof.
P0a: fees from the venues' own payloads, the PM drift resnapshot fix, `nodes/discovery` (no grid
imports a grid), credential redaction, dead grids removed, tests for every node that had none.

## Now — in this order, then fan out

1. **P0b kernel vocabulary** (one commit, before anything parallel): `OpportunityStatus`,
   `ExecutionState`, `Mode`, `FillState` enums in `kernel/schema.py`; `Book.source/server_utc/
   received_mono`; period vocabulary unified on `"game"`; status literals in `grids/live_stream`
   replaced by the enum. These names are the faithfulness contract — name once, never rename.
2. **P1 frame capture + replay** (`nodes/capture`, `nodes/replay`): raw frames to disk BEFORE parse;
   drive `KalshiStream.handle` / `PolymarketStream.handle` offline. Every later test needs this.
3. **P2 market-data completion**: Book provenance and timestamps, periodic REST reconcile for
   Polymarket (`BookReplica.reconcile` has no caller), the complementary NO ladder in the streaming
   lane, socket health persisted, `depth_truncated`, clock health.
4. **P3 `nodes/settle_wedge`**: harvest → reviewed policy table → `SettlementEquivalence` token →
   `CoverProof`. Unknown = BLOCKED_RULES. Expect the MLB cancellation wedge to bite.
5. **P5 `nodes/risk`** (pure, before any adapter): limits, reservation ledger, latching breaker,
   kill files, `RiskClearance` token, mode gate.

P1, P2, P3 and P5 touch disjoint files and can run in parallel once P0b has landed. Then P4
(opportunity records, total-cost model), P6 (execution adapters, disarmed), P7 (coordinator), P8
(paper simulator + battery), P9 (control-plane polish), P10 (Ashburn, gated), P11 (promotion).
The full plan is in the operator's plan file; this file tracks only the head of it.

## Not now, deliberately

Any order path before `nodes/risk` exists. Ashburn/EC2 before everything is proven locally.
`venue_cloudbet` (acceptance before pricing makes its leg a naked directional bet) and
`venue_sxbet` (size convention unverified against a fill). Makers on Polymarket (`rebateRate`
semantics unverified). The `kernel/grid.py` typed-faults runtime: dropped in favour of the enums.

## The question that actually matters

Unchanged: **what is the distribution of cover cost**, per league and quantity, with every blocked
reason kept distinct. Capture, replay and a CDF answer it, under a new pre-registered row.
