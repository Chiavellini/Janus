# Handoff — profit-maximizing sizing, maker execution, and coverage expansion

Date: 2026-09-09 America/Mexico_City  
Prepared from branch: `codex/ucl-coverage`  
Worktree: `/Users/bernardodelrio/Code/Janus/.codex/worktrees/ucl-coverage`  
HEAD before this handoff file: `2e9620aaf0106af812761541211b72019bd14c2a`

## Emergency release continuation — 2026-09-10

This section supersedes every operational status below it. The executable repair is commit
`42ac10cd67af9b228930481ee3fd8ea4226f72ac`; production still runs `d3237fa` until the operator
releases the final documentation commit that contains it.

### Initial state and incident

The third F20 release provisioned the redemption credential and installed its runtime, but failed
the live-clear health check because `sudo` stripped `JANUS_CLEAR_STARTED`. The remote wrapper did
not return nonzero, so release continued and the redemption unit failed with
`PackageNotFoundError: polymarket-client`. During the old clear script's interval with no kill,
one bounded taker execution entered. The rollback restored the false-maker kill as root-owned;
the fill writer then encountered a SQLite lock and could not replace it with the stronger incident.

The trade is now fully final: execution `0b425cbe71cb4ca1a919fda622538a07` is RECONCILED/released,
all orders and two positive fill FIFOs are final, settlement/reservation are released, and there is
no current open or pending money. It realized -$0.014932: the 10-contract cover locked -$0.4775
after five zero-fill Kalshi hedge attempts, while a 0.7632 PM residual happened to win +$0.4626.
The box remains active for ingestion but `kill/live` is present; no later execution exists.

### Work completed

- The PM cash/fill transaction now uses `BEGIN IMMEDIATE`, preserving the worker store's busy-wait
  behavior instead of failing during a deferred writer upgrade.
- A fresh complete two-venue guard may append an exact resolution only for a strictly parsed
  database-lock flag whose terminal order, final FIFOs, bounded overfill authorization, unique
  released execution, settlement and reservation all agree twice, including under the writer lock.
- The false-maker clear refuses all unresolved material risk flags, waits under the existing kill
  for the guard's exact recovery, stops only after risk is quiet, retains/chowns the kill during
  warm-up, checks three post-restart streams, and removes only the unchanged digest-bound kill.
  Rollback restores its byte-identical contents with lane-writable ownership.
- SSM remote failures now propagate locally. Redemption failure output includes its bounded stderr.
  The redemption unit overrides `JANUS_PYTHON` at the final shell boundary, after the environment
  file, so it uses the pinned `polymarket-client==0.9.0` environment.
- The ten-minute redemption oneshot has an explicit eight-start watchdog allowance: seven healthy
  starts are quiet, eight with a latest failure reports FAILED, and nine reports CRASH_LOOP.

Expected direct strategy EV effect is zero. The transaction change prevents a known false stop;
the remaining changes make release/recovery/redemption observable and fail-closed. F20's first
observation is adverse protection/latency evidence and does not justify lifting caps.

### Files changed

- `nodes/exec_polymarket/client.py` and its maker-fill tests: retain IMMEDIATE transaction semantics
  and reproduce the two-writer race.
- `nodes/execute/guard.py` and guard tests: invoke exact recovered-persistence closure only after a
  complete safe pass.
- `ops/box/clear_false_maker_latch.py`, `.sh`, and tests: material-flag gate, retained-kill warm-up,
  exact activation, byte/owner-safe restore, explicit sudo epoch, and bounded pre-clear wait.
- `ops/box/run.sh`, `release.sh`, systemd redemption unit, and box tests: propagate SSM failure,
  expose node stderr, and force the pinned redemption interpreter.
- `ops/watchdog.py`: correct only the redemption timer's expected start cadence.
- `snooping_ledger.md`: append-only L68–L70 registration/verdicts and F20 observation.

### Files created

- `nodes/execution/persistence_recovery.py` and its tests: exact terminal-economic-record proof and
  append-only flag resolution.
- `ops/box/tests/test_run_sh.py`: remote-status propagation regression.
- `research/exec/2026-09-10_{release-poststart-and-redeem,recovered-persistence-incident,redemption-watchdog-cadence}/`:
  immutable specs and verdicts.
- `research/sports/2026-09-10_limited-live-f20-bounded-taker/observation_1.md`: exact first F20 result.

### Source of truth and intentionally untouched areas

`AGENTS.md`, `GATE_TO_LIVE.md`, the F20 spec, and L68–L70 specs govern this repair. Caps, profit and
return hurdles, protection-loss ceiling, settlement rules, sizing, discovery/coverage, credentials,
venue balances and existing audit/accounting rows were not changed. The production kill and
database were read only throughout development.

### Verification and immediate next steps

The complete repository suite passes. Focused concurrency/recovery/clear/release tests, watchdog
selftest, compileall, YAML parsing, shell syntax and diff checks pass. On the actual box, remote
failure propagation, explicit sudo epoch, three connected streams, candidate systemd parsing,
the pinned SDK's authenticated position read, and the exact incident proof all passed without
submission or kill/database mutation.

The first operator release of this continuation (`d864447`) failed closed before stopping the lane:
fresh guard passes were economically clean, but the already-resolved historical persistence checker
still emitted `LEGACY_POSITION_EVIDENCE_BLOCKED` against unrelated shared-account positions. L69's
strict safe-pass predicate therefore refused flag 530. L71 removes only that stale proof attempt
when its exact flag class is empty, after acknowledgement validation and migration cleanup; active
or invalid incidents remain fail-closed. The kill was unchanged and redemption was not reached.

The next action is one operator release of the final pushed follow-up. It must show
`PRE_CLEAR_RISK_FLAGS_QUIET`, `STOPPED_EXACT_STATE_OK`, `POST_START_STREAMS_GREEN`,
`LIVE_CLEAR_COMPLETE`, and a successful `pm redemption ...` line. If exact persistence recovery
does not complete, release aborts before touching the kill; do not bypass it. After release, inspect
the box once for absent kill, resolved flag 530, active lane/timer, successful redemption state,
fresh streams, no watchdog alerts, and no unexpected order during the transition.

## Final operational outcome — supersedes the historical status below

At the final read-only verification on **2026-09-10T05:03:23Z**, the requested sweep was complete
and the Mexico box was fully enabled for small live trading:

- Production runs exact runner `6c694f1320459b590809f4de7496415d0a748d0e` under
  `janus-live-stream`, `LIMITED_LIVE`.
- The signed override matches that runner and the reviewed code/limits identities
  `f6ae23763f79b0f8` / `3b97a98f881fad41`, with unchanged outer caps of `$12` combined stake,
  `10` contracts per leg, and `$250` daily committed notional. It expires
  `2026-09-17T04:13:22Z`.
- The exact reviewed local `kill/live` (SHA256
  `9e93a8664fe457a85b63ea69625688126389889a345cdf0a4f445f44d442c649`) was recoverably moved by
  the operator to
  `/srv/janus/release-audit/L56/live-cleared-6c694f1320459b590809f4de7496415d0a748d0e.json`.
  No local kill file remains, the cross-host `/janus/kill/live` parameter was absent, and direct
  watchdog output contained no alert.
- Kalshi market, Polymarket market, and authenticated Polymarket user streams were connected and
  fresh. Both market clocks were healthy and the event-loop lag was below the live threshold.
- Current risk was empty: zero open/unconfirmed/cash-pending orders, unreleased executions,
  unreleased reservations, material unhedged executions, unresolved post-only markers, or active
  execution/risk flags. The post-only admission singleton was empty.
- The lane was actively evaluating the live universe. Its post-clear decisions were sizing
  refusals at the registered contract/profit/return/minimum-order boundaries, not a kill-switch
  refusal. No new order had been submitted in the first verified post-clear window.
- The five maker orders preceding the historical latch are fully accounted for: four were terminal
  zero-fill cancellations; the TEX–SEA maker filled 10, the Kalshi hedge filled 10, and the cover
  settled at `+$0.7798`.

No further release is required for this sweep. Later documentation commits must not be mistaken for
a new runtime candidate: the deployed and signed production runner remains `6c694f1`. The F18 gate
still requires authoritative cash/fill reconciliation of its first three covers before a fourth;
live enablement does not waive that evidence boundary.

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

## Initial live-box state — historical, superseded by the final outcome above

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

## Continuation outcome — completed 2026-09-09

The implementation requested by this handoff was complete in the isolated worktree and had passed
the full local release gate plus three independent reviews at this point in the session. It had
**not yet** been deployed, restarted, re-signed, or used to clear a kill; the final operational
outcome above records the later completed operator actions.
The exact reviewed runtime/research implementation is commit
`d174f24103b2a444070930e3810da085ea3c70be` (`Maximize safe maker cover profit`).

### Profit-maximizing, cap-aware sizing

- `nodes/execute/sizing.py` exhaustively evaluates every integer equal-payout quantity from the
  joint venue minimum through the signed maximum, rather than selecting the first profitable rung.
- Every candidate is repriced against the same frozen executable books and is checked against
  walked depth, exact fees, settlement reserve, minimum profit/return, combined-stake and contract
  caps, remaining daily notional, venue balances, event/league/venue/total exposure, unresolved
  exposure, and maximum unhedged exposure.
- The selected `N_star_feasible` maximizes conservative locked dollars conditional on both legs
  completing. `N_max_feasible`, the full frontier, binding constraints, and audit inputs are
  persisted. Passive maker improvement is deliberately not credited before it exists.
- Live selection always performs this exhaustive pass. It does not silently fall back to the old
  fixed-rung/first-profitable behavior.

Expected EV effect: higher locked dollars per completed cover when deeper size remains profitable,
without admitting quantity whose second leg, capital, or risk constraints cannot support. This is
not yet a claim about realized EV because size-dependent maker fill probability and hedge-tail cost
remain prospectively unmeasured under L63.

### Maker rest, immediate delta hedge, and restart safety

- A one-shot entry clearance now arms a separate immutable maker-rest deadline. While the order
  rests, the system continuously revalidates the complementary hedge, fees, settlement proof,
  caps, clock/socket health, and kill/breaker state.
- Real-capital maker entry requires the authenticated Polymarket user stream; paper modes remain
  permissive. Guard callbacks are time-bounded and any timeout/error cancels the maker remainder.
- Cancel dispatch occurs before potentially slow terminal REST reconciliation. `UNFILLED` is now
  recorded truthfully as `ORDER_UNFILLED`, distinct from a venue rejection.
- Authenticated cumulative maker fills are a high-water mark. Each new delta is hedged immediately
  and idempotently (for example, 2 then 5 hedges 2 then 3), without waiting for maker terminality.
- Every protective order now carries the exact execution ID in the durable journal. Restart recovery
  uses that ownership and refuses a new protective submit while any owned order is open, unconfirmed,
  or incompletely evidenced.
- A confirmed fill can no longer be stranded by failure of the main execution-row write: storage
  failure latches entry but the protective wire continues. The same guarantee covers unwind fills
  and the final unprotected page/latch path.

Expected EV effect: the maker gets the intended bounded queue exposure rather than 0–273 ms, while
first-fill-to-hedge delay and naked-tail risk fall materially. No taker fallback or larger outer cap
was introduced.

### Event-loop, book-frame, and opportunity correctness

- Synchronous callbacks have an enforced timeout so a stalled guard cannot starve the async loop.
- A Kalshi websocket frame updates all registered YES/NO projections before any callback, preventing
  one callback from sizing against mixed old/new projections of the same frame.
- The live economic fingerprint excludes receive-time noise, but repeated economic states are
  occurrence-aware: consecutive `A, A` is suppressed and `A, B, A` is a valid third occurrence.
- Maker currentness uses the book's verified/fetched timestamp projected to monotonic time, rather
  than requiring a price mutation to prove the unchanged book is current.

### Coverage continuation

- L62/L63 were preregistered before empirical work and appended to `snooping_ledger.md`; their
  criteria and ledger entries were not edited after observation.
- The intended Ligue 1 source archive was absent, so no acquisition or measurement was run and L62
  remains `PENDING`. Separate conservative no-data amendments L62-A1/L63-A1 preserve that fact.
- `research/sports/2026-09-09_ligue1-original-schedule/manifest.py` provides the strict offline
  firewall for a future archive: exact source hashes/URLs, canonical bound, 306 unique fixtures,
  18 clubs with 17 home/17 away, regular-season identity, complete official membership plus
  original-schedule lineage, and earliest published Paris-local date at midnight UTC. Invalid input
  makes zero terminal transport calls.

### Verification and independent review

- Full repository suite: passed at 100% after the final protection changes.
- Broad focused execution/opportunity/stream/risk/cover/L62 suite: passed at 100%.
- Hedge protection suite: 12/12 passed, including both post-fill database-failure regressions.
- Watchdog self-test: all 8 job, 7 risk, registry, and 4 socket branches fired; healthy cases quiet.
- `compileall`, four YAML parses, and `git diff --check`: passed.
- Independent maker/race review: `CLEAN` (271 focused tests in the review).
- Independent sizing/cap/recovery review: `CLEAN` after the two final persistence-path fixes.
- Independent Ligue 1 firewall review: `CLEAN` (29/29 focused tests); no L62 archive existed and no
  terminal acquisition occurred.

### Fresh exact live preflight

A new read-only box snapshot immediately before committing this continuation proved:

- active service, PID `59799`, still running `76a68da88164047ba630c74c49cb30c8c33ccefd`;
- exact kill SHA256 `0ea1acaa68c747fdaa4c54c8c05039ce11f69459dd639e89b8b80a7295fdc36b`, containing only the
  JSON latch for Polymarket CID `5a162878dc8842d09e42b797475b81e9`;
- unique owning execution `13feaaad71f547428ba70b45b0d9bd49`, event
  `espn:mlb:401816880`, `RECONCILED`, released, first/hedge `10/10`, unhedged `0`;
- PM CID `5a162…` and Kalshi CID `170c2…` both `FILLED`, closed, settlement not pending;
- settlement kind `COVER`, realized/cover P&L `+$0.7798`, directional P&L `$0`;
- exact reservation `eb9f1b31…` released; maker marker `terminal_proved=1, violated=0`; singleton
  maker admission empty;
- global current counts: flight `0`, unreleased-unhedged `0`, open/unconfirmed orders `0`, and
  unresolved/violating maker markers `0`.

This distinguishes the present latch from the older, separately acknowledged CID `40797…`
database-lock incident. The targeted historical repair did not and should not silently clear this
later TEX–SEA latch. The evidence above makes the latter eligible for the exact, recoverable
operator clear after the new release is warmed and rechecked; it does not authorize a blanket reset.

### First release feedback and compatibility repair

The operator released `7e87dd9d5e808e3cb791a5d30cd134e7118ba613` at 02:39Z. Checkout,
override re-signing, and LIMITED_LIVE restart succeeded under the unchanged caps; the retained
`kill/live` correctly prevented a new order. The post-restart watchdog then exposed a release
blocker before the kill was cleared: adding nullable `orders.execution_id` changed the dictionaries
produced by two immutable L56 version-1 evidence snapshots because they used `SELECT *`. Every
production comparison showed exactly one added key, `execution_id`, and no changed or removed
economic/accounting field. This made the older acknowledgements invalid and re-raised their flags;
it did not reveal a changed fill, position, or P&L.

Commit `472dcc2c1a396132ad784d95f30537d4ab5dec1e` repairs the migration boundary:

- version-1 order evidence now has an explicit frozen projection, so an additive nullable journal
  column cannot rewrite historical operator-attested bytes;
- the new ownership column is still checked bidirectionally and fail-closed: every legacy-owned
  order's non-null owner must equal the unique execution, and no extra journal order may claim that
  execution while absent from the immutable client-ID lists;
- null historical owner cells remain valid and all economically meaningful v1 fields remain exact.

Three migration/conflict regressions were added. The final full repository suite passed, the focused
acknowledgement/legacy/guard suite passed 101 tests, compile/diff checks passed, and the independent
review returned `CLEAN`. A second operator release of the final handoff SHA is therefore required
before warm-up verification and the exact recoverable kill clear.

The second release confirmed all five overfill acknowledgements and legacy flag 211 validate under
the repaired projection. It also showed that the first faulty process had appended 280 duplicate
`ORDER_OVERFILL` rows (56 for each of the five already-attested terminal orders) and 28 duplicate
`POST_ONLY_PERSISTENCE_FAILED` rows before it was replaced. Their five overfill details exactly match
the immutable acknowledged `(client ID, requested quantity, filled quantity)` fingerprints; the
legacy detail is exactly the generated compatibility exception for flag 211. No duplicate was
emitted after the compatibility repair, and current flight, unhedged, open/unconfirmed order,
maker-marker, and admission counts remained zero.

Commit `0edb1c3c04881e1489978a963415d67f5cb72746` adds append-only exact resolution for those rows:

- later overfill rows close only if every unresolved row's exact flag/detail fingerprint exists in
  a currently valid immutable acknowledgement; any new or changed finding blocks all resolution;
- legacy compatibility rows close only for the one canonical generated error string, a currently
  valid source acknowledgement whose original flag is already resolved, a complete safe venue
  guard, terminal/nonviolating maker history, empty admission, and no open/unconfirmed orders or
  unreleased executions/reservations;
- both paths revalidate the identical unresolved snapshots inside `BEGIN IMMEDIATE`, append exact-ID
  resolution markers, and leave `kill/live` unchanged.

Four adversarial regressions were added. The full repository suite and 105 focused tests passed;
compile/diff checks passed; independent fail-open/race review returned `CLEAN`. This exact-resolution
commit requires one final operator release before the warm-up/kill-clear gate.

The next release resolved all 280 overfill duplicates, but the 28 legacy duplicates remained because
the caller placed their compatibility-only resolver behind the original L56 one-time terminal-zero
position proof. The currently authenticated Polymarket position response no longer satisfies that
historical interpretation, although both position feeds are present, the ordinary guard reports no
orphan or mismatch, the original acknowledgement remains valid/resolved, and every current local
money/admission/order check is zero/terminal. Repeating the original proof is unnecessary for rows
whose only fact is that the faulty process rejected the immutable snapshot after adding a nullable
column.

Commit `976d925eeac32bacdbd7daf72fa97bf17023da12` moves only the exact migration-derived cleanup
ahead of that historical-only interpretation. It still requires complete authenticated fills, both
position reads, no errors/orphans/mismatches or blocking finding, a valid and already-resolved source
acknowledgement, the canonical generated error strings, terminal/nonviolating maker history, empty
admission, no open/unconfirmed orders, no unreleased execution/reservation, and the writer-locked
exact-set recheck. A current position cannot validate a new incident; any ordinary position mismatch
or changed flag still blocks. The original incident-resolution path retains its terminal-zero proof.

One adversarial regression was added. The full suite and 109 focused tests passed; compilation/diff
checks passed; independent fail-open/race review returned `CLEAN`.

Production then exposed the final exact shape of an empty released maker admission:
`slot=1, client_order_id=NULL, claimed_utc=1788992773.297811`. The ownership slot is empty, while
`claimed_utc` intentionally retains the prior claim's audit time. The compatibility resolver had
incorrectly required both owner and audit time to be null. Commit
`cbb3995db00dc76c5684dab33972192fd5de305a` accepts the retained timestamp only when the row has all
three required fields, slot is exactly 1, owner is explicitly null, and the timestamp is null or a
positive finite number. Missing schema fields, a live owner, wrong slot, or malformed time remain a
block; additive columns remain allowed. The predicate is rechecked inside the same writer lock.

The exact production-shape regression plus missing-field/owned/wrong-slot/nonfinite cases were added.
The full suite and 110 focused tests passed; compilation/diff checks passed; independent review
returned `CLEAN`.

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

## One-release deployment sequence — completed, retained for audit history

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

This sequence was completed. Do not run it again merely because the handoff receives a later
documentation-only commit.

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

### Continuation implementation — modified

- Grid/runtime: `grids/live_stream/grid.py`, its README and callback tests;
  `kernel/execution_protocol.py`; `kernel/schema.py`.
- Cover/settlement: `nodes/cover/cover.py`, its README/tests; and
  `nodes/settle_wedge/equivalence.py`.
- Execution: `nodes/exec_polymarket/client.py` and lifecycle tests;
  `nodes/execute/coordinator.py`, `guard.py`, `on_loop.py`, `plan.py`, `protect.py`, the execution
  README and their coordinator/guard/maker/on-loop/protect tests; and
  `nodes/execution/journal.py`.
- Opportunity/risk/stream: `nodes/opportunity/opportunity.py`, README and tests;
  `nodes/risk/clearance.py`, `ledger.py`, README and tests; and
  `nodes/stream_kalshi/stream.py` plus tests.
- Operations/research: `ops/reconcile_stuck_execution.py` plus tests;
  `snooping_ledger.md`; and this handoff.

### Continuation implementation — created

- `nodes/execute/maker.py` and `nodes/execute/sizing.py`.
- `nodes/execute/tests/test_maker_session.py` and `nodes/execute/tests/test_sizing.py`.
- L63 spec and no-data amendment under
  `research/exec/2026-09-09_size-dependent-maker-ev/`.
- L62 spec, no-data amendment, strict manifest firewall, and 29-test suite under
  `research/sports/2026-09-09_ligue1-original-schedule/`.

## Important files intentionally left untouched

- Main checkout user changes:
  - `research/sports/2026-09-03_co-listing-census/verdict.md`
  - `research/sports/2026-09-04_tennis-delay-forward/verdict.md`
  - associated untracked result files, `.codex/`, and `outputs/`
- Production accounting, order, position, balance, acknowledgement, and historical incident rows
  were not manually edited or deleted. The operator changed only the reviewed deployment state:
  checkout/override/service through `release.sh`, followed by the exact recoverable `kill/live`
  archive described above. Caps were not raised.
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

- Isolated branch coverage and execution changes are implemented, committed, pushed, fully green,
  independently reviewed, and deployed through runtime commit `6c694f1`.
- Production is active in `LIMITED_LIVE`, has no live kill, and is eligible to send an order only
  when the executable two-leg economics, exact settlement proof, live caps, authenticated streams,
  clock health, balances, and exposure checks all pass.
- Profit-maximizing conditional-fill sizing, continuously revalidated maker-rest authorization,
  immediate partial-fill delta hedging, and exact restart ownership are active in production.
- No cap increase has been made or justified.
- Coverage beyond the repaired registered universe remains blocked by explicit venue absence,
  settlement evidence, caps, or unverified identity—not merely by a missing boolean switch.

## Immediate next steps

1. Do **not** release or clear anything again for this completed sweep.
2. Reconcile each of the first three F18 covers against authoritative venue fills, fees, positions,
   and cash before permitting a fourth, exactly as required by `GATE_TO_LIVE.md`.
3. Treat any new local kill, unresolved order, unhedged quantity, persistence flag, disconnected
   authenticated stream, or unhealthy market clock as a fresh incident. Do not repeatedly clear it.
4. Evaluate sizing results by locked EV dollars and per-trade Sharpe under the unchanged pilot caps;
   refusal volume or raw coverage is not itself a reason to loosen a hurdle.
