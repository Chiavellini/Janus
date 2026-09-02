# Verdict — the cross-venue settlement basis (Janus Phase 1)

**Experiment:** `janus-settlement-agreement` · spec `spec.yaml` · engine `engine.py`
**Date:** 2026-07-24 · **Track:** basis · **Ledger:** `L2` (descriptive — **no test look spent**)
**Data:** Kilos read-only. Kalshi `market_data.db` ∪ the frozen 2026-07-17 shard; Polymarket
`pm_data.db` + `pm_xa_data.db`; Chainlink oracle from `pm_oracle_prices`.

---

## The question

Kalshi and Polymarket quote the same 15-minute "will BTC be up?" question at prices that routinely
differ by 5–10 pp. Buying the cheap side on one venue and the cheap complement on the other locks a
position that pays 100¢ either way — apparently free money. **Is it?**

## The answer

**No, not as stated — the two venues are not selling the same product, and they settle oppositely
5.70% of the time. But the disagreement has a mechanical cause that is observable in real time,
and gating on it cuts oracle risk to under 1%.**

---

## 1. Agreement — the headline

Every settled window joined across both venues on exact close time:

| Asset | Matched | Disagree | Rate | 95% day-block CI | Days | A hedged pair is worth |
|---|---|---|---|---|---|---|
| **BTC** | 2,859 | 163 | **5.70%** | [4.89%, 6.55%] | 43 | **94.30¢**, not 100¢ |
| ETH | 1,063 | 65 | 6.11% | [4.78%, 7.28%] | 21 | 93.89¢ |
| SOL | 1,064 | 79 | 7.42% | [5.20%, 9.56%] | 21 | 92.58¢ |

BTC disagreement is symmetric (86 one way, 77 the other) and spans 39 distinct days. Three
independent assets, three consistent rates: **structural, not an artifact and not a bad patch.**

**Applied to a live trade measured the same day** (2026-07-24 20:45Z BTC window, both books live):
buy Kalshi YES @21¢ + PM DOWN @70¢ = 91¢ outlay + 3.47¢ fees = **94.47¢** paid for something worth
**94.30¢**. The apparent **+5.53¢ riskless arb is actually −0.17¢.**

> The nominal edge *is* the oracle risk premium, priced almost exactly. That is why this gap
> persists instead of being competed away. **The naive trade is dead.**

## 2. Mechanism — why they disagree (BTC, n=1,906)

The two venues carry different reference levels, and I measured both directly rather than
inferring them (`floor_strike` from Kalshi, the window-open Chainlink print for PM; Kalshi's own
settlement value recovered from `raw_json` gives its BRTI reading at close).

| | Median | p90 |
|---|---|---|
| BRTI − Chainlink at settlement (the index difference) | **1.28 bps** | 3.66 bps |
| Kalshi reference − PM reference (the wedge) | **1.28 bps** | 3.60 bps |

The wedge **is** the index difference — same number from two independent measurements.

Disagreement is purely a small-move phenomenon:

| | Median \|move\| over the window |
|---|---|
| Windows where they **agree** | **9.70 bps** |
| Windows where they **disagree** | **1.03 bps** |

| Condition | n | P(disagree) |
|---|---|---|
| Close lands **between** the two references | 96 | **42.71%** |
| Close lands **outside** both | 1,810 | **3.37%** |
| \|move\| < wedge | 180 | **33.89%** |
| \|move\| > wedge | 1,726 | **2.38%** |

**H1 confirmed.** The venues disagree when the price finishes inside the ~1.3 bps band between
their two reference levels. Nothing exotic — two indices, one tiny gap.

## 3. The gate, computed at entry with no hindsight (BTC)

Both inputs are live-observable: Kalshi publishes `floor_strike` at market open, and the Chainlink
stream is PM's own settlement feed. So `gate = |price so far − PM ref| / |wedge|` is **observed,
not predicted**.

| Entry | Windows at gate ≥10 | P(disagree) | 95% CI | Hedge worth | Nominal edge needed |
|---|---|---|---|---|---|
| unconditional | 100% | 5.70% | — | 94.30¢ | 5.70¢ |
| open + 300s | 26.9% | 3.27% | [1.94, 4.68] | 96.73¢ | 3.27¢ |
| open + 480s | 32.0% | 2.56% | [1.51, 3.56] | 97.44¢ | 2.56¢ |
| open + 660s | 35.7% | 2.17% | [1.23, 3.04] | 97.83¢ | 2.17¢ |
| open + 780s | 37.7% | 1.11% | [0.51, 1.78] | 98.89¢ | 1.11¢ |
| **open + 840s** | **37.9%** | **0.83%** | **[0.29, 1.45]** | **99.17¢** | **0.83¢** |

**H2 confirmed.** The gate survives the loss of hindsight and degrades gracefully with time to
close. In roughly **38% of windows** — not a rare corner — a trade entered 1–2 minutes before close
carries **~1% oracle risk** and needs only **~1¢** of nominal edge to be profitable.

The complementary bucket confirms the gate is doing real work: at open+840s the gate <1 bucket runs
**21.2%** disagreement. Same windows, opposite selection, 25× the risk.

## 4. What this does *not* yet establish

**Whether a tradeable divergence still exists inside the gated states.** By construction the gate
selects windows where the price has moved decisively, so both venues quote near 0/100 — where there
is less room to disagree, and where Kalshi's `ceil()` fee imposes a **1¢ floor** per contract
regardless of how far into the wing the price sits. The hurdle in the gated regime is therefore
roughly:

```
  ~1.0¢  Kalshi fee floor  +  ~0.1¢ PM fee  +  ~0.8¢ oracle risk  ≈  2¢   plus both spreads
```

**Measuring the divergence available in the gated states is the remaining Phase-1 step**, and it
requires the entry-time quote join on both venues (`kalshi_snapshots` / `kalshi_orderbook_snapshots`
× `pm_quotes`). Until that lands, the spec's GO/NO-GO gate is **UNRESOLVED, not passed.**

## 5. Verdict

**CONTINUE — with the framing corrected.**

- The naive "same product, different price" arbitrage is **refuted**: it is oracle risk premium,
  priced correctly, and a strategy that ignores this loses ~5.7¢/trade against its own accounting.
- The mechanism is fully explained and **observable in real time**, which is what makes a gate
  possible at all.
- The gated regime is large (~38% of windows) and low-risk (~1%), so a viable strategy is not
  excluded — it now depends entirely on whether ~2¢+ of divergence survives in those states.

## Coverage limits (stated, not worked around)

- **Mechanism and gate are BTC-only.** Kilos enriches only the BTC series: `raw_json` for
  KXETH15M/KXSOL15M in this era carries neither `floor_strike` nor `expiration_value`
  (0 of 670 and 0 of 671 in the shard; 0 of 436 each in the live DB). The `raw_json` fallback
  recovers older ETH/SOL strikes but not the matched era. The *agreement* rates (§1) need only
  `result` and are solid for all three assets.
- Only BTC/ETH/SOL have both venues at all. Kilos never collected PM for XRP, DOGE, BNB, HYPE, and
  never collected Kalshi for XRP or HYPE — closing that is Phase 2's job.
- §3 uses the Chainlink price at the offset as the entry-time state. A live implementation reads
  the same feed, so this is faithful, but it assumes the feed is as fresh live as in the tape.

## Reproducing

```bash
cd research/basis/2026-07-24_settlement-agreement && python3 engine.py --out-dir .
```

Acceptance tests are asserted in the engine and **all three pass**: BTC 2,859/163, ETH 1,063/65,
SOL 1,064/79 — reproducing the ad-hoc measurement that prompted this study exactly.

Artifacts: `results.json`, `agreement_by_asset.csv`, `mechanism.csv`, `ev_surface.csv`
(hindsight upper bound), `entry_gate.csv` (the tradeable version).
