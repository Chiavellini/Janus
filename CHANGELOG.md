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
