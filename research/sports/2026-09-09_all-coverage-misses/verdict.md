# L59 — all-league coverage audit: LOCAL PASS, EXTERNAL BLOCKS REMAIN

At the frozen post-repair public snapshot (`2026-09-09T23:16:47Z`), Janus scheduled 308
registered events, built 270 complete slate candidates, and produced 263 discovery-ready events.
The 45 non-ready rows all have an explicit reason:

- 36 Polymarket tennis listings had no current open/unopened Kalshi counterpart.
- Khachanov–Blockx remained open on Polymarket after Kalshi had settled/finalized.
- Four exact CFB pairs are intentionally blocked because the prior cancellation/postponement
  evidence failed L60's population and completeness audit.
- Braga–Estoril, Anderlecht–Mechelen, and Lyon–Rennes are exact pairs but retain league-specific
  unmeasured settlement evidence and zero effective risk caps.
- Valencia–Sevilla has a genuine schedule-reference disagreement: Kalshi retained September 13
  while the current external schedule and Polymarket referenced September 11.

Seven current tennis identity variants, one duplicated ITF schedule event, and the CFB outcome
token-binding defect were repaired. Venue enumeration now requires terminal pagination, validates
schemas and cursors, merges only compatible duplicate representations, rejects critical event or
market conflicts, and carries selector diagnostics into discovery. Entity reseeding consumes the
same complete enumeration before any generated write and preserves reviewed player identities by
stable Polymarket id. Direct Polymarket token ownership is independent of array order; two-outcome,
three-way soccer, draw, and constrained tennis-surname paths have separate fail-closed proofs.

The global loose census produced 203 unregistered candidate rows across 44 mapping buckets, with
14 rows in the immediate window. These are research leads, not canonical pairs or tradeability
claims. Four are already proven cross-sport/title collisions. They are retained as
`UNVERIFIED_COVERAGE_CANDIDATE`, excluded from operational watchdog alerts, and require independent
competition identity, schedule, outcome, settlement, fee, token, book, and cap verification before
onboarding.

Independent adversarial review found and drove closure of array-order token swaps, contradictory
duplicate-market merges, three-way soccer token loss, tennis suffix loss, loose-census overclaiming,
and three stable-player identity collision modes. The final review is clean. The 316 focused tests,
the complete 1,376-test suite, watchdog selftest, compile checks, JSON validation, and diff checks
pass.

This is a local code-and-coverage result only. Public listings change over time, and CSV replacement
is not a multi-file filesystem transaction against a local I/O failure. No live box, account,
order, balance, kill file, override, service, deployment, restart, or cap was touched.
