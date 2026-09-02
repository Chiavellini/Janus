# 1st Investigation — multi-venue arbitrage sweep

**Date:** 2026-08-14 · **Status:** first sweep complete, all threads landed
**Prompted by:** operator challenge to the project's standing "no meaningful edge" conclusion

---

## Evidence tiers

Every claim below carries a tier. This discipline exists because during this session five relayed
claims turned out to be wrong while every directly-verified claim held.

| Tier | Meaning |
|---|---|
| **M1** | Measured directly in this session against a live API, output inspected |
| **M2** | Measured by a research agent against a live API, not independently re-verified |
| **R** | Researched from published sources (papers, venue docs) |
| **MOD** | Computed from assumed inputs — *not* an observation |
| **U** | Unverified / unknown |

---

## 1. What prompted this

The project's prior conclusion — "no tradeable cross-venue arbitrage" — was **over-stated**.
What was actually established was narrower:

- The **naive 15m crypto two-leg arb is dead** for a measured reason (5.70% opposite-settle rate on
  BTC, n=2,859, 43 days — Kalshi settles on BRTI vs `floor_strike`, PM on Chainlink vs window
  open). A "hedged" pair is worth 94.30¢, not 100¢. **[R, project's own study]**
- Everything else rested on **n = 35 title-matched pairs from a single snapshot**, with the
  rules-text verifier (`match/verify.py`) never written and blocking recall capped at 12 candidates
  per market. That is a statement about the matcher, not about the venues.

**Operator's position, upheld:** you cannot conclude market efficiency from a failed
implementation.

---

## 2. How the idea evolved

1. **Original** — Kalshi ↔ Polymarket pure arbitrage on identical contracts.
2. **Reframe 1 (operator)** — widen to more venues. Specific hypothesis: new Kalshi commodities 15m
   markets are so illiquid they must be inefficient.
3. **Reframe 2 (operator)** — *"it might not be as direct as exact same markets, especially
   considering IBKR."* Opened four relationship types: synthetic replication vs derivatives,
   logical/coherence constraints, correlated-but-distinct markets, cross-cadence within a venue.
4. **Reframe 3 (operator)** — parlays on both venues "pay less than they should."

---

## 3. Findings

### 3.1 The commodities-15m hypothesis — half right, wrong half

The series **exist and are new**: Kalshi's `fifteen_min` count went 15 → 19, adding `KXGOLD15M`,
`KXSILVER15M`, `KXWTI15M` (Commodities, **Pyth**-settled, unlike the crypto series on CF
Benchmarks) and `KXINX15M`, `KXNDQ15M`. **[M2]**

They are **not thin** — probed live: `KXWTI15M` 2¢ spread / 39,323 vol; `KXGOLD15M` 1¢ / 48,149;
`KXSILVER15M` 1¢ / 25,606. **[M2]**

And **Polymarket lists no intraday commodity market at all** (2,500-market scan + targeted
searches, zero hits; shortest commodity cadence is daily). **There is no Kalshi↔PM 15m commodity
pair; the corpus intersection does not exist.** **[M2]**

Where thinness actually lives: Kalshi's **hourly** commodity ladders (`KXWTIH`, `KXGOLDH`,
`KXSILVERH`) — spreads to 10¢, `KXWTIH` medians **15** volume per market. **[M2]**

### 3.2 Single-condition YES+NO arb — structurally impossible on both venues

**[M1]** Verified directly on Kalshi:

```
yes_bid 0.9780 + no_ask 0.0220 = 1.0000   (exact)
yes_ask 0.9790 + no_bid 0.0210 = 1.0000   (exact)
```

**[M2]** Confirmed at scale: across **124,437 Kalshi markets**, `no_ask = 1 − yes_bid` held with
**exactly 0 exceptions**. On Polymarket, **288/288** markets had `bestAsk(NO) == 1 − bestBid(YES)`
exactly.

This is structural, not empirical: a NO bid at *p* **is** a YES ask at 1−*p* in the same book, so
`yes_ask + no_ask = 2 − (yes_bid + no_bid) ≥ 1` identically. Crossing bids would self-match.

**The ~27% of documented Polymarket arbitrage [R, arXiv 2508.03474] attributed to this bucket has
no analogue on either venue's current book structure.**

### 3.3 Kalshi parlays — mispriced, and un-capturable from the taker's seat

**Measured on 208 live parlays with fully resolvable legs [M2]:** 91% price above the product of
their leg **asks**; median gap **+1.95¢**, rising from +0.09¢ (3 legs) to +2.81¢ (15+ legs).

> **⚠ Important reconciliation.** The published study [R, arXiv 2607.14430, n=12,639 parlay trades]
> measures median R = P_exec / P_ind by leg count as: **2 legs 0.991 · 3 legs 0.995 · 4 legs 0.999 ·
> 5 legs 1.005 · 10 legs 1.223 · 11 legs 1.305**. So at 2–4 legs parlays execute *at or below* the
> independent product; overpricing is a **high-leg-count** phenomenon (~3% per leg, β̂₁ ≈ 0.029).
> Our measurement used leg **asks**, so it embeds the spread on every leg. **Much of the +1.95¢ we
> measured is the maker's spread, not a pricing error.** This distinction is the whole finding.

> **⚠ The paper explicitly excludes same-game parlays** — its sample is "parlays whose legs
> reference outcomes of distinct games, excluding same-game combinations where leg outcomes are
> non-trivially correlated." **The correlated-parlay case is untested by the literature.** Kalshi
> does list same-game combos (`KXMVENBASINGLEGAME`, `KXMVENFLSINGLEGAME` — "choose any combination
> of game stats and props"). **[M2]**

**Why it cannot be captured as a taker:**

1. **No direct short.** `no_ask_dollars == "1.0000"` in 1000/1000 markets; `yes_bid_dollars ==
   "0.0000"` in 1000/1000; resting-YES-bid side empty in 80/80 orderbooks. Kalshi's help centre:
   *"Once a combo is placed and filled, it cannot be canceled or reversed."* **[M2 + R]**
   *(Affiliate sites claiming you can sell a combo on a combo order book are **false**.)*
2. **A synthetic short DOES exist — and is uneconomic.** `is_yes_only: false` on 565 of 835 legs
   means NO-side legs can be composed into combos, so for A∧B you can buy all three complement
   states. But each is its own RFQ: you **cross the maker's spread 2ᴺ−1 times** to short an
   instrument whose median markup at 2 legs is *negative*. Costs scale 2ᴺ; edge scales ~3%/leg. The
   large markups (10–11 legs, R = 1.22–1.31) would need 1,023–2,047 complement combos. **[M2 + R]**
3. **No static replication from legs.** A parlay pays $\prod 1\{leg_i\}$ — degree-N. Any static
   portfolio of legs pays $a + \sum w_i 1\{leg_i\}$ — affine. Affine cannot match a product for
   N ≥ 2. Demonstrated: on the largest negative gap (−3.69¢), parlay + NO on all four legs has a
   payoff floor of $1 against a cost of **$1.4530 — a guaranteed $0.45 loss**, because leg-NO costs
   enter as a *sum* while the payoff is a *product*. Across all 208, `parlay_ask + Σ(leg NO asks) <
   $1.00` was **never** true (min $1.18). **[M2 + arithmetic]**

Also: **69% of priceable parlays have zero resting depth**; 0 of 19 negative-gap cases survive
fees. **[M2]**

### 3.4 Polymarket parlays

**[M1]** Polymarket *does* have a Combos product (launched ~10 Jun 2026, sports only, RFQ-based).
It is **buy-only in substance** — docs permit selling before resolution but note a maker quote
*"frequently none is offered at all."* **[R]**

The market previously flagged here as a shortable PM parlay was **not a parlay product**:
`russia-x-ukraine-peace-parlay` is `nmkts: 1`, `outcomes: ["Yes","No"]`, `negRisk: None` — one
hand-written binary resolving on free-text conditions. Someone named a conjunction market "parlay."

### 3.5 Coherence / no-arbitrage scan — 59 gross violations, **0 net**

**[M2]** Coverage: 10,580 Kalshi events / 84,437 non-parlay markets / 40,000 parlay markets / 914
laddered series; 2,100 PM markets / 600 CLOB orderbooks.

| Check | Sample | Gross violations | Survive fees |
|---|---|---|---|
| Single-condition YES+NO (Kalshi) | 124,437 markets | **0** | — |
| Single-condition (Polymarket) | 288 markets | **0** | — |
| Ladder monotonicity | 29,336 adjacent strike pairs | 12 (0.041%) | **0** |
| ME partition, bid direction | 4,310 ME events | 36 | **0** |
| Band partitions | 176 fully-quoted events | 5 | **0** |
| PM negRisk, bid direction | 229 groups | 6 | **0** |

**The binding constraint is the fee floor, not depth.** Kalshi's taker fee is `ceil()`-rounded to
**≥1¢ per leg** against a **1¢ tick**. A 2-leg trade needs >2¢ gross; at mid-range prices (P≈0.6)
the fee is 2¢/leg, needing >4¢. Worst observed case:

```
KXFEDFUNDSYEAR-36JAN01-T1.75  ask 0.6200 (sz 365)
KXFEDFUNDSYEAR-36JAN01-T2.00  bid 0.6400 (sz 154.5)
gross +2.0c | fees 4.0c | NET -2.0c
```

Depth was ample (100–2,500 contracts) on most violations. **The fee floor is wider than the
arbitrage.** Closest call anywhere: `KXBILLSCOUNT-26AUG`, net **exactly 0.00¢**.

11 of the 12 monotonicity violations were still standing on a re-fetch 4 minutes later, so these
are real quotes, not snapshot staleness.

> **⚠ Methodological warning — carry this forward.** Four separate scans in this task produced
> large, exciting, entirely false results:
> - **251 "violations" up to 86¢** — grouping on `event_ticker` + `floor_strike` matched *opposite
>   teams* (`KXNFLSPREAD` Saints-by-4.5 vs Lions-by-5.5). Correct key is the `yes_sub_title`
>   template with numerals stripped.
> - **40 "partitions" up to +86¢ net** — `mutually_exclusive` means mutually exclusive, **not
>   exhaustive**. `KXLAPRIMARY` lists 2 candidates with no "other"; `KXBBCHARTPOSITIONALBUM` ranks
>   1–10 only. Buying all legs of a non-exhaustive set guarantees nothing.
> - **52 band "partitions" up to +87¢** — tail legs excluded. `KXLOWTLAX`: bands-only sum 0.09
>   ("+91¢ arb"); all six legs sum **1.07**, no arb.
> - **21 negRisk "partitions"** — sampling truncation. PM negRisk events *are* exhaustive but
>   append "Other" plus lettered placeholders resting at `bestAsk = 1.00`. True leg counts:
>   `nobel-peace-prize-winner-2026` 20 sampled vs **71 actual**, true ask-sum **51.38**. **PM's
>   negRisk partition arb is unreachable by construction.**
>
> **A partition scan that does not verify exhaustiveness from the rules text is a random-number
> generator.**

### 3.6 IBKR / ForecastEx — confirmed inefficient, uselessly so

**[M2, from ForecastEx's free unauthenticated CSVs]** 172 products listed, including short-dated
crypto and commodities — but **daily is the floor**. Whole-day volumes across all expiries:
`METLG` gold 8,844 pairs · `COMCO` WTI 6,517 · `CFBTC` 1,105 · `COMHH` natgas **0**. Gold's Aug-14
ladder traded **2 of 23 strikes**. A single `KXGOLD15M` market medians 66,141. **~1000× thinner.**
Against a 1% round-trip fee on $1 notional you need >1.5% gross dislocation to break even.

**[R]** IBKR is now a **router** (since 2026-05-14) across Kalshi + CME + ForecastEx — the Kalshi
leg through IBKR is a duplicate price. Paper accounts cannot get real-time data. Event-contract
history is **destroyed at expiry** in IBKR's API.

### 3.7 Synthetic replication vs option chains — untested; prior numbers were modelled

Theory is sound: $D(K) = -\partial C/\partial K$, and the risk-neutral objection largely cancels for
identical payoffs. Replication error $\varepsilon(h) \approx h f_\mathbb{Q}(K) + 2s/h$ — tightening
strikes *amplifies* spread cost. **[R]**

**The previously-stated ±5pp WTI / 2–6pp SPX figures are [MOD], not findings.** No IBKR key exists;
no option chain was ever pulled; volatility and option bid/ask were assumed.

Solid **[R]**: CL and COMEX metals options are **American** (contaminating $-\partial C/\partial K$);
SPX/SPXW/XSP and ES are **European, cash-settled, with 0DTE**, making index the only theoretically
clean family; Kalshi's 15m contracts have **no listed derivative expiring in 15 minutes**, so no
hedge exists there at all.

### 3.8 Venue landscape

**[R]** Nearly every venue is sports-only with no commodity/crypto/index/FX coverage. The entire
2025–26 land grab (20+ new CFTC DCM filings) is sports.

- **Robinhood** — Kalshi-routed. Also routes to **Rothera** (independent, no public API).
- **Sportsbook correlated parlays — dead.** Correlation-aware SGP engines standard since 2019
  (FanDuel) / 2021 (DraftKings, Caesars). Pinnacle defends itself by refusing non-moneyline
  parlays outright, and closed its public API in Jul 2025. Parlay hold is 20–30% (SGP often >35%)
  vs 4–5% on straights; SGPs are now 35–40% of US online GGR. No audited profitable
  correlated-parlay evidence post-2024 exists — everything claiming it is affiliate SEO.
- **Account limiting** — UKGC 2025: 4.31% of active accounts restricted, and **46.78% of restricted
  accounts are in profit**. Trigger is consistent CLV, not realised P&L.
- **Smarkets** allows laying custom accumulators, **but forbids >1 selection per match** — which
  excludes same-game correlation by construction. Betfair confines multiples to its Sportsbook.
- **CME event contracts** — daily expiry on the right underlyings, real liquidity, **two-sided**,
  reachable via the same IBKR integration. Still the strongest unprobed lead.
- **Limitless** — real CLOB, REST+WS, non-KYC, hourly crypto.

### 3.9 The one opening found — and it is not arbitrage

**[R + M2]** **SX Bet** is the only venue that is simultaneously non-US-accessible, KYC-free,
API-open (free), permits **retail to post maker orders**, and runs a parlay RFQ whose **own maker
documentation recommends naive independence multiplication with no same-game restriction**:

> *"The simplest approach is to multiply the implied probabilities of each leg."*

Fee structure corroborates: **0% on singles, 5% on parlay profit only** — SX runs singles as a
zero-rake CLOB and monetises the parlay layer, i.e. treats parlay flow as the spread-bearing
product.

A parallel gap exists on Kalshi: an [RFQ census](https://www.oddpool.com/research/kalshi-rfq-market-makers)
(270 test RFQs, late May 2026) found only **13 distinct quoter IDs**, split 8 singles-only / 5
combos-only with zero overlap, two "backbone bots" answering ~50% of requests, apparently **one**
combo specialist pricing correlation properly, inside spread **unchanged from 2-leg to 5-leg**, and
**zero retail quoters**.

**But this is a market-making business, not arbitrage.** It is an adverse-selection problem (your
counterparty may know the injury report first), it requires real correlation estimation rather than
a price-comparison loop, and on Kalshi it needs sub-200ms quoting against SX's more forgiving
3-second window.

**[U] Open question worth one cheap API test:** whether Kalshi's RFQ `create-quote` honours a
`no_bid` on a *multivariate* RFQ. The schema exposes both fields; the docs do not confirm both
sides are honoured for combos. That single answer determines whether Kalshi is a one-way or
two-way venue for a quoter.

---

## 4. Dead legs

| Leg | Why | Tier |
|---|---|---|
| Single-condition YES+NO arb, **both venues** | NO side is an exact complement; 0 exceptions in 124,437 Kalshi + 288 PM markets. Structurally impossible | **M1 + M2** |
| Ladder monotonicity arb | 12 violations in 29,336 pairs; gross 1–2¢ vs 2–4¢ fees. **0 survive** | **M2** |
| Partition-sum arb (Kalshi ME, bands, PM negRisk) | 47 gross, **0 net**. Loose-looking partitions are non-exhaustive sets; PM's are padded with placeholders at ask 1.00 | **M2** |
| Kalshi parlay overpricing | Real at high leg counts, but no taker short; synthetic short costs 2ᴺ spreads; no static replication | **M2 + R** |
| Polymarket parlays | Buy-only in substance; exit quotes "frequently none offered" | **R** |
| Kalshi↔PM 15m commodity pair | PM lists no intraday commodity at all | **M2** |
| IBKR/ForecastEx as a short-dated leg | Daily floor; ~1000× thinner than Kalshi | **M2** |
| Robinhood as an independent price | Kalshi-routed | **R** |
| Sportsbook correlated parlays | SGP engines since 2019–21; no API; account-limited into irrelevance | **R** |
| Smarkets/Betfair as a parlay short | Smarkets forbids >1 selection per match; Betfair multiples are Sportsbook-only | **R** |
| Implication constraints $P(A)\le P(B)$ | 0.24% of documented profit; semantic non-fungibility is permanent | **R** |
| Cross-venue identical-contract arb (naive) | Oracle risk premium priced correctly; professional competition | **R** |
| Commodity daily replication vs CME options | American exercise + 7–25pp curve basis | **R** |

---

## 5. Live legs

| Leg | Status | Note |
|---|---|---|
| **CME event contracts** | **UNTESTED — best remaining lead** | Daily, two-sided, real liquidity, right underlyings, same IBKR integration. The only surveyed venue meeting all three of: price possibly wrong, both sides tradeable, depth non-trivial |
| **SX Bet parlay market-making** | **UNTESTED — the one structural opening** | Maker docs recommend independence multiplication with no same-game restriction. Non-US, no KYC, free API, retail may quote. **Not arbitrage — an adverse-selection business** |
| **Kalshi RFQ two-way quoting** | **UNTESTED, [U]** | Does `create-quote` honour `no_bid` on multivariate RFQs? One cheap API test. Only 13 quoters, 1 pricing correlation, zero retail |
| **SPX/XSP 0DTE vs Kalshi index markets** | **UNTESTED** | Only theoretically clean replication family. Requires a real option chain to compute $\varepsilon(h)$ **before** any comparison |
| **Limitless** | **UNTESTED** | Real CLOB, non-KYC, hourly crypto — a genuine independent price |
| **Cross-cadence within Kalshi** | **UNTESTED** | 15m Pyth-settled vs daily CME-futures-settled on the same underlying |
| **The matcher rebuild** | **UNTESTED** | The original thesis. `match/verify.py` never written; recall capped at 12/market; no rules text ever read |
| **Correlated-but-distinct markets** | **UNTESTED** | Requires a model of the link — relative value, not arbitrage. Highest fake-signal risk |

---

## 6. Infrastructure facts worth keeping

- **Kalshi renamed every pricing field.** Old names absent; now `yes_bid_dollars` etc. —
  **decimal-dollar strings**, not int cents; `volume_fp`/`open_interest_fp` are **fractional**;
  orderbook top-level key is `orderbook_fp`. **[M1]**
  *`catalog/enumerate_kalshi.py` already handles this — its `f()` helper documents the rename. The
  repo is NOT broken.* **[M1]**
- `GET /markets?status=open` is **100% parlay shells**. Use `?series_ticker=<T>`. **[M2]**
- Multivariate events are **excluded** from `GET /events` — use `GET /events/multivariate`. **[M2]**
- `GET /series` returns all ~13,017 series in **one uncursored call**. **[M2]**
- Only **one market is open per Kalshi 15m series at a time** — pollers must re-discover the ticker
  every 15 minutes. **[M2]**
- **PM gamma 403s a `python-urllib` User-Agent**; curl's UA passes. 422s past offset ~2000. **[M2]**
- **PM fee schedule is not uniform.** Measured: **0.04 → 1,262 markets · 0.07 → 372 · 0.05 → 336 ·
  none → 130**, all `takerOnly: true, exponent: 1`. The pinned 0.07 in `lib/venue_costs.py` is the
  minority case, and `match/screen.py:66` applies it unconditionally while the Kalshi path
  correctly honours per-series multipliers. **PM fees are overstated across most of the
  corpus.** **[M2]**
- **Kalshi now pays ~4.05% APY on cash *and* open positions** — demolishes the "discounting
  explains the gap" argument and materially helps hold-to-resolution. **[R]**
- **ForecastEx publishes a free, unauthenticated full trade tape** (`forecastex.com/api/download`),
  ~48 pages history, refreshed every 10 min. **[M2]**
- **Kalshi `is_yes_only`** (per-leg, via `GET /multivariate_event_collections/{ticker}`) governs
  whether a leg's NO side may be *composed into* a combo. It does **not** make combos shortable.
  Measured 565 false / 270 true on `KXMVESPORTSMULTIGAMEEXTENDED-R`. **[M2]**
- PM added a **5-minute** up/down family; 7 → 8 crypto underlyings (`zec`). **[M2]**

---

## 7. Corrections made during this investigation

Recorded because the pattern *is* a finding: **everything verified directly held; everything
relayed without checking did not.**

| Claim | Status |
|---|---|
| Butterfly convexity applies to digital strike ladders | **Wrong.** A ladder *is* the survival function; its first difference is the density. Convexity would require a monotone-decreasing density — not a no-arb condition. Correct checks: **monotonicity + partition-sum only** |
| The repo silently reads `None` for Kalshi prices | **Wrong.** Handled since July |
| Replication bracket is ±5pp WTI / 2–6pp SPX | **Modelled, not measured.** Stated as finding; no option chain was ever pulled |
| Parlay-vs-legs has "zero model risk", ranked #1 | **Wrong.** Full model risk via the independence assumption |
| Walked back "cannot replicate a conjunction from marginals" under pushback | **The original argument was right.** Should not have folded. The check it prompted (are joint states listed?) was correct to run |
| PM parlays are two-sided and shortable | **Wrong.** The search matched a market *title*; PM Combos are buy-only in substance |
| Parlays are overpriced, growing with leg count | **Half wrong.** True at 5+ legs; at **2–4 legs the published median R is 0.991–0.999, i.e. at or below the independent product.** Our +1.95¢ was measured against leg **asks** and therefore embeds the spread |
| "No venue lets you short a parlay" | **Too strong.** A synthetic short **is** constructible on Kalshi via 2ᴺ−1 complement combos. It is uneconomic, not impossible |

---

## 8. What this means

The project's central law survives, properly scoped:

> Where two venues genuinely list the same market, they agree on price. Where the edge is large,
> the markets are not the same.

This sweep adds something sharper. **Prices are demonstrably and publicly wrong** — parlays carry a
~3%/leg markup, 59 hard logical violations were standing in live books, and the operator's
observation about parlays was empirically correct. **None of it is capturable**, and the reasons
are structural rather than competitive:

1. **The fee floor exceeds the tick.** Kalshi's `ceil()` taker fee is ≥1¢ per leg against a 1¢
   tick. Any 2-leg logical arb needs >2¢, most need >4¢. Observed violations were 1–2¢. The
   exchange has priced the arbitrage out of existence by construction, not by competition.
2. **The venue closes the profitable side.** Parlay markup is real and un-shortable. The synthetic
   short exists but costs 2ᴺ spreads to harvest an edge that scales ~3%/leg.
3. **What looks loose isn't.** Every large partition "violation" dissolved on reading the
   resolution rules — non-exhaustive sets, excluded tails, placeholder legs at ask 1.00.

**So the question to select on is not "where is the price wrong."** That is answered and the answer
is "in public, persistently." The question is **"where is the price wrong AND both sides tradeable
AND the edge larger than the fee floor AND depth non-trivial."** All four, in that order. The
second and third have killed more candidates in this sweep than the first.

And the one opening that survived all four points somewhere else entirely: **the markup is the
maker's spread, so the only seat that collects it is the maker's.** That is a different business
with a different risk (adverse selection, not basis), and it is worth being explicit that it is not
what this project was built to do.

---

## 9. Next

1. **Probe CME event contracts** — strongest unexplored lead; the only surveyed venue with the
   right underlyings, daily expiry, real liquidity and two-sided trading.
2. **One cheap API test:** does Kalshi `create-quote` honour `no_bid` on a multivariate RFQ? Decides
   whether Kalshi is one-way or two-way for a quoter. **[U]**
3. **Pull `settlement_source` per Kalshi series** and resolve whether `PYTHOIL` / `Metal.Index.*`
   map to a spot/CFD feed or a specific futures curve point. Determines whether the 7–25pp curve
   basis applies to any commodity comparison. **[U]**
4. **If a rate is ever wanted for coherence violations**, it needs the same scan polled at fixed
   intervals with each candidate re-confirmed against a live orderbook, over ≥1 week — plus the
   *trade* feed, not the quote feed. A violation standing in a book is not proof anyone took it.
   One snapshot cannot produce a rate and none is claimed here.
5. **Decide architecture only after the above.** The audit found the two-venue assumption is baked
   into record shapes, field names, pair keys, fee dispatch and the trade algebra — `lib/stats.py`
   and `lib/fetch.py` are the only reusable pieces.

**No test looks spent. No holdout touched. Everything above is characterization.**
