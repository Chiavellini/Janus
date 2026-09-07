# CHECKLIST — where Janus stands, what is not done, what is not proved

*2026-09-07 ~05:00 UTC. A status list, deliberately blunt. Each line is one of: DONE (and how it
is known), RUNNING (accruing), NOT DONE, or NOT PROVED (built, never demonstrated end to end).
Update in place; this file has no memory. `git log` and `CHANGELOG.md` do.*

## A. The observation lane (watching both venues)

- [x] DONE — two websockets, one poller per co-listed game, evaluations stored on material change; coalesced to one pricing per 200 ms per game (loop lag p50 0.04 s over the first 24 h, L38).
- [x] DONE — the reconnect loop, the discovery pass off the loop, the REST reconciler on the loop, the clock check that names STALL vs CLOCK (2026-09-03/04). Zero reconnects from our own code since; venue-side drops 2–3 a day.
- [x] DONE — watchdog alarms demonstrated firing in `--selftest`: SOCKET_FLAPPING, SOCKET_ERROR, LANE_SILENT, and since 2026-09-05 **SIGNAL_EXIT** (a daemon's signal death reported even after launchd restarts it) and **UNHEDGED_POSITION** (the paper row's STOP condition).
- [x] DONE — spawn blocks are said once per game (`[spawn-blocked] <game> <reason>`) and written to `events.block_reason`; on 2026-09-04 two co-listed European games sat unspawned all evening with the reason in memory only.
- [ ] NOT DONE — **the host.** The lane died of a SIGBUS (exit 138) at 03:35:05Z 2026-09-05 after 24 h: 63 MB RAM free, 5.5 of 7 GB swap, three unrelated Python processes bus-errored within 100 s. launchd restarted it in 1 s. L38: the lane's own loop is prompt (0.6% of ticks past 5 s, all in the first hours after a restart); the host is what fails. Until the box, heavy jobs beside the lane cost it seconds and paging can kill it (ops/README.md).
- [ ] NOT PROVED — the Polymarket socket drops on the tennis capture: ITF is out of the capture, drops are 2–3 a day; the venue-side cause is not understood.

## B. Pricing (what a cover costs)

- [x] DONE — fees read from each venue's payload; Kalshi curve pinned from real fills (taker 0.07, maker 0.0175 unscaled). **Paper fills now carry the pinned fee** (every paper order before 2026-09-05 recorded fee_usd 0.0).
- [x] DONE — settlement-wedge rules for 11 enabled leagues with cited rules, reviewed templates and measured rates (MLB L26, NFL L30, cfb L32, EPL/La Liga/Bundesliga L33, Championship/League One/Serie A L35, tennis L39 + F4). Polymarket soccer template **V3** registered 2026-09-05 (the venue dropped its 24-hour clause; hash `7580dcecfba14bc3`).
- [x] DONE — L36, the cover-cost distribution, run three times; third run 2026-09-05 07:44Z on the clean window: 336 profitable prints, 127 in-play clean actionable rows, n = 37 for the paper row.
- [x] DONE — **L40, a SUSPECT rule that can be false**: L36's ±60 s same-game clause fires on 335 of 336 prints under coalescing. L40 asks whether a replica THIS print was priced from faulted in the 60 s BEFORE it: **15 of 292 prints are clean** (12 cfb in play, median locked return 2.5%; 3 mlb). Not fills, not returns.
- [ ] NOT PROVED — **that any actionable cover exists after fees.** The paper lane has settled three covers (+$5.00 gross, +$0.75, and a PARTIAL at −$2.73) and L40 says one print in twenty survives a falsifiable rule. That is evidence the prints are not all artefacts; it is not edge. F5 and L27 are the rows that test it.
- [x] DONE — **L27 re-run, registered 0.0400** (p95 adverse move at 3 s over 32.1M delta instants, 326 tickers; the 2026-09-03 pin was 0.0100 from 8 MLB tickers). Honest and blunt: a 4¢ reserve prices out nearly every cover printed so far, so F5 will clear little under it. The row pools thin tennis books with MLB and weights bursts by delta count; a stratified slippage row (per league, clean windows, time-weighted, at the walked depth) is the next registration. Also fixed on the way: the capture reader now survives a file cut mid-member.

## C. Coverage (which events)

- [x] DONE — 20 leagues registered; **11 enabled and trading on paper**: mlb, nfl, epl, lal, bun, cfb, elc, el1, ita, **atp, wta** (tennis since 2026-09-05, F4).
- [x] DONE — F4 registered: `tennis.delayed_gt7d_rate` is the forward row's one-sided 95% UPPER BOUND (0 of 42 → 0.0714, ~3.6¢ of reserve per Polymarket contract) until n reaches 300; the daily resolver refreshes it. The spec says plainly it was written after the first two resolver runs.
- [x] DONE — `nodes/watch_fd`, the football-data.org snapshotter (F6, registered before any run): fl1, ere, por unblock from it; truer rates than the FLOOR proxy for epl, lal, bun, ita, elc at a season. **Awaits the operator's `FD_TOKEN`**; the job is written and not loaded.
- [x] DONE — `ops/harvest_templates.py --league nba|wnba|nhl`: prints which template each venue's text hashes to, or the unknown text verbatim, the day the venues list the league.
- [ ] NOT DONE — NBA, WNBA, NHL: the venues list no game markets yet; templates cannot be reviewed until they do (basketball moves to a Kalshi shard 2026-09-10).
- [ ] NOT DONE — MLS, Scottish Premiership, Belgian Pro League: not on football-data.org's free tier; no postponement source; blocked by name.
- [ ] NOT DONE — UFC (census rank 2 by score; needs a card-aware schedule from Polymarket events, a rule citation covering draw / no contest / cancelled bout, both texts, and a measured no-contest rate), KBO and NPB (ties after 12 innings need each venue's rule and a measured tie rate), esports and table tennis (alias tables; $10 median touch). The census (L28) has 3 of 7 runs; fewer than 4 orders nothing. Do not start before today's 20:00Z run.
- [ ] OUT OF SCOPE BY STRUCTURE — **golf**: no head-to-head game market on either venue (the census lists none); the canonical key is two or three participants. Nothing to build.
- [ ] NOT DONE — tennis REPLAYABLE offline: the lane's Polymarket REST verification is not captured, and capture-only events are not in the `events` spec table.
- [ ] NOT DONE — unresolved names in `nodes/entities/unresolved.csv`: 636 rows (cfb 358, batch-2 soccer ~200, **tennis 80** — the "1,070 tennis names" in earlier notes was wrong). Mostly Kalshi 3-letter abbreviations; rows for `aliases_manual.csv`.
- [x] RUNNING — the co-listing census (L28): 3 of 7 daily runs (1,022 co-listed events, 87 competition rows); the rank is read at 4+.

## D. Execution (placing the two legs)

- [x] DONE — two-leg coordinator, partial-fill policy, ambiguous-order recovery, single-use risk clearance, exposure ledger, arming-override caps, Kalshi shards, first real Kalshi fill and its settlement (+$2.01).
- [x] DONE — **the hedge limit is the walked level, not the VWAP budget** (`30c8511`). F3's first unhedged paper leg (MIL @ CIN, 35.82 of 100) came from sending the budget as a per-level IOC limit. The budget is recorded beside every attempt; a hedge that averages above it is labelled ABOVE_BUDGET. Fixture `MIL_CIN_2026_09_04` reproduces the exact ladders.
- [x] DONE — **holding failures settle**: PARTIAL_FILL / HEDGE_SLIPPAGE_EXCEEDED / UNKNOWN_PROVIDER_STATE end at RECONCILED through the settlement pass, the hedged part as a cover and the rest at the venue's result (`kind`, `cover_usd`, `directional_usd` on the row). Live: MIL @ CIN settled −$2.73 (cover +$1.93, directional −$4.66) and released.
- [x] DONE — execution-owned statuses (EXECUTION_PENDING, HEDGED, SETTLED, RECONCILED) reach `opportunity_transitions` (`OpportunityStore.move`); F3's own predicate had counted zero.
- [x] DONE — three-way soccer executes as two legs (Kalshi YES + Polymarket NO). All ten co-listed soccer games spawned pollers on the 2026-09-05 restart. **NOT PROVED live until a soccer cover clears** (the weekend's European kickoffs).
- [x] DONE — `nodes/risk/limits.toml`: paper caps for cfb, the six soccer leagues and both tennis tours; six simultaneous events (operator decision 2026-09-05). **The arming override's `limits_sha` pin moved: regenerate before any armed run.**
- [x] DONE — Kalshi proof, second run 2026-09-07 02:56Z: 2 @ 0.78, fee at the pin to the hundredth of a cent, balance to the cent, cancel confirmed on the venue; **settled +$0.42 on the result, 7 of 7 checks** (2026-09-07 05:55Z).
- [x] DONE — **the first real Polymarket order** 2026-09-07 04:42Z: FOK 5 @ 0.39 matched as 5.131577 @ 0.38 (V2 fills by notional); the balance moved by fills + exactly the pinned fee; **settled +$3.18 on the result, 7 of 7 checks** (2026-09-07 05:57Z). On the way: the adapter moved to CLOB V2 / pUSD / signature type 3 (CHANGELOG 2026-09-07).
- [x] DONE — the arming override rewritten by the operator 2026-09-07 (three times, as the runner sha moved under it; it expires 2026-09-08).

## E. The gate to real capital (GATE_TO_LIVE.md)

- [x] DONE — frozen venue fixtures, WebSocket replay, reconnect and sequence-gap tests, partial-fill and ambiguous-order tests.
- [x] DONE — **F3 STOPPED by its own criterion 2** (one unhedged paper leg) on 2026-09-05; its window is also void from the 24 h SIGBUS gap. Verdict: `research/sports/2026-09-04_paper-execution-f3/verdict.md`. 4 executions, 3 hedged, 3 settled.
- [x] RUNNING — **F5, PAPER_EXECUTION, n = 37**: from the 2026-09-05 07:53Z restart, on 11 leagues, with the walked-level hedge, pinned paper fees, and the STOP detected by UNHEDGED_POSITION. 0 of 37.
- [x] DONE — the settlement pass, every five minutes, paper and real alike; PARTIAL rows included.
- [x] DONE — fees reconciled on Polymarket: charged exactly the pinned 0.0604 on the first real fill, read from the balance delta (the V2 trade record reports fee_rate_bps 0).
- [x] DONE — operator decision 2026-09-04 (GATE amendment row): test trading only until L36 on clean data shows in-play actionable covers. L40 is the first honest cut of that (15 clean prints); the decision stands until the operator says otherwise.
- [ ] NOT DONE — LIMITED_LIVE for the lane itself (needs both proofs, F5 complete, a new dated GATE row from the operator, the override, caps).
- [ ] NOT DONE — PRODUCTION.

## F. The Ashburn box

- [x] DONE — launch script, cloud-init, systemd units, credential materialiser, latency tool, tests, runbook; IAM policy files committed 2026-09-05 as written (the agent trust dropped its MFA-age condition — operator decision to commit as is).
- [x] DONE — IAM: the admin's inline deny keeps its Earshot-instance protection and no longer denies RunInstances (2026-09-07); the janus-box role, profile and SSM core were already in place.
- [ ] NOT DONE — main not pushed to GitHub since `1479bd6`; the SSM sha pointer is stale by many commits. OPERATOR.
- [x] DONE — the eight SSM parameters (two pointers, six SecureStrings) are in; the repo token is the GitHub login's and should be replaced by a read-only fine-grained token.
- [ ] NOT PROVED — L34 latency bar (box p50 under half the Mac's to both venues AND Polymarket answering 200). L38 now says the Mac is an observation host that pages to death under load; the box decision has its other half.

## G. Housekeeping

- [ ] NOT DONE — label the blind gold set `nodes/match_generic/gold/nonsports.csv` (L31; 1 / 0 per pair, blind to the key). `score_gold.py` now computes the row's per-stratum bar. OPERATOR.
- [ ] NOT DONE — `FD_TOKEN` for `nodes/watch_fd` (free at football-data.org). OPERATOR.
- [x] DONE — L37 clean-hour re-run (bound stays), L36 third run (n = 37), L38 (loop lag), L40 (the falsifiable SUSPECT rule), F3 verdict, F4/F5/F6 registered; the other agents' research results and IAM files committed.
