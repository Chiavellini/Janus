# Track B — HFT & quantitative strategies on Kalshi / Polymarket / IBKR

**Issued:** 2026-08-14 · **Mandate:** research + backtest only · **Snooping budget at issue:** 0 looks spent
**Runs in parallel with Track A** (multi-venue sports arbitrage). The two tracks share `lib/` and the
snooping ledger. Coordinate before editing shared modules.

---

## 0. Read first

1. `AGENTS.md` — the constitution. Sacred rules, inherited findings, the 5 gates.
2. `1ST_INVESTIGATION.md` — what phase 1 killed and why. Its **§7 corrections table** is the most
   important page in this repo for you: it records that *everything verified directly held, and
   everything relayed without checking did not.*
3. `snooping_ledger.md`, `state.yaml`, `SHARED_SERVICES.md`.

Source material for this track: `quant_strategies_rentech_citadel.pdf` — ~25 strategy families
across RenTech, Citadel LLC and Citadel Securities, with an evidence-graded summary in Appendix A.

---

## 1. The mission, and the law that scopes it

The operator's hypothesis: *HFT strategies should be extremely inefficient on Kalshi and Polymarket;
these venues are drastically different from regular exchanges yet offer somewhat similar
instruments.*

The hypothesis is half right, and the half that is wrong is the more important half. Sort the
measured evidence:

| Evidence of inefficiency | Evidence of efficiency |
|---|---|
| Kalshi leads PM by 5–10 s; **36% of ≥10bps spot jumps unrepriced at 60 s** | 59 gross coherence violations, **0 net** |
| Opening spread **24¢ → 2¢ in 5 s** | `no_ask ≡ 1−yes_bid` exact in 124,437 markets |
| 13 RFQ quoters total, 1 pricing correlation, **0 retail** | Ladder monotonicity: 12 breaks in 29,336 pairs, 0 net |
| Retail-dominated, uninformed flow | Cross-venue mention agreement: 0.52pp mean divergence |
| MM-at-open **+4.10¢/fill**, adverse selection ≈ 0 | PM maker fills settle −22¢ while unfilled carry +9.4¢ |

These are not in tension. They say one thing:

> ### **These venues are inefficient in liquidity provision, not in price.**
> The price is anchored by an underlying anyone can observe for free. What is missing is anyone
> willing to quote in the first five seconds.

**Consequence, and your scoping rule:** every family whose return source is *"know the value better
than the market"* is dead here. Every family whose return source is *"be present when nobody else
is"* is live. That single cut disposes of roughly two-thirds of the taxonomy.

---

## 2. Governance — binding, non-negotiable

- **Mandate is research + backtest only.** `arming_allowed: false`. Nothing may be placed in a live
  book. Where a question is unanswerable without resting orders, **say so explicitly** and put it in
  the §8 costed-proposal list. Do not silently model it and report the model as a measurement.
- **Pre-registration.** Write `research/<track>/YYYY-MM-DD_<slug>/spec.yaml` with success criteria
  **before** you run. Append a `PENDING` row to `snooping_ledger.md` **before** you run. Criteria are
  **immutable** afterwards.
- **Snooping budget.** Starts at 0. BH-FDR threshold = `0.1 / m`, m = ledger rows at the time of the
  look. One test look = one new row. Characterization rows (`L#`) are free.
- **The 5 gates.** G1 no structural/lookahead leak · G2 IC screen on train · G3 permutation on the
  test split, block-shuffled by `open_date` · G4 robustness / 2× fee stress · G5 sacred one-shot
  holdout. **A gate fail is a STOP.** Never weaken a criterion after seeing results.
- **Disk.** All data to `data -> /Volumes/Kilos/janus/`. Never the root disk (~18 GB free, 91% full).
  Check `df -h` before any build; abort below 2 GB. Never `rm`/`DROP TABLE` without explicit approval.
- **Read-only toward `~/Code/Kilos`.** Never write, never import its Python, never touch a
  `com.kilos.*` job. Your launchd namespace is `com.janus.*`.

### Evidence tiers — mandatory on every claim

`M1` measured directly by you against a live API, output inspected · `M2` measured by a subagent, not
re-verified · `R` researched from published sources · `MOD` computed from assumed inputs, **not an
observation** · `U` unverified.

**Tiers propagate as a minimum, not a maximum.** A number derived from M1 quotes plus a MODELLED fill
is **MOD**, not M1. Every headline carries the weakest tier in its derivation chain. This rule exists
because phase 1 reported a modelled replication bracket (±5pp WTI) as a finding; the operator caught
it, and it cost credibility.

---

## 3. Already measured — do NOT re-derive these

Paid for in Kilos. They constrain your design; they are not your results.

- **Kalshi leads Polymarket by ~5–10 s.** 5s mid-change cross-correlation: Kalshi→PM +0.125,
  PM→Kalshi +0.032. PM reprices a ≥10bps spot jump in median 2.2 s; **36% unrepriced within 60 s**.
- **The edge is one-directional, and the mirror is SPENT.** Buying the PM side Kalshi favours:
  +8.71¢/trade at open (n=180); +4.447¢ on the registered mid-window rule (n=952, CI [+1.746,
  +7.120]). Buying the Kalshi side toward PM: **−2.375¢, p=0.772 — spent and failed.** Truth sits *at*
  Kalshi.
- **Passive maker entry inverts the PM edge.** Queue-realistic fill 23–24%. Filled windows settle
  **−22¢**; *unfilled* windows carry **+9.4¢**. A 12-cell policy grid produced 0 winners.
- **Kalshi is the opposite.** MM-at-open on `KXBTC15M`: **+4.10¢/fill (n=3,196)**, adverse selection
  ≈ 0, dead by +5 s as the spread collapses 24¢ → 2¢, and **35.8% of markets fill both sides for a
  riskless +3.75¢/pair.** Never tested beyond BTC. ← *your flagship lead*
- **Backtest EV does not carry 1:1.** Live basis entries tracked +3.05¢, not +4.45¢ — backward-vs-
  forward quote sampling.
- **Filters do not transfer across mechanisms.** basis ∧ funding-avoid *lowered* EV. Never assemble a
  composite post-hoc; test it as one pre-pinned cell.
- **Flat-share vs flat-dollar sizing differ 12.5× at ask 0.08.** `ev_c` per $1 notional is scale-free
  and carries; every dollar-denominated risk statistic does not.

### ⚠ The flagship number is an upper bound

**+4.10¢/fill is computed as though you were filled at an observed touch on a book you were not in.**
Your quote changes the queue and may deter the very taker that filled the incumbent. The quotes are
M1; **the fill layer is MODELLED**; so the headline inherits tier **MOD**.

The inherited PM result is the empirical proof that this correction is not small: filled windows
−22¢ vs unfilled +9.4¢ is a **31¢ gap** between "what the book did" and "what you would have got."

---

## 4. Infrastructure facts — verified against disk, 2026-08-14

**(a) Only BTC Kalshi data exists.** `[M1]`
```
kalshi_ob_data.db  kalshi_open_episode_samples : KXBTC15M | 68,482 rows | 2026-07-21 → 2026-08-03
market_data.db     kalshi_open_episode_samples : KXBTC15M | 20,901 rows | 2026-07-17 → 2026-08-03
kalshi_ob_data.db  kalshi_orderbook_snapshots  : KXBTC15M | 25,194,948 rows | 2026-07-25 only
```
Every non-BTC question is a **collection** problem, not an analysis problem.

**This resolves the coordination hazard for free.** Kalshi MM-at-open is registered in Kilos as its
snooping row 20 with a forward clock from 2026-07-21 — which overlaps the BTC episode set exactly.
**Declare the BTC episode set unreadable for Janus**, enforce it in `lib/kilos_data.py`, use the
published BTC numbers as a *prior only*, and collect fresh on the six untested series where Kilos has
no claim. No negotiation needed.

**(b) The 4.8 GB/day/series figure is the wrong budget for your question.** That is *continuous
per-delta L1*. The BTC episode sampler ran ~51 samples × 96 windows ≈ **4,900 rows/day/series, order
1 MB/day** — roughly 5,000× cheaper. MM-at-open needs only the first ~60 s of each window. Episode
capture across all 19 `fifteen_min` series ≈ **20 MB/day**. Full-delta on *one* series is 4.8 GB/day.
These are different projects; do not conflate them.

**(c) The rate limit binds exactly where the edge is.** Basic tier = 200 read tokens/s, most requests
cost 10 → ~20 req/s. All 15-minute series open on the *same* `:00/:15/:30/:45` instant. 19 series ×
1 Hz ≈ **190 tokens/s against a 200 ceiling**, before ticker re-discovery. REST polling cannot
capture the open across the series set with any headroom. **The authenticated WebSocket is a
precondition, not an optimization.**

**(d) Other venue mechanics.**
- **Kalshi's orderbook returns BIDS ONLY** — YES asks are expressible only as NO bids. Fold the NO
  side in or half the market is invisible. See Trap 1.
- Only **one market is open per 15m series at a time**; pollers must re-discover the ticker every
  15 minutes. Its failure mode is Trap 2.
- **PM rate limiting queues rather than rejects** — you see latency, not errors. A slow response is a
  *stale* quote wearing a fresh timestamp. Record `receive_ts`, `exchange_ts`, `late_by`; drop
  samples above a pre-declared `late_by` rather than using them.
- Kalshi renamed every pricing field to **decimal-dollar strings** (`yes_bid_dollars`);
  `volume_fp`/`open_interest_fp` are fractional; orderbook key is `orderbook_fp`.
  `catalog/enumerate_kalshi.py` already handles this — read its `f()` helper.
- **PM fee schedule is not uniform**: measured 0.04 → 1,262 markets · 0.07 → 372 · 0.05 → 336 · none
  → 130. `match/screen.py:66` applies 0.07 unconditionally, so **PM edges are currently understated
  across most of the corpus.** Resolve fees per market from the venue payload, never from a
  module-level constant. (Track A is rebuilding this into `lib/fees/`; coordinate.)
- Kalshi pays **~4.05% APY on cash *and* open positions**.

---

## 4b. ADDENDUM — what changed after this brief was issued

*Appended 2026-08-17. The brief above is unchanged; this section supersedes it where they conflict.*

Track A completed Stages 0 and 1 in the interim. Four things now differ from what §4 assumed:

**1. `lib/fees/` EXISTS — use it, do not build one.** The rebuild referenced at the end of §4 is
done (ledger row **L7**, `research/sports/2026-08-14_cost-model-rebuild/`). The API:

```python
from lib.fees.registry import model_for, params_for, screening_coeff
from lib.fees.models import Fill
```

`lib/venue_costs.py` is **frozen as the regression anchor** — it still reproduces digit-for-digit
and `tests/test_lib.py` is 13/13 — but do not extend it. Per-market payload values override the
pins automatically via `params_for()`, which is the fix for the unconditional-0.07 bug above.
An unknown venue **raises** rather than defaulting to zero.

**2. Two results from L7 bear directly on your phases.**

- *All three fee families collapse to one screening form*: `k·p(1−p)`. Commission-on-net-winnings
  has expected cost `r·p(1−p)` for a cross-venue hedge — the same parabola as Kalshi's
  `0.07·p(1−p)`. Screening only; never report it as an exact cost.
- *Kalshi's `ceil()` is a 1.14–1.59× tax at n=1, and it is a STEP FUNCTION* — flat 1¢ below
  p≈0.16 and above p≈0.84, 2¢ in between. This is already trap 3 in §9, but it is now measured
  rather than argued. **Every price-conditioned result you produce must be re-run at a flat
  2¢/leg as a control.** Extreme prices are also where calibration error lives, so cost advantage
  and signal confound exactly there.

**3. `lib/schema.py` and `lib/venues/` exist.** If you normalize a venue payload, use
`NormMarket`/`Book`/`Quote` rather than inventing a record. Two invariants hold everywhere: every
price is a YES-probability in [0,1], and every size is in contracts (= $1 payout units).
`normalize()` must be **pure** — no network, no clock, no randomness. `liquidity_source`
deduplicates: Robinhood, Webull and IBKR all route to Kalshi's CLOB, so two legs sharing one are
an accounting error, not an arbitrage.

**4. `lib/fetch.py` had a live cache-key bug, now fixed.** The response-cache key was the request
URL built with `urlencode(params)`, which preserves **dict insertion order** — so the same query
written in a different parameter order was a separate cache entry. If you wrote any crawler
against the old behaviour, its cache is invalidated (a re-fetch, not a correctness problem).

**Also worth knowing, though it is Track A's finding (L8):** Kalshi's `close_time` /
`expiration_time` are the scheduled event time **+ 3 days** on sports series, and
`expected_expiration_time` / `occurrence_datetime` are the expected *end*. This is a sports-series
convention and has NOT been checked on the 15-minute crypto series you care about — **verify it
there before trusting any Kalshi timestamp field as an event time.** Given the settlement-reference
rule below, assuming a field means what its name suggests is exactly the error class to avoid.

**One upstream amendment is now in `AGENTS.md`**, and it tightens a rule you inherit. "Never mix
venue series" was too narrow — Kalshi 15m crypto settles on BRTI, 15m commodities on **Pyth**, and
dailies possibly on a futures curve point, so an *intra*-venue comparison can be the identical
category error. The binding form is now:

> **Never compare two prices without first measuring the basis between their settlement
> references, regardless of venue.** An unmeasured basis is a BLOCK, not zero.

This bites on your cross-asset lead–lag and vol-arb phases specifically.

---

## 5. The taxonomy, mapped

### Structurally inapplicable — with the reason

| Family | Why it cannot transfer |
|---|---|
| Cross-sectional stat arb (RenTech / Citadel GQS) | Requires many *long-lived* assets with an estimable factor structure and mean-reverting residuals. A 15-minute binary has one path and a terminal 0/1 — no residual return series. The only genuine cross-section is a strike ladder, whose factor structure is *known exactly* (it is the survival function), so its residuals are the coherence scan — already run, **0 net**. |
| Trend / momentum | Contract-price momentum is a monotone transform of the underlying's move: levered crypto momentum in a 0/1 wrapper with a 1¢ fee floor. Not an independent return source — and its geometry invites the exact "never mix venue series" error. If you want crypto momentum, trade crypto. |
| **ML combination of thousands of weak signals** | **The decisive kill.** RenTech stacks weak signals because marginal cost is <1bp, so a 2bp signal is harvestable. Here `ceil(0.07·C·P·(1−P))` is ≥1¢ against a 1¢ tick → minimum viable signal is **200–400 bps**. The entire weak-signal regime sits below the cost floor. **Correct model complexity here is 1–3 parameters; reject any proposal with more on sight.** |
| ETF creation/redemption arb | **Enforced by the matching engine.** PM holds `ask_up+ask_down = 1.00+spread`; Kalshi defines `no_ask ≡ 1−yes_bid`, so `yes_ask+no_ask ≥ 1` identically. Not empirically tight — structurally impossible. |
| Index / futures–cash basis | A binary is not linear in the underlying, so "basis" is undefined without a distributional model. **Reclassify as vol arb** (family V below). |
| Convertible arb · Credit/capital-structure RV · Fixed-income RV | No converts, no credit instruments, no bonds/curve/repo. (One narrow FI survivor is carved out below.) |
| Options market making · Treasuries/rates/FX MM | No options and no such instruments listed with two-sided access. (A strike ladder *is* a digital chain — folded into V.) |
| Retail internalization / PFOF **as a business** | Requires a broker relationship and purchased flow. Neither venue has PFOF. *(The insight survives — see family F.)* |
| Microsecond latency / cross-venue arb | No colocation, no Reg NMS, no NBBO, rate-limited REST/WS. *(The 5–10 s analogue survives — see family L.)* |
| Merger / event-driven | Kalshi lists the events, but the edge is a legal judgement, the resolution risk *is* what the contract prices, there is no hedge instrument, and n=1 per event forbids cross-sectional inference. This is discretionary betting. It will look attractive. It is out of mandate. |
| Multi-manager equity market-neutral · Talent/secrecy · Basket-option leverage | Organizational forms and financing structures, not strategies. n=1 operator, own capital, no prime broker. |

Also already killed in phase 1 and not to be revisited: single-condition YES+NO arb, ladder
monotonicity arb, partition-sum arb, Kalshi parlay overpricing, PM parlays, ForecastEx as a
short-dated leg, Robinhood as an independent price, sportsbook correlated parlays.

### What transfers

**M — Electronic market making (§6.1).** Strongest fit; already has a measured positive result.
- *Microprice / order-book imbalance* — transfers, **subject to Trap 1**.
- *Glosten–Milgrom adverse selection* — transfers **with modification**. Toxicity here is not "the
  counterparty knows the fundamental" (everyone sees BTC); it is **latency toxicity against a public
  reference** — the taker saw the spot tick before the quote refreshed. That makes it *estimable
  offline* by joining quote timestamps to the reference feed. A rare gift; use it.
- *Ho–Stoll / Avellaneda–Stoikov inventory control* — transfers **in form, degenerates in practice**.
  A–S was built for exactly this problem (known terminal time, self-liquidating inventory), which is
  why it is tempting. But on a 1¢ tick over [0,1] the reservation-price adjustment `q·γ·σ²·(T−t)` is
  **smaller than one tick** for nearly all inventory levels. The continuous control collapses to a
  2–3 state policy: quote at the touch, one tick off, or don't quote. **The elegance buys nothing;
  the tick dominates.** Put the effort into the fill-intensity curve λ(δ) instead — and note λ(δ) is
  not estimable without resting orders (§8).

**P — Index-rebalance / predictable-flow trading (§6.6). The better framing for MM-at-open.**
Citadel's version harvests a calendar-scheduled, size-known, price-insensitive flow. **These venues
manufacture one 96 times a day per series**: a brand-new book opens with zero inventory and a 24¢
spread that collapses in 5 s. Two further instances: roll flow from the expiring window into the
next, and the published near-expiry insurance demand (arXiv 2607.14430 — calibration goes step-like
in the final ten minutes as losing holders buy back).

This reframing is not cosmetic. It predicts the edge is a function of *the schedule*, so it should
generalize across series **in proportion to how many participants are watching the clock** — a
directly falsifiable prediction, and Phase B tests it.

**S — Short-horizon mean reversion, conditioned off around news.** The opening spread collapse *is*
flow-driven displacement reverting. The "condition off around real news" analogue is precise and
cheap: condition off around large underlying jumps. Note the inherited asymmetry — on PM passive
entry *inverts* the sign, on Kalshi it works. **That asymmetry is itself the finding. Explain it; do
not average over it.**

**L — Cross-asset lead–lag.** Already the project's best-measured fact, but **the profitable
direction is spent.** Remaining new content: does the lead survive on the 6 alts; does BTC lead the
alts *within* Kalshi; cross-cadence 15m vs hourly vs daily. ⚠ On the second: two Kalshi contracts on
correlated assets share index-feed infrastructure, so an apparent "lead" may be feed-publication
timing, not information.

**V — Volatility arb (§5.7). The most interesting untouched family.** A strike ladder at one expiry
*is* a discretized risk-neutral CDF, since `D(K) = −∂C/∂K`. So Kalshi's hourly/daily ladders imply a
full distribution, extractable and comparable against a real, liquid, European, 24/7 option surface
— and **Kilos already collects `deribit_options`**. Uniquely in this program, there is a *tradeable
hedge instrument on the other side*. Three hard caveats: (i) 15m contracts have **no** matching
option expiry, so this works only on daily/hourly ladders; (ii) settlement references differ (BRTI vs
Deribit index) so the oracle-basis procedure is **mandatory before** any comparison; (iii)
*dispersion* does not transfer — no crypto index contract exists.
Best sub-case: **variance-risk-premium harvesting on the ladder tails**, since the published
near-expiry calibration break says retail systematically overpays for far-OTM legs.

**F — Flow segmentation (§6.2 restated). The most novel transfer.** PFOF as a business is dead, but
the *mechanism* — segregated uninformed flow is cheap to fill — is available here **with nobody
paying for it, on a public book**. You cannot segment by counterparty identity, so segment by
observable proxy: seconds-since-open, order size, round-lot vs odd-lot, inferred aggressor side,
series, time-of-day, proximity to a macro release. *Can toxic and benign flow be separated from
public tape features alone?* Fully answerable offline for the classification.

**C — Capacity management. Promote from a late portfolio step to a free first-pass screen.** The
mentions track already found capacity ($4 median at touch) binding before edge did. Depth-at-touch ×
windows/day is observable, costs no test look, and kills candidates for free. **Every candidate
passes a capacity screen before any snooping budget is spent on it.**

**A — Anomaly/seasonality harvesting with FDR control.** The FDR half is already the governance. The
harvesting half is cheap: time-of-day, weekday, funding-settlement minutes, CME open/close, macro
releases, the near-expiry break. ⚠ **The entire seasonality grid must be pre-registered as ONE
cell**, or it will eat the budget by itself.

**D — Data acquisition as strategy, reframed.** The scarce data here is not satellite imagery; it is
**the venues' own microstructure history, which nobody archives.** Kalshi sells no historical L2.
IBKR destroys event-contract history at expiry. The collector *is* the strategic asset and it
compounds daily. This is the correct justification for spending disk.

**X — Execution science.** Splits. Market-wide response functions (post-trade drift conditional on
aggressor side) are estimable from the public tape — in scope. Own-impact and queue dynamics are not
observable from data you did not cause — §8.

**Carve-out, low priority:** Kalshi's FOMC-date ladder vs the CME 30-day fed funds strip, reachable
through the IBKR Client Portal Gateway already running at `https://localhost:5055` (installed
2026-08-14 at `/Volumes/Kilos/janus/tools/clientportal.gw`, port moved off 5000 which macOS AirPlay
holds). Prior is low — this is the most-arbitraged event-contract relationship in the world, and
phase 1's worst case was a `KXFEDFUNDSYEAR` pair losing 2¢ net to fees. Keep as a cheap falsifiable
check, not a lead.

**IBKR verdict:** not a prediction venue for this program. It is a Kalshi *router* (duplicate price),
ForecastEx is ~1000× thinner than Kalshi, paper accounts get no realtime data, and event history is
**destroyed at expiry**. Its only role is as the access layer to *hedge* instruments (CME event
contracts, CME BTC futures, SPX/XSP 0DTE) for family V. That last fact argues for starting a tiny
forward archive early if you expect to need it at all.

---

## 6. Ranked questions

Metric: P(the answer changes what we do) × durability ÷ effort, penalising anything needing new
infrastructure before it can be asked.

| # | Question | Family | Effort | Looks | Why here |
|---|---|---|---|---|---|
| **1** | Does the opening spread collapse (24¢→2¢ in 5 s) occur on non-BTC series **at all**? | P/M | 3d collect + 1d | **0** | Pure characterization, so free. Gates everything downstream. Nothing else has this ratio. |
| **2** | Capacity census: depth at touch × fills/window × windows/day, per series | C | 1d, same data | **0** | Kills series for free; reframes the metric from ¢/fill to ¢/window (Trap 8). |
| **3** | Does MM-at-open generalize to the 6 alts + 5 new commodity/index 15m series? | M/P | 20–100d collect | 1 | The flagship. Ranks below 1–2 only because it depends on them and the clock is long. |
| **4** | Can toxic vs benign flow be separated from public tape features alone? | F | ~1wk | 0 + 1 | Tests whether "adverse selection ≈ 0" is real or a capture artifact. Highest-value *idea* here. |
| **5** | Does the near-expiry calibration break replicate, and survive the crossed spread? | V/A | ~1wk | 1 | Published on 23M trades, so a strong prior. The whole question is whether it survives crossing. |
| **6** | Does the Kalshi→PM lead survive on the 6 alts and PM's 5m cadence? | L | Phase-A data | 1 | Generalization, not discovery. Lower value than it looks. |
| **7** | Ladder-implied distribution vs Deribit surface | V | ~3wk | 1 | Genuinely new, real hedge instrument. Expensive and trap-dense — sequenced last deliberately. |
| **8** | Cross-cadence within Kalshi (15m vs hourly vs daily) | L/V | ~2wk | 1 | Attractive because intra-venue — but see Trap 5. Easy to fool yourself. |
| — | HMM / regime conditioning | — | — | — | **Deferred.** A second-order conditioner on a first-order edge not yet established on 6 of 7 series. Fitting regimes before you have a base rate spends the budget on nothing. |
| — | Correlated-but-distinct markets; matcher rebuild | — | — | — | **Forbidden this program.** Rated highest fake-signal risk in phase 1; the matcher belongs to Track A. |

---

## 7. Phase plan

Design principle: the first two phases spend **zero budget**, cost days not weeks, and can each
falsify the central hypothesis outright.

**Phase A — auth + episode sampler (days 1–4). 0 looks.**
Kalshi RSA-PSS auth + WebSocket; episode sampler on all 19 `fifteen_min` series + PM equivalents;
trade tape; disk floor and alarms, each **demonstrated firing against a fake target**.
Sampler design: event-triggered on each `:00/:15/:30/:45`; capture t ∈ {0, 0.5, 1, 2, 3, 5, 8, 13,
21, 34, 60}s plus a sparse tail. Schema: copy `kalshi_open_episode_samples` — it already carries
`seconds_since_open`, both-side depth at 1/2/5¢, and separate `receive_ts`/`exchange_ts`. Add PM's
`late_by` to the Kalshi side too.
*Checkpoint:* ≥98% window capture on ≥12 series over 72 h, `late_by` recorded, **capture completeness
reported conditional on realized volatility**, disk <100 MB/day.
*Fail → STOP and re-scope.* If the rate limit prevents simultaneous open-capture even on WS, the
multi-series question is unanswerable at this tier — worth knowing on day 4, not day 40.
Also: declare and seal the forward holdout as `open_date ≥ D_seal` with `D_seal` announced **in
advance** (the forward-growing pattern that worked in the mentions track). Declare the BTC episode
set unreadable.

**Phase B — open-collapse + capacity census (days 4–10). 0 looks, `L#` rows only.**
*Checkpoint:* does `spread(t=0) − spread(t=5s) ≥ 10¢` hold on **≥3 non-BTC series with ≥200 windows
each**?
*Fail → the flagship hypothesis is falsified in its strongest form.* MM-at-open is BTC-specific, and
the program pivots to Phase D having spent nothing. **This is the cheapest decisive test available
and it must come first.**
Simultaneously: capacity census (free kills) and Trap 2's volatility-conditional completeness check,
which either confirms or destroys the inherited "adverse selection ≈ 0".

**Phase C — MM-at-open on surviving non-BTC series. ONE test look.**
One pooled cell, no composite filters. Report ¢/fill **and ¢/window/day**; filled vs unfilled EV
separately; three price assumptions (mid, half-spread, full-crossed); 2× fee stress; permutation
blocked by `open_date` **and** clustered across series.
*Power, and the real constraint:* from the inherited CI [+3.39, +4.97] at n=3,196, SE ≈ 0.40¢ implies
per-fill SD ≈ 22.7¢ **[MOD — re-derive this directly, do not inherit it]**. Detecting +2¢ at 80%
power needs **n ≈ 1,010 fills per series**: ~20 days at BTC's ~50 fills/day, ~100 days on a thin alt
at ~10/day. **Phase B's fill-rate census therefore determines whether Phase C is a three-week or a
three-month project, and that number must exist before the look is registered.**
Output is explicitly an **upper bound**, tier MOD at the fill layer.

**Phase D — flow toxicity + calibration, from the tape (parallel, weeks 2–4).**
Classification is characterization (0 looks); conditioned-edge is 1 look. The near-expiry
replication criterion must be stated **at the full crossed spread** — the phase-1 lesson.
*Checkpoint:* does a tape-feature classifier separate post-trade mid drift by ≥2¢ between benign and
toxic buckets, out of sample? If not, the §6.2 transfer is refuted and family F closes.

**Phase E — distributional / vol arb (only if A–C survive; weeks 5–10).**
Gated on the oracle-basis measurement **and** Trap 9's tick-error propagation, both completed
*before* any Kalshi-vs-Deribit number is computed.

**Phase F — the costed live proposal. Written, not executed.** See §8.

---

## 8. Offline vs requires live orders

**Answerable offline:** spread dynamics and the open-collapse profile; quote and trade lead–lag;
**market-wide** adverse selection (post-trade mid drift by aggressor side — Glosten–Milgrom is
estimable from the tape); calibration by price bucket and time-to-expiry; capacity at touch;
flow classification from tape features; ladder coherence; oracle basis between settlement
references; other traders' response/impact functions; and an **upper bound** on fill rate (how often
the tape crossed a price you would have quoted).

**Requires resting orders — OUT OF SCOPE, list them, do not model them silently:** queue position and
Kalshi's queue discipline (FIFO vs pro-rata is itself undocumented); realized fill rate λ(δ); *your
own* market impact; whether your quote causes incumbents to fade; cancel/replace round-trip latency;
the realized maker fee tier (0.0175 is unverified against a fill); PM's `rebateRate: 0.2` crediting
(modelled nowhere, `PM_CREDIT_REBATE = False`); partial-fill behaviour; and whether the 35.8%
both-sides fill rate survives when **you** are the one quoting.

**Costed proposal to write in Phase F (do not execute):** minimum viable fill-rate experiment — 1
contract, one series, quotes at the touch at t=0. Distinguishing a 24% fill rate from 50% at ±5pp
needs n ≈ **370 quote attempts ≈ 4 days** on one 15m series. Gross exposure <$400; expected loss
$30–80 if the edge is zero. Present it as a discrete, bounded, separately-authorized decision.
**Never smuggle it in.**

---

## 9. Traps — ordered by how likely you are to fall in

1. **The bids-only book will manufacture a fake microprice signal.** Kalshi returns **bids only**;
   YES asks exist only as NO bids. Imbalance computed on the returned arrays measures "YES bids vs NO
   bids", which is a directional sentiment proxy that **contains the mid** — so it will predict the
   mid with a beautiful IC, circularly. **Mandatory test before any imbalance feature is used:
   imbalance must be antisymmetric under the YES↔NO relabelling, `I(yes) = −I(no)`.** If it is not,
   it is leaking the level. *This is the single most likely source of a confident false result here.*
2. **Missingness is not at random, and it biases MM upward.** One market open per series at a time →
   pollers re-discover each window → discovery fails under load → load is highest in volatile
   windows → volatile windows are exactly where adverse selection lives. Systematically losing them
   **produces "adverse selection ≈ 0" as an artifact.** Since that is a headline inherited finding,
   check this first, not last. Capture completeness must be reported **conditional on realized
   volatility**, and a capture gap must be an explicit reason-coded row, never an absent row.
3. **The fee `ceil()` step will masquerade as alpha.** `ceil(0.07·C·P·(1−P))` is 1¢ below P≈0.16 or
   above P≈0.84, and 2¢ near the middle. Any strategy selecting on extreme prices inherits a 1¢ cost
   advantage with **zero informational content** — and extreme prices are also where calibration
   errors live, so the two confound. You *will* "discover" that extreme-price trades are more
   profitable. **Mandatory control: re-run every price-conditioned result at a flat 2¢/leg and report
   both.**
4. **Mid-price EV is fiction at a 1¢ tick — and this has already cost this project once.** Phase-1
   mentions: +5.79¢ at traded price → +2.18¢ at a 3.5¢ half-spread → **−1.36¢, CI includes zero**, at
   the measured 7¢ full spread. **Every EV is reported at three prices — mid, half-spread,
   full-crossed — and the headline is the crossed number.** A single-number EV without its spread
   assumption is inadmissible.
5. **"Never mix venue series" is stated too narrowly and the narrow version will not protect you.**
   `AGENTS.md` permits comparison "between the two venues' own quoted prices." But the real hazard is
   *different settlement references*, and that exists **within** one venue: Kalshi 15m crypto settles
   on **BRTI**, 15m commodities on **Pyth**, dailies possibly on a futures curve point (unresolved —
   phase 1 §9 item 3). Comparing a Kalshi 15m to a Kalshi daily is intra-venue and can still be a
   category error.
   **Proposed stronger rule, to be carried upstream into `AGENTS.md`:** *never compare two prices
   without first measuring the basis between their settlement references, regardless of venue.*
6. **Cross-series pooling will inflate the t-stat ~7×.** 96 windows/day × 7 series looks like n=672/
   day, but windows within a day share one underlying path and same-timestamp windows across series
   share the crypto factor (alts ~0.8 correlated with BTC). **G3's day-block shuffle handles the time
   axis and does NOT handle the cross-series axis.** This bears directly on the existing pooled-alt
   prior (+11.91¢, n=114). *Proposed G3 amendment: block by `open_date` AND treat same-timestamp
   cross-series observations as a single block.*
7. **Units, twice over, in the same field.** `kalshi_snapshots.yes_bid` is a **probability in [0,1],
   not cents** — a Kilos engine once priced a 30¢ ask as 0.3¢ and produced +37.5¢/trade. Separately,
   the live API now returns **decimal-dollar strings**. Two independent unit traps, both live.
   Assert a declared range check on every price array at load.
   Related: **`kalshi_snapshots` spreads are exactly zero.** Any execution claim sourced from it
   invents a free half-spread. Assert `(ask > bid).mean() > 0.99` on any table used for execution.
8. **EV/fill will fool you where EV/window will not.** The alts are thinner: wider spreads (higher
   ¢/fill) but fewer takers (fewer fills). +4.10¢ × 50 fills/day beats +8¢ × 2 fills/day by **12×**.
   Report both; **the decision metric is ¢/window/day.**
9. **Ladder-implied vol will look mispriced because of the tick, not the market.** Extracting σ from a
   1¢-tick digital ladder means differentiating a step function. In the wings, where P is 2–3¢, one
   tick is 30–50% of the price and the implied-vol error explodes — so family V's apparent
   mispricings will concentrate exactly where the noise is. **Propagate ±0.5¢ tick uncertainty
   through to implied vol and discard any strike whose band exceeds a pre-declared width, before
   looking at the comparison.**
10. **The filled/unfilled inversion is a standing diagnostic, not a finding.** For any passive
    strategy, report EV on filled and unfilled separately. **If EV(unfilled) > EV(filled), the
    strategy is an adverse-selection machine regardless of its headline.**
11. **The 4.05% APY will make long-dated strategies look good for a non-alpha reason.** Over 15
    minutes it is ~0.0001¢; over a six-month political market it is ~2% of notional — comparable to
    the whole edge. **Long-dated EV is benchmarked against the APY, not against zero**, because you
    can earn the APY without trading.
12. **Backward-vs-forward quote sampling.** Already measured (+3.05¢ live vs +4.45¢ modelled). Entry
    prices must be sampled from the last row **strictly before** the decision timestamp, and that
    timestamp must include the round-trip latency you would actually have incurred.
13. **Untested ≠ unpriced.** Six untested series is a statement about our data, not about the market
    — phase 1's own lesson ("you cannot conclude market efficiency from a failed implementation")
    running in reverse.
14. **BH-FDR is undercounted if rejected ideas go unrecorded.** m = ledger rows, but ideas silently
    discarded after a peek are real multiplicity that never enters m. **Add a `HYPOTHESIS_REGISTRY`
    logging every hypothesis considered, including unrun ones** — the "institutional memory of every
    hypothesis tried" item from the paper's cross-cutting section, and the one cross-cutting element
    not yet implemented in this project.

---

## 10. What would make us abandon this program

If Phase B shows the opening collapse is **BTC-only**, *and* Phase D shows flow toxicity is **not
separable** from tape features, then the honest conclusion is that Kalshi's liquidity-provision
premium is a single-series artifact of BTC's participant mix rather than a structural property of
15-minute event contracts — and there is no HFT program here, only a BTC-specific one already
registered in Kilos.

**That conclusion is reachable in about three weeks for zero snooping budget.** Reaching it quickly
is a good outcome, not a failure. Say so plainly if you get there.
