# Changelog

Dated, append-only. Like `snooping_ledger.md`, an entry records what was true when written and is
never edited afterward. **This is history, not status** — for current state read `NEXT.md`,
`git log`, and `python3 ops/watchdog.py`.

---

## 2026-09-02 — foundation

Seven commits, `bd00b85` → `5eac384`. The repo went from unversioned, unmonitored and
layer-organised to a node grid under git with a dead-man's switch. **No behaviour of the
arbitrage math changed.** Every fix was to visibility, structure, or a defect that had already
fired.

### What was wrong, and what the evidence actually said

An audit ran before any change. Four findings drove everything else:

1. **The "0 opportunities above 1%" result is n=1.** `sweep_runs` holds three rows, ever — two MLB
   sweeps 82 seconds apart in one seven-minute window. The single observation priced at −1.6%,
   ~2.7 points from the hurdle. It is a coverage artifact, not an economics finding.
2. **The scanner is MLB-only.** `sports_match.py` hardcodes `^mlb-` in the Polymarket slug pattern
   and applies it to all six default leagues, so five emit zero pairs — bucketed as a benign
   reason code. Combined with a ±30 minute window against a 30-day registered universe, the null
   covers one league for half an hour.
3. **"156 tests passing" excluded the pricing engine.** `test_cover.py` and `test_spine.py` used an
   import-time harness that caught every assertion into a list nobody read; pytest collected zero
   items from both. All 28 assertions pass once visible — the engine was never broken, but a
   regression could not have been noticed.
4. **A collector had been crash-looping every 30 seconds for thirteen days.** 15,207 identical
   tracebacks, 11.9 MB of unrotated stderr, undetected.

### Commits

| | |
|---|---|
| `bd00b85` | **Freeze.** First commit of the tree as found, including another agent's in-flight work. Janus had run unversioned since 2026-07-24. |
| `53aee43` | **The crash loop.** `Resolver.resolve` signals failure by *returning* `Resolution(entity_id=None)`, so the `try/except` around it caught nothing and the `None` reached `sorted()` several frames away. The invariant was known — one of four call sites guarded it — so the check moved into `game_key()` and a new `resolved_ids()`. |
| `0b4afc7` | **Run index + watchdog.** Append-only `runs/index.jsonl`; the start row is written *before* the interpreter runs, so a crash at import still leaves a trace. `CRASH_LOOP` detects restart *rate* — "did it finish" could never have caught this, because a crash loop does keep running. All seven alert branches demonstrated firing against a fake target, and demonstrated staying silent on the live index. |
| `57a652a` | **Visible tests.** Harness converted, repo-root `conftest.py`, `_no_network` autouse fixture, `pyproject.toml`, and `tests/test_meta.py` so the failure mode cannot recur. 156 → 215. |
| `5a8c813` | **Strip, part 1.** Four abandoned tracks removed, chosen by import closure from the sports entry points rather than by eye. 76 → 48 Python files. |
| `3f194fb` | **Ledger closures.** F1, F2, L24 closed under rule 6 as appended notes. |
| `5eac384` | **The node grid.** `kernel/` + `nodes/<name>/` + `grids/<name>/` + `ops/`, one README per node. `sports_books.py` split three ways by venue. Six phase-1 fuzzy-matching modules removed. |

### Operational state changed on this machine

All seven `com.janus.*` collectors are **unloaded**; `com.janus.watchdog` runs every 5 minutes.
Plists are preserved, so each is one `launchctl bootstrap` from returning. WALs were checkpointed
before shutdown — `forward.sqlite` merged 21.6 MB, `kalshi_open.sqlite` 4.1 MB — so no write was
lost. The 960 MB L24 capture is archived intact under
`/Volumes/Kilos/janus/archive/newborn_L24_closed_2026-09-02/`.

Ledger rows F1 (shadow, MLB) and F2 (convergence, MLB) are closed **unscored**; no outcome was
read. F2 is the methodological finding: its accrual in fact ended 2026-08-27, so a registered
forward evaluation read `PENDING` for six days while collecting nothing.

### What the next agent inherits

- **Green suite from any directory**: `python3 -m pytest` → 92 passed.
- **A layering rule that holds**: grids import nodes, nodes import the kernel, nodes never import
  grids. Verified, not merely stated.
- **Two known correctness bugs, and a mandatory order.** `nodes/cover` receives `exhaustive=True`
  for every league including 3-way EPL and tie-capable NFL; an EPL match would report a +31%
  "cover" that is really a bet the match is not drawn. This is masked *only* by the MLB-only slug
  regex. **Mint `ExhaustiveOutcomeSet` before widening coverage** — fixing coverage first switches
  on a fake-arbitrage generator.
- **Invariants asserted in prose that no code enforces**: the settlement classifier
  `kernel/schema.py` claims exists, the fee-multiplier that "is an error, not a default" and then
  defaults, the Polymarket rate the registry warns against hardcoding and a grid hardcodes anyway.
  Each node README names its own.

### Deliberately not done

No grid runtime yet (typed faults, run manifest) — that is step 1 in `NEXT.md`. No Ashburn/EC2, no
order path, nothing armed. `venue_cloudbet` is parked, not deleted: its acceptance-before-pricing
sequencing makes its leg a naked directional bet, and `venue_sxbet` — zero-rake, two-sided, parser
already written — is the replacement.

### Recovery

Nothing is gone. Every removed file is in `bd00b85`:

```bash
git show bd00b85 --stat | head -50
git checkout bd00b85 -- <path>
```

---

## 2026-09-02 — P0a: the live lane was mispricing fees, and the docs described fixed bugs

First step of the v1 plan (Mac first, execution built but disarmed, dead grids retired). Nothing
armed. No arbitrage math changed except what the venues actually charge.

### What was wrong

1. **Kalshi sports fees were charged at 2×.** `GET /series/KXMLBGAME` reports
   `fee_type: quadratic_with_maker_fees, fee_multiplier: 0.5`. The lane never read it, and
   `nodes/fees/models.KalshiQuadratic` silently defaulted a missing multiplier to 1.0 while its own
   docstring said "missing is an error". Every cents-from-actionable figure before today overstates
   the Kalshi fee by a factor of two.
2. **Polymarket's rate was a constant** (`{"fee_rate": 0.05}` at four sites) rather than the
   market's `feeSchedule`. Game markets happen to be 0.05 today; the futures market sampled was 0.03.
   The hurdle (`hurdle_for`) meanwhile used the registry pin, 0.07 — so the near-miss column and
   the cover disagreed about the fee.
3. **A Polymarket drift never forced a resnapshot.** `stream.py` set `resubscribe_needed`, but the
   run loop only sends frames for a CHANGED asset set; the set was unchanged, so nothing went out
   and the replica waited on the venue's next trade.
4. **A grid imported a grid.** `grids/live_stream` pulled discovery from `grids/live_sports`.
5. `venue_polymarket.fetch_pm_books` raised `NameError` on every call (`errors`/`slug` out of scope).
6. `README.md`, `NEXT.md`, `nodes/cover`, `nodes/match_sports` still described the `exhaustive=True`
   bool and the `^mlb-` slug hardcode, both fixed on 2026-09-02 in `1c3b931` and `f8a187e`.

### What changed

- `nodes/discovery` (new): schedule → co-listed slate → per-game fee params from the venues' own
  payloads → `events` table. Both grids compose it.
- `nodes/game_poller` takes `fee_params` per venue; a venue without one blocks its legs with
  `FEE_SCHEDULE_MISSING`. `grids/live_stream` passes the same params to the hurdle.
- `nodes/fees/models`: a missing or null Kalshi multiplier raises. The registry pin (1.0) remains a
  labelled screening fallback reached only through `params_for`.
- `nodes/stream_polymarket`: drift queues the asset for an unsubscribe/subscribe round trip; the
  drifted local ladder is dropped rather than patched.
- `kernel/redact` (new): argv redaction before the run index persists it; exception text reduced to
  type and first line before it can reach a log.
- `kernel/venue_registry`: Kalshi and Polymarket are registered (`nodes/venue_*/adapter.py`); one
  spelling of the Polymarket liquidity source (`pm_clob`).
- `nodes/store_tuples.ensure_ddl`: a node owns its tables. `sweep_runs.error` now carries the exception.
- Deleted `grids/scan_pure_arb` (bypassed `nodes/cover`, wrote into an immutable research dir) and
  `grids/sports_books_poll` (passed `exhaustive=True`; every cover rejected since `1c3b931`).
  Recoverable from `2695129`. `nodes/venue_sxbet` stays, parked.
- Tests for `kernel/fetch`, `kernel/redact`, `match_sports`, `store_tuples`, `venue_polymarket`,
  `venue_kalshi` (series), `discovery`; `tests/test_meta.py` now checks every node-level test file.
- `GATE_TO_LIVE.md`: sports amendment logged (see its amendment log).

### Measured today

`GET /series/KXMLBGAME`: `quadratic_with_maker_fees`, multiplier 0.5, settlement sources ESPN, Fox,
MLB. Gamma MLB game markets: `feeType sports_fees_v2`, `feeSchedule {rate 0.05, takerOnly, rebateRate
0.15}`, `orderMinSize 5`, tick 0.01. Two live games co-listed at the time of the check, both fee
schedules fetched, zero blocks.

---

## 2026-09-02 — P0b and P1: the vocabulary, then capture and replay

**P0b.** `kernel/schema.py` carries `OpportunityStatus`, `ExecutionState`, `FillState`, `Mode`;
`Book` carries `source`, `server_utc`, `received_mono`; `NormMarket.exhaustive: bool` became
`proof`; the period vocabulary is `"game"` everywhere. `nodes/opportunity/status.py` classifies
every evaluation; both grids write the enum. `DISCOVERED` (positive, under the hurdle) and
`BLOCKED_FEES` (positive gross, fee-net ≤ 0) are now visible where the table used to say
`NO_EDGE`.

**P1.** `nodes/capture` writes the raw text of every WebSocket frame, before parse, hour-rotated
gzip JSONL under `/Volumes/Kilos/janus/frames/<venue>/`. Both stream loops stamp one receive time
per frame and hand it to the capture, to `handle()`, and — through `on_update(market_id, now)` —
to the poller, so `evaluated_utc` is the venue message's arrival time live and offline alike.
(Before this, the callback carried no time and the poller stamped wall clock.) `nodes/replay`
feeds captured frames into the same handlers, spawns pollers from the slate specs the supervisor
persisted (`events.spec_json`), writes through the same `nodes/opportunity.record_evaluation`,
and `compare()` diffs the rows against the live table. GATE step 4 is a command now.

---

## 2026-09-02 — P2: the market-data layer as the spec describes it

**Provenance.** `Book` and `BookReplica` carry `source` (`ws`/`rest`), `server_utc` (Kalshi delta
`ts_ms`, Polymarket event `timestamp`, else None) and `received_mono`. One receive time per frame
feeds capture, `handle()`, the replica and the poller.

**Sequence per sid.** Every Kalshi frame carries `sid`; the gap check is keyed on it. The old
socket-wide counter could not see a gap once a second `subscribe` had opened a second sid — which
the supervisor caused on every slate change. Probed live: `update_subscription` adds/removes
markets on the existing sid, its `ok` consumes a seq, and the added market's snapshot lands on the
same sid. The run loop now subscribes once and diffs; only a gap tears the subscription down.

**The clock.** `ClockMonitor` per socket (venue stamps run 30–70 ms ahead of local receipt);
seconds of skew halt every poller with `CLOCK_UNHEALTHY`. Socket health rows land in
`socket_health` on the report tick.

**The REST backstop.** `nodes/stream_polymarket/reconcile.py` gives `BookReplica.reconcile` its
first production caller: quiet, SYNCED replicas past half their unverified budget are fetched and
reconciled; disagreement adopts REST and reports. REST-sourced books get a stricter freshness bound.

**The NO ladder** is in the streaming lane: each outcome gets a `kalshi_no` replica on the other
market's ticker, offered as extra depth, never required. `GamePoller.registrations()` is the one
definition of what a game is priced from; supervisor and replay both use it.

`depth_truncated` is set on a Kalshi REST ladder as long as the request.

---

## 2026-09-03 — P3: settlement equivalence as a proof, priced from a measurement

`nodes/settle_wedge` (new). Both venues' rules text is harvested per game and hashed twice: the
text as served (the audit trail) and the text with participants, dates and times stripped (the
template a human has reviewed). Reviewed templates and, per pair of templates, a verdict on all
twelve settlement dimensions live in `policy.py`. `certify()` mints `SettlementEquivalence`;
`certify_cover()` composes it with the exhaustiveness proof into `CoverProof`, which `nodes/cover`
now requires and which supplies the settlement-risk reserve inside every cost.

**The MLB wedge, measured.** Kalshi stays open only if a makeup finishes within two days and
otherwise resolves to a fair price; Polymarket stays open until the game is completed and
resolves a cancellation 50-50. Ledger **L26** (descriptive, pre-registered): 2,100 regular-season
games, 27 postponed, **10 made up more than two days later (0.476%, exact)**, **0 cancelled**.
Those two rates are the evidence registry; a 0.70 Polymarket favourite now reserves ~0.67¢ per
contract. NFL and NHL block at `TEMPLATE_UNKNOWN` until their Polymarket game text exists and
is reviewed.

`nodes/match_sports` constructs the kernel's `CanonicalKey` and joins on it, recording key
provenance per venue. Discovery carries the rules text in every spec and records the settlement
and equivalence tables; the supervisor and the replay certify from the same words.

---

## 2026-09-03 — P5: the risk manager, before any adapter exists

`nodes/risk` (new). `RiskClearance` is the token every order adapter's `submit()` will require:
minted only by `clear()` after every fail-closed condition in spec §13 is checked in order (mode,
kill switches, breaker, clock, fee schedules, venue connectivity, book age, minimum profit and
return, balances, then the ledger's caps), single-use, expiring in half a second, carrying the
reservation it was cleared against and the sha of the limits it was cleared under. Limits live in
a checked-in `limits.toml`; absent is zero. Kill switches are files under `/Volumes/Kilos/janus/kill/`
in five scopes. The daily realized-loss breaker latches across restarts and latches the `live`
switch; an UNCONFIRMED fill makes the day's PnL unknown, and unknown is closed. The exposure
ledger reserves before submission, releases only on both-venue reconciliation, journals to
`capital_reservations`, and reloads open reservations at start. The mode gate decides once:
`LIVE=1` in a non-live mode refuses to start; capital-risking modes need the signed override
with matching runner and limits shas, positive caps and an unexpired date. The watchdog gained
three risk alarms — kill file present, breaker latched, reservation unreconciled too long — each
demonstrated firing in its selftest.

---

## 2026-09-03 — P4: the total-cost model and the opportunity record

`nodes/cover`: fees over one fill per ladder level actually consumed; a size below a leg's
venue minimum order is not a cover (`below_min_order`); `Leg` carries the venue's order limits,
which discovery reads from Gamma and the poller passes through. `frontier()` takes balances,
fixed costs and a slippage term with a `slippage_modelled` label that stays False — capping the
mode at PAPER — until the buffer is measured from captured frames under a registered row.

`nodes/opportunity`: `thresholds.py` (discovery gross edge > 0; execution locked return ≥ 1% and
net profit ≥ $0.50, as importable constants), `opportunity.py` (the record, the allowed-transition
table, `opportunities` / `opportunity_transitions` / `frontiers` with the priced books kept when
the edge goes away). The supervisor and the replay both write through it. The fee registry pins
are re-verified to 2026-09-02 with what the venues reported.

---

## 2026-09-03 — P6: the order path, disarmed by construction

`kernel/execution_protocol.py` is the contract: `OrderRequest`, the three-way `Ack`/`OrderState`
(FILLED / PARTIAL / UNFILLED as the venue says, UNCONFIRMED when it did not, REJECTED when it
refused), `FillRecord` with a venue-final flag, `Balance`, and the `ExecutionVenue` Protocol whose
`submit()` takes a `RiskClearance` and consumes it. `nodes/execution` holds the shared journal
(a row before the wire; duplicate client ids refused; `venue_fills` is the breaker's FIFO), the
gate, `PaperVenue` (fills against the priced book) and `RefusingVenue` (SHADOW). `nodes/exec_kalshi`
signs REST the way the socket does (verified read-only against production), speaks the v2 order
API in YES terms (buying NO is an ask at 1 − price), and recovers an unanswered POST by client id
rather than resubmitting. `nodes/exec_polymarket` treats every outcome as its own token, calls a
matched FOK FILLED-but-settlement-pending until the trade is CONFIRMED on-chain, and delegates
signing to `py_clob_client` through a lazily imported transport that names the install step when
absent; the wallet key is a separate 600-mode file. Nothing runs below DEMO on Kalshi or
LIMITED_LIVE on Polymarket, and nothing has been sent to either venue.

---

## 2026-09-03 — P7: the coordinator, and reconciliation before release

`nodes/execute`: `plan_from_cover` fixes the leg order — Polymarket first as a FOK at the walked
limit, Kalshi as an IOC hedge for exactly what leg A filled, at a limit derived from what leg A
paid — and `Coordinator.execute` runs DETECTED → … → HEDGED over two `ExecutionVenue`s and one
`RiskClearance`, persisting every transition with the priced books. An UNCONFIRMED leg is polled
and never resubmitted; whatever is unhedged at the deadline is recorded and the reservation is
kept; a kill switch or disconnect before leg A aborts and releases; a hedge book above the limit
is `HEDGE_SLIPPAGE_EXCEEDED`, not a chase. `venues.py` is the one place adapters are chosen by
mode. `nodes/reconcile` resolves UNCONFIRMED orders through `status()`, ingests fills with their
final flag, compares charged fees with the pinned curve (an excess is a STOP), and settles each
leg against its own venue's result into the breaker's FIFO; capital is releasable only when no
leg is UNCONFIRMED. The paper venue now consumes liquidity it fills. `grids/live_stream` takes
`--mode`, resolved once by the risk gate; PAPER_EXECUTION runs the whole machine against live
books; real-order modes are refused by the grid until P8/P11.

---

## 2026-09-03 — P8 (part): offline execution and settlement ingestion

`nodes/replay` in `OFFLINE_REPLAY` runs the paper coordinator over captured books on the
captured clock, producing a reproducible execution record; `nodes/reconcile/results.py` reads
each venue's own settlement result (Kalshi `result` once settled; Gamma `outcomePrices` once
closed, 50-50 excluded) for `settle()`. The mode vocabulary names the one exception: OFFLINE_REPLAY
ranks lowest yet drives paper venues. Verified live: `grids/live_stream --mode PAPER_EXECUTION`
constructs the gate, venues, ledger and coordinator against real books; `LIVE=1` in that mode is
refused at start.

---

## 2026-09-03 — P9: the registry as the spec describes it

`nodes/discovery`: a 48-hour rolling universe (`universe`), one priority tier per game in the
spec's order (`tier_of`: live, starting soon, newborn, recently listed, closing soon, long term;
newborn and recently-listed are dated from the registry's own `first_seen`), the tier carried on
the slate spec and the `events` row, and `registry_health` (no co-listed game for a day in
season is a discovery failure, not a quiet slate), wired into the watchdog with a firing test.
`grids/live_stream` reports the tier counts and the box's wake/drain state from `nodes/slate` on
every slate rebuild. `BATTERY.md` lists each pre-capital item with who has to run it.

---

## 2026-09-03 — the operator's list, shortened

Main carries the v1 build and `com.janus.live-stream` runs it in SHADOW_LIVE with capture. Then:

- **NFL reviewed.** Both venues list NFL game markets now. Templates harvested verbatim and pinned;
  the pair's verdicts recorded. Both venues pay each side $0.50 on a tie, so a two-leg cover pays
  exactly $1 on a tie and the tie dimension is SAME; the NFL exhaustiveness rule is cited through
  those two clauses. Postponement beyond 48 h and cancellation are BOUNDED by `nfl.*` rates nobody
  has measured, so NFL now blocks at `EVIDENCE_UNMEASURED` (was `TEMPLATE_UNKNOWN`). The
  normaliser strips nicknames ("Patriots") as well as full names.
- **Slippage measured.** Ledger L27, from the frames captured so far: 2,152 samples over 8 tickers at
  the 3 s window, p95 adverse move one tick. Registered as `capacity.SLIPPAGE_PER_CONTRACT = 0.01`
  with `slippage_modelled=True`; the frontier charges it by default. Re-runnable.
- **Polymarket client installed** (`py-clob-client 0.34.6`, Homebrew site-packages). The transport
  refuses cleanly until `JANUS_PM_WALLET_KEY_PATH` names a 600-mode key file.
- **Real-order modes wired into the grid**: DEMO builds `nodes/exec_kalshi` on the demo host from
  `JANUS_KALSHI_DEMO_*`; LIMITED_LIVE/PRODUCTION build both real adapters. Each refuses to start
  with a named reason when its credentials are absent.
- Streams no longer connect with nothing to subscribe; the registry alarm is silent on a fresh table.

---

## 2026-09-03 — coverage first: the census, the registry, three-way soccer

The operator's scope is every competition and every live event both venues list; sports were
chosen because contract life is short and arbitrage may appear, a property of a market and not
of a sport. Built on the branch while the Kalshi proof waits for its armed run (the override pins
the runner sha, so nothing merges to main before that run).

- **The post-proof checklist as code.** `ops/proof_check.py` and `--check` on the proof script;
  the armed flow driven offline by a scripted venue in `ops/tests/test_proofs.py`, including the
  fee-above-pin latch, which had never fired in a test.
- **The co-listing census (ledger L28).** `nodes/discovery/census.py`: both venues enumerate
  themselves (Kalshi `/series?category=Sports`; Polymarket `/sports`, its own league table), events
  are joined on date and participants, competitions are scored by co-listed capacity at the touch
  over contract life. Run 1: 1,021 co-listed events across 81 competitions; the 48-hour window led
  by La Liga, college football (39 games), CS2, EPL, UFC, EFL Championship. Daily under
  `com.janus.census` for seven days; rank from the median.
- **The league registry as one table.** `nodes/entities/leagues.py`; the seed, the ESPN map, the
  grid default and the proof script read it. `enablement()` names what a league lacks (a cited rule,
  both templates, a measured rate per bounded dimension); MLB alone lacks nothing.
- **Three-way soccer.** epl, lal, bun, mls registered with three outcomes; IFAB Law 10.1 cited;
  Kalshi's per-competition texts and Polymarket's one soccer text pinned verbatim; the draw carried
  through the token map, both matchers, the exact join and the slate. Every soccer pair blocks at
  `EVIDENCE_UNMEASURED` on per-competition postponement and cancellation rates. UCL waits on a club
  being one entity across competitions. Execution stays two-leg.
- **NFL certifies.** Ledger L30 (L29 closed INCOMPLETE when its Friday gate met the scheduled São
  Paulo games): nflverse denominator, a cited table of every schedule change 2015–2025 excluding
  2020, strict >48 h, a completeness gate over Tue/Wed/Fri games. `nfl.postponed_gt48h_rate`
  0.001515 (4 of 2,640), `nfl.cancelled_rate` 0.000379 (1). NFL now lacks nothing.
- **College football registered** (FBS + FCS from ESPN, both texts pinned, NCAA no-tie rule cited);
  blocks on `cfb.*` rates.
- **Soccer certifies on a proxy.** Ledger L33: no free archive keeps a match's original kickoff
  (the survey is in `DESIGN.md` beside the row), so the rate is every match played more than 48 h
  after its round's core window over openfootball 2021-22 … 2024-25 — labelled FLOOR, and an
  over-count for cup-related moves. EPL 0.038, La Liga 0.014, Bundesliga 0.003; 0 cancellations.
  The soccer verdicts charge postponement once (suspended/abandoned ruled SAME as the same
  population). MLS stays blocked (no rounds, no source). `default_leagues()` is now MLB, NFL,
  EPL, La Liga, Bundesliga.
- **The generic verifier** (`nodes/match_generic`) recovered from `5eac384^`, reproducing the
  archived 51,306 verdicts; ledger L31 declares its precision bar before any label exists.
- **The Polymarket proof script** (`ops/polymarket_live_proof.py`), driven offline by a scripted CLOB.
- **College football certifies.** Ledger L32: ESPN completed games (FBS + FCS, 2019 and 2021–2025)
  as the denominator, a cited table of 28 schedule changes as the numerator. 6 of 9,529 moved
  more than 48 h, 17 cancelled; FLOOR for FCS. `default_leagues()` adds cfb.
- **Kalshi exchange shards.** The first armed proof was refused by the venue: `user_not_found`,
  because baseball lives on exchange shard 3 since 2026-08-24 and collateral is per shard. The
  adapter now reads each market's `exchange_index` once and sends it (or `-1`, auto-route, never a
  silent 0); `balances_by_shard()` reads the breakdown; the proof refuses `SHARD_UNFUNDED` with the
  move command; `ops/kalshi_shards.py` shows and moves collateral (`--confirm` is the operator's).
- **The lane watches the enabled set.** `--leagues enabled` resolves to `default_leagues()`; the
  plist uses it with a six-hour pre-game horizon instead of a stale five-league list.
- **Batch 2 of soccer.** Eight more competitions registered with their Kalshi texts pinned verbatim
  (EFL Championship, EFL League One, Serie A, Ligue 1, Eredivisie, Primeira Liga, Scottish
  Premiership, Belgian Pro League), Gamma events pulled by tag id where the slug is not the sport
  code. L35 measures the Championship, League One and Serie A with L33's proxy (FLOOR); the other
  five have no openfootball archive and block by name. `default_leagues()` is nine leagues.

## 2026-09-03 (night) — the lane was flapping, and the watchdog could not see it

Found on taking the handoff. `python3 ops/watchdog.py` said "all registered jobs healthy" while
both sockets reconnected five to six times a minute (eighteen to twenty a minute for two hours in
the afternoon). Nothing crashed, so nothing alerted.

- **The opportunity state machine could not move between blocks.** `TRANSITIONS` was built by
  reading itself mid-loop, so `BLOCKED_MATCH` (the first block, and the default for any unknown
  refusal) could reach no other block. A disconnect turns every evaluation `NOT_SYNCED`, the store
  tried `BLOCKED_MATCH -> BLOCKED_STALE`, `IllegalTransition` escaped the socket callback, the
  transport's blanket handler tore the socket down, resubscribed, and the first frame raised
  again. 3,302 such lines today. The block set is now fixed before the loop; every block reaches
  every other.
- **A record error can no longer reach the socket.** The supervisor's callback runs inside the
  venue's receive loop; it now catches, counts per (game, exception) and says so once, the same
  doctrine `_execute` already had. A reconnect now also counts in the stream's `errors`, so
  `socket_health.errors` climbs with it.
- **Capacity was never sized.** The grid called `frontier(exhaustive=...)`; the keyword is
  `proof=`. Every `PROFITABLE_UNEXECUTED` print today ended `(capacity failed: TypeError)` and no
  frontier row was written. Fixed; the size frontier lands beside the record again.
- **The lane now honours the arming override's caps.** `resolve_mode()` returned them and the
  grid dropped them; only the proof scripts checked `CAP_STAKE`. `clear()` refuses a
  capital-risking order without caps (`NO_CAPS`), beyond the stake (`CAP_STAKE`), beyond the
  contracts (`CAP_CONTRACTS`), and beyond the day (`CAP_DAY_NOTIONAL`, from the ledger's
  reservations since 00:00 UTC, released or not). PAPER ignores caps. Not changed:
  `nodes/risk/limits.toml` lists no per-league cap for cfb or any soccer league, so the ledger
  refuses those at `LEAGUE_EXPOSURE` until the operator adds rows.
- **Two socket alarms in the watchdog**, both demonstrated firing in `--selftest`:
  `SOCKET_FLAPPING` (five or more reconnects or connect flips over the last fifteen health rows)
  and `SOCKET_ERROR` (the last error names one of our own exception classes and the socket was
  seen down). Against tonight's live store the second fires on both venues.
- **Reconciled evaluations were being lost.** Once the socket callback stopped swallowing
  exceptions into the transport, the restarted lane printed `[record] … ProgrammingError: SQLite
  objects created in a thread can only be used in that same thread` for nine games in its first
  minute: the Polymarket REST reconciler ran its whole pass in a worker thread, callbacks included,
  so every evaluation a REST reconcile triggered died at the store. The pass is now two halves:
  the fetch in the worker, the adoption and the callback on the event loop.
- **L36, the recorded cover-cost distribution**, registered and run once (`nodes/cover_cost`,
  `research/sports/2026-09-04_cover-cost-distribution`). BLOCKED_STALE holds most of the dwell in
  every cell; `kalshi:HEARTBEAT_LOST` alone is 72% of in-play college football, which says the
  Kalshi replica's heartbeat bound is wrong for a quiet market, not that the market is stale.
  All 19 profitable prints are SUSPECT; the forward paper row's n is 30 by declaration.

## 2026-09-04 — the Kalshi proof filled, and two things it proved were wrong

The operator's armed run (`proofs/kalshi_20260904T000452Z.json`, MIA @ KC, 2 contracts at 0.35)
filled and reconciled to the balance. Its checklist failed twice, and both failures were ours.

- **The fee pin was half the venue's charge.** KXMLBGAME reports `quadratic_with_maker_fees` with
  `fee_multiplier 0.5` (a scheduled series fee change since 2026-08-07, `GET /series/fee_changes`),
  and the model applied the multiplier to the taker coefficient. The venue charged exactly
  0.07 × 2 × 0.35 × 0.65 = $0.031900: the full coefficient, kept to the hundredth of a cent. The
  proof STOPped on `FEE_ABOVE_PIN` and latched `kill/live`, as designed. Re-pinned from the fill
  as a frozen fixture (`nodes/fees/tests/fixtures/kalshi_fill_20260904_KXMLBGAME.json`): for that
  fee type the taker coefficient is unscaled and the order fee is ceil'd at $0.0001; the maker side
  is unverified and pinned conservatively at the unscaled 0.0175; plain `quadratic` is unchanged.
  Consequence: every Kalshi sports leg the lane priced before this carried half its real fee, so
  every recorded cover cost on a Kalshi taker leg understates by 0.035 × P × (1−P) per contract
  (about 0.8¢ at the money). L36's first run carries that; its next run will not.
- **The resting bid was never cancelled.** The adapter's DELETE went bare, the venue looked on
  shard 0, answered 404, and the adapter swallowed the 404. The bid rested on shard 3 the whole
  time. Cancels (and `cancel_all`) now carry the market's `exchange_index`, or auto-route by
  ticker when the shard is unreadable; a 404 lands in `last_error`; `ops/kalshi_cancel_all.py` is
  the operator's hand tool for anything already resting.
- The Polymarket proof was refused `KILL_LIVE` because the Kalshi STOP had latched the switch;
  that is the ordering the gate asks for.
- **The proof's resting bid filled after all.** At 00:13Z, nine minutes after the file was
  written, someone hit the 0.25 bid the proof believed cancelled: 1 contract, maker, fee
  $0.0033 = 0.0175 × 0.25 × 0.75 — the maker coefficient is unscaled too, now in the fixture.
  The position is 3 contracts of KC YES. `--settle` now settles every venue fill on the proof's
  own orders, not the file's memory (`merge_venue_fills`), and the ledger's reservation follows.
- **L37, the Kalshi socket cadence** (`research/infra/2026-09-04_kalshi-socket-cadence`): Kalshi
  sends no heartbeat frames; the clean hour carried 915,247 deltas at a 1 ms median gap and still
  went silent ten times for 43–107 s, 13.2% of the hour past the 15 s bound. Every silence starts
  at the discovery pass, whose HTTP ran synchronously inside the event loop. **The bound stays;
  discovery moves off the loop**: `fetch_discovery()` / `fetch_watch()` in a worker thread,
  `apply_discovery()` / `apply_watch()` on the loop (the reconciler's shape). L36's HEARTBEAT_LOST
  dwell was the lane starving itself; the row re-runs after a clean hour.
- `[clock]` prints once per tick with the poller count, not once per poller.
- **The clock flip was the lane falling behind real time.** Checklist A1. Receive lag measured
  from the raw capture (received minus the venue's own stamp) was 10–20 s p50 in busy minutes on
  Kalshi and up to 85 s on Polymarket, both together, while the process used a fifth of a core:
  the Mac is starved (15 MB free, 5 of 6 GB swap, other agents, collectors) and every heavy job
  beside the lane, this session's test suites included, showed up as seconds of lag. The clock
  monitor was an unbounded EWMA that never forgot and was fed once per price change in a batch;
  it is now a 60 s windowed median, one sample per frame, re-arming after a quiet spell. The lane
  carries a loop probe (a 250 ms sleep's overshoot, `socket_health.loop_lag_s`, `loop` on the
  report line) and the halt names its cause: `HALT STALL 12.4s` (LOOP_STALLED) or
  `HALT CLOCK kalshi` (CLOCK_UNHEALTHY). Halting stays; it was right. L38 registered to measure
  the stall over 24 h beside L34. `ops/README.md` says what not to run beside the lane.
- After the A1 restart: a 9 s stall in the first minute (19 pollers spawning, 130 subscriptions),
  then stamps 14–42 s behind with the loop overshoot under 5 s — saturation, not blocking: ~3,000
  frames and ~3,400 evaluations a second in bursts. The halt names it. Coalescing evaluations is
  the next throughput item (CHECKLIST A).
- **L39, tennis walkover rate**, registered and run: 0.7955% pooled (ATP 0.72%, WTA 0.88%) over
  26,398 main-draw matches 2021–2025. Jeff Sackmann's repositories were gone from GitHub on
  2026-09-04; the same layout is frozen from a live ATP database and a WTA fork, commits pinned.
  The delay rate has no backward source (files carry tournament starts, never match dates) and
  waits on a forward collector; tennis still blocks by name.

## 2026-09-04 (night) — coalescing, three-way soccer as two legs, and the tennis collector

- **Coalescing.** The poller prices a game at most once per 200 ms on quiet books (the frame's
  receive time, so replay reproduces it); a replica state change or the 15 s heartbeat still
  prices on its frame. Live: ~2,000 evaluations a minute where there were ~250,000, loop lag
  0.1 s. Captures before `f0bcef5` replay to different rows (nodes/replay/README.md).
- **Three-way soccer executes as two legs.** A `Leg` now carries `covers`, the proven outcomes it
  pays on; `price_combination` checks that a cover's legs partition the proven outcome set
  (`outcome_set_not_proven_exhaustive` was declared in 2026-08 and never used; it is now); the
  settlement enumeration runs over outcomes, not legs. Discovery carries the NO token of each
  team market (`polymarket_no`; never the draw market), the poller keeps a replica on it and files
  its leg under the compound key of the outcomes it covers, and `best_cover` prices every shape
  whose keys partition the set: {home, draw, away} as three legs or {home} + {draw|away} as two.
  Plan and coordinator are untouched: the NO leg is a `buy_yes` of the NO token, Polymarket
  leads FOK, Kalshi hedges IOC. Reconcile pays a `:NO` leg on either venue when its YES twin
  loses. The settlement buffer still charges the NO leg against the cancellation state in which
  it wins (conservative, named in `CoverProof.settlement_buffer`). Frozen: a real EPL event with
  both token ids per market.
- **Polymarket keep-alive at 4 s.** At 10.0 s, the venue's own limit, a quiet feed (eight late
  games at 03:00Z) dropped the socket every 30 s with "no close frame"; busy feeds had hidden it.
- **The tennis settlement collector** (`nodes/watch_settle`): the capture-only watchlist keeps its
  events, the lane records each Polymarket event's first-seen start (immutable; the venue rewrites
  it in place when a match moves), and `com.janus.watch-settle` resolves them daily at Gamma:
  winner, HALF (0.5/0.5), or open. Writes land in one retried transaction: the live lane holds a
  write transaction between report ticks and the first run hit `database is locked`. F4 registers
  once the first rows resolve. 86 rows after the first pass, mostly ITF.
- **Polymarket still drops the capture socket every ~30 s at night**, ping fix or not. Probed
  read-only: a socket on the eight live games' tokens stays up; one on the 72 tennis capture
  tokens is dropped by the venue after 20–30 s; closed markets alone do not do it; the tokens of
  matches already under way do. Bisection in progress; the reconnect is clean and the slate's
  own books resync within a second, so this costs capture continuity on tennis, not pricing.
- **F3's first cleared cover, and the settlement pass it needed.** At 03:05:41Z the paper lane
  cleared and paper-hedged STL @ LAD at q=100 (Polymarket LAD YES 0.45 + Kalshi NO on LAD 0.50,
  cost 0.9744, N_max 625). Nothing then settled a hedged execution against the game's result or
  released its capital: the reservation sat open and the watchdog said UNRECONCILED_TOO_LONG.
  `nodes/reconcile/settle_executions` now runs in the lane every five minutes (PAPER and above):
  finished games' executions, each venue's own result (Kalshi per ticker, Polymarket per moneyline
  market, three-way included), `reconcile.settle` over the recorded orders, release when every leg
  is final, SETTLED -> RECONCILED on the execution and the opportunity, one `execution_settlements`
  row with the realized PnL. Network in a worker, state on the loop. Paper and real settle alike.

## 2026-09-05 — F3 stops itself, the lane is rebuilt around what it exposed, tennis enables, soccer spawns

- **The other trees' work committed.** The previous agent's L36 and L37 results (the files
  `9790176` described), the tennis resolver's three runs, census run 3, and the infra agent's IAM
  files (the agent trust drops its MFA-age condition; committed as written at the operator's
  decision).
- **F3 STOPPED by its own criterion 2.** Execution `69852b86` (MIL @ CIN, 00:49:35Z, q=100) left
  35.82 contracts unhedged after three IOC attempts. Cause: `plan.hedge_limit()` returned the
  VWAP *budget* (1/1.01 − fee − leg A = 0.8452) and the coordinator sent it as the IOC's
  per-level limit; the pricer had walked the Kalshi ladder to 0.85. Now the limit is the walked
  level less any leg-A overpay, floored to the tick; the budget is recorded beside every attempt
  and a hedge averaging above it is labelled ABOVE_BUDGET. Fixture `MIL_CIN_2026_09_04`.
- **Holding failures settle.** PARTIAL_FILL, HEDGE_SLIPPAGE_EXCEEDED and UNKNOWN_PROVIDER_STATE
  are no longer terminal: the settlement pass marks the hedged part as a cover and the rest at the
  venue's result (`kind`, `hedged_contracts`, `unhedged_contracts`, `cover_usd`, `directional_usd`)
  and releases capital. MIL @ CIN settled live at −$2.73 (cover +$1.93, directional −$4.66).
- **Execution transitions persist.** `OpportunityStore.move()` writes the row the coordinator
  never did; `load()` rehydrates after a restart. F3's `cleared_cover` predicate had counted zero.
- **Paper fills carry the pinned fee.** Every paper order before today recorded fee_usd 0.0.
- **The lane died of a SIGBUS** (exit 138) at 03:35:05Z after 24 h — the host paging (63 MB free,
  5.5 of 7 GB swap; three unrelated Python processes within 100 s) — and launchd restarted it in
  1 s with no alarm. `SIGNAL_EXIT` now reports a daemon's signal death inside 24 h even after a
  restart; `UNHEDGED_POSITION` alarms at once on a holding failure. Both fire in `--selftest`.
- **Soccer never spawned.** LIV @ IPS and KOE @ VFB were co-listed all of 2026-09-04 and blocked at
  TEMPLATE_UNKNOWN: Polymarket's soccer description is now V2 without its 24-hour no-data sentence
  (hash `7580dcecfba14bc3`). The reason lived in a dict; now `[spawn-blocked]` prints once per game
  and the reason lands on `events.block_reason`. V3 registered from the lane's own harvested text
  with V1/V2's verdicts. On the restart all ten co-listed soccer games spawned.
- **Risk limits** (operator decision): paper caps for cfb, the six soccer leagues and both tennis
  tours; six simultaneous events (three held covers had refused every new one at MAX_EVENTS).
  The override's `limits_sha` moved; it must be regenerated before any armed run.
- **F5 registered** at n = 37 (L36's third run: 127 in-play clean actionable rows) and the lane
  restarted at 07:53Z on eleven leagues.
- **F4 registered; tennis enables.** `tennis.delayed_gt7d_rate` is the forward row's one-sided 95%
  upper bound (0 of 42 → 0.0714) until n reaches 300, refreshed from the newest results file at
  import. The spec states it was written after the first two resolver runs.
- **L38 executed**: loop lag 0.6% past 5 s over the first 24 h, all in the first hours after the
  restart; the lane is prompt, the host is not.
- **L40 registered and run**: L36's SUSPECT clause fired on 335 of 336 prints under coalescing.
  L40 asks whether a replica THIS print was priced from faulted in the 60 s before it: 15 of 292
  clean (12 cfb in play, median 2.5%; 3 mlb). A priced book no recorded fault contradicts, not a
  fill.
- **L31's scorer** computes the registered bar (per-stratum rejection precision ≥ 0.95, 1/0
  labels) instead of the phase-1 gate it carried.
- **`nodes/watch_fd` and F6**: the football-data.org snapshotter, registered before any run,
  awaiting `FD_TOKEN`. **`ops/harvest_templates.py`**: step 3 of the unblock workflow as a tool.
- `grids/live_sports` and `nodes/slate` read the league registry instead of a six-league list;
  the slate has a duration for every registered league.
- **L27 re-run, registered 0.0400.** The first attempt died on the 03:00Z hour the SIGBUS cut mid-member (the capture reader now stops at a cut instead of raising). The full run: 32.1M delta instants over 326 tickers, p95 adverse move at 3 s = 4 ticks, four times the 8-ticker MLB pin. The row's rule is mechanical and the pin follows it; the consequence -- a 4¢ reserve prices out nearly every cover printed so far -- is stated in the ledger, and a stratified row is the next registration.

## 2026-09-07 — both execution proofs sent; Polymarket had changed underneath us

- **Kalshi proof, second run** (`proofs/kalshi_20260907T025629Z.json`, WSH @ LAD, 2 @ 0.78):
  fee charged 0.0241 = pinned to the hundredth of a cent, balance to the cent, resting bid
  cancelled (the venue processes a cancel asynchronously; the file first recorded the pre-cancel
  status, so both proof scripts now poll a cancel to finality and re-read it at settle). 6 of 6
  before settlement; settles after the game.
- **Polymarket proof, the venue's first real order** (`proofs/polymarket_20260907T044255Z.json`,
  FOK 5 @ 0.39): matched as **5.131577 @ 0.38** -- CLOB V2 fills a BUY by notional, more shares at
  a better price -- and the balance moved by 2.0104 = fills 1.95 + **exactly the pinned taker fee
  0.0604**, which the trade record reports as fee_rate_bps 0. 6 of 6 before settlement.
- **What was actually wrong with Polymarket, in order of discovery.** (1) `balance_usd()` called
  the client's balance endpoint without its params and swallowed the AttributeError into "balance
  could not be confirmed". (2) The venue replaced its exchange on 2026-04-28 (CLOB V2: new
  contracts, EIP-712 domain v2, no fee/nonce/taker order fields) and its collateral (**pUSD**
  `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB`, not USDC.e); the V1 client still answered reads and
  reported the operator's collateral as 0.00 while the account held 95.60 pUSD; V1-signed orders
  are refused. `PyClobTransport` now wraps `py_clob_client_v2`. (3) The operator's account is a
  post-May **Deposit Wallet** (the app shows its address as "for API use only"); the exchange
  reports its balance only under **signature type 3** (EIP-1271), zero under 0/1/2. The
  credentials env now says 3. (4) A matched ack is UNCONFIRMED until status() gives the venue's
  size (the coordinator would otherwise under-hedge by the price improvement); a taker fill the
  venue reports without a fee carries the pinned fee, labelled.
- **The key file was overwritten** by a `pbpaste > pm_wallet.key` the agent asked the operator to
  run; the clipboard held other text. The key was re-exported from Polymarket (reveal.magic.link)
  and stored through `ops/set_pm_key.py` (hidden prompt or `--from-clipboard`, validated, mode
  600, prints only the address). It controls the same signer as before; nothing was lost. A key
  was also pasted into the chat once and should be rotated after the pilot.
- `ops/proof_target.py` prints the two proof commands with real tickers and slugs filled in, so a
  placeholder never reaches the shell again (two armed runs died on `<ticker>`).
- The lane: F5 at 32 of 37 hedged covers (all settled positive on paper, +$41.73), the first live
  three-way soccer covers among them; a second SIGBUS at 02:19Z (host paging), restarted by launchd
  and reported by SIGNAL_EXIT; Kalshi cfb template V2 (neutral-site wording) registered.
- **Both proofs settled, 7 of 7 each** (05:55Z): Kalshi +$0.4159 on the Dodgers' win (2 × 0.22 − 0.0241), Polymarket +$3.1816 (5.131577 × 0.62 − 0.0604), reservations released. GATE_TO_LIVE step 8 is complete on both venues.
- **The Ashburn box launched** (05:45Z, `i-0c86891ee306de0b8`) as the pilot's host after the read-only survey's fixes; cloud-init, L34 and the box's paper lane (F7) follow in this entry's successor.
- **Box bring-up**: the first boot had no AWS CLI on the image and cloned nothing (fixed: snap aws-cli, fatal on an empty pointer); the re-bootstrap through SSM cloned `24611d1`, materialised the secrets into `/run/janus`, and the suite is green on the box once `numpy`/`pandas` are in the venv (pinned now; the meta test no longer scans the venv inside the tree).
- **L34 executed**, same hour on both hosts: Kalshi 184 → 51 ms p50, CLOB 309 → 184 ms, CLOB 200 from the box. Bar (half) met on Kalshi, not on the CLOB. **OBSERVATION_HOST**; the box runs the paper series F7.
- **The box's paper lane started** at 06:04Z (`[mode] PAPER_EXECUTION`, both sockets connected, loop 0.1 s): ledger F7's clock runs. The Mac's F5 continues until the 48 h cutover decision.

## 2026-09-07 — why tennis never priced, why Serie A never joined, and why quiet books were "stale"

Three refusals of good books, found by reading the F5 window per league instead of in aggregate.
None changes the arbitrage math; each changes what the lane is allowed to price.

- **A late replica never synced.** Kalshi snapshots a market once per subscription and the run
  loop adds only what is new. Tennis tickers sit on the capture watchlist from discovery, hours
  before the match, so the poller's replica registered at first serve waited `NOT_SYNCED` for a
  reconnect that never came: every tennis match that went live after a lane start (25,563
  evaluations across F5), while the matches present at a start priced. `KalshiStream.register`
  now seeds a replica from the stream's own folded book (that snapshot plus every sequence-checked
  delta since) at the subscription's current seq; never after a gap, a resubscribe or on a fresh
  socket. `stats()["seeded"]` counts it. The Polymarket stream never had the bug: it resubscribes
  on every register.
- **Quiet is not stale.** `BookReplica.check` measured its age bound from the last mutation. A
  Kalshi book that has not moved for 5 s on a socket carrying 250 frames a second is the venue's
  book as of the last frame, and the replica's own README said so ("liveness is not freshness")
  while the gate did the opposite. In F5 that was 331,743 college-football and 4,836 tennis
  evaluations refused `STALE`. `as_of()` is the latest of the last mutation, the last verification
  and the last sign of life; the bound runs from there, `Book.fetched_utc` carries it, and the hard
  bounds stay (`HEARTBEAT_LOST` at 15 s, `UNVERIFIED_TOO_LONG` at 30 s on Polymarket, a REST-sourced
  ladder as old as its fetch). Ledger F5 and F7 carry the era note.
- **Serie A pointed at the futures tag.** Gamma's `/sports` gives Serie A `primaryTagId` 100618,
  whose events are champion / top scorer / relegation with no teams; the games live under 101962
  (`sea`). Four days of zero Polymarket events with no reason: a teamless event is skipped before
  the matcher counts it, and the matcher's reasons were computed every pass and read by nothing.
  Registry fixed, Serie A's 20 Polymarket cross-references seeded, Como aliased by hand
  (`Como 1907` on Polymarket, `Como` on ESPN), and the lane now prints `[discovery] <league>: N
  games, 0 pairs; ... reasons=...` for any league with games and no pair.
- **`seed <league>` keeps the other leagues.** It rewrote every generated CSV with the one league
  asked for; a league-scoped run now merges.
- Not a current bug, recorded because the log made it look like one: the 3,435 `IllegalTransition`
  reconnects in the lane log are all from 2026-09-03 games, fixed at `acb020d` that day.

## 2026-09-07 — the operator moves the box to small real fills; two holes in the order path closed first

- **The decision.** Asked "shouldn't we change that? if our objective is truly testing the strat we
  should focus on actually filling contracts", and offered the choice, the operator answered
  "You approve; I run all three": the GATE row, the arming override on the box and the switch to
  LIMITED_LIVE are the agent's to execute, at $12 per order, 25 contracts, $60 a day, breaker $25.
  `GATE_TO_LIVE.md` carries the dated row in the operator's words; ledger F8 is the series.
- **Two real-money holes**, found by a review of the frame-to-order path before arming, fixed:
  (1) `Coordinator._settle_ack` read a NON-final `UNFILLED` status (Polymarket `DELAYED`, a failed
  poll) as "no position" and released the reservation while the venue could still fill; a status
  is an answer only when final, filled, or rejected, and the first poll is immediate (the blind
  100 ms before it is gone). (2) The clearance's hedge window ran from the mint while the
  coordinator's ran from leg A's settle, so a slow settle spent the token's window and every hedge
  came back `CLEARANCE_SPENT` with leg A filled; and `HEDGE_UNAVAILABLE` was terminal, so the
  position was never settled and nothing alarmed. Now `RiskClearance.arm_hedge()` starts the one
  window when leg A is known, the coordinator uses it, and `HEDGE_UNAVAILABLE` holds a position.
- **The path is instrumented.** Every execution carries per-stage stamps (`executions.stages_json`,
  a `[latency]` line per execution, `ops/latency_report.py` for p50/p95 per stage) so the next cuts
  are made where the measurement points. The review's map: the order path is synchronous inside
  the websocket receive coroutine; about 1.4 to 1.7 s frame to hedge ack on the Mac, almost none of
  it Python compute. Balances were fetched twice per venue before every clearance (fixed: once),
  Kalshi's transport opens a fresh TLS connection per call, a cold market pays lookups, the
  coalescing gate drops events. L27 puts the Kalshi ask's p95 move at 2c inside 1 s and 4c at
  3 s: a hedge inside a second is worth 2c per contract of reserve. That is the answer to the
  operator's C++ question: the waits are ours and in Python; the venues' server time is not
  reachable from any language. Cuts follow in the reviewed order (balances cached, pre-warm at
  spawn, a pooled Kalshi client, then the store's commit cadence).
- Polymarket orders post with `defer_exec=True`: the library no longer polls settlement hashes
  inside the POST; `fills()` reads the confirmed trades later.

## 2026-09-07 — the coverage audit: every unpaired event says why, by name

The operator: "these should be discoverable; I don't want to need to tell you about these"
(Cagliari v Lecce in play, Getafe v Celta at kickoff, Swiatek v Zheng unpaired for hours). The
matcher had always computed a named reason for every venue market it could not pair
(`near_miss`); the live lane returned only its length and nothing read it; the `[discovery]`
line fired only for a league with zero pairs; the census's "unmatched" was a per-competition
count from a separate join. GATE step 1 promised "every unmatched game in a named reason
bucket; zero silent drops"; in the lane they were counted and discarded.

- **Every in-window game that did not pair carries `UNPAIRED:kalshi=<found|missing>,
  polymarket=<found|missing>`** in `events.block_reason` (a transition like any other), from the
  games each venue's matcher did match (`kalshi_games` / `polymarket_games` in the per-league
  stats). The near-miss list itself now reaches the supervisor with the venue's own labels and
  the candidate games.
- **The lane says it once, by name**: `[unpaired] SWIATEK V ZHEN (wta) 15:30Z kalshi=missing,
  polymarket=missing` and `[near-miss] wta kalshi KXWTAMATCH-26SEP06SWIZHE: entity_resolution
  (Iga Swiatek | Qinwen Zheng)`, each once per reason change; the league summary stays.
- **`ops/coverage_report.py`**: the census's independent join (its results now carry the event
  lists beside the counts: `co_listed_pairs_48h`, `unmatched_*_events_48h`) against the lane's
  events table — every event both venues list in an enabled league, covered or gap, with the
  lane's reason. The watchdog's **`COVERAGE_GAP`** fires for a gap inside the lane's window (3 h
  back, 6 h ahead), demonstrated in the selftest; `ops/box/status.sh` prints the games in play,
  the unpaired ones with reasons, and the counts.
- Reason hygiene on the way: the Polymarket side now splits `no_schedule_match` from
  `outside_window` like the Kalshi side (every tennis "schedule miss" today was a match past the
  window).

## 2026-09-07 — tennis pairs by the venues' own rosters; the series and the window the lane was missing

The per-league inventory (2026-09-07 ~17:05Z) found no pairing gap outside tennis and a whole one
inside it: 53 tennis matches in the window, 21 on Kalshi, 4 paired. The causes were identity,
series, and windows, not the join.

- **Identity.** No tennis alias table existed (`seed.py` kept only ESPN-sourced aliases), the
  xref tables were a roster snapshot (147 of 180 ATP and 110 of 126 WTA players on the day's slate
  absent; Swiatek had no row), and a Kalshi tennis xref needed the ticker suffix AND the full name
  to agree, which a 3-letter suffix never does. Now: `Resolver.add_player` mints an entity from a
  venue's live listing (name, abbreviation, "I. Surname", the venue id as an xref); `match_live`
  seeds every player Polymarket lists today BEFORE the Kalshi pass, so a Kalshi market's full-name
  label resolves to the same entity and its UUID is learned on first sight; the seeder writes
  venue-sourced aliases; doubles pairs are not players.
- **Series.** `League.kalshi_series_extra`: atp and wta own their Challenger series
  (`KXATPCHALLENGERMATCH`, `KXWTACHALLENGERMATCH`: 35 of 41 co-listed with Polymarket today);
  a new `itf` league row (`KXITFMATCH` + `KXITFWMATCH`, prefix `itf-`, 69 co-listed today) is
  registered and NOT enabled: its rules texts hash to templates the policy does not hold yet
  (`ops/harvest_templates.py --league itf`: Kalshi's ITF text differs from the tour text on the
  retirement clause; Polymarket's names the ITF as the source). Their review is the next commit.
- **Windows and paging.** The matchers pair against the 48 h universe (`UNIVERSE_HOURS`, defined
  and unused until now) while `select_live` still gates spawning; `pull_kalshi` follows the
  cursor and every series of the league (college football was cut at 200 events with no signal);
  Polymarket pulls page to the end (the tennis tag sat 38 events under the old cap).
- **Reason hygiene.** `teams_not_two`, `no_participant_market`, `other_league_under_shared_tag`,
  `doubles`, `slug_piece_too_long` are counted; Polymarket's `no_schedule_match` is split from
  `outside_window` like the Kalshi side.
- **The box's first actionable covers**, LAA @ BOS in play at 17:47Z: 25 and 100 contracts at a
  4.6 % locked return, refused `CAP_STAKE` by the override ($23.25 and $94 against $12), and the
  same books at 5 contracts held at DISCOVERED by the $0.10 floor once the pooled 4c slippage
  reserve is charged ($0.22 − $0.20). Each refusal had first fetched both venues' balances on the
  event loop; dozens a minute stalled it 5.6 s with 17 pollers live. The override caps and the
  profit floor are now checked before any round trip and said once per game and size. What
  unlocks the 5-contract size is L41's per-league reserve (running); what unlocks 25 is a cap the
  operator has not given.
## 2026-09-07 — the arm pins the code tree, is re-read while running, and has a kill that crosses hosts

- **Why.** The override pinned `git rev-parse HEAD` of the whole checkout and the gate compared it
  by string, so the first docs-only commit deployed to the box invalidated the arm and cost the
  operator two pastes (`write_override.sh`, `mode.sh LIMITED_LIVE`); `update.sh` restarted the
  lane by default, so a deploy under the LIMITED_LIVE drop-in left the unit crash-looping until
  it was re-signed. Worse, the mode was resolved once at start and the override never read again:
  an arm that expired under a running lane stopped nothing, and only the kill files were checked
  per clearance. No alarm existed for either. The box's kill files were local; `kill/all` on the
  Mac stopped nothing there. Offered the options, the operator chose: "Pin the code tree, one
  daily paste".
- **The pin is the executable tree.** `kernel/code_sha.code_tree_sha` hashes the git tree ids of
  `nodes`, `grids`, `kernel`, `ops/run_node.sh` and `ops/box/systemd` (a dirty tree is `"dirty"`,
  no git is `"unknown"`; the writer refuses both). The override carries `code_sha`; `runner_sha`
  (the whole HEAD) is still written and logged, for the record, and is no longer compared.
  `resolve_mode` refuses `OVERRIDE_CODE_SHA` on a mismatch and `OVERRIDE_INCOMPLETE` on an old
  file without the key. A commit to `README.md` no longer moves the pin; a commit under `nodes/`
  still does (`kernel/tests/test_code_sha.py` proves both against a throwaway repo).
- **The override is re-read every report tick.** `nodes/risk/gate.override_state` is the pure
  read; `Supervisor.check_arm()` calls it after `on_report_tick()`, and in a capital-risking mode
  an override that has expired, gone missing, or pins another tree or other limits sets
  `arm_stale`, prints `[arm] STALE <why>` once, and `_execute` refuses at the door (`ARM_STALE`,
  before any plan, balance call or clearance). Pricing continues; a matching override lifts it
  without a restart. The tree compared is the one the PROCESS runs (fixed at start), so between a
  release's re-sign and its restart the old lane refuses rather than trades under a pin for code
  it is not running.
- **Two alarms, both demonstrated firing.** `OVERRIDE_EXPIRING` (under 24 h left) and
  `OVERRIDE_STALE`, from `nodes/risk/health.override_alerts`, only where the box's systemd drop-in
  says `LIMITED_LIVE` (the Mac has no drop-in and stays quiet); `watchdog.selftest` drives both
  and the quiet cases (no drop-in, a paper drop-in, 48 h left and matching).
- **The cross-host kill.** `/janus/kill/all` and `/janus/kill/live` in SSM; `ops/box/kill.sh`
  sets or clears them from the Mac, `ops/box/kill_sync.py` (the box's watchdog job, guarded by
  `JANUS_HOST=box`) mirrors them into `/srv/janus/kill` with reason `ssm: ...` and removes only a
  file it latched. A breaker's or a human's file is never lifted from SSM.
- **The daily paste.** `ops/box/release.sh <sha>`: checkout without restart, re-sign at the F8 caps
  from `ops/box/arm_statement.txt`, restart under `LIMITED_LIVE`; refuses while a co-listed game
  is in play unless `--now`. `ops/box/update.sh` refuses to check out under a `LIMITED_LIVE`
  drop-in without `--no-restart`. `GATE_TO_LIVE.md` carries the dated amendment row.

## 2026-09-07 — a 10-contract rung, and a release that refuses only on money in motion

- The operator's rule for size: "as little as possible per event (which still makes them
  executable)". Under the $12 per-order cap only the 5-contract rung fits, and 5 contracts net
  under the $0.10 floor once the pooled 4c reserve is charged. `QUANTITIES` gains 10 (about $9.30
  per order at tonight's books; twice the net for the same reserve), in the lane and the replay
  harness together; F5 and F8 carry the era note. The floor stays: it is the fixed cost of two
  orders, two fees and two settlements. L41's per-league reserve is the other lever.
- `ops/box/release.sh` refused while any co-listed game was in play; with ITF enabled that is
  most of the day. It now refuses only with an execution in flight or an unhedged position on
  the box, and warns about games in play (their pollers' state is what a restart costs).
- Funding, the operator's: Kalshi shard 0 $247.86 (shard 3, the tennis shard, still $22.43);
  Polymarket read from the box at the time of the entry.

## 2026-09-07 — the box's first real order: Polymarket geoblocks the Ashburn host

At 18:45Z a 5-contract cover on ATL @ PHI cleared every check on the box and the Polymarket leg
came back **HTTP 403, "Trading restricted in your region"**. The CLOB serves reads to AWS Virginia
(L34's 200s) and refuses order entry from it. No order was placed, no money moved, the Kalshi hedge
was never sent. The proofs had run from the Mac, whose egress is Mexico City, where the CLOB
accepts orders.

- The adapter read the 403 as an ambiguous transport failure (UNCONFIRMED): the reservation was
  held, status was polled 31 times over 3.3 s, and the game sat EVENT_IN_FLIGHT. Now a CLOB answer
  of 400/401/403/404/422 is a definite REJECTED (`HTTP_<code>`, journaled as a reject, released);
  a 403 naming the region latches `PolymarketExecution.geoblocked`, and the lane refuses every
  cover cheaply (`VENUE_GEOBLOCKED`, said once) until a restart from a permitted host. A 5xx stays
  UNCONFIRMED: the venue may still have taken the order.
- The `[latency]` line of that execution, the first from the path's stamps on a real venue:
  frame→eval 1.25 ms, balances 141.6 ms (both venues, from the box), clearance 2.7 ms, leg A
  submit→ack 341 ms (the 403), 31 polls to the 3 s deadline.
- What it means: real two-leg execution cannot run from a US-hosted box. The Polymarket leg needs a
  host in a permitted jurisdiction; the Mac's (Mexico) is the one that has worked. The region of
  the next box is the operator's decision (CHANGELOG records the fact; NEXT.md the choice).
