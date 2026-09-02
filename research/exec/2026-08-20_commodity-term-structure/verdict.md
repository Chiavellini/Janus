# L23 — Kalshi commodity term-structure and settlement-reference map — VERDICT

**The obvious §5.6 calendar spread is FORBIDDEN on the four biggest commodity complexes.**
**21 live series' binding rules name no settlement source at all.**
**Series metadata is demonstrably unreliable and must never be used as the reference.**

Test looks spent **0** · no price compared to another price · no IBKR · no spend.
Spec: `./spec.yaml` (criteria untouched). Ledger: L23. 134 series enumerated, 80 with open markets.

## Headline: the four you would pick first are the four you cannot spread

| underlying | classified cadences | reference classes found | verdict |
|---|---|---|---|
| **WTI** | 10 | `NAMED_MONTH_FUTURES`, `FRONT_MONTH_FUTURES`, `PYTH_INDEX`, `CANDLESTICK_UNNAMED` | **CROSS_CADENCE_BLOCK** |
| **GOLD** | 7 | `PYTH_INDEX` (15m), `CANDLESTICK_UNNAMED` (daily/hourly/weekly/monthly) | **CROSS_CADENCE_BLOCK** |
| **SILVER** | 5 | `PYTH_INDEX` (15m), `CANDLESTICK_UNNAMED` (daily/hourly/weekly/monthly) | **CROSS_CADENCE_BLOCK** |
| **NATGAS** | 5 | `PYTH_INDEX` (daily/weekly/monthly), `AGENCY_PUBLICATION` (EIA, max/min) | **CROSS_CADENCE_BLOCK** |

A calendar spread across cadences of any of these is **not an arbitrage** — the legs settle on
different references, so the spread contains an unmeasured basis. That is the phase-1 "efficient
open" error, and it is exactly what family §5.6's calendar-spread trade would have walked into.

Overall: **9 COMPARABLE, 4 CROSS_CADENCE_BLOCK, 12 NO_LIVE_MARKETS.**

## Where the calendar spread IS structurally available

Groups whose every classified cadence shares one reference class:

| underlying | cadences | shared reference |
|---|---|---|
| **BRENT** | daily, weekly, monthly, one-off | `PYTH_INDEX` |
| **COPPER** | daily, weekly, monthly | `PYTH_INDEX` |
| **GASOLINE_RETAIL** | daily → annual, 14 series | `AGENCY_PUBLICATION` (AAA) |
| **GPU_COMPUTE** | weekly → annual, 25 series | `THIRD_PARTY_QUOTE` (Ornn) |
| **DRAM** | weekly, monthly, one-off | `THIRD_PARTY_QUOTE` |

Shared reference class is **necessary, not sufficient** — the named instrument must still match, and
for the Pyth groups the feed-access problem from L17 still applies.

## Finding 2 — 21 live series do not name their own settlement source

Their binding `rules_primary` and `rules_secondary` describe *"the close price of the 1-minute
candlestick for gold"* and never say **whose** candlestick. Affected series include **KXGOLDD,
KXGOLDH, KXGOLDW, KXGOLDMON, KXSILVERMON, KXPLATINUMH** — all of which advertise "Pyth" in metadata
the rules never confirm.

The contrast is what makes it a finding rather than an oversight: **KXNATGASD uses the identical
candlestick construct and its secondary DOES name Pyth**, and further documents a futures roll. So
Kalshi can and does name the source when it chooses to; on gold and silver it does not.

This is the same species as the KXINX result (map v4): the number that settles the contract is not
identified by the contract.

## Finding 3 — the metadata is unreliable, as the spec assumed before the run

Two hard conflicts, where the advertised source names a **different commodity** than the series:
- `KXWHEATMON` ("Wheat Monthly") → source **"Trading Economics - Corn"**
- `KXGOLDEOY` ("How high will Gold get by end of year?") → source **"Trading Economics - Copper Futures"**

And plainly junk values: `KXGOLDVSSILVER` and `KXOPUS48OY` both carry
**"San Francisco Unified School District"** as their settlement source. The spec pre-declared that
`settlement_sources` is a hint and never the reference; that was the correct call.

## Finding 4 — ten series settle on a ROLLING futures contract

`KXWTI`, `KXBRENTD/W/MON`, `KXCOPPERD/W/MON`, `KXNATGASD/W/MON` document a roll:
*"the nearest listed contract month, rolling forward to the next contract 5 business days before the
current contract's last trading day."*

A rolling reference is a different economic object from a spot print. For calendar-spread work this
is central rather than incidental: on a roll date the two legs of a spread can reference **different
delivery months**, which manufactures a spread that is pure roll mechanics. L19 measured this exact
effect on WTI — a front-month continuous series faked ~0.9 USD/Bbl at every roll.

## Part B — liquidity census (family C, free kills)

**80 of 134 series have open markets.** Best structures by depth:

| series | cadence | rungs | median spread | two-sided | open interest |
|---|---|---|---|---|---|
| `KXWTI` | daily | 95 | 0.06 | 91 | 352,385 |
| `KXRTX5090WS` | weekly | 102 | **0.01** | 79 | 98,188 |
| `KXH200MS` | one-off | 143 | 0.05 | 136 | 112,389 |
| `KXAAAGASM` | monthly | 26 | **0.01** | 6 | 290,373 |
| `KXWTIMAX` | annual | 30 | 0.295 | 30 | **2,946,878** |

Note `KXWTIMAX`: the largest open interest in the whole complex, at a **29.5¢ median spread**. Open
interest is not tradeability. And `KXAAAGASM` shows a 1¢ median spread with only **6 of 26** rungs
two-sided — a tight touch on a mostly one-sided book.

The genuinely tight, deep, two-sided structures are `KXWTI` daily and the **GPU-compute weeklies**,
which is not where a commodities program would have looked first.

## What this does not claim

No calendar spread, no seasonal effect, no relative value, and no edge. This row maps structure and
liquidity so that every later §5.6 row knows which comparisons are legitimate. Commodity series carry
`fee_multiplier: 1` — the 0.07 tier — so the round-trip floor is ~1–2¢ and the minimum viable signal
in this complex is roughly **100–200 bp**; recorded here so no later row forgets it.

## Method note

`OTHER` was split mid-run into `CANDLESTICK_UNNAMED_SOURCE` after inspection showed the bucket was
hiding the finding, and `NO_MARKETS_TO_SAMPLE` was separated from `UNPARSEABLE` — the first pass
counted 46 dormant series as unreadable rules and poisoned four group verdicts with
`INSUFFICIENT_RULES`. Both are reporting corrections, not criteria changes; the classification rule
in the spec is unchanged. Named sources always win over the candlestick fallback, with a test.
