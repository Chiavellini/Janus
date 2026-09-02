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
