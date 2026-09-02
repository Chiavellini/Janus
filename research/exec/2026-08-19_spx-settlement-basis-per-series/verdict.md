# L15 — S&P 500 settlement basis, per Kalshi series — VERDICT

**The two Kalshi S&P series settle differently, and only one of them settles on the official close.**

| series | what it is | n dates | exactly equal | max &#124;diff&#124; | verdict | status |
|---|---|---|---|---|---|---|
| **KXINX** | daily range ladder | **42** | **42 / 42 (100%)** | **0.00** | `MATCHES_OFFICIAL_CLOSE` | **OK** |
| **KXINXU** | hourly above/below | 37 | 15 / 37 (40.5%) | **0.44** | `WEDGE_MEASURED` | **BLOCK** |

Test looks spent **0** · quotes read **none** · PnL/outcomes read **none** · IBKR touched **not at all**.
Spec: `.../spec.yaml` (criteria untouched). Ledger: `snooping_ledger.md` L15, supersedes L14.
Suite: **87/87** hermetic. `results.json` is **byte-identical on re-run**.

## KXINX — exact, on every date

Over **42 settlement dates (2026-06-12 → 2026-08-18)**, `KXINX.expiration_value` equals the official
S&P 500 close **on every single date, to the cent**. Median diff 0.00, max |diff| 0.00, block-
bootstrapped 95% CI **[0.00, 0.00]**. Zero reference disagreements between FRED and Yahoo; zero
within-series date disagreements.

This is as clean as a settlement-reference measurement gets, and it clears the pre-registered gate
(≥95% exact **and** max |diff| ≤ 0.01) without needing the slack the gate allowed.

## KXINXU — a real wedge, small in bp, decisive at a strike

Only **15 of 37** dates are exact. Median diff 0.00 and CI **[−0.019, +0.068]** — so it is *centred*
on the close and unbiased on average — but the tails are what matter: **max |diff| 0.44 index
points**, median |diff| 0.027 bp. Worst dates: 2026-07-28 **+0.44**, 2026-07-30 **+0.36**,
2026-07-14 **+0.29**.

An average of zero is not agreement. KXINXU strikes are pinned at `.9999` increments, so a
0.44-point discrepancy is exactly the size that flips a digital whose close lands near a strike —
the only region where such a contract carries information. "Unbiased" and "safe to compare against
an option" are different claims, and only the first is true here.

## The series wedge that stopped L14

`KXINX − KXINXU` over the 39 shared dates: **14/39 exactly equal**, median 0.0000, mean −0.0262,
range **−0.4400 … +0.1900**, **not single-signed**. Both series' `rules_primary` is the same
sentence — *"the end-of-day S&P 500 index value on <date>"* — and both close at 16:00 ET. L15 now
locates the discrepancy: **KXINX is the one that matches; the wedge lives in KXINXU.**

## The n=1 IBKR gap is resolved, and it was IBKR's

The settlement map's open observation was Kalshi 7691.76 vs IBKR SPX `last` 7693.26 on 2026-08-18,
1.50 points, "which one is official — U".

Measured: for 2026-08-18 the official close is **7691.76**, `KXINX` is **7691.76** (exact, one of
42/42), and `KXINXU` is 7691.97 (+0.21). **The 1.50-point gap was the IBKR print**, which was read
with the index feed frozen (availability code `Z`) outside RTH. Kalshi's daily ladder was right.

Tier discipline: the official-close side is **R** — FRED's redistribution of the S&P DJI series,
cross-checked against Yahoo `^GSPC`, agreeing on every date. Equality with the S&P DJI **primary**
publication remains **U**. What is established is that KXINX and the widely redistributed official
close are the same number on 42/42 dates.

## Consequences for the settlement map

- Pair `KALSHI_SPX_LADDER_vs_CBOE_SPX_XSP_OPTIONS` moves **BLOCK → OK for `KXINX` only**, and the
  map must name the series. CBOE PM-settled SPXW/XSP exercise-settle on the official closing index
  value by rule, which is the number KXINX matches exactly.
- **`KXINXU` stays BLOCK** with its measured wedge recorded as the pair's `known_basis`.
- A comparison that does not **name** its Kalshi series stays BLOCK, because on 64% of shared dates
  the two series are different numbers.

## What this does not unblock

Nothing IBKR-dependent. **L13's entitlement block is separate and untouched** — every IBKR family
is still `D*` (delayed), so no option-implied digital can be computed at all yet. This removes the
*settlement-reference* obstacle from one side of one pair. The remaining blockers on TB-H11 are the
entitlement, tick-error propagation (Track B trap 9), and the unread Kalshi indices-rulebook
"modified Source Agency" clause.

## Method notes

- Enumeration: both pre-registered channels, agreeing exactly; union 49,530 settled markets across
  4 series (`KXINXAB`/`KXINXI` returned 0). 45,520 rejected as `RULES_NOT_EOD_SP500` (intraday
  strikes), 81 `NO_EXPIRATION_VALUE`, 90 bucketed `NOT_1600_ET`; 3,839 included. Every exclusion is
  reason-coded and counted.
- Sources: FRED 2,512 observations, Yahoo 498, **0 reference disagreements**; 3 dates per series
  were `PRIMARY_ONLY` (outside Yahoo's 2-year window) and were kept out of the headline as
  registered. `stooq` dropped after L14 measured it serving a JS anti-bot page as HTTP 200; the new
  `SourceUnparseable` guard makes that failure mode raise instead of reading as an empty series.
- Defect found and fixed mid-run: `lib.stats.block_bootstrap_ci` returns a **dict**, and unpacking
  it as a tuple degraded every CI to `None`. It was recorded as `ci95_error` rather than dropped
  silently, then fixed to use `day_block_ci`, with a regression test. No verdict depends on the CI,
  so no result changed.
