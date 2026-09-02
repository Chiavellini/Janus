# JANUS_CHECKLIST — phase history, pre-registered

> Mirrors the approved plan. Tick items as they complete. Gates are pre-committed; a gate fail is
> a STOP, not a softer bar. Append phase outcomes; never rewrite a completed section.

---

## Phase 0 — Scaffold  ✅ COMPLETE (2026-07-24)

- [x] `~/Code/Janus` created; `data` → `/Volumes/Kilos/janus` (863 GB free; root disk excluded)
- [x] Directory skeleton: `catalog/ collectors/ lib/ exec/ specs/ handoffs/ tests/ research/{basis,catalog,exec,ops}/`
- [x] `lib/stats.py` — copied with provenance from Kilos `Phase1/validate.py` + `Equity/lib/stats.py`
- [x] `lib/venue_costs.py` — two-venue cost model, **self-test passing** against real anchors
- [x] Doc set per `DOCS.md` Layer 2: `AGENTS.md`, `state.yaml` (schema-validated), `VALIDATION_STATUS.md`, `GATE_TO_LIVE.md`, `README.md`, `snooping_ledger.md`, this file
- [x] `SHARED_SERVICES.md` — the Kilos boundary contract + 7 invariants
- [x] Corpus mapped empirically against both live APIs (ledger row `L1`)

**Verified:** cost self-test reproduces Kilos' frozen `+47/−53`, breakeven `53.0%`, the on-chain PM
`FeeCharged 0.2205` anchor, and Kalshi's `ceil` at both 1-contract and 100-contract order sizes.
`state.yaml` carries every key the schema requires. No Kilos imports anywhere in the tree.

**Found during Phase 0** — a float artifact in the Kalshi per-order fee: `0.07·100·100·0.25`
evaluates to `175.00000000000003`, so a naive `ceil` bills 176¢ for an order whose true fee is
exactly 175¢. Fixed with a 9dp snap before every `ceil`. Harmless at 1 contract (which is why the
Kilos lineage never hit it) and material at size. The same latent issue exists upstream in
`Kilos/Phase1/costs.py` — report, do not edit.

---

## Phase 1 — Catalog + pair map  ⬜ NEXT

- [ ] `catalog/enumerate_kalshi.py` — cursor-paginated `/series` then `/markets`, with a real
      token-bucket rate limiter (today's Kilos handling is reactive 429-backoff only)
- [ ] `catalog/enumerate_pm.py` — Gamma `/events` + `/markets` pagination (**not** slug
      construction; nothing in Kilos asks either API what exists)
- [ ] `catalog/build_pair_map.py` → `data/catalog/pairs.parquet`
- [ ] Per-pair metadata: settlement source, reference convention, tick, min size, fee schedule,
      `match_confidence`
- [ ] `research/catalog/2026-MM-DD_pair-map/verdict.md` — measured coverage + every
      unmatched-reason bucket

**Gate (pre-committed):** 7 assets × 15m mapped · **≥95%** of expected windows matched · **zero
silent drops** (every unmatched window carries an explicit reason) · **byte-identical on re-run**.

**Cost of failure to notice:** Kilos' live arm lost most of its population to `kalshi_no_match`
(308) and `feed_gap` (136). This phase exists to make that impossible to miss.

---

## Phase 2 — Dual-venue collector  ⬜

- [ ] `collectors/collect_janus.py` — Kalshi WS `orderbook_delta` L2 for 7 series + PM CLOB WS +
      PM RTDS oracle + Kalshi REST fallback
- [ ] Own DB under `data/`; own `com.janus.*` launchd namespace
- [ ] Hot tier 3–5 days → nightly parquet cold tier → delete
- [ ] Fail-closed disk floor; liveness / preempt / disk alarms
- [ ] **Every alarm emits a self-test line** proving its comparison and field indices work, and is
      demonstrated firing against a fake target

**Gate:** 72 h continuous run · **≥98%** capture of expected windows per asset · disk trajectory
inside budget · clean resume from a mid-window kill (no gaps, no duplicates) · all alarms shown
firing.

**Binding constraint — disk, not code.** Measured on Kilos: **4.8 GB/day/series** of Kalshi
per-delta L1 (55.1 M rows / 14.6 GB in 3.03 days, one series). Seven series ≈ 34 GB/day ≈ 1 TB/month
against 863 GB free — **~25 days** without a cold tier. The parquet tier is mandatory.

**Then:** seal the Janus forward era (`GATE_TO_LIVE.md` Step 3) and record its start in `state.yaml`.

---

## Phase 3 — Research, pre-registered  ⬜

Each read gets a `spec.yaml` written **before** the run and a numbered `snooping_ledger.md` row
appended `PENDING` **before** the run. Splits pre-committed by date, never edited.

### R1 — convergence, generalized to 7 assets
- [ ] Port the registered rule: offsets `{0,120,300,480,660}s` (never the final 120 s), first
      `|divergence| ≥ 5pp`, buy the PM side Kalshi favors, one trade per window, hold to settlement
- [ ] **BTC is the acceptance test, not evidence** — must reproduce ≈ +4.447¢ digit-close on the
      overlapping era before any alt number is read
- [ ] The 6 alts are the actual new evidence

*Prior (spent Kilos evidence, used as prior only):* the C6 Kalshi-agree cell was positive on 6 of
6 series; pooled 4-alt same-event 15m = +11.91¢ [+2.77, +20.56] excl-0, n=114.

### R2 — hedged two-leg
- [ ] **First deliverable: measure the per-asset opposite-settle rate** (BRTI vs Chainlink
      disagreeing on the same window's direction) and add its expected loss to the cost model
- [ ] Only then price the two-leg arm

*Prior is structurally poor and stated up front:* the Kalshi leg has a spent, failed one-shot
(−2.375¢, p=0.772), so hedging mostly buys the edge away. And `pair_cost_cents(45, 52)` already
shows **101.75¢ of cost for a 100¢ payoff** before oracle risk. R2's honest purpose is to price
the trade-off, not to assume it works.

### R3 — Kalshi MM-at-open across 7 series
- [ ] **Coordinate with Kilos first** — this mechanism is its registered row 20, forward clock
      started 2026-07-21. Settle who spends the evidence before either project reads it.
- [ ] Direction-agnostic both-sides touch-join at offset 0, queue-realistic fills, real maker fee

*Prior:* the only GREEN execution-side Kalshi read in either project — +4.10¢/fill [+3.39, +4.97],
n=3,196, 63 day-blocks, adverse selection ≈ 0, dead by +5 s, 35.8% locked pairs at +3.75¢ riskless.
Measured on **KXBTC15M only**; the other six series are untested.

---

## Phase 4 — Execution, disarmed  ⬜

- [ ] Port the PM executor, risk shell, and the ~32-class live battery
- [ ] **Build the Kalshi executor from scratch** — orders, positions, balances, cancels. No Kalshi
      order-placement code exists in either project; the RSA-PSS auth pattern is reusable, the rest
      is new
- [ ] Rehearse the Kalshi executor against the demo environment (place → poll → cancel → settle)
- [ ] Shadow loops that structurally cannot post
- [ ] Kill files, latching breaker, single-flight persisted across restarts
- [ ] Cross-venue additions: leg-risk measured, partial-fill policy pre-declared, net exposure in
      one place, settlement-timing mismatch handled

Arming stays a separate explicit human decision — `GATE_TO_LIVE.md` Step 9.

---

## Open items

- [ ] Project name — `Janus` is a working name
- [ ] PM `rebateRate: 0.2` is in the live fee schedule and modelled nowhere. Pin against a real
      maker fill before crediting it (currently `PM_CREDIT_REBATE = False`)
- [ ] Kalshi maker tier `0.0175` — re-verify against a real fill before sizing any maker strategy
- [ ] No measured Kalshi↔PM clock offset exists. Fine for 15m windows (matching is on implied
      close time); will not survive sub-second work
- [ ] Report upstream to Kilos: `KALSHI_15M_SERIES` lists 5 series and no XRP/HYPE, but 15
      `fifteen_min` series exist; and the `ceil` float artifact in `Phase1/costs.py`
- [ ] Later scope decision: widen past the 7-asset intersection? (sports pairs need fuzzy title
      matching; Kalshi's 100-strike hourly ladders open intra-venue no-arb checks)
