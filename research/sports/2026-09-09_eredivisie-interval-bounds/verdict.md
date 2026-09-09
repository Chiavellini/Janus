# L50 — Eredivisie regular-season settlement bounds registered

All L50 gates pass for the complete 2025/26 Eredivisie regular season. This enables
population-bound settlement certification, not profitable execution or live promotion.
L49 remains **BLOCKED_ORIGINAL_LINEAGE** with no outcome distribution scored under
that row. L50's immutable spec and PENDING ledger row precede its first outcome read.

| Dimension | Adverse / full population | One-sided exact 95% Clopper-Pearson upper bound |
| --- | ---: | ---: |
| Permanent cancellation / abandonment without completion | 0 / 306 | 0.009742208949783377 |
| Completion after earliest original midnight +48 elapsed hours | 7 / 306 | 0.04253671926053953 |

At a $0.50 Polymarket fill, the two settlement dimensions reserve
**$0.026139464105161454 per contract (2.6139464105161454 cents)**. This is deducted
from executable edge; no prices, books, fills, realized P&L, EV uplift or Sharpe
were measured. Zero cancellations does not become zero risk. The two confidence
bounds are dimension-specific, not a claim of simultaneous 95% coverage.

## Complete originals and conservative timing

The [June 24 definitive publication](https://eredivisie.nl/nieuws/definitief-competitieprogramma-vriendenloterij-eredivisie-2025-26-bekend/)
links the surviving [2025/26 definitive program](https://d3et0fncpz2hhr.cloudfront.net/Overig/Competitieprogramma-VriendenLoterij-Eredivisie-definitief19.pdf).
The [September 10 publication](https://eredivisie.nl/nieuws/wedstrijdwijzigingen-competitieprogramma-vriendenloterij-eredivisie-najaar-2025/)
links the [autumn program](https://d3et0fncpz2hhr.cloudfront.net/Programma-najaar-VriendenLoterij-Eredivisie.pdf).
The [December 23 KNVB publication](https://www.knvb.nl/nieuws/betaald-voetbal/competitiezaken/71370/speelrondes-22-tot-en-met-32-vriendenloterij)
links the [spring program](https://www.knvb.nl/downloads/bestand/29832/vriendenloterijeredivisieprogrammavoorjaar2026).
The generic overwritten definitive URL is not used. The June and autumn responses
retain matching historical Last-Modified dates; the spring response has none, so
its dated official publication and retained conditional schedule are the lineage.
No URL is claimed intrinsically immutable; acquired bytes and provenance are pinned.

June contains 309 rows for exactly 306 ordered home/away fixtures: all distinct
pairs of 18 clubs, each appearing 34 times. Three pairs have duplicate alternative
dates, not extra games. The autumn and spring programs contain 272 and 154 league
rows. First fixture-specific timings occur in June for 126 fixtures, September
for 81, and December for 99. A round window alone never supplies a kickoff.

Every table row and conditional footnote is retained and reviewed. Using the PDF
skill, the relevant full pages were rendered and inspected: June pages 2–6,
autumn pages 4, 6–7, spring pages 5–7. The 47 conditional first publications remain
conditional; L50 never chooses their eventual winning alternative. It instead
uses the earliest published candidate day at **00:00 Europe/Amsterdam**, including
two earlier candidates supplied only by footnotes. Same-day clock permutations
cannot precede midnight. All fixture-specific alternatives have a bounded earliest
day; generic warnings that future cup scheduling may change a date do not erase
the published baseline. See the pre-outcome `source_review.md` and full raw PDFs.

The 306-row original table was frozen with SHA256
`10aaaf0b3b9fed76d21990887e72b8403dc79ea2e89327e94f5d6c3fb45ff647`
before the first final-inventory request. Later dates never replace earlier originals.
The reserve therefore also charges relevant changes announced before venue listing,
and midnight deliberately overcharges some completions relative to actual kickoff.

## Terminal population and exception audit

The [full ESPN inventory](https://site.api.espn.com/apis/site/v2/sports/soccer/ned.1/scoreboard?dates=20250801-20260630&limit=1000)
contains 306 uniquely joined regular-season events plus two Conference League
qualification semifinals and one final. The three playoffs are retained in the
archive but excluded by explicit season/phase, never by their outcome. Unknown
phases, duplicate keys, wrong competitors, missing fixtures or nonterminal
dispositions block registration.

All 306 individual summaries have exactly one period-two `end-regular-time`
wallclock after the event start. The clock is actual completion, not kickoff,
`lastUpdated`, nominal endDate or the last ordinary play. Every initial changed
kickoff date and every completion outside the original calendar date is reconciled
in the 15-entry official review. Suspension reports additionally confirm actual
completion, even where ESPN rewrites the event start to its resumption:
[Ajax–Groningen](https://english.ajax.nl/articles/ajax-record-home-win-over-fc-groningen-in-empty-johan-cruyff-arena/),
[Sparta–N.E.C.](https://www.sparta-rotterdam.nl/sparta-en-n-e-c-houden-elkaar-in-evenwicht/),
and [NAC–Heerenveen](https://www.nac.nl/nieuws/winst-in-twee-delen-voor-gedegradeerd-nac).
NAC's physical venue changed while its home designation remained NAC; the canonical
ordered fixture was not reversed or dropped. The three completion reports and
ESPN final-whistle clocks preserve those events' original timing exposure.

| ESPN event | Home — away | Conservative original date | Actual completion date | Delay adverse |
| --- | --- | --- | --- | --- |
| 740997 | AZ — PEC Zwolle | 2025-08-24 | 2025-09-24 | Yes |
| 741031 | Groningen — Feyenoord | 2025-09-27 | 2025-09-28 | No |
| 741048 | Heracles — Feyenoord | 2025-10-18 | 2025-10-19 | No |
| 741100 | Ajax — Groningen | 2025-11-30 | 2025-12-02 | Yes |
| 741111 | AZ — Excelsior | 2025-12-14 | 2026-01-21 | Yes |
| 741122 | Heracles — Heerenveen | 2025-12-19 | 2025-12-20 | No |
| 741126 | Volendam — Sparta | 2025-12-20 | 2025-12-21 | No |
| 741135 | N.E.C. — Utrecht | 2026-01-09 | 2026-02-11 | Yes |
| 741145 | Excelsior — Telstar | 2026-01-16 | 2026-01-17 | No |
| 741149 | Go Ahead — Heerenveen | 2026-01-25 | 2026-02-11 | Yes |
| 741177 | Sparta — N.E.C. | 2026-02-15 | 2026-02-17 | Yes |
| 741206 | N.E.C. — Volendam | 2026-03-06 | 2026-03-08 | Yes |
| 741209 | Heracles — Utrecht | 2026-03-06 (corrected from March 7) | 2026-03-06 | No |
| 741255 | AZ — Twente | 2026-05-02 | 2026-05-03 | No |
| 741267 | NAC — Heerenveen | 2026-05-10 | 2026-05-11 | No |

## Preserved correction and independent replay

The initial review found the [February 2 KNVB notice](https://www.knvb.nl/node/71450)
advanced Heracles–Utrecht from March 7 to March 6. Its frozen lower bound was still
March 7. Independent review correctly required an earlier bound under L50's
preregistered later-revision rule. `original_bounds_corrections.json` appends that
decision and official source hash; `original_bounds_corrected.json` changes only
that bound to March 6 midnight and retains both candidates. Its completion interval
increases from −2.093333 to 21.906667 hours, still nonadverse. No adverse indicator
is allowed to decrease. All 15 initially required reviews remain present.

The original freeze, first `results.json`, initial official review and initial
manifest remain unchanged. Corrected and registered outputs are separate files.
Independent replay imports none of the author's measurement functions: it verifies
all **329** raw and request-metadata hashes, rebuilds all source rows and original
lower bounds, redoes all 306 initial and corrected joins, confirms the full row
outputs and reproduces the exact confidence bounds within 1e-15. The first HTTP
403 inventory response remains preserved; the same public endpoint succeeded with
the standard client user-agent, and no failed request was deleted or reclassified.

`source_manifest_registered.json` pins the complete source set, immutable criteria,
correction chain, measurement code, independent implementation and final result.
Raw data remains on `/Volumes/Kilos/janus/research/eredivisie-L49` and `eredivisie-L50`.
The recorded acquisition chronology is corroborated by local file birth times and
request timestamps, not an independently timestamped preregistration service.

## Population-bound implementation and current templates

Both `soccer.ere` evidence keys cite L50 only. All twelve existing settlement
dimensions remain ruled; suspension is counted once under postponement. Proof
minting requires an ESPN `regular-season` tag, league `ere`, and numeric
`espn:ere:<id>` game key. Slate recertification also requires an exact match to its
own game ID. Unknown, venue-structured, foreign, preseason and playoff populations
block even when test-injected rates are supplied. No MLS or other league evidence
can substitute.

The canonical current template harvest at **2026-09-09 09:12Z** found one game in
the normal 48-hour window, one co-listed (TEL @ TWE), and zero blocked. The 168-hour
diagnostic returned 11 schedule games and the same one co-listing; the other ten
were not paired (the CLI displays only the first five block details). Actual rule
hashes were `cbf32c90c9032f61` → `kalshi_ere_game_v1` and
`c96e5aa78081bdba` → `polymarket_soccer_game_v3`, both already reviewed. Commands and
verbatim stdout/stderr are preserved in `current_harvest.json` and the external
archive. No new template, league or cap change was made from that result.

Evidence enablement does not override risk authorization. **No league or outer cap
changed**; a missing Eredivisie allowance still refuses execution. No deployment,
live process, arm, account or order changed. This one historical regular season
does not guarantee a future rate, measure postseason, or independently validate
ESPN's underlying clock precision. A forward collector remains the route to
replace historical reserves, as specified in the preserved L49 failure verdict.

## Offline reproduction and tests

```sh
python3 research/sports/2026-09-09_eredivisie-interval-bounds/manifest.py
python3 research/sports/2026-09-09_eredivisie-interval-bounds/independent_replay.py
python3 research/sports/2026-09-09_eredivisie-interval-bounds/register.py
python3 -m pytest nodes/settle_wedge/tests nodes/entities/tests/test_leagues.py research/sports/2026-09-09_eredivisie-interval-bounds/test_measure.py -q
git diff --check
```

Focused suite: **160 tests passed**. It covers actual completion clocks, missing or
ambiguous final events, wrong season/phase/competitors, preserved alternatives,
nonzero confidence bounds, strictly conservative corrections, complete official
reviews, registered rates, full dimension coverage, no transferred evidence and
exact regular-season game binding. All checks are local; the root task owns any
subsequent full-suite, release and live-promotion decision.

**Post-study operational note (F17).** After L50 closed and registered its evidence, the F17
candidate added `ere = 200.0` to the checked-in PAPER/DEMO per-league allowance. This prevents the
newly evidence-enabled league from being refused at a zero effective allowance. It did not change
L50's criteria or result, and it does not raise the signed LIMITED_LIVE event, contract, daily,
loss, protection, or economic-hurdle caps. F17 remains undeployed.
