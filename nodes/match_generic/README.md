# match_generic

**Kind:** `pure` (verify, block) + `tool` (score_gold)
**Implements:** `verify.py`, `block.py`, `score_gold.py`, `gold/`

The cross-venue matcher for markets that are NOT team games: threshold and date events (prices,
prints, rankings, utterances, "will X happen by"). Recovered on 2026-09-03 from `match/` at
`5eac384^`, where it was left out of the node grid, because the operator's scope is every
co-listed short-life event, not only sports.

`block.py` proposes candidate Kalshi–Polymarket pairs from a catalog (recall-optimised, expected
to emit garbage). `verify.py` is the deterministic equivalence layer: it reads NO prices and
rejects on structure — unrendered placeholders, archetype, resolution date, no shared subject,
settlement-source mismatch, subject, superlative-vs-threshold, strike ladder and direction,
range-vs-threshold, rank/region qualifiers, and the trigger-set relation for utterance markets
(a strict superset of triggers is a HARD reject: the "AI / Artificial Intelligence" case).
It never returns EQUIVALENT on its own: a pair that survives is UNDECIDED and needs both rules
texts read. `screen.py` (the price screen) was deliberately not ported: prices are read after
equivalence, never while deciding it.

## The gate (ledger L31)

L25 measured 61% of this population's apparent edge as false pairs. Before any pair from here can
reach a settlement-reference equivalence record and the lane, the blind gold set
`gold/nonsports.csv` (144 pairs, 8 strata of 18, verdicts withheld in `gold/nonsports.key.json`)
must be LABELLED — by the operator, reading both texts — and the deterministic layer's precision
scored per stratum with `score_gold.py` against a bar declared before scoring. The `label` column
is empty on 2026-09-03: nothing here has a measured precision yet, and no number may be quoted.

Reproduced on the archived 2026-08-20 corpus (`/Volumes/Kilos/janus/catalog_2026-08-20_nonsports`
+ `match_2026-08-20/candidates.json`): see the commit that added this node for the counts.

## Tests

`tests/test_verify.py` — every case a real pair from the 2026-08-20 crawl or the 2026-07-25
mentions corpus, including the two bugs the file caught: the trigger extractor firing on
non-utterance markets, and `archetype == "other"` (a no-match sentinel) treated as a difference.
