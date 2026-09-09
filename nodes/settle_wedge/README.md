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
   `verdicts_for(..., league=...)` also selects the evidence population when leagues share wording.
   Kalshi's explicit half-at-walkover tennis wording is used on both ITF and tour matches; that
   shared hash cannot transfer a measured ATP/WTA frequency to ITF or an ITF frequency to the tours.
   Explicit ITF qualifying also selects its own evidence key (L47); the main-draw key (L46)
   cannot satisfy it. A missing population-specific rate remains `EVIDENCE_UNMEASURED`.
   L46/L47 completed the fresh historical ITF catalog on 2026-09-09: main-draw reserve
   `0.01768867361249885` (178 adverse / 11,370 mature) and qualifying reserve
   `0.031076457689201795` (27 / 1,185), each an always-one-sided 95% upper bound with
   100% all-singles parseability. HALF/open/malformed cases stay conservative; no future-profit
   guarantee is claimed. L46's corrected offline replay reproduced results/rows byte-for-byte.
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
hash. Only recognizable calendar dates, timezone/AM-PM clock literals, Kalshi tickers and the
league's explicit tournament/round patterns are removed. All other numbers remain, including
settlement durations, payout splits, percentages and decimal amounts. `7 days` and `14 days`
must hash differently. An unfamiliar date/time format remains in the text and blocks for review.
The first validated date and repetitions of that same date are event metadata. Later full dates
retain their signed calendar-day offsets from it, including across month/year/leap boundaries;
their clocks and timezones remain literal settlement content. For example, September 2 → 16 and
October 3 → 17 both retain `calendar_offset_+14d`, while September 2 → 15 does not match. The event
clock may vary; changing the later deadline clock or timezone changes the hash. This also catches
a calendar deadline changed without updating its stated relative duration. A lone yearless event
date may be removed; multiple dates with missing years and invalid calendar dates remain literal.

**Numeric-hash migration (2026-09-09).** The former normalizer dropped every digit-bearing token,
making substantive rule changes invisible. Reviewed hashes now derive automatically from their
verbatim samples with numeric terms preserved; no legacy-hash fallback is permitted. Fresh
discovery and `records_from_spec` reharvest raw rules, so they need no network refetch or manual
hash mapping. Already spawned pollers/proofs must be rebuilt under the new code before use.
Historical `settlement_records` retain legacy hashes (their insert key is the unchanged raw hash),
and `equivalence_records` do not append merely because normalization changed. Preserve those audit
rows as historical evidence; reharvest the stored raw text for current certification. Do not
interpret a legacy stored template hash as approval under the new normalizer.

**The buffer is conservative and orientation-aware.** It charges only Polymarket legs, at the
fill price, summed over bounded dimensions. It is not an expectation; it is a reserve.

## Tests

`tests/test_settle_wedge.py` — the verbatim templates hash to the registered ones, a reworded
template blocks, each block code is reachable, the buffer arithmetic, the composite proof refuses
mismatched leagues, the audit tables are append-on-change.

## Unblocking a competition (the workflow, 2026-09-03)

Every competition trades only when three registries agree, and each step is a file a reader can
audit. In census order (`research/sports/2026-09-03_co-listing-census/`, ledger L28):

1. **Register the league** — one row in `nodes/entities/leagues.py` (Kalshi series, Polymarket tag
   and slug prefix, ESPN path or a `venue_structured` anchor, outcome cardinality). Re-seed the
   entity tables (`python3 -m nodes.entities.seed`); add `aliases_manual.csv` rows for the names a
   venue renders differently from ESPN (`unresolved.csv` lists them with counts).
2. **Cite the rule** — `nodes/rules_exhaustive/rules.py`: the sport's own law that makes the outcome
   set a partition, with the period both venues settle on. Uncited blocks; wrong count blocks.
3. **Harvest and review both texts** — read one live market's `rules_primary`/`rules_secondary`
   (Kalshi) and `description` (Polymarket), record them VERBATIM as `Template`s in `policy.py`
   with the participant names to strip, and rule on the twelve dimensions in `PAIR_POLICY`.
   Kalshi names the competition in its sentence (one template per competition); Polymarket's
   soccer text does not (one template for every soccer league).
4. **Measure every BOUNDED rate** — a `research/sports/…` row registered before the run, a
   results file, a verdict, then the `Evidence` entry in `evidence.py` citing the row. Until then
   the pair blocks at `EVIDENCE_UNMEASURED` and `nodes/entities/leagues.enablement()` says so.
5. **Certify on a fixture pair** in tests, then the league runs unasked (`default_leagues()`).

By the evening of 2026-09-03: MLB, NFL (L30), EPL / La Liga / Bundesliga (L33, a proxy labelled
FLOOR) and college football (L32, FLOOR for FCS) pass step 5 and run unasked. MLS sits at step 4
(no round structure, no original-date source). NBA/WNBA/NHL sit at step 3. UCL and every
competition ESPN does not schedule as team games sit at step 1.

**MLS evidence added 2026-09-09 (L43).** The official preseason 2025 MLS record book supplies the
original schedule that was missing on September 3. All 510 regular-season fixtures join uniquely
to final records and actual final-whistle wallclocks; every one of 19 changed dates is reconciled
to official club sources. Zero cancellations and 13 >48-hour completion delays are registered as
one-sided exact 95% upper bounds, **0.005856766730583303** and **0.040221661406316125**, not zero-risk
or another league's proxy. At a $0.50 Polymarket fill the two dimensions reserve 2.3039214 cents.
MLS now passes evidence enablement; executable edge, other risk gates and operator caps remain.
The research population is regular season only: proof minting requires the externally anchored
ESPN `regular-season` tag and exact slate game ID. Missing/unknown/preseason/postseason tags
block; the tag survives discovery, supervisor/replay recertification and the diagnostic grid.
See
`research/sports/2026-09-09_mls-original-schedule/verdict.md` for the complete audit and limitations.

**Eredivisie evidence added 2026-09-09 (L50).** All 306 fixtures from three dated official
2025/26 scheduling publications join to actual final-whistle clocks; all 15 original date
exceptions have official reviews, including three resumed matches. Original lower bounds use
the earliest candidate date at local midnight, not a selected later confirmation. A discovered
March 7-to-6 advance is corrected append-only; initial artifacts and L49's failure remain.
Independent replay verifies all 329 source/request hashes and every original/corrected row.
Zero cancellations and seven conservative delays register exact one-sided 95% upper bounds
0.009742208949783377 and 0.04253671926053953, reserving 2.6139464 cents at a $0.50 PM fill.
Certification requires the exact ESPN `espn:ere:<id>` regular-season schedule population and
matching slate game ID. Unknown, foreign, preseason and playoff populations still block.
No other league's rates transfer. L50 itself changed no cap. The later F17 operational integration
adds a checked-in `$200` PAPER/DEMO Eredivisie allowance so an evidence-enabled game is not refused
at zero; signed LIMITED_LIVE event/day/contract caps and economic hurdles remain unchanged. See
`research/sports/2026-09-09_eredivisie-interval-bounds/verdict.md` for sources and reproduction.
