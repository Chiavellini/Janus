# L145 verdict — removing selection also removed the regime where the defect lives

**Registered verdict: `MIXED_OR_INCONCLUSIVE`.** Too few moved pairs to compute a direction:
Polymarket **0** moved, Kalshi **1** moved, against a registered minimum of 30 per venue. No branch was
widened.

The row does not answer its question. It does answer a more useful one — *why* this design cannot —
and it recovers one selection-free venue contrast along the way.

## What the sweep did

One bounded pass on the box while the kill was latched, 87.8 s, no deadline hit, no fetch errors.
179 Polymarket and 155 Kalshi plain legs fetched once each (Polymarket at rate 2, half the lane
reconciler's bucket). 182 REST reads paired with a `stream_evaluations` row for the same game and
quantity; **47 of them within the registered 3.0 s window** (22 Polymarket, 25 Kalshi). 460 candidate
pairings had no matching leg in the nearest row and 196 `:NO` legs were excluded, all counted.

## What came back

Inside the 3.0 s window:

| | fresh pairs | exactly unchanged | moved | favourable given move |
|---|---|---|---|---|
| **Polymarket** | 22 | **22** | 0 | undefined |
| **Kalshi** | 25 | 24 | 1 (−0.2c) | undefined at n=1 |

**Every fresh Polymarket pair matched REST exactly.** On its face that says the Polymarket feed is
perfectly faithful off-selection — which would refute L144. It does not license that reading.

## Why the zeros cannot be read as fidelity

**The sample is dominated by quiet, unselectable books.** Of all 182 pairs, 135 were `BLOCKED_MATCH`
and 36 `NO_EDGE`; only 2 were `PROFITABLE_UNEXECUTED`. 69% were ITF tennis, the rest ATP/WTA
Challenger. These are markets the lane could not pair or found no edge in — thin, and mostly not
moving.

**On a quiet book the comparison is close to circular.** The lane's Reconciler
(`nodes/stream_polymarket/reconcile.py`) fetches a REST book for every quiet replica roughly every
15 s and *adopts* it into the replica (`replica.py:287-314`). A quiet book's websocket price is
therefore often already a REST price, and a fresh REST read of an unchanged book returns the same
thing. `legs_json` does not store `source`, so which pairs were adopted cannot be separated.

**The regime is wrong.** L143 and L144's losses occurred on *selected* markets while the book was
*moving*. An exogenous-clock sweep of unselected markets lands overwhelmingly in books that are
neither. A quiet book agreeing with REST says nothing about a moving one.

This is the methodological lesson of the row, and it generalises: **selection is not only a bias to
subtract — it is what concentrates the lane in the moving-book regime.** Removing it on a fixed clock
also removed the conditions under which the defect appears.

## The one selection-free venue contrast available

The spec registered `socket_health` as context. Over the 183 s around the sweep, with no reconnects on
either socket:

| | updates | integrity failures | measure |
|---|---|---|---|
| **Polymarket** | 288,592 | **613 top-of-book drifts** | agreement 0.9974 |
| **Kalshi** | 453,878 | **0 sequence gaps** | — |

Directionally this matches L144: Kalshi's sequenced feed recorded no integrity failure while
Polymarket's recorded 613 — about 3.4 a second across all subscribed assets, selected or not.

Three limits keep this from carrying a verdict. The instruments differ — Polymarket's is a
claimed-bid/ask check (`stream.py:160-181`), Kalshi's a sequence-gap check — so this is not
like-for-like. It is **top-of-book only**. And every Polymarket drift **invalidates the book**
(`Fault.HASH_MISMATCH`), so a book that failed this check was never traded. At 99.74% agreement the
top-of-book failure rate is far too low to explain L143's 128 adverse moves in 169.

Which points somewhere specific: **the books that hurt the lane are the ones that pass the top-of-book
check and are wrong deeper down.** That is precisely what the top-of-book check cannot see.

## The reconciler's depth check is discarded — and only ever sees quiet books

> **CORRECTION 2026-09-17.** This section originally said `rest_drift` "runs on every subscribed
> asset about every 15 s" and recommended persisting it. **Both were wrong.** `due()`
> (`reconcile.py:28-37`) selects only replicas more than 15 s past their last verification, and any
> agreeing `price_change` at any depth resets that clock (`stream.py:164-170`). Busy books are never
> selected — by design (`reconcile.py:9-11`). So `rest_drift` measures exactly the quiet books this
> row already found faithful, and persisting it would not answer the question. See L146.

The Reconciler's `rest_drift` counter compares websocket against REST **level by level** —
`BookReplica._close` requires the identical *set* of price levels, with sizes within tolerance
(`replica.py:316-320`). It is depth-aware, but it runs only on **quiet** replicas.

**It is never persisted and never printed.** `TupleStore.socket_health` (`store.py:385`) does not
write the `reconcile` key, and the report tick (`grid.py:1947-1951`) prints only frames, drift and
agreement.

**Documentation defect:** `grids/live_stream/README.md:94` states the reconciler counters "ride along
in the Polymarket `stats()` and so in `socket_health`." The first half is true; the second is false.
(Line 93 of the same README correctly describes the reconciler as covering "quiet Polymarket
replicas" — this row's original text got that part wrong, not the README.)
This is the same class of defect as the other instrument traps in this project — a number believed to
be recorded that is not.

## What this leaves

L144's reading — a Polymarket-side defect — is **neither confirmed nor refuted** by this row.

~~The cheapest correct way to answer it is to persist `rest_drift` per asset.~~ **Withdrawn
2026-09-17:** `rest_drift` only ever sees quiet books, so persisting it would reproduce this row's
regime problem rather than solve it. The follow-up is L146, which reproduces the depth-verification
defect directly against the deployed stream code.

No production state, order, kill, override, cap, hurdle or entry policy was changed. No replica was
touched and no second socket was opened. Raw extractor output is retained verbatim at
`results_20260916.json`, schema `janus.l145.pm_feed_fidelity.v1`, matching `measure.py`.

---

*Description only, never the verdict:* across all 182 pairs at any separation (p50 ≈ 11 s), both
venues look roughly symmetric and alike — Polymarket 9 favourable / 13 adverse (0.409 given a move,
n=22), Kalshi 7 / 10 (0.412, n=17). At eleven seconds apart, genuine price movement dominates any feed
effect, so this similarity is expected under every hypothesis and discriminates nothing. Both moved
counts are also below the registered minimum.
