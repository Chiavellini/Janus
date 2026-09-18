# NEXT

Current-state handoff, updated 2026-09-18. Evidence belongs in the linked registered rows; this
file is an opinionated map and may be overwritten.

## Where things stand (2026-09-18)

**Production is unchanged and not trading.** The F22 kill is latched and byte-identical; nothing was
deployed, released or re-signed. The lane runs normally under the kill (it restarts cleanly under
`kill/live` since d416bf8) and refuses every entry.

**F24 is authorised, fully tooled, and waiting on ONE thing.** The operator chose to run it with
**every league, unchanged limits** ("don't exclude anything; 5 dollars should be reachable"). Two dated
GATE amendments carry the operator's words (*"I approve"*; *"I authorize you to arm, and yes, commit
and push everything"*). The agent arms with
`arm_f24.sh "I approve" --send` the moment the quiet check passes, re-verifies ~2 minutes later, and
reads `check_f24.sh` daily, stopping by hand at −$50 **all-in** realised loss.

**The blocker is the operator's own manual Kalshi trade:** ORPHAN_FILL #1172 (KXTRUMPSAY buy_yes 6.67
@ 0.68, 2026-09-17 19:36Z) and GUARD_FAILED #1173 behind it. The guard clears them once that position
is closed or settles; the agent never clears them. Any manual fill during F24 latches the kill and ends
the row (a registered STOP).

**What the money bounds really are** (RUNBOOK.md, verified against deployed code): only the $25
breaker and the override expiry act by themselves, and the breaker is a **gate on starting trades**
against money already settled that UTC day — not a cap on a day's loss. Unattended worst case is
roughly **$200 plus whatever is open**. The $50 and 30-cover ends exist only because someone reads the
report daily.

**What the evidence says F24 will find — recorded, not argued:**
- **L150:** over 25 real covers the ARBITRAGE made **+$0.812**; unhedged remainders made **+$3.365**.
  Through 09-09 +$0.462/cover, since 09-10 **−$0.209/cover** (bootstrap interval excludes zero, by one
  cent). The entry rule did not loosen (planned edge 6.0c → 4.3c); the hedge stopped cooperating
  (fills went from ~3c better than planned to ~2c worse). **ATP is the loss:** 9 covers, −$3.662.
- **L151:** over every real-money hedge order, realised hedge slippage is **median +1.98c per
  contract against the 0.50c margin entry requires — about 4x**, adverse on 15 of 17 fills. Entry
  charges the hedge nothing for this: `slippage_for` gates no order (capacity.py:49-50). The pooled
  4c reserve went to 0.0 on 2026-09-08 and its replacement (L41) never ran. Wiring the charge into
  `plan_from_cover.clears()` was tried and **reverted as ineffective** (it binds only on the tick-snap
  and the pad); it must bind on `locked_return` at `clearance.py:205`, which moves every recorded
  evaluation and needs its own row, GATE amendment and release — and would price out most covers.
- **$6.67/day was always a ceiling** (every cover at $0.28 under the $500/day cap), never an
  expectation. The operator believes $5/day is reachable; F24 is the test of that.

**The F24 tooling was audited five rounds** (each round's fixes introduced new defects, twice the
agent's own). Final shape: `verify_f24.sh` judges "can it trade" from the lane's own recorded refusals
(`refusal_counts`), not from which files exist; `report.py` separates the verdict statistic
(`net.settled_covers_only`) from THE MONEY (`net.all_in_realised`, including partial hedges) and
withholds a verdict rather than asserting one; `check_f24.sh` ships the reader compressed (it outgrew
SSM's 97 KB) and renders the banner locally. 203 F24 tests; verified live against the box.

**The Polymarket depth defect (L146):** the REST write-through (L148) failed review and was reverted.
Its replacement, **L149** (on a REST disagreement, ask the websocket for a fresh book; never keep the
REST content), is implemented and tested in this tree and **not deployed**. It is a data-integrity
fix, not a profit lever, and it must **not** be deployed during F24 (it would change what F24
measures). See the L146 section below.

**A pre-existing entry-rate suspect the L149 review surfaced (not investigated):** when a discovery
refresh changes a game's executable specification, the grid unregisters and re-registers the same
Polymarket token in one tick (`grids/live_stream/grid.py:441-449`, `478-481`). No subscription frame
is sent and the ladder is dropped, so the new replica stays DISCONNECTED until the socket reconnects.
It fails closed (no wrong price), but it silently stops pricing that game. How often it fires in
production (`[refresh] ... executable slate specification changed` lines) is unmeasured.

## Production now

Re-proved read-only on 2026-09-15 after the audit below. The Mexico box is still deployed at
`59dd5ae2ce3619104aa95d127d1b115d7c0702a9`; `kill/live` carries SHA-256
`d81bbfc267a235ca7f268e7317d77ee7e83c65f5263117590e4e86d1552b1636` latched at `1789504505.261733`,
and `arming_override.json` is still pinned to **F22** (expires 2026-09-22T20:22:36Z). The working
tree is now committed at `c0cc5eb`; production does **not** run it.

The service is active for streams/reconciliation but entry is blocked by `kill/live`; it is **not
trading**. The retained kill's exact reason:

> F22 STOP: terminal maker zero-fill fee evidence is NULL; strict report classifies persistence_or_reconciliation_failure

At the latch there was zero flight and zero unhedged quantity. F22 is permanently closed. Its first
two maker decisions and orders remain unchanged evidence: authoritative terminal zero fills with
valid post-only proof, but `fee_usd=NULL`, so F22 correctly stopped rather than manufacturing a
zero-dollar observation.

The earlier scalar/cancelled cover is settled and released at `-$0.99357`. That economic loss did
not cause the current stop. The separately reported approximately $100 `ORPHAN_FILL` was operator
manual activity, not Janus, and the operator has asked that it not be pursued as a system incident.

The Polymarket redemption timer's rate-limited positions call remains an operating-cost issue. It
is distinct from order attempts and should stay bounded/quiet rather than retrying expensively.

## Audit verdict: DO NOT RELEASE (2026-09-15, independent)

The candidate below was committed to `claude/hedge-safety-and-speed` as four checkpoints
(`fa00a8d..c0cc5eb`) and then independently audited. Full result:
`AUDIT_2026-09-15_F23_RELEASE.md`.

**Three independent blockers, any one sufficient.**

1. **The GATE grant is broader than its statement — a scope question, not a forgery.** The operator
   confirmed on 2026-09-16 that the 2026-09-15 F23 statement is genuinely theirs; an earlier audit
   finding of fabrication is **withdrawn**. What remains open: the sentence mentions none of
   release, re-signing, arming or kill-clearing, yet `GATE_TO_LIVE.md:173` grants all four while
   `:172`, the same day, forbids exactly that list. Separately, the statement is also the arm's own
   authority check (`entry_experiment.py:27`, via `ops/box/f23_arm_statement.txt`), so the grant,
   the pinned evidence and the code's validation are one string. Only the operator can close this.
2. **F23 cannot complete.** L140 fixed only the **maker** path, so the first taker terminal
   zero-fill — 8 of 11 taker orders in the measured window — is an immediate registered STOP,
   reproducing the exact F22 failure. Separately, L142's 100 ms guard budget on a single-vCPU box
   makes any timeout a `persistence_or_reconciliation_failure`, discarding even a filled profitable
   maker cover. And at its registered 200-decision minimum the primary estimand carries **t ≈ 0.36**,
   so its verdict is predetermined.
3. **The kill-clearing route was never executable.** `ops/box/clear_f22_instrumentation_latch.sh`
   has no `ops/box/run.sh` wrapper (all three siblings do), so its `systemctl`/`sudo`/`/srv/janus`
   commands would run on the operator's Mac. Line 5 sets `HERE=` and never uses it — the dropped
   wrapper line. Also: `KillSwitches.latch` swallows `FileExistsError`, so a later ORDER_OVERFILL
   latch leaves `kill/live` byte-identical and still matching the pinned digest — the digest pin
   narrows *which kill* is cleared, not *what state* it is cleared from.

Do not run `release.sh`, `write_f23_override.sh` or `clear_f22_instrumentation_latch.sh`.

**Correction to the Profit arithmetic section below.** Its `$0.27636`/cover is a 3-of-4 subsample.
The omitted cover `17077a35` realized **−$0.99357**, in the same registered window. All four covers:
**−$0.16449**, i.e. **−$0.04112 per cover**. Over its one complete registered window the lane's
realized net was **negative**. Every `$100/day` figure below (362 covers, 209, $9.95) is built on the
positive subsample.

**Correction on speed.** The ~181 ms confirmation is **already overlapped** with the hedge read
(`coordinator.py:218-222`); L141's own p50s are `max()`, not `sum()`. Removing it saves ~65 ms at
p50 and ~0 at p90 — and deletes L83's collateral ceiling, after which price-improved fills trip
`_check_overfill` and latch the kill. Neither proposed successor exists: the only authenticated PM
socket carries order/trade events, not books, and hedge-first over-hedges with `unwind_enabled=false`.

Verified sound and worth keeping: unchanged limits, unchanged F22 blocking (`ops/f22_report.py:272`),
true cohort separation, no crossover, exact F23 minimums, a real event-cluster bootstrap, correct
America/New_York venue dates. Focused tests and the full suite pass; the replay rows digest `13e4fb08a76c920f` is unchanged. **Replay scope (corrected 2026-09-17):** that digest covers 9 columns of 1,093 `stream_evaluations` rows on a 63-second fixture. The paired selections digest `4f53cda18c2baa0c` is `sha256("[]")` — every replay run made zero selections — so it checks nothing. Neither proves live-vs-replay parity, ladder correctness, reconciler behaviour or the execution path.

## L143 (2026-09-16): the first-leg gap is one-sided — speed is not the lever

Registered before extraction; read-only over the whole `executions` table (334 in scope, **202
carrying both a frozen plan ladder and a fresh confirmation ladder**). Verdict by the registered rule
is `MIXED_OR_INCONCLUSIVE` and no branch was widened. The data is still decisive in one direction.

**155 adverse / 46 exactly zero / 1 favourable.** Favourable fraction **0.005**, median gap **+6.0c**
against us. A genuine ~700 ms race would put roughly half the moves in our favour; we capture
essentially none. It is bimodal by outcome, not continuous: `RECONCILED` (n=10) and `ORDER_REJECTED`
(n=7) show gap **0.0c at min, median and max**, while `BOOK_MOVED` (n=161) shows **+7.0c** median,
+51c max. **Every row that reached a fill saw the book not move at all.** The lane does not lose a
race by a little — it either sees a stable book and trades, or sees a price that was never there.

The pooled elapsed-vs-gap rho of 0.3068 — the one condition that blocked an
`ADVERSE_SELECTION_DOMINATES` verdict — is confounded by outcome: declines take ~2× as long *and*
move further. **Within** state it is 0.1646 (BOOK_MOVED, n=95) and 0.0825 (ORDER_UNFILLED, n=8), both
under the registered 0.20. Phantom depth was refuted outright: 0 of 161 declines.

**Consequence: do not register a speed successor for the taker first leg.** Removing the confirmation
cannot recover rows whose price was already wrong when selected; it converts a safe decline into a
fill 6c worse than planned.

Two caveats, neither minor. This is a **taker-path result only** — the confirm block is gated on
`not post_only` (`coordinator.py:207`) and 132 of 334 executions carried no confirm ladder. And
**winner's curse is not excluded**: an execution starts only when the frozen book passes the screen,
so the frozen price is selected favourable. The next row should test whether gap magnitude scales
with the apparent edge at selection — if it does, the fix is in what we screen on, not how fast we
act. Full result: `research/exec/2026-09-16_book-move-attribution/verdict.md`.

## L144 (2026-09-16): it is Polymarket's book, not our selection

The discriminator was the Kalshi hedge leg — confirmed concurrently with leg A on the same clearance
window, off the same `books_json` snapshot. Joint selection predicts both legs regress; a
Polymarket-specific data defect predicts only leg A does.

Same 169 executions, same windows:

| | favourable | zero | adverse | median | mean |
|---|---|---|---|---|---|
| **Kalshi** | **45** | 102 | 22 | **0.0c** | **−0.05c** |
| **Polymarket** | **1** | 40 | 128 | +6.0c | +6.10c |

Conditional on moving at all: Kalshi **67.2%** favourable, Polymarket **0.78%**.

**`JOINT_SELECTION` is affirmatively excluded by the registered rule** (it required Kalshi median
≥ 1.5c; the median is 0.0c). The hedge leg does not regress. The defect is on the Polymarket side.

The verdict is still `MIXED_OR_INCONCLUSIVE` because `VENUE_SPECIFIC_POLYMARKET` required Kalshi
favourable ≥ 0.30 and observed 0.2663 — a threshold I mis-specified, since 102 of 169 Kalshi rows are
exactly unchanged and a 60%-zero distribution caps that statistic near 0.40 under perfect symmetry.
Reported as registered rather than upgraded after the fact.

**Both secondary mechanisms are load-bearing** and each survives stratification on the other:
apparent edge rho 0.3648 (strata 0.167 / 0.298 / **0.654**) and frozen book age rho 0.3337 (strata
0.231 / 0.459 / 0.380). The edge effect is weakest in the freshest books and strongest in the
stalest — consistent with a stale ladder *manufacturing* the apparent edge that the screen then
chases. Staleness and selection are not competing here; one feeds the other.

**Next target is Polymarket websocket fidelity**, measured on markets the lane did *not* select —
which removes selection entirely. Taker-arm only; the Kalshi leg is a weaker control than it looks,
because L141 showed the screen binds far harder on leg A (90 of 95 declines failed the PM check, 5 the
Kalshi check). Full result: `research/exec/2026-09-16_venue-gap-asymmetry/verdict.md`.

## L145 (2026-09-16): inconclusive — and the reason is the finding

A paced REST sweep of markets the lane never selected, run while the kill was latched, returned
`MIXED_OR_INCONCLUSIVE`: **Polymarket 22 of 22 fresh pairs matched REST exactly**, Kalshi 24 of 25,
so neither venue had enough moved pairs to measure a direction.

The zeros are not evidence of fidelity. 135 of 182 pairs were `BLOCKED_MATCH` and 69% were ITF
tennis — quiet books the lane could not even pair. And the lane's Reconciler **overwrites quiet
replicas with the REST book** every ~15 s, so on a quiet market the websocket price is often already
a REST price and the comparison is close to circular. **Removing selection also removed the
moving-book regime where L143's losses happen.** Selection is not just a bias to subtract; it is what
puts the lane in front of moving books.

One selection-free contrast survived, from `socket_health` over the same 183 s: **Polymarket 613
top-of-book integrity failures, Kalshi 0 sequence gaps.** Directionally consistent with L144, but the
instruments differ, both are top-of-book only, and a drifted Polymarket book is invalidated and never
traded — at 99.74% agreement it cannot explain 128 adverse in 169. The books that hurt the lane are
the ones that pass the top-of-book check and are wrong *deeper down*.

The Reconciler's `rest_drift` compares websocket against REST level by level, but is never written
anywhere (`store.py:385` omits it). `grids/live_stream/README.md:94` says it reaches `socket_health`;
it does not. **Correction (2026-09-17):** an earlier version of this section said `rest_drift` runs
on every asset and recommended persisting it. It runs on **quiet books only** — see L146 below — so
that recommendation is withdrawn. Full result: `research/exec/2026-09-16_pm-feed-fidelity/verdict.md`.

## L146 (2026-09-17): the Polymarket depth defect reproduces in the deployed code

**Registered outcome: `DEFECT_REPRODUCED`**, with both controls catching theirs. The tested stream
modules are byte-identical to deployed `59dd5ae`, so this is a statement about production code.

- **R1:** an ask the venue had removed survived **60 agreeing updates — 60 checks, 0 drift, no
  fault, never selected for REST** — and the book was re-verified on every message.
- **R2:** a touch size of 8 locally against 1 at the venue was judged to agree. Only prices are
  compared.
- **R3:** a quiet book *was* REST-corrected, but the stream's own ladder (`ps.books`) was not. **One
  update later the phantom level was back**, relabelled `"ws"`, with no fault.
- **Controls:** the same lost update *at* the touch is caught instantly; a Kalshi sequence gap is
  caught.

A supporting pin isolates the cause: the same stale book is reconciled when quiet and **never** when
it is being traded. The trade-off behind that is deliberate and reasonable — reconciling a busy book
"would report timing skew as drift" (`reconcile.py:9-11`) — but the stream relies on REST as its
only depth backstop (`protocol.py:18-20`), and the filter keeps that backstop off exactly the books
the lane prices.

**What it does not prove:** that this happens in production, how often, or that it explains L143's
losses. It is the most specific mechanism found and it points the right way; the below-touch loss
rate is unmeasured.

**Fixes, each needing its own spec, PENDING row and, before production, a dated GATE amendment and
the operator's release:**
1. **R3, quiet books.** Writing REST into `ps.books` (L148) was tried and **withdrawn**: REST has no
   sequence number and can lag the socket, so it can make a removed level permanent. **L149** instead
   queues a websocket resnapshot on a REST disagreement — prepared and tested here, not deployed.
   Full result: `research/exec/2026-09-17_rest-mismatch-resnapshot/verdict.md`.
2. Stop a below-touch update from verifying the whole book. (Open.)
3. Depth-check active books with a tolerance for the REST round trip. (Open.)

(2) and (3) change which books the lane prices from, which is entry-adjacent. Measuring the real rate
needs on-box frame replay, which conflicts with L51 — also your call. Full result:
`research/exec/2026-09-17_pm-depth-verification/verdict.md`.

## Release candidate in this tree (F23 — audited DO NOT RELEASE; superseded by F24 for now)

L140 fixes the F22 instrumentation defect prospectively: explicit `fee_usd=0.0` is persisted only
for complete terminal, non-open, non-pending, zero-fill maker proof. Ambiguous, partial and filled
orders retain blocking fee requirements. Historical F22 rows are not repaired.

F23 is a fresh event-randomized comparison of the same bounded immediate Polymarket taker entry
against the registered two-second post-only maker entry. It has a separate table, assignment
digest, authority and report. F22 cannot reactivate in capital mode. The fixed F23 end is 200
eligible decisions, at least 80 per arm, 50 events, five league-local days and three leagues; the
first three covers must reconcile before the fourth, but later fills are not serialized behind
settlement. Each F23 decision now persists its event start, league and canonical America/New_York
venue date before the wire; malformed or missing dates keep the five-day minimum unscored.

L142 closes a defect observed on both F22 maker orders. Their loop-owned safety callback went
unserviced for 1.62/1.75 seconds and timed out at nearly the full rest deadline. Each check is now
bounded by the existing poll interval; timeout/error cancels immediately and structured evidence
distinguishes responsive checks, timeout, refusal, fill and deadline.

The release/recovery route recognizes only the exact retained F22 kill, proves the complete
decision/execution/opportunity/client/order/digest identities of decisions 1 and 3 and their
unchanged NULL-fee orders, requires zero F23 rows and globally quiet capital, runs two
stopped complete guards around a retained-kill stream warmup, archives only that exact kill, and
restarts under exact F23 authority. A mismatch remains stopped and rollback restores the kill.

Local verification is green: 172 focused tests, all 1,766 collected tests in the complete suite,
compilation, shell syntax and
diff checks. Replay is unchanged over 20,000 frames, 234 pollers, 5,858 evaluations and 1,093 rows:
`13e4fb08a76c920f / 4f53cda18c2baa0c`.

## What the last live window actually proved

L141 fixed the denominator. In the registered 24-hour window, the included execution records span
15.34 wall-clock hours and reconcile exactly to:

- 95 `BOOK_MOVED` before wire;
- ten authoritative Polymarket terminal zero fills; and
- three complete covers, net `+$0.82908` after `$1.40092` fees.

The 95 declines were not 95 independent games: 35 event IDs and 49 opportunity IDs, with up to 13
attempts on one event. They do map to separate selected sizing windows, but none is proved safely
fillable. All have structured fresh confirmation: 90 failed Polymarket first-leg price/depth by
6c median and 10c p90; the other five passed leg A but the Kalshi hedge was above break-even by
1.88c median. Calling all 108 records “takeable prints” is therefore false.

The correct submitted-first-leg conversion was 3/13 = **23.1%**. The raw selected-window conversion
was 3/108 = 2.78%. Thirteen submitted orders are too few to distinguish a true one-third fill rate,
but one-third of all 108 is contradicted under the existing safe economics because no declined row
has a two-leg executable counterfactual.

The execution problem is nevertheless real. All eight eligible taker zero fills had sufficient
depth at the sent price immediately before submission and zero depth afterward: interim L102
classification `CONSUMED=8`, `STILL_THERE=0`, `PULLED=0`. Median REST confirmation was 180.74 ms,
confirmation-to-submit only 6.83 ms, and submit-to-ack 197.63 ms. This is latency-consistent but is
only eight observations, not L102's approximately 50-order final verdict.

For the 95 pre-wire declines, the Polymarket websocket book was already 548 ms old at median and
the fresh confirmation completed another 180 ms later. Ordinary machine dispatch is not the main
cost: frame-to-evaluation 1.66 ms, evaluation-to-executor 32.09 ms, worker hop 5.59 ms, clearance
5.55 ms and database work 8.14 ms at median. The direct target is the serial
websocket/venue-authority/network path while retaining a fresh hedge proof.

## Profit arithmetic

The recent three-cover mean was `$0.27636` net. Thirty-six covers at that mean produce `$9.95`, not
`$100`. The exact Polymarket fees on those covers were `$0.60932`; removing them raises 36 covers to
`$17.26`. Even removing **all** `$1.40092` of venue fees produces only `$26.76`.

At observed economics, `$100/day` requires about 362 covers. With only the Polymarket fee removed,
it still requires about 209. Therefore execution conversion plus the current maker saving are
necessary improvements but not sufficient. Reaching the goal also requires materially more
eligible surface, more dollars per cover within proven caps, a cheaper venue/mechanism, or some
combination. The high-evidence Kalshi MM-at-open lead remains untested in sports and avoids the
expensive two-venue fee pair, but it is a different mechanism and must be registered separately.

## Open questions that directly target the goal

1. Does F23's maker fee saving survive its lower fill probability, event-loop proof availability,
   waiting drift and hedge tail? Only the fixed forward cohort can answer.
2. Can taker entry remove one serial Polymarket confirmation round trip while preserving the fresh
   Kalshi hedge guarantee? The current data support testing a hedge-first strict-limit IOC arm, not
   blindly sending all 95 declined rows. That requires a new preregistered entry experiment and a
   dated GATE amendment before live use.
3. Why is the local Polymarket book commonly roughly 0.5–0.8 seconds old at selection, and can
   network placement or stream handling reduce the venue-authority gap? L141 says Python dispatch
   alone cannot supply the needed gain.
4. Can co-listed event coverage rise beyond the observed 35 `BOOK_MOVED` events without importing
   unmeasured settlement basis? Coverage and repeated covers are needed because current per-cover
   dollars cannot close `$100/day` alone.
5. Does the L102 `CONSUMED` split persist near 50 eligible taker zero fills? If it does, speed is the
   correct execution lever; if it reverses toward `STILL_THERE`, more speed will not fix the engine.

## Things that will mislead you

- `stages_json` stamps are cumulative from `_t0`; difference adjacent stamps per row.
- `socket_health.frames` is cumulative; use deltas and treat decreases as reconnects.
- `refusal_counts` are callback counts, not unique opportunities or stage conversion.
- `PROFITABLE_UNEXECUTED` is material-change gated and per size rung.
- `BOOK_MOVED` is a safe pre-wire terminal, not a submitted order and not proof the frozen print
  was still executable at the venue.
- A service can be active while `kill/live` blocks every entry.
- A provider response that is unresolved is not a zero fill.
- Negative unconditional hedge drift is not maker EV. The F23 randomized result governs.
