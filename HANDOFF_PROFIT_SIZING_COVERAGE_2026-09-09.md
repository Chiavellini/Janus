# Handoff — profit-maximizing sizing, maker execution, and coverage expansion

Date: 2026-09-09 America/Mexico_City  
Prepared from branch: `codex/ucl-coverage`  
Worktree: `/Users/bernardodelrio/Code/Janus/.codex/worktrees/ucl-coverage`  
HEAD before this handoff file: `2e9620aaf0106af812761541211b72019bd14c2a`

## The operator's next objective

Implement, test, independently review, and ultimately deploy the following as one controlled release:

> Determine which execution mechanisms merit changes. Increase size toward the number of contracts
> safely allowed when doing so maximizes profit, while explicitly controlling the risk that the
> first venue fills more contracts than the second venue can hedge. Minimize decision-to-order and
> first-fill-to-hedge latency. Continue the sports coverage expansion. Keep the box ingesting while
> developing and avoid repeated stop/restart cycles; stop/restart only once after this sweep is
> complete and reviewed.

Do not interpret “as many as allowed that still make a profit” as blindly choosing `N_max`. Janus's
objective is total profit and Sharpe per trade. On a layered book, the largest still-positive size
can make less total profit than a smaller size. The correct conditional-fill target is the feasible
`N_star = argmax_N locked_profit(N)`, subject to every live cap and hedge constraint. Eventually it
should be adjusted for size-dependent maker fill probability and hedge-tail cost, but those terms
must be measured prospectively rather than invented.

## Read this first; do not reread the whole repository

1. `AGENTS.md` for invariants and preregistration rules.
2. This handoff.
3. `research/sports/2026-09-09_execution-rejections-and-coverage-progress/verdict.md`.
4. `nodes/execute/README.md`, `nodes/cover/README.md`, and
   `nodes/settle_wedge/README.md` only when touching those nodes.
5. `GATE_TO_LIVE.md` only before changing live state or deploying.

Use this isolated worktree. The main checkout at `/Users/bernardodelrio/Code/Janus` is old and dirty.
Do not copy files from it and do not clean or overwrite its changes.

## Current live-box state — important correction

A fresh read-only SSM snapshot at **2026-09-10T00:21:40Z** established:

- Host: Mexico, region `mx-central-1`, instance `i-0a8c073c72dcdae11`.
- `janus-live-stream` is `active` and runs `--leagues enabled --mode LIMITED_LIVE`.
- The signed override is valid through `2026-09-16T21:03:16Z` with:
  - combined planned stake cap: `$12`
  - maximum contracts per leg: `10`
  - day notional cap: `$250`
- The override identifies deployed runner `76a68da88164047ba630c74c49cb30c8c33ccefd`.
- **It is not currently able to enter new trades.** `/srv/janus/kill/live` remains present:

  `post-only cancel/late-fill lifecycle unresolved: 5a162878dc8842d09e42b797475b81e9`

- The service is therefore active and may continue discovery/ingestion, but later candidates have
  been refused with `KILL_SWITCH active: live`.
- The triggering TEX–SEA execution later reconciled completely at `+$0.7798`, all five current
  `pm_post_only_orders` markers are `terminal_proved=1, violated=0`, and the post-only admission
  singleton is empty. The safety latch intentionally did not self-clear.
- There is a separate older `POST_ONLY_PERSISTENCE_FAILED: database is locked` incident. Do not
  blanket-delete or blindly reset all incident evidence.

Development must not stop the active ingesting service. Before the final release, resolve the exact
terminal incident through the repository's operator recovery/preflight path, verify money quiet,
then deploy and restart once. Do not clear a kill file just because its triggering order looks old.

Read-only box command pattern:

```bash
JANUS_BOX_REGION=mx-central-1 \
JANUS_BOX_ID=i-0a8c073c72dcdae11 \
bash ops/box/run.sh '<read-only command>'
```

## Initial project state encountered in this sweep

- The live box ran `76a68da`, while the isolated coverage branch contained two undeployed code
  commits plus a descriptive audit commit.
- Four same-day executions were shown as `ORDER_REJECTED`, which suggested venue refusals.
- Direct database evidence showed all four were accepted-live Polymarket post-only GTC orders that
  Janus canceled with zero matches.
- Current live sizing evaluated a small fixed rung set and generally dispatched the first qualifying
  rung; it did not use the already-computed `N_star` to choose the live order quantity.
- The broad coverage investigation had repaired UCL and generic enumeration/matching bugs locally,
  but neither coverage commit had been deployed.
- CFB remained enabled on the deployed code using evidence that the corrected L60 audit invalidated.

## What was completed

### 1. UCL and settlement coverage, commit `98e89c7`

- Added competition-independent soccer club identity and exact competition-filtered ESPN anchoring.
- Added deterministic dual-selector Polymarket UCL enumeration.
- Certified only the current UEFA league-phase settlement population; qualifying, old group stage,
  knockout, foreign, and unknown populations remain blocked.
- Frozen probe produced 6/6 scheduled UCL games, 18 exact outcome pairs, and 6 equivalent settlement
  results.
- Added positive PAPER/DEMO UCL allowance. Signed live outer caps remain authoritative.

### 2. Broad coverage repair and adversarial review, commit `d6ed3d6`

- Fixed seven current tennis identity misses and one duplicated ITF schedule representation.
- Fixed CFB token ownership while separately removing CFB eligibility because the settlement evidence
  failed its corrected audit.
- Added complete venue pagination, cursor/schema/conflict validation, dual PM selector diagnostics,
  stable entity reseeding, order-independent PM token ownership, exact three-way soccer structural
  mapping, and constrained tennis surname fallback.
- Reclassified the loose global census as research-only unverified candidates rather than operational
  coverage alerts.
- Independent adversarial review closed all reproduced issues and returned clean.
- Final verification at that commit: 316 focused tests and 1,376 full-suite tests passed, plus
  watchdog selftest, compile, JSON, and diff checks.

### 3. Exact live rejection and coverage audit, commit `2e9620a`

- Pre-registered L61 and accounted for all five Mexico-local-calendar execution attempts.
- One TEX–SEA cover: two filled legs, zero unhedged, settled `+$0.7798`.
- Four zero-fills were accepted-live PM maker orders, not venue rejections.
- Proved the effective post-ack rest times were only 148, 0, 229, and 273 ms.
- Proved that the lingering `kill/live` prevents new entries even though the triggering lifecycle
  eventually became terminal.
- Recorded deployed versus committed-only coverage and all explicit coverage blocker classes.

No order, cancel, account, balance, kill, cap, service, deployment, or restart mutation was made in
these audits.

## Exact maker zero-fill diagnosis

| Execution | Event/order | Recorded ask | Post-ack rest | Authoritative result |
|---|---|---:|---:|---|
| `5815da66...` | WSH–SD, Padres 5 @ 61c | 62c | 148 ms | accepted live; Janus canceled; zero matched |
| `92d06b19...` | Jeanjean 10 @ 34c | 35c | 0 ms | accepted live; immediate cancel; zero matched |
| `cf9fa81e...` | Pareja 10 @ 40c | 41c | 229 ms | accepted live; Janus canceled; zero matched |
| `23324c90...` | Jeanjean 10 @ 54c | 55c | 273 ms | accepted live; Janus canceled; zero matched |

The implementation behaves exactly as coded but the resulting trading behavior is defective:

- `nodes/execute/coordinator.py` nominally allows at most two seconds of maker rest.
- The actual rest deadline is the minimum of quote expiry and `clearance.expires_mono`.
- `nodes/risk/limits.toml` gives a clearance only 500 ms, intended for one prompt submit.
- Network acknowledgement consumes most or all of the 500 ms.
- `UNFILLED` is then mapped to execution-level `ORDER_REJECTED`, which is an observability bug.

Do not “fix” this by lengthening the generic clearance TTL. That would let a stale decision remain
authorized. Introduce a separate resting authorization whose validity is continuously conditioned
on a fresh complementary hedge, fees, settlement proof, caps, and an absolute cancel deadline.

## How live contract sizing actually works now

Relevant files:

- `nodes/game_poller/poller.py`
- `nodes/cover/capacity.py`
- `grids/live_stream/grid.py`
- `nodes/execute/plan.py`
- `nodes/risk/clearance.py`
- `nodes/risk/limits.toml`

Current behavior:

1. `GamePoller` calculates `q_min`, the maximum of each venue's share minimum and the conservative
   Polymarket `ceil($1 / best_ask)` minimum-notional requirement.
2. It evaluates sorted quantities drawn from `{q_min, 5, 10, 25, 100}` above that minimum.
3. For each quantity it walks both executable ladders, computes VWAP, exact fees, and the bounded
   settlement reserve.
4. The evaluation must clear the 1% locked-return floor and `$0.10` minimum locked profit.
5. Live risk then applies available balances/exposure plus the signed `$12 / 10 contracts / $250 day`
   caps.
6. The grid dispatches the first qualifying evaluation. Since quantities are ascending and only one
   real execution may be in flight, this is generally the smallest qualifying quantity.
7. `nodes/cover/capacity.py` separately computes `N_max` and `N_star`, but `_record()` uses it mainly
   for reporting/persistence. It is not the live quantity selector and is not called there with the
   live caps or balances.

Thus today's 5- and 10-contract orders were pilot-sized, first-qualifying rungs, not a bankroll model,
Kelly size, or profit-maximizing `N_star`.

Equal payout units are non-negotiable: an entry of `N` contracts on PM must be hedged by exactly the
actual filled `N` complementary contracts on Kalshi. Unequal quantities create a directional bet.

## Required implementation direction

### Priority A — cap-aware profit-maximizing live size

Replace first-qualifying-rung dispatch with one decision per event/book epoch:

1. Build a feasible candidate set from:
   - venue minimum size;
   - integer/equal-payout quantities compatible with both venues;
   - cumulative order-book depth breakpoints;
   - `max_contracts`;
   - combined-stake cap;
   - remaining daily notional;
   - current venue balances;
   - per-event, per-league, total, and unresolved exposure.
2. Reprice each candidate against the same frozen pair of books. Include full walked VWAP, exact
   per-level fees, settlement reserve, minimum-profit floor, and locked-return hurdle.
3. Select the feasible quantity that maximizes **conservative locked dollar profit conditional on
   completion**, not the largest merely positive quantity.
4. Record both `N_star_feasible` and `N_max_feasible`, every binding constraint, and why the selected
   quantity won.
5. Pass that exact frozen plan through risk; revalidate freshness and hedge capacity immediately
   before entry.

At the present 10-contract cap the answer may often be 10, but not automatically. A shallow second
book, settlement reserve, fee step, `$12` stake limit, or decreasing total profit can make a smaller
quantity correct.

Do not claim this maximizes realized EV until maker fill probability by quantity is measured. Add a
forward descriptive/evaluation row for:

`realized_EV(N) = P(first-leg fill | N, queue state) * locked_profit(N) - hedge_tail_cost(N)`.

Until that exists, use the conservative conditional-fill `N_star` and label the missing fill model.

### Priority B — control first-leg/second-leg mismatch

The operator explicitly identified the central risk: filling many PM contracts and then lacking
Kalshi depth. The safe design must include all of the following:

- Reserve and validate Kalshi depth for the full prospective PM quantity at a hard hedge limit.
- While the PM maker rests, continuously revalidate that full hedge capacity and all-in budget.
- Cancel the PM remainder immediately when the hedge proof expires, price exceeds the budget, depth
  falls below the open remainder, a socket/clock becomes unhealthy, or a kill/breaker activates.
- Treat authenticated cumulative PM fill quantity as a high-water mark.
- Hedge each newly observed fill delta immediately and idempotently; never wait for the PM remainder's
  lifecycle/accounting finality before protecting known inventory.
- Never hedge above the confirmed cumulative PM fill. Preserve dust explicitly.
- Keep new-entry admission blocked until the maker order's cancellation/late-fill lifecycle is proven
  terminal, even if known fills have already been protected.
- Every cancel/fill race and retry needs durable client IDs and restart-safe recovery.

Today's successful TEX–SEA order demonstrates the latency defect: PM fill was known about 0.664 s
after submit, but the Kalshi hedge was not sent until about 6.766 s because lifecycle reconciliation
blocked protection. Split immediate protection from terminal reconciliation.

### Priority C — maker resting and retry policy

- Separate one-submit clearance from a bounded maker-rest authorization.
- Use an absolute maker deadline and ensure cancel dispatch cannot be delayed by a slow synchronous
  status read.
- Prefer authenticated user-stream fill signals; timer/cancel ownership must remain independent so a
  slow stream cannot extend the deadline.
- Replace or justify the current 20-second per-game backoff after a zero-fill. A 0–273 ms maker attempt
  followed by 20 seconds of silence is especially destructive. Prefer a bounded continuously
  revalidated quote or a book-change-driven retry, with anti-spam and queue-priority measurements.
- Rename or separately count maker `UNFILLED` versus true venue `REJECTED`. Do not rewrite historical
  audit rows in place.

Do not fall back to crossing Polymarket orders casually. The current maker-only live route exists
because immediate/non-post-only BUY quantity safety is not proved under the signed share-cap model.
Any taker fallback requires its own proof before wire use.

## Coverage state and next work

The local enabled set at `d6ed3d6` is:

`mlb,nfl,epl,ucl,lal,bun,mls,elc,el1,ita,ere,atp,wta,itf`

It adds UCL and removes CFB, so the enabled count remains 14. Production instead still enables CFB
and lacks UCL because it runs `76a68da`.

Frozen L59 snapshot:

- 308 registered scheduled
- 270 complete slate
- 263 discovery-ready
- 45 explicit non-ready
- 36 PM tennis listings with no open/unopened Kalshi counterpart
- one additional PM tennis listing whose Kalshi counterpart was already finalized
- four exact CFB pairs blocked on invalid/unmeasured settlement evidence
- three exact soccer pairs blocked on missing evidence and zero cap:
  - Braga–Estoril, Primeira Liga
  - Anderlecht–Mechelen, Belgian Pro League
  - Lyon–Rennes, Ligue 1
- one genuine Valencia–Sevilla schedule conflict: Kalshi Sep 13 versus ESPN/PM/official Sep 11

Prioritized coverage continuation:

1. Preserve and include the already-reviewed `d6ed3d6` coverage changes in the final release.
2. Register and complete league-specific original-schedule cancellation and >48-hour postponement
   evidence for Ligue 1, Primeira Liga, and Belgian Pro League, then Scotland. Only add positive caps
   if the immutable evidence criteria pass.
3. Rebuild CFB using a complete authoritative FBS/FCS ordinary-regular-season original kickoff
   corpus and conservative exact upper bounds. L32 is invalid and must not be reused.
4. Keep NBA/WNBA/NHL listing monitors. The frozen longer-horizon inventory had no exact cross-venue
   pairs: NBA 3 Kalshi/0 PM; WNBA 0 Kalshi/23 PM; NHL 0 Kalshi/102 PM. Code cannot manufacture a second
   venue leg.
5. Treat the 203 loose rows across 44 unregistered mappings only as research leads. The largest are
   CS2 63, Rainbow Six 18, LoL 14, and Eerste Divisie/KHL/NPB 8 each. Four loose rows are already
   proven false cross-sport/title collisions. Each new competition needs canonical schedule identity,
   both venue templates, all twelve settlement dimensions, bounded population evidence, complete
   enumeration, fee/token/depth proof, and a positive cap.

## Tests and review required before release

Pre-register any empirical experiment before running it and append `PENDING` to `snooping_ledger.md`.
Criteria and ledger rows are immutable after results are seen. Descriptive code tests do not create
permission to claim EV.

Minimum focused suite for the execution change:

```bash
python3 -m pytest -q \
  nodes/cover/tests/test_capacity.py \
  nodes/game_poller/tests/test_poller.py \
  nodes/execute/tests/test_maker_entry.py \
  nodes/exec_polymarket/tests/test_post_only_lifecycle.py \
  grids/live_stream/tests/test_grid_callbacks.py \
  nodes/risk/tests/test_risk.py
```

Add adversarial tests for:

- `N_star < N_max` and a live cap that binds between them;
- `$12` stake, 10-contract, remaining-day, balance, event, and league cap boundaries;
- two profitable quantities arriving in one frame but exactly one chosen;
- PM partial fills arriving before, during, and after cancel;
- repeated cumulative fill reports and out-of-order user-stream/REST evidence;
- Kalshi depth falling while the maker rests;
- immediate delta hedge while maker terminality remains unresolved;
- cancel timeout, late fill, process restart, and no overhedge;
- truthful `MAKER_UNFILLED` versus venue rejection accounting;
- no extra event-loop blocking or socket starvation.

Then run the full suite, watchdog selftest, compile/JSON validation, and `git diff --check`. Assign an
independent reviewer specifically to race safety, quantity conservation, and cap calculation. Do not
deploy code merely because unit tests pass; inspect a deterministic replay of the exact four zero-fill
incidents and the TEX–SEA delayed-hedge incident.

## One-release deployment sequence

The operator wants one final stop/restart, not iterative live restarts.

1. Finish execution sizing, immediate-hedge, taxonomy, and approved coverage work locally.
2. Commit every intended runtime change in this isolated worktree and ensure it is clean.
3. Complete independent review and all tests.
4. Read-only verify on the box:
   - current service/runner;
   - no execution in flight;
   - no unhedged quantity;
   - reservations and maker admission state;
   - exact kill incidents and their terminal evidence;
   - current balances and day-notional headroom.
5. Use the repository's exact incident-recovery/preflight procedure. Do not blanket-remove
   `/srv/janus/kill/live`.
6. Release the final commit with the existing operator-approved outer caps unless the operator gives
   a new explicit cap instruction. A new code/limits tree requires a newly signed matching override.
7. Restart once under `LIMITED_LIVE`, verify active code/limits hashes, sockets, enabled leagues,
   fresh books, settlement proofs, discovery counts, and that a safe actionable candidate reaches
   the entry gate.
8. Do not raise caps merely because sizing is smarter. First verify the new selector and partial-fill
   hedge behavior under the current `$12 / 10 / $250` pilot caps.

The existing release pattern is:

```bash
JANUS_BOX_REGION=mx-central-1 \
JANUS_BOX_ID=i-0a8c073c72dcdae11 \
JANUS_ARM_CAPS='12 10 250 168' \
bash ops/box/release.sh <final-commit-sha>
```

Do not run it until the full sweep and incident preflight are complete.

## Files changed by completed commits

### Commit `98e89c7` — modified

`.gitattributes`; `nodes/discovery/census.py`; `nodes/discovery/tests/test_census.py`;
`nodes/entities/README.md`; `nodes/entities/aliases.csv`; `nodes/entities/aliases_manual.csv`;
`nodes/entities/leagues.py`; `nodes/entities/resolve.py`; `nodes/entities/seed.py`;
`nodes/entities/teams.csv`; `nodes/entities/tests/test_leagues.py`;
`nodes/entities/unresolved.csv`; `nodes/entities/xref_conflicts.csv`; `nodes/entities/xrefs.csv`;
`nodes/match_sports/README.md`; `nodes/match_sports/sports_match.py`; `nodes/risk/README.md`;
`nodes/risk/limits.toml`; `nodes/risk/tests/test_risk.py`;
`nodes/schedule_espn/tests/test_espn.py`; `nodes/settle_wedge/README.md`;
`nodes/settle_wedge/equivalence.py`; `nodes/settle_wedge/evidence.py`;
`nodes/settle_wedge/pair.py`; `nodes/settle_wedge/policy.py`;
`nodes/settle_wedge/tests/test_settle_wedge.py`; `snooping_ledger.md`.

### Commit `98e89c7` — created

`nodes/entities/tests/test_club_identity.py`; `nodes/entities/tests/test_manual_xrefs.py`;
`nodes/entities/xrefs_manual.csv`; `nodes/match_sports/tests/fixtures/ucl_20260909_10.json`;
`nodes/match_sports/tests/test_ucl.py`; `nodes/settle_wedge/tests/test_ucl_evidence.py`;
the complete `research/sports/2026-09-09_ucl-coverage-repair/` spec/verdict;
and the `collect.py`, `measure.py`, `results.json`, spec, verdict, source-integrity spec and verdict in
`research/sports/2026-09-09_ucl-settlement-bounds/`.

### Commit `d6ed3d6` — modified

`nodes/discovery/discovery.py`; `nodes/discovery/tests/test_discovery.py`;
`nodes/discovery/tests/test_venue_schedule.py`; `nodes/discovery/venue_schedule.py`;
`nodes/entities/aliases_manual.csv`; `nodes/entities/seed.py`; `nodes/entities/teams.csv`;
`nodes/entities/tests/test_leagues.py`; `nodes/entities/tests/test_manual_xrefs.py`;
`nodes/entities/tests/test_tennis_aliases.py`; `nodes/entities/xrefs_manual.csv`;
`nodes/match_sports/sports_match.py`; `nodes/match_sports/stage1_checkpoint.py`;
`nodes/match_sports/tests/test_match.py`; `nodes/settle_wedge/README.md`;
`nodes/settle_wedge/equivalence.py`; `nodes/settle_wedge/evidence.py`;
`nodes/settle_wedge/pair.py`; `nodes/settle_wedge/policy.py`;
`nodes/settle_wedge/tests/test_settle_wedge.py`;
`nodes/settle_wedge/tests/test_soccer_three_way.py`; `ops/coverage_report.py`;
`ops/tests/test_coverage_report.py`; `ops/watchdog.py`; `snooping_ledger.md`.

### Commit `d6ed3d6` — created

`nodes/entities/tests/test_seed_enumeration.py`; `nodes/settle_wedge/tests/test_cfb_template_v2.py`;
all artifacts in `research/sports/2026-09-09_all-coverage-misses/`; and all artifacts in
`research/sports/2026-09-09_cfb-settlement-bounds-v3/`.

### Commit `2e9620a` — modified/created

- Modified: `snooping_ledger.md` with immutable L61 registration and result append.
- Created: `research/sports/2026-09-09_execution-rejections-and-coverage-progress/spec.yaml`.
- Created: `research/sports/2026-09-09_execution-rejections-and-coverage-progress/results.json`.
- Created: `research/sports/2026-09-09_execution-rejections-and-coverage-progress/verdict.md`.

### This handoff

Created `HANDOFF_PROFIT_SIZING_COVERAGE_2026-09-09.md`. It has no runtime effect.

## Important files intentionally left untouched

- Main checkout user changes:
  - `research/sports/2026-09-03_co-listing-census/verdict.md`
  - `research/sports/2026-09-04_tennis-delay-forward/verdict.md`
  - associated untracked result files, `.codex/`, and `outputs/`
- Live box code, service, database, positions, balances, orders, kill files, arming override, and caps.
- `NEXT.md` in the old main checkout: it contains stale status and was not treated as authoritative
  over direct git/database/service evidence.
- Historical ledger rows: corrections were appended; no row was rewritten in place.

## Sources of truth

- `AGENTS.md`: pure two-leg arbitrage, executable ladder prices, settlement-reference proof, exact
  canonical matching, preregistration, and EV/Sharpe objective.
- `GATE_TO_LIVE.md`: operator authorization, promotion sequence, and cap history.
- `snooping_ledger.md`: immutable research/audit registration and results.
- `nodes/risk/limits.toml` plus the signed box override: inner risk ceilings and current outer live caps.
- `nodes/cover/capacity.py`: exact breakpoint frontier and definitions of `N_max`/`N_star`.
- `grids/live_stream/grid.py` and `nodes/game_poller/poller.py`: actual live quantity dispatch behavior.
- Mexico `/srv/janus/tuples/tuples.sqlite`, order journal rows, post-only lifecycle tables, kill file,
  service unit, and signed override: authoritative current execution/operational state.
- L57–L61 specs, results, and verdicts: frozen coverage, settlement, and execution findings.

## Current project state

- Isolated branch runtime coverage changes are reviewed and committed but undeployed.
- Production continues to run the older `76a68da` code and is presently blocked from new entry by a
  persistent live kill latch, although the service is active.
- No profit-maximizing live sizing, continuously revalidated maker-rest authorization, or immediate
  partial-fill delta hedging change has yet been implemented.
- No cap increase has been made or justified.
- Coverage beyond the repaired registered universe remains blocked by explicit venue absence,
  settlement evidence, caps, or unverified identity—not merely by a missing boolean switch.

The next agent should begin with a fresh `git status`, preserve this clean isolated branch, write the
required preregistration before any empirical evaluation, and divide implementation/review work into
bounded subagents if useful. Keep all live actions until the single final release gate.
