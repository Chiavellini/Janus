# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-12 ~22:00Z, on `claude/hedge-ladder-speed-3b5042c`.

## Where it stands

**Trading is stopped and should stay stopped until the release below is pasted.** `kill/live` is
latched (the operator, ~19:30Z). The box is healthy and still runs `3b5042c`: **nothing from today
is deployed.** No open unhedged positions.

A three-way audit swept connectivity, opportunity detection, and execution/accounting against
`5b8cf11`. It found real money-path defects — including four in the L85 code written an hour
earlier, one of which would have stopped the lane trading outright. Rows **L88–L94** are registered
and green at **1,524 tests, zero skips**.

## What the sweep found and fixed

- **L85 corrected (four defects).** `clearance_ttl_ms` is 500 ms from the mint on the loop, and L85
  added a *second* REST read after L77's measured 187.7 ms one; sequential they would have spent the
  window and every send would have returned `CLEARANCE_SPENT`, which the grid backs off as a venue
  rejection. The reads now run concurrently and `confirm_budget_ms` records what is left. Also:
  `at_mono` had no lower bound (a pre-reboot monotonic stamp gives a *negative* age that passed an
  upper bound alone); `entry_book_trust_s` was never parsed from `limits.toml`, so its documented
  "0 disables" lever did not exist; and the skip compared a reading taken for the full planned hedge
  size against a send for whatever leg A actually left. Each pinned by a test that fails against the
  old condition — checked, not assumed.
- **L88, the phantom edge.** `status_for` had no lower bound on gross, so three-leg soccer/MLS covers
  summing to **0.31 against a $1 payout** published as 201 % returns. That is the operator's "the
  dashboard's raw is buggy", and they were right. `MIN_CREDIBLE_GROSS = 0.70`.
- **L89, a frozen book that reported itself fresh forever — and it was LIVE.** `unregister` was keyed
  by ticker with no owner, so a capture ticker ageing out took the *poller's* registration with it;
  the orphan kept the shared socket pulse, so `as_of()` read age 0 and `SYNCED` over a dead ladder,
  unreachable by both sweeps. The box runs without `--capture-series`, whose argparse default is the
  four tennis series plus the PM `tennis` tag — **exactly the leagues carrying the losses** (atp 5 of
  5 adverse, −$3.29). A frozen book priced against a live one manufactures the entire apparent edge.
- **L90** an undated leg escaped the staleness gate; **L91** a fill with no reported average was
  booked at $0.00/contract, re-opening the whole loss allowance; **L92** a zero-fill *state* was
  read as finality, releasing capital while a position could still fill and letting a second
  full-size execution open on the same game; **L94** a venue token claimed by two entities bound to
  one of them, which is a naked directional bet wearing a 40–50 % edge.
- **L93, the alarm that did not exist.** All ~33 watchdog conditions were operational; the first
  money signal was the daily breaker at −$25. `cover_pnl_alerts` now raises `COVERS_LOSING` and
  `HEDGE_ABOVE_BREAK_EVEN`. Checked against the box: last 10 real settled covers net **−$3.55**, 8
  losers, 6 above break-even — both fire.

## Now — the sequence, and it is not optional

1. **Operator pastes the release at measurement caps.** Small size is the point: a DJERE-shaped
   disaster costs cents instead of $2.50, and the slippage samples the reserve needs can only come
   from real fills.
   `JANUS_BOX_REGION=mx-central-1 JANUS_BOX_ID=i-0a8c073c72dcdae11 JANUS_ARM_CAPS="6 5 60 168" bash ops/box/release.sh <sha>`
   `ops/box/arm_statement.txt` must be edited to match those numbers first, or the release signs a
   statement that does not describe it.
2. **The restart re-latches `kill/live`** (the overfill acknowledgement still does not exist). Clear
   it once by hand. L87 means that should be the last time.
3. **Watch, read-only:** `ops/box/status.sh`, and `ops/slippage_report.py --hours 168 --rows` on the
   box. The three things that decide whether to step size back up: whether `atp` slippage stays at a
   5c median now that L89 is fixed (some of that "slippage" may have been the frozen book), whether
   `BOOK_MOVED` starts appearing on the hedge leg, and whether the margin column ever clears a cent.

## Still owed, in order

1. **The `as_of()` question.** L89 fixed the ownership bug; the deeper one stands. `as_of()` folds
   the shared socket pulse into per-market freshness, so `max_book_age_s` (5 s),
   `max_rest_book_age_s` (3 s) and the cover's `max_leg_age_s` are **inert for every streamed
   book** — on Kalshi there is no per-market freshness bound at all, and on Polymarket the real
   bound is `max_unverified_s` at 30 s. Changing it could stop the lane trading the moment the
   bounds start binding, so it wants its own row and its own release.
2. **The identity check behind L88.** The floor is arithmetic standing in for an identity test. The
   exhaustiveness proof is tautological in the live lane: `proof.outcome_ids` is minted from the
   same offers keys it is checked against, so it compares labels this code path invented and cannot
   see a wrong instrument behind a right label. The fix is a venue-independent outcome identity on
   `Leg`, asserted against the proof.
3. **`correct_fills` has no ratchet** (`guard._reconcile_execution`): a missing journal row can zero
   a real fill, after which `protect_existing` may buy the hedge a **second** time. Largest blast
   radius found; the audit marked reachability UNCERTAIN, so reproduce it in a test *before*
   changing behaviour.
4. **The slippage reserve.** Entry still charges nothing for the hedge moving. `ops/slippage_report.py`
   measures it and refuses a per-league number under 20 covers; no league qualifies yet. Charging it
   is a dated GATE row.
5. **The kill-latch on losing covers** — drafted at
   `research/exec/2026-09-12_pnl-latch-GATE-ROW-DRAFT.md`, needs the operator's N-of-M and signature.
6. **The overfill acknowledgement** (one order now, thanks to L87): freeze the venue evidence for
   `0429ef24…`, `--prepare`, dry run, then the operator's `--confirm`. Evidence must be committed
   *before* the release that carries it.

## Deferred from the sweep, each with file:line in the audit

Kalshi seq-gap holes (a regression is invisible, unsequenced frames unchecked, `sid=None` aliasing);
`unregister`+`register` in one pass leaving a market dark; one malformed `best_bid` tearing down the
whole PM socket (`float()` outside the try); the unbounded `kalshi_open_markets` cursor loop; the
REST reconciler adopting a ~3-minute-old ladder; `shard_of` blocking up to 62 s between clearance and
wire; `_hedge_capacity_ok` using the WS bound on a REST book; `UNWOUND` rows carrying unrealised P&L
into the breaker (latent while `unwind_enabled=false`); phase 1's walked ceiling never bounded by the
loss cap; sizing optimising against an unpadded price it will not pay; the three-way YES/NO index
binding; `PMQuadratic` ignoring `fee_exponent`; PM `socket_health.seq_gaps` NULL by construction;
`coordinator.py:531,564` swallowing a failed kill write where the guard records and retries one.

## Not now, deliberately

Spreads and totals (`STRATEGY_VERSION` is moneyline-only, and thinner books slip more while slippage
is the binding problem). Lowering the hurdle or widening caps — on these numbers that buys variance,
not profit.

## The question that actually matters

Whether the edge was ever real. L89 means some of the measured 5c "hedge slippage" on tennis may not
have been slippage at all but a dead Kalshi book quoting a world that had moved. The next twenty
small covers, read through `ops/slippage_report.py`, are what answer it.
