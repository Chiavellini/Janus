# L48 — NBA, WNBA and NHL current template readiness

The complete public inventory at **2026-09-09 08:38:44 UTC** contains no current
Kalshi/Polymarket game pair in any of these three leagues. There is no legitimate
current cross-venue event for a settlement-policy edit to unlock.

| League | Kalshi open/unopened games | Polymarket moneylines | Actual listing dates | Current exact pairs |
|---|---:|---:|---|---:|
| NBA | 3 (6 team markets) | 0 | Kalshi: October 20 | 0 |
| WNBA | 0 | 23 | PM: September 17–22 Eastern | 0 |
| NHL | 0 | 102 | PM: September 19–October 5 Eastern | 0 |

Kalshi's NBA games are Boston–Detroit, Philadelphia–New York and Oklahoma
City–San Antonio. Gamma returned 24 NBA-tag events, 35 WNBA-tag events and 111
NHL-tag events, including futures/other market types; those totals are not
moneyline counts. Both the registry slug and each sport's official primaryTagId
were queried and deduplicated by event ID: NBA 745, WNBA 100254, NHL 899.

Every Kalshi open/unopened cursor chain and Gamma tag chain ended naturally.
The unchanged discovery path returned zero scheduled live/near games, zero
co-listed games and zero fetch failures for all three leagues. Its 168-hour
schedule horizon ends before the first currently listed game. Separately, its
matcher still limits the candidate universe to 48 hours even when the harvest
CLI accepts `--pre-hours 168`; the raw inventory above does not rely on that
matcher. No venue absence is inferred from a zero-match result.

## Actual rules inspected

All verbatim texts, participant labels, market IDs, normalized texts and hashes
are preserved in `results.json`. Each populated venue has one distinct template:

- **Kalshi NBA, `72a912923ff0350e`, six markets.** The governing league's final
  winner determines the result. A delayed game remains open if it begins within
  48 hours of the original start; cancellation or failure to begin within 48 hours
  pays a fair price. The current NBA series names the NBA as its settlement source.
- **Polymarket WNBA, `3ad1cae690aca2e7`, 23 markets.** Final winner includes
  overtime. Postponement stays open until completion; cancellation with no makeup
  pays 50-50.
- **Polymarket NHL, `f88aa393390c266f`, 102 markets.** Final winner includes
  overtime and shootouts. A shootout adds one goal to the winning side for the
  score. Postponement stays open until completion; cancellation with no makeup
  pays 50-50.

These are inspected one-venue texts, not approved paired templates. Neither an
NBA Polymarket moneyline nor a WNBA/NHL Kalshi event-level rules text is available
in the current catalog. The WNBA series points to the same basketball contract
family as NBA, but its source metadata includes ESPN and the WNBA; that is not
permission to substitute NBA's current event wording. NHL's series points to
`ACHIEVEMENTS.pdf`, a different contract family, so basketball's 48-hour clause
cannot be inferred for hockey.

## Exact blockers and shortest evidence path

All three league registries still correctly return `NO_KALSHI_TEMPLATE` and
`NO_POLYMARKET_TEMPLATE`. For each pair, all twelve cross-venue dimensions remain
unreviewed: official source, winner determination, overtime, tie, postponement,
cancellation, suspended, abandoned, player non-participation, retirement,
dispute/revision and settlement timing. Available wording helps the eventual
review; a missing counterpart prevents a pair verdict now.

1. When the missing venue lists the same game, obtain its verbatim event rules
   and the applicable full contract terms; retain exact schedule identity and
   season type. Reharvest both texts and review all twelve paired dimensions.
   For WNBA/NHL, confirm the actual Kalshi delay cutoff instead of copying NBA's.
2. Preregister any required rate study for that **league and season population**.
   NBA's observed fair-price cancellation and 48-hour start cutoff require
   cancellation and late-start measurement if the eventual PM text differs.
   WNBA/NHL's observed 50-50 cancellation and indefinite wait require the same
   comparison to their actual future Kalshi text before naming rate keys.
3. Use an immutable original schedule with exact game IDs, reconcile every
   moved/cancelled/suspended game to authoritative start and completion times,
   and require complete denominators and exception coverage. An alternative is
   a separately registered first-seen forward population. Keep preseason,
   regular season and postseason explicit; do not label the current future NHL
   or WNBA listings regular-season merely from their dates. A rate from MLB,
   NFL, NBA, WNBA or NHL cannot cover a different league/population.
4. Register only evidence whose prespecified completeness gates pass; bind
   certification to its exact schedule population and test actual archived
   fixture pairs plus missing/wrong-population blocks. Then add reviewed templates
   and all paired verdicts. Existing executable-EV hurdles and outer caps remain.

No new rate was measured. No policy, proof, cap, live mode, arm, deployed tree or
order was changed. The EV effect of this audit is zero; any future enablement
adds only opportunities that pass their own settlement reserve and executable
net-return checks, and does not establish profit.

## Audit verification

The 21 successful public HTTP responses are atomically written under
`/Volumes/Kilos/janus/research/L48/20260909T083844Z/`. `manifest.json` records each
request, timestamp, response path and SHA256. An independent read-only pass
verified all 21 response hashes, request identities and the manifest hash against
`results.json`. There were zero request failures. Raw payloads may contain venue
price/outcome fields incidentally; this measurement reads no books and scores no
price, historical outcome or P&L.

The series-linked Kalshi contract PDFs could not be opened by the web reader
(`not safe to open`); no unseen PDF clause is cited as reviewed. That leaves
future paired-contract review explicitly incomplete and affects no availability
count or policy decision above.
