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
