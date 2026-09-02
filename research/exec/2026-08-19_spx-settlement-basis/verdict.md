# L14 — S&P 500 settlement-reference basis — VERDICT

**STOP — `WITHIN_DATE_DISAGREEMENT`. The registered design is not well-defined on the data.**
Pair `KALSHI_SPX_LADDER_vs_CBOE_SPX_XSP_OPTIONS` **stays BLOCK.**
Test looks spent **0** · quotes read **none** · PnL/outcomes read **none** · IBKR touched **not at all**.

Spec: `research/exec/2026-08-19_spx-settlement-basis/spec.yaml` (criteria untouched).
Ledger: `snooping_ledger.md` L14. Code: `measure_spx_basis.py`. Suite: **81/81** hermetic
(66 pre-existing + 15 new in `tests/test_spx_basis.py`).

## What stopped it

The spec's dedupe rule reads *"one `(settlement_date, expiration_value)` pair per settlement date"*.
That sentence contains an assumption about the venue — that a date **has** one Kalshi settlement
value — and the assumption is **false**.

| | |
|---|---|
| Qualifying settlement dates (EOD-rules text **and** 16:00 ET close) | **46**, 2026-06-12 → 2026-08-18 |
| Dates carrying **both** S&P series | **39** |
| Dates where the two series settle at the **same** value | **14 / 39** |
| Dates where they **disagree** | **25 / 39 (64%)** |

Coverage was never the problem — 46 dates comfortably clears the pre-registered 20. The problem is
that "the Kalshi settlement value for date D" does not identify a number.

## The finding (M1)

**Two Kalshi series on the same index, the same day, the same 16:00 ET instant, whose rules text is
the same sentence, publish different settlement values.**

```
KXINX-26JUL07H1600   (daily range ladder,  30 markets)  expiration_value 7503.85
KXINXU-26JUL07H1600  (hourly above/below,  60 markets)  expiration_value 7503.74
                                                        wedge            0.11
```

Both rules_primary strings read *"the end-of-day S&P 500 index value on July 07, 2026"*.

`KXINX − KXINXU` over the 39 shared dates: median **0.0000**, mean **−0.0262**, range
**−0.4400 … +0.1900**, median |wedge| **0.027 bp**, **not** single-signed. Small in bp, but the
strikes are pinned at `.9999` increments — a 0.44-point discrepancy decides a digital whose close
lands near a strike, which is precisely where such a contract is worth anything.

**The registered within-EVENT consistency check passed everywhere — 0 event stops across 3,839
included markets.** The two series are each internally consistent. They disagree with *each other*.
So this is not a misread field; it is a real intra-venue settlement-reference wedge, and it is the
exact hazard the `AGENTS.md` 2026-08-14 amendment was written for — *"an intra-venue comparison can
be the identical category error"* — showing up on a pair that looked like the safe one.

## What this does and does not say

- It does **not** say Kalshi disagrees with the official close. That comparison was never reached.
- It does **not** unblock or further block anything IBKR-dependent. The L13 entitlement block is
  separate and untouched.
- It **does** mean any future Kalshi-S&P-vs-option comparison must name its series. Treating
  "Kalshi's S&P settlement" as one reference would silently mix two, on 64% of dates.

## Enumeration and sources (M1)

Both pre-registered channels agreed exactly — `markets` and `events` each returned 1,410 KXINX and
48,120 KXINXU settled markets; union 49,530. Of these, 45,520 were rejected as `RULES_NOT_EOD_SP500`
(intraday hourly strikes), 81 as `NO_EXPIRATION_VALUE`, 90 bucketed as `NOT_1600_ET`, leaving 3,839
included. No silent drops: every exclusion is reason-coded and counted.

**Relay failure, recorded as an access result.** `stooq` — the spec's *primary* close source —
returns HTTP 200 carrying a JavaScript challenge page, not CSV, from three URL variants. The
collector parsed 0 rows without raising, which is a reporting defect: an anti-bot page and an empty
series are not the same event and must not look the same. Yahoo returned 498 sessions. With one
relay, every row is `SINGLE_RELAY` and the spec correctly keeps them out of the headline.

## Disclosure — a source read after the STOP

Looking for a second relay for the successor row, I fetched **FRED series `SP500`** (2,608 rows,
sourced by FRED from S&P Dow Jones Indices — closer to primary than either pre-declared relay) and
its most recent row was visible: **2026-08-18 → 7691.76**, equal to Kalshi's `expiration_value` for
that date and 1.50 points below the IBKR frozen print of 7693.26.

This is disclosed rather than used. It is **n=1**, I saw it before the successor row was registered,
and it sets no criterion there — the successor's gates are structural (exact-equality fractions),
fixed before the join, and cannot be tuned by one observation. It is suggestive that the IBKR
frozen (`Z`) print was the outlier in the original n=1 gap, and that remains **suggestive, not
measured**.

## Consequence

L14 is closed as a STOP. Its criteria are not edited and its dedupe assumption is not repaired in
place — per ledger rule 6, a correction is a **new row**, not an amendment. The successor is
registered as **L15** with a per-series design (each series measured separately against the close,
plus the series-vs-series wedge as a first-class output) and FRED promoted to the primary reference.
