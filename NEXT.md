# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-03, after P3 of the v1 plan.

## Done

Substrate (git, watchdog, visible suite, node grid). The streaming lane: two shared sockets, book
replicas with liveness ≠ freshness, one actor per game, the size frontier. Exhaustiveness as an
unforgeable proof. **P0–P3 of the v1 plan** (2026-09-02/03): fees from the venues' own payloads;
the vocabulary enums; raw-frame capture and a replay whose parity against live is zero mismatches
on real traffic; provenance and server time on every book; one Kalshi subscription per socket
with per-sid sequencing; a REST backstop for quiet Polymarket books; the complementary NO ladder
streamed; `nodes/settle_wedge` — settlement equivalence as a second proof, priced from a measured
rate (ledger L26), certified live on real MLB text; `CanonicalKey` as the join key.

## Now

1. **P5 `nodes/risk`** (pure, before any adapter): `RiskLimits` from a checked-in YAML with a sha
   pin; the reservation ledger (release only after both legs reconcile); the latching daily
   realized-loss breaker fed by a FIFO ledger that re-polls UNCONFIRMED fills; kill files under
   `/Volumes/Kilos/janus/kill/` (all / live / venue / event / strategy); `RiskClearance` — a minted,
   single-use, short-expiry token every adapter's `submit()` will require; the mode gate that
   refuses to start on any inconsistency. Watchdog alarms for kill-file-present, breaker-latched,
   unreconciled-too-long, each with a firing test.
2. **P4 opportunity records + total-cost model**: the `Opportunity` record and allowed
   transitions, per-level fills in `cover._fill_for`, min order size / balance / all-levels-
   executable in `capacity`, the slippage buffer MEASURED from captured frames (until then
   `slippage_modelled=False` caps the mode at PAPER), the frontier persisted.
3. **P6 execution adapters** (disarmed): `kernel/execution_protocol`, `nodes/exec_kalshi`
   (REST signing generalised from the socket's, demo host), `nodes/exec_polymarket` (CLOB auth,
   EIP-712, wallet key in its own 600-mode file). Both journal-first, `post_json_once`,
   three-way fill state, and both require a `RiskClearance`.
4. Then P7 coordinator, P8 paper simulator and battery, P9 control-plane polish, P10 Ashburn
   (gated), P11 promotion.

Harvest and review the Polymarket NFL and NHL game templates when they list; until then those
leagues block at `TEMPLATE_UNKNOWN`, which is correct.

## Not now, deliberately

Any order path before `nodes/risk` exists. Ashburn/EC2 before everything is proven locally.
`venue_cloudbet` (acceptance before pricing makes its leg a naked directional bet) and
`venue_sxbet` (size convention unverified against a fill). Makers on Polymarket (`rebateRate`
semantics unverified). The `kernel/grid.py` typed-faults runtime: dropped in favour of the enums.

## The question that actually matters

Unchanged: **what is the distribution of cover cost**, per league and quantity, with every blocked
reason kept distinct. Capture, replay and a CDF answer it, under a new pre-registered row.
