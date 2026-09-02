# L18 — Kalshi FOMC ladder settlement characterization — VERDICT

**`INSUFFICIENT_COVERAGE` — 2 settled meetings recoverable, against a pre-registered gate of 5.**
**External comparison `NOT_REACHED`. Pair `KALSHI_FOMC_LADDER_vs_CME_ZQ` stays BLOCK, as registered.**

Test looks spent **0** · quotes read **none** · PnL/outcomes read **none** · IBKR touched **not at all**.
Spec: `research/exec/2026-08-19_fomc-ladder-settlement/spec.yaml` (criteria untouched). Ledger: L18.

## The pre-registered expectation held

The spec stated, before running, that this row was expected to fail its coverage gate. It did:

| | |
|---|---|
| settled markets across both series | **32** |
| meetings recoverable, KXFED | **2** (26JUN, 26JUL) |
| meetings recoverable, KXFEDDECISION | **2** (26JUN, 26JUL) |
| shared meetings | **2** |
| pre-registered gate | 5 |

The intra-venue consistency question was therefore **not answered** and no distribution is quoted.
Per the spec, the external comparison against the Fed's published target range was **not attempted** —
recorded as `NOT_REACHED`, which is neither agreement nor failure.

## What this actually establishes: the retention floor, now on three independent families

This is the third independent confirmation of L17's finding, and the cleanest:

| row | series family | earliest recoverable | consistent with ~68 days? |
|---|---|---|---|
| L15 | index (KXINX / KXINXU) | 2026-06-12 | yes |
| L17 | BTC (KXBTC / KXBTCD) | 2026-06-12T00:00Z | yes |
| **L18** | **FOMC (KXFED / KXFEDDECISION)** | **June 2026 meeting** | **yes** |

Three different series families, three different query shapes, one boundary. **Kalshi's settled-market
enumeration reaches back roughly 68 days and no further.** The FOMC case is the sharpest test because
its events are sparse and calendar-pinned: with ~8 meetings a year, a 68-day window can hold about
two, and exactly two are there.

## The actionable consequence

**The FOMC pair cannot be characterized from Kalshi's available history at any point in the future by
backfilling — it must be collected forward.** At ~8 meetings a year, reaching the gate of 5 takes
roughly **7–8 months of forward collection**, and the clock only starts when someone starts recording.

This generalizes beyond FOMC: any Janus study whose unit of observation is sparser than about one per
week is permanently uncharacterizable from Kalshi backfill. That is a design constraint on the whole
program, not a fact about this row.

## What this does not say

Nothing about whether KXFED and KXFEDDECISION are mutually consistent — n=2 is an observation, not a
measurement, and the spec forbids quoting it as one. Nothing about the pair's real blocker either:
ZQ prices a **monthly average of daily EFFR** while Kalshi prices the **target-range upper bound after
one meeting**, and bridging them needs the meeting date, pre/post-meeting day counts, the
EFFR-minus-upper-bound spread, a move-size grid, and any second event in the month. None of that is
touched here, and the pair's low prior (Track B brief: "a cheap falsifiable check, not a lead")
is unchanged.
