# settle_wedge

**Kind:** `pure`
**Implements:** `harvest.py` (rules text → record), `policy.py` (reviewed templates and verdicts),
`equivalence.py` (the token, the composite proof, the buffer), `evidence.py` (measured rates),
`records.py` (the audit tables)

**The second proof a cover needs.** `nodes/rules_exhaustive` proves the outcome set is complete;
this proves the two venues pay the same thing in every way the game can end — or that where they
differ the difference is bounded and priced. `CoverProof` composes the two and is what
`nodes/cover` requires. An unknown ruleset is a BLOCK, never zero risk.

## Position in the grid

```
Kalshi market rules_primary/secondary ─┐
Polymarket market description ─────────┼──▶ [harvest] ──▶ RulesRecord (rules_hash, template_hash)
                                        │                       │
reviewed templates + per-pair verdicts ─┘◀── [policy] ◀─────────┘
measured rates ◀── [evidence] ◀── research/…            [equivalence.certify]
                                                                │
rules_exhaustive proof ──▶ [certify_cover] ──▶ CoverProof ──▶ [cover] (buffer into the cost)
                                                                │
                                                       [records] ──▶ settlement_records, equivalence_records
```

**Upstream:** `nodes/discovery` (the market dicts), `nodes/rules_exhaustive`.
**Downstream:** `nodes/game_poller` (certified at spawn), `nodes/cover` (the buffer), the store.

## How a verdict is reached

1. `harvest` strips participants, dates, times and tickers from the venue's text and hashes what is
   left: the **template**. Kalshi and Polymarket generate game rules from a per-league template,
   so one hash covers a league-season.
2. `policy.TEMPLATES` holds each template a human has read, recorded verbatim with the date.
   A hash that matches nothing → `TEMPLATE_UNKNOWN` → block. A venue editing its wording moves
   the hash and blocks the league until the new text is reviewed.
3. `policy.PAIR_POLICY` holds, per pair of templates, a verdict on all twelve dimensions:
   `SAME`, `NA` (with the citation), `BOUNDED` (with the evidence key and loss model),
   `DIFFERENT`, `UNKNOWN`. Any `DIFFERENT`/`UNKNOWN`, or a missing dimension, blocks.
4. A `BOUNDED` dimension is priced as probability × worst-case loss. The probability must be in
   `evidence.EVIDENCE`, which only a `research/` row may fill; absent → `EVIDENCE_UNMEASURED` → block.
5. `certify()` mints `SettlementEquivalence`; `certify_cover()` checks it names the same
   (league, market type, period) as the exhaustiveness proof and mints `CoverProof`.

## The MLB wedge (2026-09-02)

Kalshi: postponed/delayed → stays open if the makeup finishes **within two days**, else
**fair price**; cancelled → fair price. Polymarket: postponed → stays open **until completed**;
cancelled or tie → **50-50**. On a cancellation the Kalshi leg pays ≈ its own price and the
Polymarket leg pays a half, so the cover loses `max(0, p_pm − 0.5)` when the Polymarket leg is
the favourite; on a makeup more than two days out the Polymarket leg pays the eventual result,
worst case 0. Both are `BOUNDED` by `mlb.cancelled_rate` and `mlb.postponed_gt2d_rate`.
**Until those are measured, every MLB cover blocks with `EVIDENCE_UNMEASURED`.** That is the
spec's rule and it is deliberate.

NFL: Kalshi settles a tie at $0.50 each and a game not started within 48 h at a fair price;
Polymarket has no NFL game market listed yet, so nothing is reviewed and NFL blocks at
`TEMPLATE_UNKNOWN`. NHL likewise until harvested.

## Failure modes

**Normalisation is by stripping, not by parsing.** Team names come from the pair (venue labels
and ESPN names); a name the caller does not supply survives into the template and moves the
hash — a false block, never a false pass. Digits, months and timezones are dropped wholesale.

**The buffer is conservative and orientation-aware.** It charges only Polymarket legs, at the
fill price, summed over bounded dimensions. It is not an expectation; it is a reserve.

## Tests

`tests/test_settle_wedge.py` — the verbatim templates hash to the registered ones, a reworded
template blocks, each block code is reachable, the buffer arithmetic, the composite proof refuses
mismatched leagues, the audit tables are append-on-change.
