# Stage 0 — venue-agnostic schema + cost model rebuild

**Date:** 2026-08-14 · **Track:** sports · **Ledger row:** L7 (characterization, no test look)
**Kind:** arithmetic on published fee schedules. **No market data was read.** Nothing was fitted.

---

## What was built

| Module | Purpose |
|---|---|
| `lib/schema.py` | Normalized market record. The repo previously had **zero** dataclasses, Protocols or registries; every venue was ad hoc. |
| `lib/fees/models.py` | Four fee models + the Premium Charge schedule. Replaces the flat `FEE_SCENARIOS` dict of `lambda c:` that could not express order size, maker/taker, venue, or a per-market rate. |
| `lib/fees/registry.py` | Venue → model + pinned params, with per-market payload overrides winning. |
| `lib/venues/{base,registry}.py` | Adapter Protocol + registry. Removes the matcher's privileged Kalshi→PM direction. |
| `tests/test_schema_fees.py` | 18 tests, including the legacy regression contract. |

**Regression contract holds.** Every anchor in `lib/venue_costs.py` reproduces digit-for-digit
through the new API — Kalshi's per-order ceil across 7 prices and 5 order sizes, the maker tier,
the per-series multiplier, Polymarket's continuous curve, and the on-chain-verified
`pm_fee_usd(13.51, 0.37) = 0.2205`. `tests/test_lib.py` still passes 13/13 untouched.

---

## Finding 1 — the three fee families are one family for screening

Commission on net winnings looked structurally alien to a per-contract fee. It is not. Back one
outcome at price *p* for one contract of payout: stake is *p*, and if it wins you receive 1, so
net winnings are (1−*p*) and commission is *r*(1−*p*). If it loses you pay nothing. So

> **E[commission] = P(win) · r · (1−p) = r · p · (1−p)**

— the same parabola as Kalshi's 0.07·*p*(1−*p*). Verified numerically across 5 prices × 2 rates.
Every venue therefore reduces to one screening coefficient *k* in `k·p(1−p)`:

| k | Venues |
|---|---|
| 0.0700 | Kalshi taker · Polymarket crypto |
| 0.0500 | Betfair (base) · Polymarket sports |
| 0.0350 | Kalshi index series (S&P/NASDAQ, multiplier 0.5) |
| 0.0200 | Smarkets · Matchbook · Sporttrade · Betfair at max discount |
| 0.0175 | Kalshi maker |
| 0.0000 | Polymarket maker · SX Bet singles · sportsbooks (embedded vig) |

⚠ **Screening only.** The exact evaluation differs in *when* the charge lands and *what it
aggregates over*: Kalshi's ceil aggregates fills within one order; net-winnings commission
aggregates per venue per market and is state-dependent. Never mix the two in one reported number.

⚠ The collapse is specific to a **cross-venue** hedge. Cover every outcome on the *same* exchange
and its net winnings are your arb profit alone, so commission is *r*·edge — measured at **~50×
cheaper** than the same exchange holding one leg of a cross-venue pair.

⚠ A zero coefficient is **not free**. For a sportsbook the vig is inside the ask, surfacing as
`NormMarket.overround` (a −110/−110 two-way books 4.76%). The cover cost captures it because you
sum real asks. Adding a fee on top would double-count.

---

## Finding 2 — the fee floor is 7.5× lower on the right venue pair

Two-leg cover, both legs at the money, 1 contract:

| Venue pair | Fee floor |
|---|---|
| Kalshi + Polymarket crypto | **3.75¢** ← phase 1's pair |
| Kalshi + Polymarket sports | 3.25¢ |
| Kalshi + Betfair | 3.25¢ |
| Kalshi + Smarkets | 2.50¢ |
| Kalshi + Pinnacle | 2.00¢ |
| Polymarket sports + Smarkets | 1.75¢ |
| Smarkets + Sporttrade | **1.00¢** |
| Smarkets + Pinnacle | **0.50¢** |

**This qualifies phase 1's central structural conclusion.** Phase 1 found the fee floor exceeds the
tick and concluded the exchange had priced arbitrage out by construction. That was measured on
**Kalshi + Polymarket crypto — the most expensive pair available.** All 59 coherence violations it
found were 1–2¢ gross against a 3.75¢ floor. Several would clear a 1.00¢ floor.

The conclusion was right about that venue pair and over-generalized to the asset class.

**What this does NOT establish.** It says the *cost* obstacle is smaller than believed. It says
nothing about whether prices actually diverge, whether both sides are tradeable, or whether depth
exists — filters two, three and four of the phase-1 criterion, which killed more candidates than
cost did. Cheap fees on an efficient pair of venues is still no trade. That is Stage 2 and Stage 3.

---

## Finding 3 — Kalshi's ceil is a 1.14–1.59× tax at n=1

| Price | Smooth curve | Billed | Multiple |
|---|---|---|---|
| 0.10 | 0.63¢ | 1¢ | **1.59×** |
| 0.25 | 1.31¢ | 2¢ | 1.52× |
| 0.50 | 1.75¢ | 2¢ | 1.14× |
| 0.75 | 1.31¢ | 2¢ | 1.52× |
| 0.90 | 0.63¢ | 1¢ | **1.59×** |

The ceil is **per order**, so it amortizes with size but never disappears — even a 100-contract
order on a half-rate index series pays 88¢ where the smooth curve says 87.5¢.

Consequence for Track B, carried into `handoffs/TRACK_B_BRIEF.md` as trap 3: the step function is
flat 1¢ below p≈0.16 and above p≈0.84, and 2¢ in between. **Any strategy selecting on extreme
prices inherits a cost advantage with zero informational content** — and extreme prices are also
where calibration errors live, so the two confound. Every price-conditioned result must be re-run
at a flat 2¢/leg as a control.

---

## Corrections carried into the code

- **Polymarket's rate is per-market, and the pinned 0.07 is the minority case.** Measured
  distribution: 0.04 → 1,262 markets · 0.07 → 372 · 0.05 → 336 · none → 130. `match/screen.py:66`
  applied 0.07 unconditionally, so **PM edges were understated across most of the corpus** — a bug
  that biased results toward "no edge", which is the more dangerous direction. `params_for()` now
  takes the payload value; an unknown venue raises rather than defaulting.
- **`liquidity_source`** added to prevent the scanner reporting an arbitrage between a book and
  itself. Robinhood, Webull and IBKR all route to Kalshi's CLOB.
- **`exhaustive` defaults to False and `SettleRef.provenance` defaults to `"assumed"`.** Phase 1
  burned four scans inferring exhaustiveness from `mutually_exclusive`. An unknown ruleset is a
  BLOCK, not zero risk.

## Not done here

No venue adapter is implemented yet — `lib/venues/` is the interface and registry only. No network
call was made. The Betfair, Matchbook, Sporttrade, ProphetX and Novig pins are **researched, not
verified**, and are labelled `unverified` in the registry; several were reported inconsistently
across sources and Matchbook is pinned at the worst cited value. Nothing resting on those pins may
be promoted without a direct check.

**0 test looks spent. No holdout touched.**
