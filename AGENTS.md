# AGENTS.md — Janus cold start

> Zero-cross-context entry point. You can work this project end-to-end from the docs listed here
> without opening another project's files. ~60 seconds.

## What Janus is

Cross-venue engine over the **shared Kalshi ↔ Polymarket market corpus**. Phase-1 scope is the
exact-match intersection: **7 assets × 15-minute up/down** (BTC, ETH, SOL, XRP, DOGE, BNB, HYPE).
Two strategy families under test: **convergence** (directional, on the lagging venue) and the
**hedged two-leg** (both venues, held to resolution).

**Current phase: 0 — scaffold. No data. No capital. Nothing armed.**

## Read order

1. **This file**
2. `README.md` — what the corpus is, why the two venues are not the same contract
3. `state.yaml` — machine-readable current state
4. `VALIDATION_STATUS.md` — gate-by-gate distance to live
5. `JANUS_CHECKLIST.md` — the phase plan and its pre-registered gates
6. `GATE_TO_LIVE.md` — the promotion sequence to real capital
7. `SHARED_SERVICES.md` — the Kilos read surface and its invariants

## Sacred rules

### Read-only toward Kilos
Janus never writes to `~/Code/Kilos`, never imports its Python, never touches a `com.kilos.*` job.
Full contract + the seven invariants: `SHARED_SERVICES.md`. Two of them cost real money to learn:
Kalshi snapshot prices are **probabilities in [0,1], not cents**, and `kalshi_snapshots` spreads
are **exactly zero**, so execution claims must come from `kalshi_orderbook_snapshots`.

### Pre-registration — always, before running anything
1. Write `research/<track>/YYYY-MM-DD_<slug>/spec.yaml` with success criteria **before** you run.
2. Append a `PENDING` row to `snooping_ledger.md` **before** you run.
3. Criteria in `spec.yaml` are **immutable**. Never edit them after seeing results.

### Snooping budget
`snooping_ledger.md`. Janus starts at **0 spent test looks** and does **not** inherit Kilos' row
count. BH-FDR threshold = `0.1 / m`, m = total rows in the Janus ledger at the time of the look.
One test look = one new row. Dev-selection grids count as ONE look at the selected config. Forward
eval rows do not count.

### The 5 gates
G1 no structural/lookahead leak · G2 IC significance screen on train · G3 permutation test on the
test split (block-shuffle by `open_date`) · G4 robustness / 2× fee stress (CI excludes 0 at
stressed fees) · G5 sacred one-shot holdout.
**A gate fail is a STOP.** Never weaken a criterion or lower a threshold after seeing results.

### Never mix venue series
Measure displacement/momentum **within a single price series**. Comparing a Kalshi strike
(BRTI-derived) against a Binance spot price produced a false "efficient open" result in Kilos and
wasted a look. Cross-venue comparison is legitimate *only* between the two venues' own quoted
prices — that is the basis, and it is the point of this project.

**Amendment (2026-08-14, phase 2).** The rule above is stated too narrowly — it reads as a
*venue* rule when the real hazard is a *settlement-reference* rule. Kalshi's 15m crypto settles on
BRTI, its 15m commodities on **Pyth**, and its dailies possibly on a futures curve point, so an
**intra**-venue comparison can be the identical category error. The stronger form, which subsumes
the original:

> **Never compare two prices without first measuring the basis between their settlement
> references, regardless of venue.**

An unmeasured basis is a BLOCK, not zero. This is the same failure that made the crypto two-leg
look like 100¢ when it was worth 94.30¢ (L2).

### Disk safety
Never `rm` or `DROP TABLE` without explicit approval and proof of preservation. Check `df -h`
before any freeze or build; abort below 2 GB free. All Janus data goes to `data ->
/Volumes/Kilos/janus/` — **never the root disk** (~18 GB free, 91% full).

## Inherited findings — do not re-derive these

These were measured and paid for in Kilos. They constrain the design; they are not Janus results.

- **Kalshi leads Polymarket by ~5–10 s.** Cross-correlation of 5 s mid changes: Kalshi→PM +0.125,
  PM→Kalshi +0.032. PM reprices a ≥10 bps spot jump in median 2.2 s, and **36% of jumps are
  unrepriced within 60 s**.
- **The edge is one-directional.** Buying the PM side Kalshi favors: +8.71¢/trade at open (n=180),
  +4.447¢ on the registered mid-window rule (n=952, CI [+1.746, +7.120]). The **mirror was spent
  and FAILED**: buying the Kalshi side toward PM = −2.375¢, p=0.772. Truth sits *at* Kalshi.
- **Passive maker entry inverts the PM edge.** Queue-realistic fill 23–24%; filled windows settle
  −22¢, *unfilled* windows carry +9.4¢. A 12-cell policy grid produced 0 winners. Taker-at-open
  beats every maker cell on PM.
- **Kalshi is the opposite.** MM-at-open on KXBTC15M: +4.10¢/fill (n=3,196), adverse selection
  ≈ 0, dead by +5 s as the spread collapses 24¢ → 2¢, 35.8% of markets fill both sides for a
  riskless +3.75¢/pair. Never tested beyond BTC — that is Janus R3.
- **Backtest EV does not carry to live 1:1.** Live basis entries tracked +3.05¢, not +4.45¢ —
  backward-vs-forward quote sampling. Decompose real entries before believing any modelled EV.
- **Filters do not transfer across mechanisms.** basis ∧ funding-avoid *lowered* EV. Never
  assemble a composite post-hoc; test it as one pre-pinned cell.
- **Flat-share and flat-dollar sizing differ 12.5× at ask 0.08.** `ev_c` per $1 notional is
  scale-free and carries; every dollar-denominated risk statistic (worst day, max DD, day-Sharpe,
  concentration) does **not**.
- **An unresolved poll is not a no-fill.** Execution logs must separate a venue-authoritative
  no-fill from "no answer". Collapsing them overstates PnL, blinds the loss breaker, and makes
  retries double-buy.

## Objective

**EV¢ per trade + Sharpe per trade.** Volume and coverage are means, never ends. State the
expected EV and dSR effect of every proposed change.

## Where things live

| | |
|---|---|
| Cost/fee pins | `lib/fees/registry.py` — the only place a fee is defined (phase 2+). `lib/venue_costs.py` is the phase-1 original, kept as the regression anchor; it is frozen, not extended |
| Venue schema | `lib/schema.py` — `CanonicalKey`, `NormMarket`, `Book`, `SettleRef` |
| Venue adapters | `lib/venues/` — Protocol + registry; `normalize()` is PURE |
| Stats primitives | `lib/stats.py` — permutation, block bootstrap, dSR, BH-FDR |
| Research artifacts | `research/<track>/YYYY-MM-DD_<slug>/{spec.yaml,results.json,verdict.md}` |
| Tracks | `basis` · `catalog` · `exec` · `ops` · `mentions` · **`sports`** (phase 2) |
| Handoffs | `handoffs/` — briefs for parallel agents (`TRACK_B_BRIEF.md`) |
| Data | `data/` → `/Volumes/Kilos/janus/` |

## Phase 2 — the `sports` track (appended 2026-08-14; phase-1 scope unchanged)

Phase 1's central negative rested on **n=35** title-matched pairs. That is a matcher limit, not a
venue fact. The `sports` track attacks it where it is solvable: one game is co-listed by Kalshi,
Polymarket, every betting exchange and every book, and settlement is unambiguous.

Three rules specific to this track:

1. **Match on a canonical key, never on title similarity.** The key is
   `league + {sorted participant set} + start_time(±window) + market_type + period + line + side`.
   Both venues are anchored to an **external schedule** rather than to each other, which turns an
   O(n·m) fuzzy problem into two O(n) exact joins. Jaccard is *anti*-correlated with truth here:
   "Lakers vs Celtics Nov 3" and "Lakers vs Celtics Nov 17" share nearly every token.
2. **`liquidity_source` deduplicates.** Robinhood, Webull and IBKR all route to Kalshi's CLOB. Two
   legs sharing a liquidity source are an accounting error, not an arbitrage.
3. **An unknown ruleset is a BLOCK, not zero risk.** The sports settlement wedge (cancellation →
   LFMP vs void-at-par; tie → $0.50 vs push; tennis retirement; OT included except soccer) is the
   direct analogue of the measured 5.70% opposite-settle rate that killed the crypto two-leg.

Also established (L7): the two-leg fee floor is a **venue-pair choice spanning 7.5×**, from 3.75¢
(Kalshi+PM crypto — phase 1's pair, the most expensive available) down to 0.50¢. Phase 1's cost
conclusion was correct for its pair and over-generalized to the asset class.
