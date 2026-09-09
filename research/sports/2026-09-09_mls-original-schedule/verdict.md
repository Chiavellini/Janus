# L43 — MLS settlement evidence registered

All preregistered gates pass for the **2025 MLS regular season**. The two missing MLS
settlement rates can be registered without borrowing another league's rate or changing an
UNKNOWN verdict to zero. This is a settlement-reserve measurement, not a profitability test.

| Dimension | Observed events / complete population | Registered one-sided exact 95% upper bound |
| --- | ---: | ---: |
| Cancelled / abandoned without completion | 0 / 510 | 0.005856766730583303 |
| Completed >48 hours after original schedule, with conservative calendar boundary | 13 / 510 | 0.040221661406316125 |

For a Polymarket leg bought at $0.50, these rates reserve **$0.023039214068449714 per contract**
(2.3039214068449714 cents). The cancellation reserve is nonzero despite observing no cancellations.
The existing cover calculation still requires executable positive edge after fees, depth,
freshness and this reserve. Coverage increases; positive EV is not demonstrated by this row.

## Source and completeness audit

- Original schedule: official [2025 MLS Fact and Record Book](https://images.mlssoccer.com/image/private/fl_attachment/mls/lcq7kwlyhdgd4qnpfnqy.pdf),
  physical PDF pages 259–261, explicitly dated January 6, 2025 and expressed in Eastern time.
  All three pages were rendered and visually checked with the PDF skill. The official publication
  is linked by the [MLS 2025 media center](https://www.mlssoccer.com/news/mls-is-back-2025-media-center).
  SHA256: `65ce092fff5ad01d9fe3499e10fb7afcdabb025a93d2107b4e8ec84a1cf807f9`.
- The original inventory contains exactly 510 fixtures, 30 clubs each appearing 34 times, and
  no repeated home/away pairing. It joins one-to-one to the 510 regular-season records in the
  [ESPN full-season inventory](https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard?dates=20250201-20251019&limit=1000).
  The all-star game is excluded structurally; no original fixture is dropped.
- Every one of the 510 individual ESPN summaries contains exactly one completed competition and
  a period-two `end-regular-time` key event with a final-whistle `wallclock`, later than kickoff.
  This measures actual completion, including a suspended match that resumes later. Current
  scheduled kickoff, `lastUpdatedAt`, and `wasSuspended=false` are **not** substituted for this
  timestamp. Missing or ambiguous completion blocks registration.
- All 19 changed kickoff calendar dates are independently reconciled to an official MLS/club
  publication in `official_review.json`; their raw HTML is archived and hashed. Thirteen changes
  exceed 48 hours and six are next-day changes. There are no additional delayed completions
  hidden behind an unchanged kickoff date in this population.
- The registered conservative boundary counts a completion at least two Eastern calendar dates
  after the original date, even if elapsed time could be under 48 hours. None of the 13 observed
  long moves is such a borderline case. Changes announced before venue listing remain included.

## Exact official date mismatches

All dates below are Eastern calendar dates. The event ID resolves to the review's official URL.

| ESPN event | Home — away | Original | Actual | Charged to >48h numerator |
| --- | --- | --- | --- | --- |
| 726939 | Inter Miami — Dallas | 2025-04-26 | 2025-04-27 | No |
| 726944 | Minnesota — Vancouver | 2025-04-26 | 2025-04-27 | No |
| 727034 | LAFC — Kansas City | 2025-05-28 | 2025-06-08 | Yes |
| 727045 | Vancouver — Portland | 2025-05-31 | 2025-09-24 | Yes |
| 727046 | LAFC — Colorado | 2025-05-31 | 2025-07-09 | Yes |
| 727157 | Houston — LA Galaxy | 2025-07-25 | 2025-09-06 | Yes |
| 727055 | LAFC — Toronto | 2025-06-13 | 2025-10-08 | Yes |
| 727169 | New York City — Columbus | 2025-08-09 | 2025-09-17 | Yes |
| 727077 | Salt Lake — LAFC | 2025-06-25 | 2025-09-17 | Yes |
| 727082 | Inter Miami — Atlanta | 2025-06-28 | 2025-10-11 | Yes |
| 727093 | LAFC — Vancouver | 2025-06-28 | 2025-06-29 | No |
| 727103 | Austin — LAFC | 2025-07-05 | 2025-10-12 | Yes |
| 727217 | Orlando — Vancouver | 2025-08-30 | 2025-10-11 | Yes |
| 727214 | Inter Miami — Chicago | 2025-08-30 | 2025-09-30 | Yes |
| 727227 | LA Galaxy — Dallas | 2025-08-30 | 2025-10-11 | Yes |
| 727226 | Seattle — Salt Lake | 2025-08-30 | 2025-10-11 | Yes |
| 727248 | New York City — Charlotte | 2025-09-19 | 2025-09-20 | No |
| 727258 | Austin — Seattle | 2025-09-20 | 2025-09-21 | No |
| 727264 | Cincinnati — Orlando | 2025-09-27 | 2025-09-28 | No |

## Reproduction, invariants and limits

The immutable `spec.yaml` and original PENDING ledger row predate measurement. The initial
`results.json` and `source_manifest.json` preserve the state before official exception review;
`results_registered.json` and `source_manifest_registered.json` are separate final artifacts.
The runner refuses changed existing results or manifests. Raw PDFs, text, 510 summaries,
scoreboard and 19 review pages live on `/Volumes/Kilos/janus/research/mls-L43`, not the root disk.

Reproduce offline with:

```sh
python3 research/sports/2026-09-09_mls-original-schedule/measure.py --review
python3 -m pytest nodes/settle_wedge/tests/test_mls_evidence.py -q
```

The MLS-specific certification test checks both evidence keys, their source row, full template
certification, enablement with no missing evidence, and that each probability is charged once.
The suspension dimension remains `COUNTED_UNDER_POSTPONEMENT`; it is not a third charge.

Review identified and closed two scope hazards. A suspension-only long completion requires an
official **completion-date** review, not merely a kickoff-date announcement. MLS proof minting
also requires an ESPN schedule tag explicitly naming `regular-season`; discovery and the
diagnostic live-sports grid preserve that tag with its exact game ID. Missing, mismatched,
preseason and postseason tags fail `EVIDENCE_POPULATION_MISMATCH`, including legacy slate specs
that have no tag. The proof's audit record carries its population and schedule game ID.

Limitations: one regular season, no postseason population, no independent validation of ESPN's
underlying event clock accuracy, and no claim that a historical confidence bound guarantees the
future rate. Cup/calendar moves make this bound conservative for venue-listing-time decisions.
The requested paper/demo MLS league allowance is added at $200 so an enabled regular-season
fixture does not encounter an accidental zero league cap. Event/day/live outer caps are unchanged.
This edits the limits SHA and is **not** a live promotion: a fresh signed override and GATE
sequence are required before deployment. No live override, running process, account or order
was changed by this work.

The other blocked soccer leagues require their own original-date and completion populations;
see `other_soccer_source_assessment.md`. No MLS rate transfers to them.
