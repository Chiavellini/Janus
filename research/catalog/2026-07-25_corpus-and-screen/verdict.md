# Verdict — the shared corpus, and a first economic screen (Janus Phase A + partial B)

**Date:** 2026-07-25 · **Track:** catalog · **Ledger:** `L3` (descriptive — **no test look spent**)
**Code:** `catalog/enumerate_kalshi.py`, `catalog/enumerate_pm.py`, `match/block.py`, `match/screen.py`
**Data:** both venues' public APIs, crawled live.

---

## 1. The corpus is far larger than a naive crawl suggests — on both venues

Both venues' obvious endpoints are misleading, and each one nearly killed the project on a false reading.

**Kalshi.** `GET /markets?status=open` returns 40,000 rows that are **99.8% parlay baskets**
(`KXMVE*`); only 79 were real markets and none had volume. The tradeable book is only visible via
`/events?status=open&with_nested_markets=true`:

| | |
|---|---|
| Events / markets | **8,470 / 72,351** (zero parlays) |
| Short-dated (≤30d) | **26,012** |
| ...two-sided quoted | **14,991** |

Short-dated tradeable by category: Sports 9,940 · Financials 2,111 · Economics 740 ·
Entertainment 491 · Commodities 465 · Climate 280 · Crypto 243 · Politics 181 · Elections 28.

**Polymarket.** Gamma `/events` **422s past offset ~2100**, and ordering by id biases to
newly-created markets. A single-channel crawl returned **2,078 events** and made Polymarket look
like a table-tennis venue with 15 political markets. Three independent channels, unioned:

| Channel | Events found | New |
|---|---|---|
| per-tag pagination | 7,522 | 7,522 |
| global offset (to the cap) | — | +2,175 |
| **date-window slicing** | — | **+3,268** |
| **union** | | **12,965 events / 106,136 markets** |

The date-window channel alone added **25% more events than the other two combined could reach**.
The naive crawl was off by **6×**. Short-dated (≤30d): **56,314 markets, 50,178 tradeable,
$67.1M liquidity.**

> **Neither venue can be enumerated through one channel.** Any future crawler must union multiple
> channels and report per-channel contribution, so a silently-dying channel is visible instead of
> quietly shrinking the corpus.

**Fee tiers are not uniform** (this matters — Janus previously hardcoded 0.07):
`quadratic:1` on 69,976 markets · **`quadratic_with_maker_fees:1` on 2,317** · `quadratic:0` on 58.

## 2. Matching is the hard problem, and title similarity is not enough

Blocking over the short-dated two-sided sets (Kalshi 14,991 × PM 50,196) produced **111,804
candidate pairs**, of which 50,550 share a question archetype. Three independent channels —
rare-token entity overlap (93,634), distinctive numbers (89,148), entity+shared-resolution-date
(42,579) — because token overlap alone finds *nothing* on politics/economics, where the two venues
phrase the same question completely differently.

**The screen's first run validated its own warning: a big nominal edge means a mismatched pair.**
The top 20 "arbs" by raw edge were all garbage, e.g. *"3M Open: Will Beau Hossler win"* matched to
*"Tour de France: Will Tadej Pogačar win"* — jaccard 0.30, a fake **+97.94¢** manufactured purely
by pairing a 2¢ longshot against a 99¢ favourite.

## 3. The economic result — genuine pairs show no arbitrage

Restricting to high-quality matches (jaccard ≥ 0.70, resolution dates within 2 days), **n = 35**:

| | Price gap between venues | Nominal edge |
|---|---|---|
| median | **3.00 pp** | **−1.72¢** |
| p75 | 13.00 pp | −0.21¢ |
| max | 68.00 pp | +46.48¢ |

Split by whether the two venues actually agree on price:

- **24/35 price within 5pp of each other** — the plausibly-genuine pairs. Their nominal edge:
  **median −1.85¢, only 3 of 24 positive, max +2.25¢.** After two spreads and two fees there is
  **nothing to capture.**
- **7/35 price >20pp apart** — and every one inspected is a **different question wearing similar
  words**:
  - Kalshi *"ISM Manufacturing PMI at least **52**"* (mid 90) ↔ PM *"at least **57.0**"* (mid 22) —
    a strike-ladder mismatch that passed both the archetype filter and jaccard 0.71.
  - Kalshi *"Tour de France **Green Jersey** winner"* (mid 46) ↔ PM *"**overall** winner"* (mid 0).
  - Kalshi *"Tour de France **Stage 21** winner"* ↔ PM *"**overall** winner"* — +6.79¢ of fake edge.

Confirmed genuine pairs behave exactly as an efficient cross-venue market should:

| Pair | Kalshi | PM | Edge |
|---|---|---|---|
| Tour de France overall winner — Pogačar | 98 | 99 | **−0.86¢** |
| Kevin Warsh press-conference words (several) | 16–82 | 12–84 | **−0.2 to −5.4¢** |

## 4. Verdict

**The same pattern as the BTC study, reached by a completely different route: where the two venues
genuinely list the same market, they agree on price; where the edge is large, the markets are not
the same.** No tradeable cross-venue arbitrage was found in this sample.

**This is a preliminary read, not the Phase-C gate.** Two honest limits:

1. **n = 35 is thin**, and it is thin *because of the matcher*, not because the corpus is thin.
   Jaccard ≥ 0.70 is reachable only for markets that happen to share wording. The Fed, CPI,
   elections and legislative markets — where both venues are deepest — are phrased too differently
   to ever score that high, so they are absent from this sample entirely.
2. **No rules text has been read yet.** Every conclusion above rests on titles and prices. The
   ISM 52-vs-57 case shows titles are not sufficient even at jaccard 0.71.

So the next step is unchanged and is now clearly the load-bearing one: **the LLM verifier reading
both full rules texts**, to find the true pairs that token overlap cannot reach — followed by
**Phase C**, the historical resolution-agreement measurement, which is the only thing that can turn
"these look like the same market" into a number.

**Working hypothesis carried forward, stated so it can be refuted:** the genuine cross-venue
opportunity, if one exists, is in markets whose *wording* differs enough that no simple matcher
finds them — because those are exactly the pairs other arbitrageurs' matchers also miss.

## Reproducing

```bash
python3 catalog/enumerate_kalshi.py --out-dir data/catalog   # 44 requests, 0 retries, 0 429s
python3 catalog/enumerate_pm.py     --out-dir data/catalog   # 3-channel union
python3 match/block.py  --catalog data/catalog --out-dir data/match
python3 match/screen.py --match-dir data/match --catalog data/catalog --min-edge 2.0
```

Artifacts: `data/catalog/{kalshi,pm}_{markets,summary}.json`, `kalshi_series.json`,
`data/match/{candidates,screened,arb_candidates}.json`.
