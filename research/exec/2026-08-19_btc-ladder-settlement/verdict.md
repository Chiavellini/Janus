# L17 — Kalshi BTC ladder settlement characterization — VERDICT

**Intra-venue: `AGREE` — KXBTC and KXBTCD are identical on 1,603 / 1,603 shared strike hours.**
**External: `SOURCE_UNAVAILABLE` — no CF Benchmarks BRTI source reachable; nothing substituted.**
**Pair `KALSHI_BTC_LADDER_vs_CME_BTC_MBT_FUT` stays BLOCK — unchanged, as registered.**

Test looks spent **0** · quotes read **none** · PnL/outcomes read **none** · IBKR touched **not at all**.
Spec: `research/exec/2026-08-19_btc-ladder-settlement/spec.yaml` (criteria untouched). Ledger: L17.

## The headline, and why it matters more than it looks

| | KXBTC vs KXBTCD (this row) | KXINX vs KXINXU (L15) |
|---|---|---|
| shared periods | **1,603 strike hours** | 39 dates |
| exactly equal | **1,603 (100%)** | 14 (36%) |
| max &#124;diff&#124; | **0.00** | **0.44** |
| CI95 | [0.00, 0.00] | — |
| within-series stops | 0 | 0 |
| periods in only one series | **0** | — |

Both BTC series settle every one of 1,603 hours to the same number, to the cent, over
**2026-06-12T00:00Z → 2026-08-19T06:00Z**. Perfect overlap: neither series has a single strike hour
the other lacks.

**This is the opposite of the index result, and it sharpens that anomaly rather than softening it.**
A plausible reading of L15 was that Kalshi simply computes settlement per-series with some slop. That
is now refuted on this venue's highest-volume ladder: 1,603 consecutive hours with zero disagreement
shows the machinery is capable of exact cross-series consistency. **So the KXINXU wedge is specific,
not systemic** — which strengthens (without proving) the v4 hypothesis that the hourly index series
runs on a different Source Agency or certification from the daily one.

What this does **not** say: nothing about whether either BTC series matches BRTI. That half is
unmeasured, below.

## External half: SOURCE_UNAVAILABLE (an access result, never agreement)

All three pre-declared CF Benchmarks endpoints failed — `api.cfbenchmarks.com` does not resolve from
this host (DNS `nodename nor servname provided`), and the `www` host returns HTTP 400.

Per the spec's `FORBIDDEN_SUBSTITUTION` rule, **no exchange spot, aggregator, or futures price was
substituted.** BRTI is a specific multi-venue index with its own methodology; swapping in spot would
be the settlement-reference category error the `AGENTS.md` 2026-08-14 amendment forbids and the one
that produced phase 1's false "efficient open". The Kalshi-vs-BRTI basis therefore remains **entirely
unmeasured**, and that is the honest state, not a gap to be papered over.

## Infrastructure finding (M1, unregistered but free): Kalshi's settled history reaches ~68 days

Both BTC series' earliest recoverable strike hour is **2026-06-12T00:00Z**. L15 independently found
the earliest qualifying S&P settlement date to be **2026-06-12** — a different series family, a
different query, the same floor.

Two independent studies hitting the same boundary is evidence that **Kalshi's settled-market
enumeration reaches back roughly 68 days**, not that either crawl was cut short in time. Consequence
for any future settlement study: the usable window is ~10 weeks, so a design needing a longer history
must collect forward rather than expecting to backfill.

## Enumeration and truncation — stated, not hidden

The registered enumeration is unbounded. These hourly ladders are ~20× the index series: the crawl
had pulled 651 pages / 2.0 GB and was killed before terminating naturally. The analysis ran on the
cached slice: **587,450 unique markets over 651 pages, 0 unparseable**, of which 587,230 were included
and 220 rejected (all `NO_EXPIRATION_VALUE`; **zero** rejected as `RULES_NOT_BRTI`, so every included
market's own rules text names BRTI).

Whether that slice is the *complete* available history cannot be proven — the process did not
terminate on its own. But the evidence points that way: both series share an identical first hour,
that hour matches L15's independently-derived floor, and **zero** strike hours appear in one series
and not the other. A partial cut-off would be unlikely to produce all three. Reported as evidence,
not as proof.

## What is still blocking this pair

Unchanged and untouched by this row: the BRTI-vs-BRR index difference, futures carry / term
structure, the binary-vs-linear hedge delta, and the 17:00–18:00 ET CME crypto halt that brackets the
17:00 ET strike hour. All need the IBKR side. This row characterized one half of one side.
