# GATE_TO_LIVE — the promotion sequence to real capital

> Pre-committed **before** any result exists, which is the only time such a sequence can be
> written honestly. Once a number is on the table, the temptation to adjust the bar is exactly
> what this file exists to prevent.

## The pre-commitment

**No Janus arm trades real money until every step below is satisfied in order.** A step may not
be skipped, reordered, or weakened. If a step fails, the arm stops — it does not get a softer bar.

Two clauses that make this binding rather than decorative:

- **Nothing here may be edited after a result is known.** Amendments must be appended as a dated
  entry in the log at the bottom, stating what changed, why, and what was already known. An
  unlogged edit invalidates the arm.
- **A gate fail is a STOP, not a retry.** Re-running a failed one-shot on the same population is
  forbidden. New evidence means *new data*, not a second look.

---

## The sequence

### Step 1 — Corpus (Phase 1)
Pair map built and **byte-identical on re-run**. ≥95% of expected windows matched across all
7 assets, with every unmatched window assigned an explicit reason bucket. Zero silent drops.

### Step 2 — Capture (Phase 2)
Collector passes a **72 h soak**: ≥98% capture of expected windows per asset, disk trajectory
inside budget, resumes cleanly from a mid-window kill with no gaps and no duplicates, and **every
alarm demonstrated firing against a fake target** (a monitor that has never emitted is untested —
Kilos found three silent monitor bugs this way on 2026-07-24).

### Step 3 — Seal the forward era
The Janus holdout era is declared in `NEXT.md`, its start timestamp recorded, and it becomes
unreadable. From that moment, reading outcomes from it requires the Step-6 ritual.

### Step 4 — Faithfulness
An offline parity check rebuilds **every** logged decision by *importing the live runner's own
constants* — never re-hardcoding them. Bar: **zero decision mismatches**. This is the check that
catches the class of bug where the study and the runner quietly disagree.

### Step 5 — Gates 1–4, pre-registered
Each of R1/R2/R3 carries its own `spec.yaml` written before the run and its own numbered
`snooping_ledger.md` row appended `PENDING` before the run. Required to pass:
- G1 anti-leak audit clean,
- G3 day-block permutation p below the BH threshold (`0.1/m`),
- G4 day-block CI **excluding zero at 2× fees**,
- and the BTC anchor reproduced digit-close before any new-asset number is read.

### Step 6 — Gate 5, the one-shot holdout
Fires **once**. Requires all of: an explicit user approval naming the holdout specifically in the
current conversation ("proceed" or "go ahead" does **not** count); a `PENDING` numbered ledger
row; `spec.yaml` with `holdout_touched: true`, `requires_user_approval: true`, and
`user_approved_by` filled with the verbatim approving message; and no pre-existing `results.json`.
Rehearse the full pipeline on spent data first — rehearsal is free, the spend is not.

### Step 7 — Forward paper
The arm runs shadow, structurally unable to post: credentials `unset` in the wrapper, and the loop
refuses to start if `LIVE=1` is present. Accrues until it has the power to say something — Kilos'
live basis arm reached n=23 with an MDE of $3.94/trade against a ~$0.25 edge, which answers
nothing. Decide the required n from a power calculation **before** starting, not after looking.

### Step 8 — Execution proof
Battery green. Kalshi demo round-trip proven end-to-end (place → poll → cancel → settle). One $5
live fill on each venue, reconciled against a wallet delta / statement, with the **charged fee
matching the pinned curve** in `nodes/fees/venue_costs.py`. A fee above the pinned curve is a STOP and a
re-pin, not a rounding note.

### Step 9 — Arming
A separate, explicit, human decision. Requires a signed override file recording: the verbatim
operator statement, sha pins of the runner and spec, the registered verdict as it actually stands
(including if it is a FAIL being knowingly overridden), hard caps (stake, day notional, wallet
funding), a latching realized-loss breaker, and an expiry date. Arming is never implied by a PASS.

---

## Standing safety requirements

These hold whenever anything is armed:

- **Kill files** — one for all trading, one for live only. The live kill latches automatically on
  the realized-loss breaker and requires a human reset.
- **Latching daily realized-loss breaker**, fed by a FIFO ledger that re-polls unconfirmed fills
  *before* computing the day's PnL.
- **Three-way fill taxonomy**: FILLED / UNFILLED / **UNCONFIRMED**. An unresolved or errored poll
  is *not* a no-fill. Collapsing them overstates PnL, blinds the breaker, and makes retries
  double-buy.
- **Single-flight per (market, window)**, persisted across restarts.
- **`cancel_all()` on SIGTERM.**
- **Own credentials** (`JANUS_*`), file mode 600, never committed, never shared with Kilos.
- **`nice -n 19`** on any heavy engine while a live loop is trading.

## Cross-venue additions (no precedent in Kilos — Janus is first)

The two-leg arm introduces failure modes single-venue execution does not have. Before any two-leg
capital:

1. **Leg-risk is measured, not assumed.** The per-asset rate at which BRTI and Chainlink settle
   the same window in *opposite* directions must be measured and its expected loss added to the
   cost model. Until then `pair_cost_cents(..., oracle_risk_modelled=False)` is the honest label.
2. **Partial-fill policy is pre-declared.** What happens when leg 1 fills and leg 2 does not is a
   decision made in advance and encoded, not improvised at runtime. An unhedged leg is a
   directional position that was never authorized.
3. **Cross-venue net exposure is accounted in one place**, not per venue.
4. **Settlement timing mismatch is handled.** The two venues do not credit at the same moment;
   capital availability on one side is not a proxy for the other.

---

## Amendment log

| Date | Change | What was already known |
|---|---|---|
| 2026-07-24 | Created at Phase 0, before any Janus result exists. | Nothing — zero Janus data collected. |
| 2026-09-02 | Sports equivalents for steps 1–8 defined below. No sports execution result exists; shadow evidence so far is a cover-cost distribution with no actionable observation and fees now known to have been overstated 2× on the Kalshi leg. | Best streamed cover cost 1.0020; tennis 0 actionable frontiers; stage 3 interim "prices diverge, the fee floor eats it". |

### 2026-09-02 amendment — the sports arm

Steps 1–6 above were written for the crypto two-leg (BRTI vs Chainlink, seven assets, R1–R3). The
sports arm keeps every step and every clause; only the nouns change. Appended, not edited.

- **Step 1, corpus** = the co-listed pair map from `nodes/discovery`, byte-identical on re-run,
  with every unmatched game in a named reason bucket (`INCOMPLETE_EXACT_TWO_OUTCOME_MATCH`,
  `PM_TOKEN_RESOLUTION`, `FEE_SCHEDULE_MISSING`, `RULE_UNCITED`, …). Zero silent drops.
- **Step 2, capture** = a 72 h soak of raw WebSocket frame capture (`nodes/capture`) on both venues:
  zero unexplained sequence gaps on Kalshi, Polymarket top-of-book agreement ≥ 99.5% with every
  drift resynced, disk inside budget, clean resume from a mid-window kill, and every stream alarm
  demonstrated firing.
- **Step 3, seal** = the forward era is the first day the streaming lane runs with fees read from
  the venues' payloads and settlement equivalence gating covers. Nothing before it counts.
- **Step 4, faithfulness** = `nodes/replay` rebuilds every `stream_evaluations` row from captured
  frames by importing the runner's own constants (fee params, enums, thresholds). Zero mismatches.
- **Step 5, gates** = G1–G5 over the recorded cover-cost distribution per league and quantity,
  pre-registered. "Edge" is a locked return after fees, buffers and settlement risk, never a mid.
- **Step 6, one-shot** = unchanged.
- **Step 7, forward paper** = `PAPER_EXECUTION` against live replicas with the same coordinator that
  would trade, n pre-computed from a power calculation on the recorded distribution.
- **Step 8, execution proof** = Kalshi demo round-trip (place → poll → cancel → settle) on the demo
  host. **Polymarket has no demo environment**: its leg's first real test is the one $5
  `LIMITED_LIVE` fill, with the charged fee matching the market's `feeSchedule` and the Kalshi fee
  matching `fee_multiplier` from the series. A fee above either is a STOP and a re-pin.
- **Cross-venue additions, item 1** (leg risk) = the measured rate at which the two venues settle
  the same game differently — cancellation, postponement, suspension, tie — from
  `nodes/settle_wedge`, priced into the settlement-risk buffer. Until measured the label is
  `settlement_risk_modelled=False` and the mode is capped at `PAPER_EXECUTION`.

| 2026-09-03 | Step 8 for Kalshi: the demo round-trip is **waived** at the operator's decision; replaced by a live fill of 1–10 contracts on the production account. Operator statement, verbatim: *"i dont care if we test with the actual kalshi account (as long as the fills are very small) Theres no need for a kalshi demo account."* The proof stays reconciled against fills, the pinned fee curve at the series multiplier, and the balance delta; it runs under `LIMITED_LIVE` with a signed override whose caps bound it. The $5 figure in step 8 was a pre-committed floor with nothing depending on it; the cap is now "≥ 1 contract, ≤ $10 stake". | Only production Kalshi credentials exist on the box; no fill has been placed. Polymarket unchanged (no demo exists; wallet not yet created). |

| 2026-09-04 | **Test trading only, until edge is shown on clean data.** Operator statement, verbatim: *"The only trading we should be doing right now is test trading; no serious amounts; because of the bug we are no longer sure there even is edge in our strategy."* Consequences, appended not edited: (1) the only real orders permitted are the execution proofs (GATE step 8) under the arming override's caps — $5 per order, 10 contracts, $20 a day — one clean fill per venue; (2) the lane stays at `PAPER_EXECUTION` (ledger F3) and does not advance to `LIMITED_LIVE` until L36 re-run on data recorded after 2026-09-04 00:25Z shows actionable covers in play, not at closing books, AND F3 has its n; (3) any later override raising those caps needs a new dated row here quoting the operator. | Every profitable print recorded before 2026-09-04 was a closing book under a flapping socket with fees pinned at half (CHANGELOG 2026-09-03 night, 2026-09-04); the first real Kalshi fill exists; no Polymarket fill exists; no edge has been demonstrated on clean data. |

| 2026-09-07 | **Small real trading on every enabled league, from the Ashburn box.** Operator statements, verbatim (2026-09-07): *"we should start testing actual fills on actual live events (eventhough small)"*; *"shouldnt we change that??; if our objective is truly testing the strat we shoud focus on actually filling contracts"*; and, offered the choice of running the row, the override and the mode switch themselves or having the agent do it: *"You approve; I run all three"*. Caps for the pilot, proposed by the agent and approved with that answer: **$12 stake per order, 25 contracts per leg, $60 notional a day**, the realized-loss breaker at **$25**, `limits.toml` `min_net_profit_usd` 0.10 (from 0.50), the 1% locked-return floor unchanged, override expiry 7 days. The box executes; the Mac stays paper (F5). This row overrides two earlier consequences with measured facts: the 2026-09-04 paper-only clause (both proofs settled 7 of 7; F5 at 34 of 37 paper covers, all hedged) and L34's OBSERVATION_HOST consequence for the box (Kalshi 51 vs 184 ms, CLOB 184 vs 309 ms; the Mac that ran the proofs has paged to death twice). Ledger F8 reports it: STOP on one unhedged real leg; the first three covers reconciled by hand before the fourth. The agent writes the override and switches the mode under this row, and rewrites the override after every deploy to the box, each rewrite appended to F8. Caps may only be raised by a later dated row here. | Known at the time: no edge shown on clean data (L40: 15 clean prints of 292; three paper covers settled +$3.02 net); the pooled slippage pin is 4c pending L41; two order-path holes (a non-final status released the reservation; the hedge window ran from the mint) fixed the same day, before arming; the box's Kalshi shard 0 holds $41.24, shard 3 (tennis) $22.43, the Polymarket account about $93 pUSD. |

| 2026-09-07 | **The override pins the executable tree; it is re-checked while running; a kill crosses hosts.** Operator's answer, verbatim (2026-09-07): *"Pin the code tree, one daily paste"*. Consequences, appended not edited: (1) the arming override pins the hash of the executable tree (`kernel/code_sha`: `nodes`, `grids`, `kernel`, `ops/run_node.sh`, `ops/box/systemd`) instead of the whole checkout's HEAD, so documentation and research commits no longer invalidate an arm; a code change under any of those paths still does (`OVERRIDE_CODE_SHA`), and an override without the pin is incomplete. The whole-checkout sha is still recorded, for the log. (2) The override is re-read on every report tick; an expired or mismatched arm makes the lane refuse real orders (`ARM_STALE`) until a matching one is written, and the box's watchdog says `OVERRIDE_EXPIRING` under 24 h and `OVERRIDE_STALE` after. (3) A cross-host kill exists in SSM (`/janus/kill/all`, `/janus/kill/live`; `ops/box/kill.sh`), mirrored into the box's kill files by its watchdog job and never lifting a breaker's or a human's file. (4) The release is one paste a day, `ops/box/release.sh <sha>`, at the F8 caps in the standing statement `ops/box/arm_statement.txt`; caps and statement change only by a later dated row here. Step 9's requirements are otherwise unchanged: verbatim statement, signed, capped, expiring, on the box. | Known at the time: F8 armed on the box 2026-09-07 16:18Z under the whole-checkout pin (runner 5a07e4e); no real cover has filled yet; a docs commit to the box would have invalidated that arm and a deploy would have crash-looped the unit; the lane read the override once at start and an expiry stopped nothing already running. |

| 2026-09-07 | **The smallest executable size, never bigger; a cap that refuses it is a defect.** Operator statements, verbatim (2026-09-07 evening): *"no caps: as little as possible per event (which still makes them executable)"*; *"I want the smallest amount that doesent cause fill failures (like the one that happened previously today)"*. Caps become **$12 per order (both legs), 10 contracts per leg, $250 notional a day**; the realized-loss breaker stays at $25 a day; the capital limits in `limits.toml` (per venue $250, unresolved $250, total $500, six simultaneous events) and the single-flight rule per event are what bound exposure. The lane prices 5, 10, 25 and 100 contracts and executes the smallest profitable size first; the per-order cap admits exactly the two smallest rungs. The day cap moves from $60 (five covers a day, which would have refused the sixth good one) to the value of one venue's capital so that the capital limits bind before it. A cap refusing the smallest rung raises `CAP_BINDS_SMALLEST` in the watchdog. The pooled 4c slippage reserve is what held the 5-contract size under the $0.10 floor today; L41 replaces it per league, and the floor is re-read against measured fills in a later row, never lowered ahead of them. The agent writes the override and the switch under this row. | Known at the time: the lane is LIMITED_LIVE on the Mexico box since 20:22Z; no real fill has yet reconciled (the only real order, from Virginia, was geoblocked); today's actionable prints were 4–5 % locked at 25 and 100 contracts and refused by the $12 cap; three paper covers cleared in Mexico's bring-up, one at 10 contracts. |
