# CHECKLIST — where Janus stands, what is not done, what is not proved

*2026-09-04 ~01:00 UTC. A status list, deliberately blunt. Each line is one of: DONE (and how it
is known), RUNNING (accruing), NOT DONE, or NOT PROVED (built, never demonstrated end to end).
Update in place; this file has no memory. `git log` and `CHANGELOG.md` do.*

## A. The observation lane (watching both venues)

- [x] DONE — two websockets, one poller per co-listed game, evaluations stored on material change. Verified by the lane log and `stream_evaluations`.
- [x] DONE — the reconnect loop that flapped both sockets all of 2026-09-03 (state-table bug). Fixed, tested; zero reconnects from our own code since 23:26Z.
- [x] DONE — the discovery pass no longer freezes the sockets (L37: 13% of every hour lost). Fixed 00:25Z; 178k frames, zero gaps over 15 s across two passes.
- [x] DONE — Polymarket REST reconciler applies on the loop (its evaluations were being lost).
- [x] DONE — watchdog alarms that would have caught all of the above: SOCKET_FLAPPING, SOCKET_ERROR, LANE_SILENT. Each demonstrated firing in `--selftest`.
- [ ] NOT DONE — the clock-health check flips HALT/healthy about once a minute and blocks every poller for that tick. Unexplained.
- [ ] NOT DONE — Kalshi keepalive ping timeouts still cause an occasional venue-side reconnect (one at 00:27Z). Venue behaviour; the resubscribe is clean.

## B. Pricing (what a cover costs)

- [x] DONE — fees read from each venue's payload; Kalshi curve re-pinned from a real fill 2026-09-04 (taker 0.07 and maker 0.0175 unscaled, to the hundredth of a cent). Fixture in `nodes/fees/tests/fixtures`.
- [x] DONE — settlement-wedge rules for 9 leagues with cited rules, reviewed templates and measured rates (MLB L26, NFL L30, cfb L32, EPL/La Liga/Bundesliga L33, Championship/League One/Serie A L35).
- [x] DONE — the size frontier is computed again (`frontier(proof=)` bug).
- [x] DONE — L36, the cover-cost distribution, registered and run once. First run is tainted: sockets starved, fees at half. Re-run due on the first clean hour.
- [ ] NOT PROVED — that any actionable cover exists on these two venues after fees. All 19 profitable prints in history were closing books under a broken socket. This is the question the project exists to answer; the clean data starts 2026-09-04 00:25Z.
- [ ] NOT DONE — slippage row L27 re-run after NFL/NBA traffic (registered as one tick from one MLB evening).

## C. Coverage (which events)

- [x] DONE — 20 leagues registered; 9 enabled and trading on paper: mlb, nfl, epl, lal, bun, cfb, elc, el1, ita.
- [x] DONE — tennis CAPTURED (raw frames from both venues, ~35k tennis frames per half hour tonight, 62 markets on the watchlist).
- [ ] NOT DONE — tennis PRICED: `tennis.walkover_rate` and `tennis.delayed_gt7d_rate` unmeasured, so atp/wta block by name. Walkovers are measurable from the Sackmann results files; the delay rate has no results-archive source and needs a declared proxy.
- [ ] NOT DONE — tennis REPLAYABLE offline: the Polymarket side needs the lane's REST verification, which is not captured.
- [ ] NOT DONE — NBA, WNBA, NHL: settlement templates not reviewed (Kalshi lists no NHL yet).
- [ ] NOT DONE — MLS, Ligue 1, Eredivisie, Primeira Liga, Scottish Prem, Belgian: no source for postponement rates; blocked by name.
- [ ] NOT DONE — UFC, table tennis, esports, KBO, NPB, Argentine Primera and the rest of the census's 82 competitions: not registered (need citation, templates, rates; UFC also a card-aware schedule parser).
- [x] RUNNING — the co-listing census (L28): 2 of 7 daily runs; 1,025 co-listed events across 82 competitions; the rank is read at 4+ runs.
- [ ] NOT DONE — 191 unresolved batch-2 soccer names and 1,070 tennis names in `nodes/entities/unresolved.csv`.

## D. Execution (placing the two legs)

- [x] DONE — two-leg coordinator, partial-fill policy, ambiguous-order recovery, single-use risk clearance, exposure ledger: all in code with tests.
- [x] DONE — the lane enforces the arming override's caps (was only the proof scripts).
- [x] DONE — Kalshi orders and cancels carry the market's exchange shard (collateral is per shard since 2026-08-24).
- [x] DONE — first real Kalshi fill (2026-09-04 00:04Z): 2 taker at 0.35 + 1 maker at 0.25, balance reconciled to the cent. Fee STOP fired correctly on the old pin.
- [ ] NOT PROVED — a Kalshi proof file passing all six checks (the first fails `resting_cancelled` and `fee_ok` on record; both causes fixed). Needs one clean armed re-run. OPERATOR.
- [ ] NOT DONE — the Polymarket proof: no real Polymarket order has ever been sent. OPERATOR.
- [ ] NOT DONE — `--settle` of the Kalshi proof: automatic when MIA @ KC resolves (a watcher is running).
- [ ] NOT DONE — three-way soccer execution: a draw is priced as a third outcome but the planner is two-leg only; needs the Polymarket NO-token design. Until then soccer contributes evidence, not trades.
- [ ] NOT DONE — `nodes/risk/limits.toml` has no per-league cap for cfb or any soccer league: those are refused at reservation even on paper. OPERATOR decision.
- [ ] NOT DONE — the arming override must be rewritten at main's current sha before any armed run. OPERATOR.

## E. The gate to real capital (GATE_TO_LIVE.md)

- [x] DONE — frozen venue fixtures, WebSocket replay, reconnect and sequence-gap tests, partial-fill and ambiguous-order tests.
- [x] RUNNING — live shadow evidence (from the 2026-09-02 seal; clean from 2026-09-04 00:25Z).
- [x] RUNNING — F3, PAPER_EXECUTION: 0 of 30 cleared covers so far.
- [ ] NOT PROVED — fees reconciled on Polymarket (needs its proof).
- [x] DONE — operator decision 2026-09-04 (GATE amendment row): test trading only, no serious amounts, until L36 re-run on clean data shows in-play actionable covers. Real orders = the two proofs under $5 / 10 contracts / $20 a day.
- [ ] NOT DONE — LIMITED_LIVE for the lane itself (needs both proofs, F3 complete, a new dated GATE row from the operator, override, caps).
- [ ] NOT DONE — PRODUCTION.

## F. The Ashburn box

- [x] DONE — launch script, cloud-init, systemd units, credential materialiser, latency tool, tests, runbook.
- [ ] NOT DONE — IAM: `janus-scope` denies `iam:PassRole` on `janus-box`; the admin user's inline `EarshotDenyDirectBoxLaunch` denies `ec2:RunInstances`. OPERATOR.
- [ ] NOT DONE — no instance has ever been launched.
- [ ] NOT DONE — main not pushed to GitHub since `1479bd6`; the SSM sha pointer is stale by ten commits. OPERATOR.
- [ ] NOT DONE — the five secrets into SSM. OPERATOR.
- [ ] NOT PROVED — L34 latency bar (box p50 under half the Mac's to both venues AND Polymarket answering 200). Decides execution host vs observation host.
- [ ] NOT DONE — the other agent's trust policy dropped its MFA condition; flagged, unchanged.

## G. Housekeeping

- [ ] NOT DONE — label the blind gold set `nodes/match_generic/gold/nonsports.csv` (L31). OPERATOR.
- [ ] NOT DONE — forward football-data.org snapshotter for true original kickoff dates (needs the operator's free token); until then soccer rates are a FLOOR proxy.
- [ ] NOT DONE — L36 re-run and L37 re-run on the first clean hour; recompute F3's n only to extend.
