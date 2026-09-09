# Other blocked soccer competitions — source assessment only

As of 2026-09-09. No outcome distributions were read or measured, no new evidence was registered,
and no other league was unblocked. Each needs a separate immutable spec and PENDING ledger row
before joining original schedules to final results. **No MLS rate transfers.**

The MLS method needs fixture-level original dates, a complete final inventory, and actual
completion evidence that detects suspended/resumed matches. A league's calendar page showing
the eventual dates is not an original schedule. A nominal Sunday for a Friday–Monday round is
not the original kickoff. No complete original/final pair for these five has passed those gates
in this source-only assessment; claiming it has would require running the next registered row.

| League | Original source found | Shortest separately preregistered path |
| --- | --- | --- |
| `fl1` Ligue 1 | Immutable-looking, season-specific official 2025/26 PDF, all 306 pairings, but nominal round days rather than individual kickoff times | Recover the dated LFP television scheduling batches for every fixture. Join to `fra.1` final inventory and final-whistle summaries; review all exceptions. If complete dated batches cannot be recovered, collect first-seen scheduled times forward. |
| `ere` Eredivisie | Official June 18, 2025 concept PDF survives for 2025/26; individual dates/times through round 12, ranges thereafter, with conditional alternative fixtures | Most promising historical route: preregister all 306 fixtures, preserve this PDF and each later official scheduling batch, resolve conditional originals conservatively without reading outcomes, then join `ned.1` finals/completion clocks. Do not use the overwritten generic final PDF. |
| `por` Liga Portugal | Official 2025/26 calendar PDF survives, but it lists round windows, not fixture-specific kickoffs; the calendar URL is reused | Enumerate dated official scheduling communiqués for all 306 top-flight fixtures before measuring. If their archive cannot prove each original fixture's first confirmed date, a forward collector is required. |
| `scop` Scottish Premiership | June 20, 2025 announcement survives, but its full-fixture link goes to the mutable current fixture page | Recover frozen league/club fixture publications for the initial 33 rounds (198 fixtures), plus the separate April post-split publication (30). Repeated home/away pairings require round/date-aware unique joins. Otherwise collect forward; do not treat the mutable page as preseason evidence. |
| `bel1` Belgian Pro League | Dated initial and later scheduling announcements survive; a complete immutable fixture-level original file was not verified | Recover the dated regular-season TV batches (240 fixtures) and separately register playoff fixtures/format. Otherwise forward collection is required. Never transfer regular-season evidence to playoffs or the changed 2026/27 format. |

## Exact official source pointers and hazards

### Ligue 1

The [June 27, 2025 announcement](https://ligue1.com/fr/articles/l1_article_2812-) links this
[season-specific fixture PDF](https://s3.eu-west-3.amazonaws.com/ligue1.image/cms/Calendrier_L1_M_0fd5bc8c7b.pdf).
It labels opening round Sunday August 17 although the announced season starts Friday August 15.
Thus it can prove fixture identities/round membership, not actual original kickoffs. A new study
could instead preregister a worst-case bound from the earliest possible time in each original
round, but it would charge ordinary weekend scheduling as risk and may be too costly to trade.
The accurate path is dated fixture-level broadcast announcements, not the existing round proxy.

### Eredivisie

The [June 18, 2025 concept announcement](https://eredivisie.nl/nieuws/concept-speelschema-vriendenloterij-eredivisie-2025-26/)
links the surviving [2025/26 concept PDF](https://d3et0fncpz2hhr.cloudfront.net/CONCEPT-Competitieprogramma-VriendenLoterij-Eredivisie.pdf).
It includes alternative UEFA-dependent dates and later round ranges, which cannot be flattened
into one chosen date after seeing results. The
[September 2025 scheduling update](https://eredivisie.nl/nieuws/wedstrijdwijzigingen-competitieprogramma-vriendenloterij-eredivisie-najaar-2025/)
is the next dated source to archive. The generic `Definitief-Competitieprogramma-VriendenLoterij-Eredivisie.pdf`
URL now serves 2026/27; its URL is not proof of a 2025 original. A
[KNVB 2024/25 PDF](https://www.knvb.nl/downloads/bestand/28758/competitieprogrammaeredivisiedef)
is another season-specific candidate, not measured here.

### Portugal

The [official 2025/26 calendar communiqué](https://www.ligaportugal.pt/backoffice/assets/Comunicado_Oficial_n_292_Calendarios_das_Competicoes_Profissionais_2025_26_34bdb36f90.pdf)
is a round calendar with explicit alternative UEFA dates, not a complete original fixture list.
The `/pages/calendario-2025-26` page now renders a different season. Search the
[official communiqué archive](https://www.ligaportugal.pt/statements) for dated kickoff batches;
preserve every source before computing a result.

### Scotland

The [June 20, 2025 fixture announcement](https://spfl.co.uk/news/spfl-fixtures-for-202526) confirms
the original publication, but its fixture link is `https://spfl.co.uk/league/premiership/fixtures`,
which is mutable. It also explicitly permits UEFA-related postponements and later TV moves.
The [fixture Q&A](https://spfl.co.uk/news/season-202526-fixtures-qa) and
[post-split announcement](https://spfl.co.uk/news/press-release-post-split-fixtures-51159) explain
why a full-season study needs two original publications and distinct phase tags. Neither a
33-round denominator applied to 38-round outcomes nor a home/away-only join is acceptable.

### Belgium

The [initial 2025/26 announcement](https://www.proleague.be/fr/informations/calendrier-2025-2026-lunion-ouvre-la-saison-a-lantwerp-le-club-brugge-face-au-krc-genk)
and [exact-date update through the winter break](https://www.proleague.be/fr/informations/programme-exact-des-matchs-fixe-jusqua-la-treve-hivernale)
are source leads, not yet a complete first-scheduled timestamp archive. The
[season structure announcement](https://www.proleague.be/fr/informations/les-grandes-lignes-de-la-saison-2025-2026-fixees)
must define regular-season/playoff populations before counting. The calendar landing page did
not yield a verified immutable downloadable schedule in this assessment.

## Forward fallback contract

For a league without a complete historical original archive, preregister a forward row before
collecting: persist the first observed fixture identity, provider original timestamp, collection
time, official phase, and raw payload hash; append all schedule changes without overwriting the
first observation; follow each match to authoritative final completion/cancellation, retaining
unresolved rows. Add a watchdog SLA so an empty/crashing collector cannot look like evidence.
Register a conservative nonzero upper bound only at the prespecified completeness gate. A
confirmed in-play state alone does not remove abandonment/cancellation or long suspension risk.

Final-inventory candidate endpoints are the existing ESPN scoreboard/summary interfaces under
`soccer/fra.1`, `soccer/ned.1`, `soccer/por.1`, `soccer/sco.1`, and `soccer/bel.1`. Their historical
completeness and final-whistle coverage remain gates to test **after** each league's registration;
none is represented as already verified by this source assessment.
