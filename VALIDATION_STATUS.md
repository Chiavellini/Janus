# VALIDATION_STATUS — how far Janus is from trading real money

> Updated when a gate status changes. Last updated 2026-07-24 (Phase 0).

## Honest one-line answer

**Janus has produced zero results.** It is a scaffold with a verified cost model and a mapped
corpus. Nothing has been collected, fitted, or tested. Distance to live is measured in phases,
not in tuning.

## The two gates

Every arm must pass both. Neither is close.

| Gate | Status | Blocked on |
|---|---|---|
| **EDGE** — a real edge surviving out-of-sample | NOT_STARTED | Phase 1 (pair map) → Phase 2 (collector) → R1 |
| **TRADABILITY** — legal + practical ability to trade | **OPEN on both venues** | Kalshi order placement is unbuilt (new work) |

**Tradability detail.** The operator declared non-US status on 2026-07-15, so Polymarket's
geo-block does not bind, and Kalshi is a CFTC-regulated exchange the operator can use directly.
Both venues are legally reachable. The practical gap is that **no Kalshi order-placement code
exists in either project** — Kilos never built it (its Phase C `kalshi_executor.py` was never
started). Polymarket execution is proven and portable.

## Gate-by-gate

| Gate | Status | What would move it |
|---|---|---|
| **G1** no structural / lookahead leak | NOT_STARTED | No features exist. First run when the R1 feature builder lands; port the six-check structure from Kilos' `Equity/phase2/anti_leak_audit.py` (its UTC-vs-ET check caught a real IC 0.85 → 0.02 leak). |
| **G2** IC significance screen on train | NOT_STARTED | Needs a collected panel — Phase 2. |
| **G3** permutation test on the test split | NOT_STARTED | `lib/stats.py:day_block_perm_p` is in place and ready. Needs data. |
| **G4** robustness / 2× fee stress | NOT_STARTED | The stress axis exists (`lib/venue_costs.py:STRESS_PAIRS`); nothing to stress yet. |
| **G5** sacred one-shot holdout | NOT_STARTED | **No Janus holdout era is declared** — no Janus data exists. It will be declared and sealed when the Phase-2 collector passes its 72 h soak. Kilos' sealed eras are not Janus holdouts. |

## What is actually done

- ✅ Repo scaffold, `DOCS.md` Layer-2 arm schema, fresh snooping ledger at 0 spent looks.
- ✅ Corpus mapped empirically against both live APIs: 7-asset × 15m exact-match intersection.
- ✅ Cost model built and self-tested against real anchors — Kalshi `ceil(0.07·p(1−p))` per order
  (with the per-contract vs per-order distinction made explicit), Polymarket's on-chain-verified
  `shares·0.07·p·(1−p)`, and the frozen +47/−53 / 53.0% breakeven pair reproduced digit-exact.
- ✅ Boundary contract to Kilos written, with the seven invariants that keep it safe.

## What is missing, in order

1. **Venue enumeration + pair map** (Phase 1). Neither project can currently enumerate either
   venue — Kalshi discovery is a hardcoded 5-series list, Polymarket discovery is slug
   *construction* that never asks the API what exists. This is the foundational gap.
2. **The collector** (Phase 2). 7 series × 2 venues. The binding constraint is disk, not code:
   measured ~4.8 GB/day/series of Kalshi per-delta L1 means a naive 7-series hot tier fills the
   volume in ~25 days. Cold-tier parquet + a fail-closed disk floor are mandatory, not optional.
3. **Forward era** — declared and sealed only once the collector is proven (72 h soak, ≥98%
   capture, alarms demonstrated firing).
4. **R1/R2/R3** (Phase 3), each pre-registered.
5. **Execution** (Phase 4), including the Kalshi executor, built disarmed and battery-verified.

## Known risks carried into the design

- **The two-leg trade may be structurally dead.** At Kalshi 45¢ / PM 52¢ with 0.5¢ slip, a hedged
  pair costs **101.75¢** to acquire something that pays 100¢ — negative *before* oracle risk. It
  needs a large divergence plus tight spreads on both legs merely to break even. R2's honest
  purpose is to price that, not to assume it works.
- **The convergence edge is one-directional and the profitable leg is the PM leg.** Kilos spent a
  one-shot on the Kalshi-side mirror and it FAILED (−2.375¢, p=0.772). Hedging therefore buys away
  the edge rather than protecting it.
- **Capture, not signal, is the historical bottleneck.** Kilos' live skip reasons were
  `kalshi_no_match` (308) and `feed_gap` (136). Phase 1 and 2 exist precisely to fix that, and
  their gates are coverage gates for that reason.
- **Modelled EV overstates live EV.** Kilos' live entries tracked +3.05¢ against a +4.45¢ backtest,
  explained by backward-vs-forward quote sampling. Any Janus EV claim must be decomposed at real
  entry prices before it is believed.
