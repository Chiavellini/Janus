# Handoff — cross-venue Kalshi↔Polymarket work, session of 2026-08-20/21

Written at the end of the session. Everything below is either measured in this session or cited from
a file in the repo. Where a number is uncertain or unmeasured it says so explicitly.

---

## 1. Initial project state

The session opened with the question "16 hours passed — what did we capture and test?" The answer
found on disk:

- **L22 (`collectors/collect_wti_ladder.py`) had been capturing for ~17 h**, and was **half dead**.
  Kalshi side healthy: 208/208 scheduled slots, 24,820 rung rows, zero silent absences. IBKR side
  broken: auth failed at `2026-08-19T21:26:43Z` (26 min into the run) and never recovered — **6
  futures rows total, 4 of them frozen repeats**; `archive.sqlite` showed 59,764 `AUTH_INVALID`
  polls and **zero priced quotes after 21:30Z**.
- **No analysis had run.** No repo file had been modified since 2026-08-19 15:23. The L22 checkpoint
  (≥10 sessions) was nowhere near met and its futures leg was absent entirely.
- **Host was unhealthy**: load avg 64, swap 8.7/10 GB, root disk had hit **607 MB free** that
  morning, killing two collectors.

### Issues found at the start that shaped everything after

1. **`match/verify.py` did not exist.** Both `match/block.py:7` and `match/screen.py:10` document the
   pipeline as `block → ECONOMIC SCREEN → LLM equivalence verify → trade`. The verify stage had never
   been written, so recall-optimised blocking had no adjudicator. This is the mechanism behind phase
   1's `n=35` — which `AGENTS.md` already concedes is *"a matcher limit, not a venue fact."*
2. **`match/screen.py:pm_fee_c()` charged a constant 0.07** to every Polymarket market.
   `lib/fees/registry.py` documents 0.07 as *"the MINORITY case."* Measured in scope: rate 0.04 →
   1,577 markets, 0.05 → 1,481, 0.07 → 2,426, absent → 255. **56% of markets with a schedule were
   overcharged**, biasing toward "no edge" — the direction that hides opportunities.
3. **`--require-archetype-match` was `action="store_true", default=True`** and could never be turned
   off from the CLI.

---

## 2. Work completed

### 2a. Universe re-crawled (nothing was overwritten)

Ran `catalog/enumerate_kalshi.py` and `catalog/enumerate_pm.py` into **`data/catalog_2026-08-20/`**,
deliberately NOT over `data/catalog/` (the July snapshot is irreplaceable and there is no VCS here).

- Kalshi **95,852** tradeable markets (parlays excluded); 25,095 short-dated and two-sided
- Polymarket **179,863** markets; 91,464 short-dated tradeable
- For scale: phase 1's `n=35` sampled roughly one pair per 3,000 markets

### 2b. Built the missing equivalence stage

`match/verify.py` — deterministic structural rejection, then an `UNDECIDED` bucket for adjudication.
Funnel on the non-sports scope: **51,306 blocked candidates → 1,834 → 364 → 271 → 237** as signals
were added. Contamination proxy (share of markets with implausible |edge| > 20¢) fell **61% → 41%**.

Signals, each derived from a real observed failure:

| check | what it kills |
|---|---|
| `STRIKE_MISMATCH` | the ISM PMI ladder — 8 Kalshi rungs blocked to one PM market at 59 |
| `SUBJECT_MISMATCH` | Kalshi *Insidious* vs PM *"Mutiny"* at the same score |
| `SETTLEMENT_SOURCE_MISMATCH` | PM resolves crypto on Chainlink/Pyth, Kalshi on CF Benchmarks/Coinbase |
| `NO_SHARED_SUBJECT` | numeric collisions — Larry Page `$290B` vs Amazon `$290` |
| `NOT_RECIPROCAL_BEST` | one Kalshi market fanned out to 8 PM markets |
| `RANGE_VS_THRESHOLD` | a PM bracket is not a Kalshi one-sided strike |
| `SUPERLATIVE_VS_THRESHOLD`, `QUALIFIER_MISMATCH` | "highest" vs "at least 60"; `#2 US` vs `top global` |

Three bugs were found *in the verifier itself* during development and are pinned by tests: the
trigger extractor firing on non-utterance markets (1,350 false rejects), `archetype == "other"` (a
no-match sentinel) being read as evidence of difference, and the subject check hijacking utterance
markets.

### 2c. Capacity measured for the first time (and corrected twice)

The program's objective in `AGENTS.md` is EV¢ per trade; **nobody had ever multiplied it by size.**

- First figure **$131,099** was wrong — it summed per *pair*, and one Kalshi market appears in many
  pairs. Deduplicated: **$38,918 across 509 unique Kalshi markets**, median **$9.31** at the touch.
- Claim that "PM has ~200× Kalshi's capacity" was **wrong** — it rested on gamma's `liquidityNum`,
  a derived aggregate, not executable size. Real CLOB depth: Kalshi $4.00 vs PM $3.12 at the touch.
- Capacity is extremely concentrated: **top 50 markets = 76%** of all transactable dollars.
- The real structure: books are **deep but not at the touch** (p50 $6.96 at touch, $79.81 within
  +5¢, $12,050 across the full ladder), so **edge and size trade off directly**.

### 2d. L25 — the project's first test look was spent

`research/exec/2026-08-20_capacity-edge-correlation/` — "does edge live where size lives?"
Registered with immutable criteria **before** the statistic was computed; BH-FDR bar `0.10/25 = 0.0040`.

**Verdict `NOT_SIGNIFICANT`.** Top capacity decile 43.758¢ vs rest 24.471¢, diff +19.287¢, **p=0.128**;
Spearman rho −0.0646, p=0.154. Trimmed cut also null.

The real content is a **contamination measurement**: a median apparent edge of 24.5¢ implies two legs
costing 75.5¢ for a $1 payoff. The pre-committed trim dropped 494→193 markets, i.e. **61% carry
|edge| > 20¢**. The row was largely uninformative about its own hypothesis because the variable it
correlated against was dominated by false pairs.

### 2e. Pivot to sports — the finding that reframed the program

Non-sports was the wrong scope, and it was my recommendation. Hand-adjudicating 40 survivors of the
full deterministic layer found **2 strict equivalents in the first 22 and ZERO in the next 18** — the
venues are almost never asking the same question there. Two systematic divergences worth recording:

- **Kalshi writes `above X`, Polymarket writes `at least X`** across whole families (every Rotten
  Tomatoes and GPU-price market). On integer quantities that is a genuine off-by-one.
- Kalshi monthly **average** vs PM single-day **index**; `more than 15` vs `exactly 15`; named
  contract month vs "Active Month"; daily **settlement** vs 1-minute candle high/low.

Sports is the opposite. `match/sports_match.py --league mlb --days 8` paired **47 of 47 eligible
games (coverage 1.00)**, 94 outcome pairs, on a canonical ESPN key. Binding two-leg capacity is ~7×
deeper (p50 **$21.84** vs ~$3; p90 **$563** vs ~$100).

**And the newborn configuration exists and is measurable**: Polymarket lists an MLB game **~82 hours
before Kalshi opens** it — measured +81.9h to +83.4h across 7 games, PM created in a 13:00 UTC batch.
By Kalshi's open PM carries an established price (median **0.085** off its 0.500 listing default).

### 2f. F1 — shadow trading (forward eval, no test look)

`collectors/collect_shadow.py`, spec `research/exec/2026-08-21_shadow-kalshi-open/spec.yaml`,
ledger **F1**. Rule pinned before the first decision. Detection validated **94/94** against the known
pairs via `lib/entities` (Kalshi uses `ATH`/`AZ` where PM uses `oak`/`ari` — 12 of 94 broke a naive
parser).

**First run was discarded.** No cold-start guard meant the opening poll treated all 94 already-open
markets as newly discovered, producing 94 decisions at **lag 1.6–71.1 h including 18 TRADE signals**.
DB preserved as `CONTAMINATED_coldstart_20260820T220341Z.sqlite`; none of it is scored. Guards added:
`COLD_START_SEED`, `MAX_LAG_S=900s` → `STALE_OPEN`, per-decision flush.

**First genuine at-open observation (lag 88s):** Kalshi opened ATL@MIL at **0.25 / 0.95 — a 70¢
spread**. PM at that instant 0.41/0.66. Apparent mid gap +6.5¢; **executable two-leg cost 143.9¢ for
a 100¢ payoff — a 44¢ loss.** Arbitrage is dead at the open.

### 2g. F2 — convergence (forward eval, no test look)

Operator reframed correctly: this is not arbitrage, it is **Kalshi moving toward PM**. A one-legged
bet pays one spread, giving an exact condition:

> **edge = |mid_error| − half_spread**, i.e. **spread < 2 × |error|**

`collectors/collect_convergence.py`, spec `research/exec/2026-08-21_convergence/spec.yaml`, ledger
**F2**. Samples all 90 open MLB markets every 60 s using **batch** top-of-book on both venues. Needs
no settlement, so an observation is one poll rather than one settled game.

**Two bugs were found and fixed before any result was believed** — both would have looked like huge
signal:

1. **Gamma's `bestBid`/`bestAsk` are per-MARKET, not per-outcome.** Assigning one pair to both teams
   put the complement's price on one side of every game: a manufactured ~14¢ error (|2p−1|) that read
   as "13.78¢ average edge, 73/88 tradeable."
2. **A PM game event carries ~17 markets and six use team names as outcomes** (`Spread: Milwaukee
   Brewers (-1.5)`, `1st 5 Innings Spread: …`). Letting the last win compared Kalshi's **moneyline**
   against a **run-line spread** — a 23.5¢ phantom on a game where both moneylines read 0.565 to the
   cent. This is precisely the trap `block.py:12` and `sports_match.py:20` document.

**Clean result, n=90 paired moneylines:** median |error| **1.00¢**, p90 1.50¢, max 3.50¢; Kalshi
spread median 1.00¢, PM 1.00¢.

```
gross one-legged edge = 1.00c error − 0.50c half-spread = 0.50c
Kalshi taker fee alone                                  = 2.00c
```

**Dead by 4×** in the mature cohort.

---

## 3. Files changed

| file | change | why |
|---|---|---|
| `match/screen.py` | `pm_fee_c()` now takes `fee_schedule` and uses the **per-market** rate; `screen_pair()` gained a `pmeta` argument; records `pm_fee_rate` + `pm_fee_rate_source`; added `--no-require-archetype-match` and a `--candidates` flag | the constant 0.07 overcharged 56% of markets, biasing toward "no edge"; the archetype flag could never be disabled |
| `state.yaml` | appended four dated sections: `cross_venue_newborn`, `capacity_edge_correlation_L25`, `precision_work_2026_08_20_evening`, `sports_is_where_the_pairs_are_2026_08_20` | append-only convention; nothing above the banner was rewritten |
| `snooping_ledger.md` | added **L24** (newborn capture), **L25** (first test look + verdict), **F1**, **F2**; F1 amended with the cold-start disclosure | rows must be registered PENDING before running |

**Note on L23:** a collision was caught — `L23` already existed (commodity term-structure). The new
capture row was renumbered **L24**. Verify uniqueness with:
`grep -o '^| L[0-9]*' snooping_ledger.md | tr -d '| ' | sort | uniq -d`

---

## 4. Files created

**Matcher**
- `match/verify.py` — the missing equivalence stage (deterministic layer)
- `match/adjudicate.py` — LLM adjudication via `claude-opus-5`, structured output, batched.
  **BLOCKED: `ANTHROPIC_API_KEY` has no credit balance.** Failures record `UNSURE` +
  `ADJUDICATION_ERROR`, never silent acceptance
- `match/make_gold.py` / `match/score_gold.py` — blind labelling sheet + scorer (precision ≥0.98,
  recall reported alongside)
- `match/gold/nonsports.csv` (144 pairs, 8 strata) + `nonsports.key.json` (**do not open until
  labelled**)

**Catalog**
- `catalog/prefilter.py` — streaming JSON-array reader (`raw_decode` windowing) so the 438 MB PM
  catalog never loads whole on an 8 GB host; enforces the non-sports scope and the `state.yaml:173`
  CFTC mentions gate in code

**Collectors**
- `collectors/collect_newborn.py` + `run_newborn.sh` + `com.janus.newborn.plist` — L24. **STOPPED
  and superseded** (see §5)
- `collectors/collect_shadow.py` + `run_shadow.sh` + `com.janus.shadow.plist` + `report_shadow.py` — F1
- `collectors/collect_convergence.py` + `run_convergence.sh` + `com.janus.convergence.plist` — F2

**Research rows**
- `research/exec/2026-08-20_newborn-capture/spec.yaml` (L24)
- `research/exec/2026-08-20_capacity-edge-correlation/{spec.yaml,measure.py,results.json,verdict.md}` (L25)
- `research/exec/2026-08-21_shadow-kalshi-open/spec.yaml` (F1)
- `research/exec/2026-08-21_convergence/spec.yaml` (F2)

**Tests** — `tests/test_verify.py`, `tests/test_shadow.py`. Suite went **138 → 149 passing**.

---

## 5. Files intentionally left untouched

- **`AGENTS.md`, `JANUS_CHECKLIST.md`, `GATE_TO_LIVE.md`, `README.md`, `VALIDATION_STATUS.md`,
  `SHARED_SERVICES.md`, `1ST_INVESTIGATION.md`** — read as source of truth, never edited.
- **`match/block.py`** — its recall channels are correct and deliberately emit garbage; the fix
  belonged in `verify.py`, not here.
- **`match/sports_match.py`** — works (coverage 1.00); only *run*, never modified.
- **`lib/**`** — `fetch.py`, `fees/registry.py`, `stats.py`, `entities/`, `schedule/espn.py` all used
  as-is. **One latent issue noted, not fixed:** `Client.cache_key()` calls `.items()` on `params`, so
  a repeated-key query (gamma's `condition_ids`) raises before the request; worked around locally in
  `collect_newborn.py` by building the URL directly.
- **`collectors/collect_wti_ladder.py`, `collect_track_b.py`, `collect_ibkr_archive.py`,
  `lib/ibkr_readonly.py`** — the IBKR/WTI track is untouched. Its futures leg is still dead.
- **`data/catalog/`** (the July snapshot) — never overwritten.
- **`~/Library/Caches`** — 7.9 GB, mostly `com.openai.codex` (2.8 G) and Google (1.2 G). Only
  `com.microsoft.VSCode.ShipIt` (1.5 G, a stale updater download) was removed, with approval.

---

## 6. Source-of-truth documents

- **`AGENTS.md`** — the governing document. Supplied: the sacred settlement-reference rule (*"never
  compare two prices without first measuring the basis between their settlement references"*), the
  snooping budget (*"One test look = one new row … **Forward eval rows do not count**"* — which is
  why F1 and F2 are free), the disk-safety rule, and the inherited Kilos findings that constrain
  design (Kalshi leads PM by 5–10 s; the edge is one-directional; **the mirror was spent and FAILED
  at −2.375¢, p=0.772** — which is why both arms are pinned in F1).
- **`snooping_ledger.md`** — every row registered PENDING before running; verdicts appended, never
  edited in place (rule 6).
- **`state.yaml`** — running state; append-only below dated banners.
- **`JANUS_CHECKLIST.md`** — R1/R2/R3 definitions. `:98` is why R3's ~5 s at-open mechanism is
  excluded: *"Coordinate with Kilos first … Settle who spends the evidence."*
- **Docstrings in `match/block.py` and `match/screen.py`** — treated as specification. They are what
  revealed the missing verify stage and the moneyline-vs-spread trap.

---

## 7. Current project state

**Running now** (`launchctl list | grep janus`):

| job | pid | status |
|---|---|---|
| `com.janus.shadow` (F1) | 29251 | running, seeded, 1 game decided |
| `com.janus.convergence` (F2) | 51283 | running, sampling 90 markets / 60 s |
| `com.janus.wti-ladder` (L22) | 95647 | running, futures leg still dead |
| `com.janus.ibkr-archive` | 3206 | exit status 2; gateway unauthenticated |
| `com.janus.newborn` (L24) | — | **stopped, superseded** |

Suite **149 passing**. Root disk **7.0 GB** free (was 1.8 GB). Kilos 753 GB free.

**What is different from the start:** the matcher hole is closed; capacity has a number for the first
time; the program's scope moved from non-sports to sports on evidence; two forward-eval rows are
collecting; and one test look has been spent (`m=25`, BH-FDR bar now 0.0040).

**Uncertainty and incomplete work**

- **L24 is superseded for three reasons**, all my defects: it never captures the counterpart
  (`store.pair()` is dead code, `pairs` is empty); its Kalshi age axis uses `created_time`, which can
  precede `open_time` by three weeks (mean detection lag 21.9 h; 968 rows have no book because
  trading had not opened); and it has no reference-quality gate. Its DB (8,352 book rows) is
  preserved. Per rule 6 the fix is a **new row**, not an edit.
- **`sports_match.py` precision is UNEVALUATED, not passed.** Its gold file is frozen for 2026-08-17
  games so a current-window run has zero overlap (`judged_against_gold: 0`). Coverage 1.00 on a
  canonical key is strong evidence but is not a measured precision.
- **`match/gold/nonsports.csv` is unlabelled**, so verifier precision is unknown.
- **Adjudication is blocked** on API credit.
- **Direction is genuinely open.** `AGENTS.md`'s *"truth sits at Kalshi"* was measured on crypto where
  Kalshi **leads**; in MLB Kalshi is the **late** lister by 82 h. F2 exists to settle this.
- The **2¢ Kalshi figure is the taker fee.** Maker is 0.0175 vs 0.07 — 4× cheaper — and is the one
  thing that could change the arithmetic. That is R3 territory, blocked on Kilos.

---

## 8. Immediate next steps, in priority order

1. **Read F2 after it accumulates.** This is the live question and it needs no settlement.
   ```bash
   sqlite3 /Volumes/Kilos/janus/convergence/track.sqlite \
     "SELECT cohort,count(*),round(avg(abs(error_c)),2),round(avg(k_spread_c),2) FROM samples WHERE error_c IS NOT NULL GROUP BY 1;"
   ```
   The statistic is **attribution**, pinned in the spec: over an interval where |error| closes,
   decompose `d_error = d_kalshi_mid − d_pm_mid` and report each venue's share. **Do not** substitute
   correlation — two series can correlate with either one leading. An attribution reporter has **not
   been written yet**; that is the single most valuable next piece of code.

2. **Label `match/gold/nonsports.csv`** (144 rows, `SAME`/`DIFFERENT`/`UNSURE`; `UNSURE` is a real
   answer). Then:
   ```bash
   python3 match/score_gold.py --gold match/gold/nonsports.csv --key match/gold/nonsports.key.json
   ```
   Until this runs, no cross-venue statistic on the non-sports corpus is interpretable.

3. **Clear the Anthropic API credit balance**, then run the adjudication over the 237 survivors:
   ```bash
   PYTHONPATH=. python3 match/adjudicate.py --match-dir data/match_2026-08-20
   ```
   Expectation from hand-adjudicating 40: the true non-sports pair count is small, possibly a few
   dozen.

4. **Watch F1 accumulate.** Opens are sparse — 1 game in ~5 h, far slower than first projected.
   ```bash
   PYTHONPATH=. python3 collectors/report_shadow.py
   ```
   The checkpoint gates on **gap existence**, not PnL (binary settlement has ~50¢ SD; at n=10 the
   standard error is ~16¢ against a hoped-for ~4¢ edge). Watch the **entry-venue split**: ~50/50 is
   noise, a skew is signal.

5. **Move both collectors to the VPS.** Decided 2026-08-20, still unexecuted. The host hit its disk
   floor twice in one day and killed two collectors. Kalshi and PM are public HTTP with no IBKR
   dependency, so nothing binds this work to the Mac.

6. **Decide L22's fate.** Its futures leg has been dead ~24 h and the checkpoint clock never started.
   Either re-auth the IBKR gateway (manual browser login at `https://localhost:5000` — never
   automated) or stop the row.

7. **Settle R3 with Kilos** (`JANUS_CHECKLIST.md:98`). It is the best-evidenced trade in either
   project (+4.10¢/fill, n=3,196, adverse selection ≈0, 35.8% locking a riskless +3.75¢/pair) and it
   is blocked on a conversation rather than on research. It is also the only route to the **maker**
   fee tier, which is the one thing that could revive the convergence arithmetic.

### Do not do

- **Do not tune F1's or F2's pinned constants after seeing results.** That converts a free forward-eval
  row into a spent test look. `tests/test_shadow.py` pins them so such an edit fails loudly.
- **Do not score anything from `CONTAMINATED_coldstart_20260820T220341Z.sqlite`.**
- **Do not use mid prices for any tradeability claim** — that produced phase 1's 47¢ ghost and L21's
  24 fictional arbitrages.
- **Do not use gamma's `liquidityNum` as capacity.** It is a derived aggregate, not executable size.
