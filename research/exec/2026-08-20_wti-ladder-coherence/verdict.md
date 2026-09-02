# L21 — KXWTI ladder coherence, capacity, implied mean — VERDICT

**Part A: `COHERENT`. Zero executable violations across 2,515 ordered strike pairs.**
**Part B: the near-dated ladder is tight (1¢ median); the far-dated one is not (10¢).**
**Part C: `OBSERVATION` — implied mean sits 4.45 bp above CL futures, inside the ladder's own spread.**

Test looks spent **0** · orders **0** · no subscription purchased · snapshot 2026-08-19T20:26Z.
Spec: `./spec.yaml` (criteria untouched). Ledger: L21.

## Part A — the ladders are coherent, and the "inefficiency" at mid is a spread artifact

| event | rungs | mid monotonicity violations | **executable violations** | surviving flat-2¢ | within tick noise |
|---|---|---|---|---|---|
| KXWTI-26AUG2014 | 30 | 2 | **0** (of 435 pairs) | 0 | 0 |
| KXWTI-26NOV03 | 65 | 22 | **0** (of 2,080 pairs) | 0 | 0 |

**24 monotonicity violations exist at mid. Every one of them disappears at executable prices.** Not a
single pair satisfies `yes_ask(K1) < yes_bid(K2)` — the condition for riskless profit — before fees
are even considered. `no_ask ≡ 1 − yes_bid` held exactly on **95/95** rungs, so the NO side carries no
independent information, as phase 1 found on 124,437 markets.

This is the phase-1 lesson reproduced on new instruments: a mid-price "violation" is a spread, not an
edge. Had this been scored at mid it would have reported 24 arbitrages and every one would have been
fictional.

## Part B — capacity, reported per event and never pooled

| event | rungs | median spread | min / max | rungs w/ two-sided depth | total OI |
|---|---|---|---|---|---|
| **KXWTI-26AUG2014** (expires next day) | 30 | **0.01** | 0.01 / 0.04 | 26/30 | 26,461 |
| KXWTI-26NOV03 (~2.5 months out) | 65 | **0.10** | 0.03 / 0.82 | 65/65 | **324,239** |

A **1-cent median spread** on the near-dated ladder — genuinely tight, and on the series L20 proved
settles on exactly the NYMEX CL settlement. The far-dated ladder carries 12× the open interest but a
10× wider spread. Pooling these two would have reported a meaningless ~5¢ median and hidden the only
structure that matters.

## Part C — no detectable mispricing (n=1, an observation)

For **KXWTI-26AUG2014** (OCT 26 contract):

```
ladder implied mean (mid)   84.2475
NYMEX CL futures mid        84.2100   (availability DB, delayed)
gap                         +0.0375 USD/Bbl  =  +4.45 bp
```

**The gap is smaller than the ladder's own 1-cent quote spread, so it is not executable.** The honest
object here is an interval, and it could not be formed: the ask-side survival function truncated
(P at the highest strike = 0.03, above the pre-declared 0.02 guard), so the spec's rule fired and no
interval is quoted. The mid-based number above is reported explicitly as **not executable**.

**KXWTI-26NOV03 could not be evaluated at all** — both bid and ask sides truncated (bid-side P = 0.73
at K=62.99 while WTI is ~84, which is illiquidity rather than probability), and its contract month
did not parse. See below.

**One snapshot. This is an observation, not a measurement**, and it claims nothing about
harvestability, which would require a new numbered row.

## Two findings that were not the point but matter more than Part C

**1. `KXWTI` contains two different settlement definitions.** The near-dated event settles on
*"the daily settlement price for WTI crude oil**(October 2026 contract)**"* — a named month, which is
what L20 measured. The far-dated event settles on *"the **front-month** settle price for a barrel of
West Texas Intermediate oil"* — a **time-varying** reference that will be a different contract when it
settles. **L20's equivalence result therefore applies to the named-month form only**, and any use of
the far-dated ladder needs its own settlement-reference measurement. This is an intra-*series* split,
one level finer than the intra-venue split L15 found between KXINX and KXINXU.

**2. The far-dated rules text contains an unrendered template placeholder.** Its `rules_primary`
reads *"is above `||Price||`"* rather than a number, on a live tradeable market carrying **324,239**
open interest. Recorded as a venue data-quality observation; it does not affect the quoted prices,
but it means the human-readable rule on that market does not state its own strike.

## Method notes

The live snapshot is deliberately **uncached** (`cache_dir=None`), so `results.json` is not
byte-identical across runs — prices move. Reproducibility here is that the pure core is deterministic
given the saved snapshot (`/Volumes/Kilos/janus/wti_ladder/kxwti_ladder_snapshot.csv`), and the two
runs performed agreed on every structural conclusion.

Controls applied as registered: ±0.5¢ tick band (violations under 1.0¢ gross are noise), flat-2¢/leg
fee control, both timestamps recorded with staleness, decimal-dollar strings converted with a [0,1]
assertion that raises rather than clips. IBKR surface unchanged — `/trsrv/futures` and
`/iserver/marketdata/snapshot` only, delayed data, nothing purchased.

A reporting defect was found and fixed mid-run: the interval check reported the string `"OK"` as its
reason for failing, because it used `a.get() or b.get()`. It now names which side truncated, with a
regression test.
