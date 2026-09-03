# Soccer settlement-wedge rates — measurement design (not yet a ledger row)

Written 2026-09-03 after a source survey (probes listed below). The soccer pairs (epl, lal, bun,
mls) block at `EVIDENCE_UNMEASURED` on `soccer.<code>.postponed_gt48h_rate` and
`soccer.<code>.cancelled_rate`. This memo records what the survey found so the row that gets
registered is honest about what it can and cannot see. Register the row (`spec.yaml`, ledger
`PENDING`) BEFORE running anything here.

## What the survey found (2026-09-03)

**No free source exposes a completed match's originally scheduled kickoff.** Every results archive
stores the date played:

- football-data.org v4 has status flags (`POSTPONED`, `CANCELLED`, `AWARDED`, …) but `utcDate` is
  overwritten; the free tier is PL / PD / BL1, current season only; MLS is paid.
- api-football: same shape, ~3 seasons, 100 req/day; unverified.
- openfootball (GitHub): final season files carry the ROUND label and the played date; the
  original date survives only in git history for 2019-20, 2020-21 and 2024-25 (2021-22 to 2023-24
  were added retroactively). Verified: `england@ec01fd8` lists Man Utd–Liverpool under Sat 1 May
  2021; the final file has it under Thu 13 May. The MLS repo no longer exists.
- football-data.co.uk CSVs (E0, SP1, D1, USA): played date only; a clean denominator.
- Premier League pulselive API: `provisionalKickoff == kickoff` on completed games.
- OpenLigaDB (BL1): no original date; an abandoned-and-awarded match is stored as finished.
- ESPN drops a postponed match from its original date (probed `eng.1?dates=20210502`: no
  Man Utd–Liverpool), as L26 found for MLB.
- BBC Sport month pages in the Wayback Machine DO carry `startTime` and `FIXTURE/POSTPONED`
  status as of the capture date (e.g. capture 20211214082126 shows Burnley–Watford at
  2021-12-15 19:30, later played 2022-02-05): a validation set, not a denominator.

## The honest design

- **Denominator**: openfootball final files per competition and season (2019-20 … 2024-25; MLS
  2019–2025 from football-data.co.uk), cross-checked against football-data.co.uk row counts.
- **`postponed_gt48h` proxy**: a match played more than 48 h after the last kickoff of its round's
  core window (the span of that round's modal weekend, Fri–Mon). Validated on Man Utd–Liverpool
  (R34, played +12 days), Burnley–Watford (R17, played 5 Feb), Bielefeld–Bremen (BL1 R20, +33
  days). It CANNOT see a move inside the window (Sat 15:00 → Mon 20:00 is 53 h) nor a same-week
  reschedule, so **the rate is a floor**. A floor under-prices a reserve; the spec must say so and
  the enablement should carry the label until a forward measurement replaces it.
- **`cancelled_rate`**: scheduled N(N−1) minus played, per competition-season, with each
  cancellation cited (Wikipedia season articles as the index, the league's release as the
  citation). Expected 0 for PL/PD/BL1 2019–25 (Bochum–Gladbach 2022 was abandoned and awarded;
  Bournemouth–Luton 2023 abandoned and replayed); MLS 2020 = 7 of 299 (pandemic).
- **2020**: the operator excluded 2020 for the NFL; the same decision should be taken explicitly
  here (2019-20 and 2020-21 straddle the pandemic in Europe; MLS 2020 is the only cancellation
  source). Decide before registering.
- **Definition caveat**: Kalshi's clause measures from the kickoff "originally scheduled" at
  listing time (~72 h before), not from the June fixture release; a TV move announced weeks
  ahead is not a postponement for the venue. The proxy over-counts those only if a TV move leaves
  the round window, which it rarely does.

## Going forward (the measurement that is not a floor)

Register a free football-data.org token and snapshot `/v4/competitions/{PL,PD,BL1}/matches`
daily (`utcDate`, `status`, `lastUpdated`) so the 2026-27 season has true original dates; MLS
needs another feed. That is a forward row with a watchdog SLA, like the census.
