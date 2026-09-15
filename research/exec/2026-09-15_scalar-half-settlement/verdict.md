# L139 verdict — LOCAL PASS; PRODUCTION RELEASE PENDING

## Measured venue result

Fresh raw venue reads established the exact final payout vectors:

- Kalshi `KXATPCHALLENGERMATCH-26SEP15SHAIVA-SHA`: `status=finalized`, `result=scalar`,
  `settlement_value_dollars=0.4400`.
- Kalshi `KXATPCHALLENGERMATCH-26SEP15SHAIVA-IVA`: `status=finalized`, `result=scalar`,
  `settlement_value_dollars=0.5600`.
- Polymarket main moneyline: `closed=true`, `umaResolutionStatus=resolved`, outcomes mapped to the
  two registered CLOB tokens, `outcomePrices=[0.5,0.5]`.

The held cover's exact realized economics are therefore:

- Polymarket: `25 * 0.50 - 25 * 0.51 - 0.31237 = -0.56237` USD.
- Kalshi: `25 * 0.44 - 25 * 0.44 - 0.43120 = -0.43120` USD.
- Total: **`-0.99357` USD**; the descriptive COVER field rounds to `-0.9936`.

## Implementation result

Janus now parses complete finite bounded scalar/half payout vectors, retains its binary-winner
interface, prices complementary `:NO` and sell legs correctly, and persists venue and settlement
payout evidence in new additive tables. The additive tables leave historical settlement row shapes
unchanged; this was required after the first full-suite run correctly rejected an earlier
column-addition design through four exact legacy-evidence tests. Contradictory durable final evidence
raises instead of overwriting. The position guard treats a complete durable payout row as venue
finality.

The stopped-lane helper additionally binds the measured vectors and exact `-0.99357` PnL to the
registered cover. It still requires the exact retained kill, stopped unit, release, execution,
reservation, outcome map, order economics, zero unhedged quantity, and atomic post-proof.

## Verification

- Focused reconcile/helper/guard/legacy suites: green (167 tests in the final combined selection).
- Full `python3 -m pytest -q`: exit 0.
- Python compilation, shell syntax, and `git diff --check`: pass.
- Fresh live API parse through the new code returned the exact registered payout maps.
- Final replay over 20,000 frames: 234 pollers, 5,858 evaluations, 1,093 rows, zero selections;
  exact digests `13e4fb08a76c920f / 4f53cda18c2baa0c`.
- Fresh independent Luna audit: `RELEASE` with no blocking finding.

One non-blocking limitation remains: non-binary Polymarket events represented only as multiple
per-side markets remain fail-closed. The exact production event uses the single main moneyline
market, so this cannot affect the registered release.

## Production result

Release `59dd5ae2ce3619104aa95d127d1b115d7c0702a9` settled the exact cover, released only reservation
`b292be2a`, passed both stopped credentialed guards, resolved only registered guard failures 1169
and 1170, archived the unchanged kill, and restarted the lane. Independent proof found the exact
deployed SHA, active service, no `kill/live`, three connected fresh sockets, zero unreleased
executions/reservations, zero unresolved material flags, and the exact payout evidence and
`-0.99357` settlement row.

The release command itself ended nonzero only after recovery, when its separate final immediate
Polymarket redemption invocation failed. The redemption timer remains an operating-cost/reliability
issue; it did not undo or invalidate settlement, guard recovery, or lane restart. F22 had zero
decisions at the first post-release read.
