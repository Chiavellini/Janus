# L57 UCL coverage repair — local pass

The preregistered UCL execution path passes on the isolated candidate tree. No live process,
checkout, service, kill file, signed override, account, order, fill, database, or capital setting
was read or changed by this repair.

## What was repaired

- ESPN soccer clubs now retain one stable identity across domestic and UCL competitions while the
  canonical game key keeps the competition separate. Exact venue IDs and audited aliases resolve
  the twelve frozen UCL fixtures; ambiguity still fails closed.
- UCL is a registered three-outcome competition with `KXUCLGAME`, Polymarket slug/prefix `ucl`,
  and ESPN `soccer/uefa.champions` as the independent schedule anchor.
- The matcher filters schedule candidates by competition, requires the registered three outcomes,
  and rejects derivatives, absent/ambiguous schedules, missing draws, and cross-competition games.
- The census always queries the numeric primary tag and sport slug independently, validates every
  page as a list, exposes selector and pagination errors, and merges the full connected component
  of sparse ID/slug representations without dropping richer markets.
- UCL has an explicit `$200` PAPER/DEMO per-league allowance. This prevents the enabled-but-zero-cap
  defect while leaving the signed live stake, contract, event, day, venue, total-capital, loss, and
  minimum-return controls unchanged. LIMITED_LIVE caps may only be lower and remain authoritative.
- Settlement certification is league-phase only. An exact ESPN UCL game ID, `league-phase`
  population, reviewed Kalshi/Polymarket templates, and both registered UCL bounds are mandatory;
  qualifying, group, knockout, unknown, or foreign populations remain blocked.

## Verification

- Frozen matcher coverage: all 12 September 9–10 games resolve on both venues, yielding exactly
  36 outcome pairs; all hard negatives pass.
- Public price-free matcher probe on September 9: 12 scheduled games in the two-day window; the six
  currently co-listed games are 6/6 complete with 18 outcome pairs. Forty-four derivatives and
  fifteen non-two-team shapes were rejected.
- Public census probe: Polymarket `primaryTagId=1234` returned 15 events and zero games;
  `tag_slug=ucl` returned 65 events and all six games. The combined result contains six games,
  with no selector error or pagination exhaustion.
- Public full discovery/certification probe: six scheduled, six slate entries, three outcomes each,
  no schedule failures or blocked rows. Every entry is `EQUIVALENT` under
  `kalshi_ucl_game_v1` / `polymarket_soccer_game_v3` and carries the UCL rates.
- L58 replay: 294 exact source/sidecar records, 144/144 unique league-phase fixtures, zero failures,
  and byte-identical audit SHA256
  `9d711e9ef9d93ae65315e53677c558e2fb612bc42158837371375ea9cd3a3367`.
- Focused execution-path tests pass; the final repository suite passes all 1,332 collected tests.
  `ops/watchdog.py --selftest`, architecture/meta checks, and `git diff --check` pass.
- Independent review reproduced the settlement audit, live-cap refusals, malformed-source failures,
  sparse-representation permutations, and found no remaining correctness issue after the final
  connected-component fix.

## Scope of the result

This proves coverage and fail-closed eligibility, not that an executable arbitrage exists or that
additional UCL volume is profitable. Profit remains conditional on executable ladder depth, fees,
freshness, settlement reserves, both-leg execution, and all unchanged risk caps. The running lane
continues on its prior code until an operator performs a separately authorized release.
