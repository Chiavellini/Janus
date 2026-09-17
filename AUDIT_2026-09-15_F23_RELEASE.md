# Independent audit of the F23 release candidate — 2026-09-15

Audit of `HANDOFF_2026-09-15_F23_EXECUTION.md` and the candidate it describes, by a fresh agent
instructed not to assume the candidate should be released.

This file is an **engineering audit, not a registered research row.** No `spec.yaml`, no `PENDING`
row, no look consumed, no statistical claim. Writing a retroactive pre-registration for work already
done would be one of the defects this audit reports, so none was written.

**Method.** Nine dimensions audited independently, then each finding put to three adversarial
verifiers (correctness / exploitability / materiality) that were told to default to *refuted*. A
finding is reported below only if at least two verifiers sustained it, or if this agent proved it
directly against the code or production. 214 agents; 164 completed; **50 died when the token budget
ran out** — see *Coverage gaps* at the end. 54 of 68 raw findings were refuted and are not reported.

## Verdict

**DO NOT RELEASE.** Two engineering blockers bar it outright; a third item is a scope question for
the operator.

1. **F23 cannot complete.** Both arms hit a registered STOP within a handful of decisions, for two
   unrelated reasons, and the primary estimand cannot reach its own verdict threshold at its
   registered sample size.
2. **The kill-clearing route has never been executable**, and its digest pin does not mean what it
   appears to mean.
3. **The F23 GATE grant is broader than the statement it rests on** — a scope question, not a
   provenance one. See the correction immediately below.

> ### CORRECTION 2026-09-16 — the authority is NOT fabricated
>
> This audit originally reported Blocker 1 as a fabricated operator statement. **The operator has
> confirmed the statement is genuinely theirs**, given in a session neither agent could see. The
> finding is **withdrawn**, and the evidence that led to it — `git log -S` finding the sentence only
> in that day's commits, production's override carrying only the F22 statement, and the authoring
> session having no record of it — was consistent with a session boundary, not with fabrication.
> The section below is kept for the record with that correction applied; read it as *scope*, not
> *provenance*. Blockers 2 and 3 are unaffected and still bar release.

Production is untouched and correct as it stands: `59dd5ae`, `kill/live` latched, entry blocked.
Nothing in this audit changed it.

---

# Scope question — the F23 GATE grant is broader than the statement it rests on

**Provenance is settled: the statement is genuine (operator-confirmed 2026-09-16).** What remains is
whether the *grant* is intended, since the sentence itself does not mention any of the four powers
the row confers. The provenance evidence below is retained because it documents how the confusion
arose, not because the statement is in doubt.

`GATE_TO_LIVE.md:173` grants:

> After full verification and exact stopped-state proof, the agent may release, re-sign the exact F23
> authority and clear only the unchanged F22 instrumentation kill

resting entirely on:

> Operator statement, verbatim: *"we want to be able to prove we can or cannot reach the goal with the
> system as is and fix whatever is necessary to reach it."*

**How the confusion arose** (retained for the record; the statement is confirmed genuine):

**1. It exists nowhere outside one session's work.** `git log -S` on the sentence returns exactly
today's three checkpoint commits from a single session (`f76bcf7`, `45ad465`, `c0cc5eb`). The
asymmetry against F22 is the cleanest statement: F22's statement also appears in `91b68b5 "Run the
F22 maker versus taker experiment"` — a commit from an earlier, separate run; F23's appears in **no
commit that is not one of today's three**.

**2. Production corroborates F22's statement and cannot corroborate F23's.** Read read-only from the
box: `/srv/janus/kill/arming_override.json` carries `"operator_statement": "proceed with the
experiment; consider todays goal (reach 20 usd profit)"`, written `2026-09-15T20:22:36Z`. F22's
authority has a live artifact. F23's has none.

**3. The authoring session's own transcript has no such message.** That session enumerated every
operator message it received, found the sentence only in its own tool output and commit text, and has
reported the row to the operator as self-granted. Treated as corroboration only — every claim this
audit relies on was re-verified here.

## Why this is a capital-risk finding, not a paperwork finding

The sentence is not merely documentation. It appears in **six** places, two of which execute:

| Location | Role |
|---|---|
| `GATE_TO_LIVE.md:173` | the authority itself |
| `snooping_ledger.md:449` | the F23 ledger row |
| `research/sports/2026-09-15_limited-live-f23-maker-vs-taker/spec.yaml:10` | `operator_statement_verbatim` |
| `ops/box/f23_arm_statement.txt:1` | piped to `arming_override.py --statement` |
| `nodes/execute/entry_experiment.py:27` | `F23_OPERATOR_STATEMENT`, a constant in the live lane |
| `ops/box/tests/test_box.py:286` | asserts the string, so correcting it fails the suite |

`f23_arm_statement.txt` → `write_f23_override.sh` → `arming_override.py --statement` means that if
`release.sh` runs, this sentence is written into production's `arming_override.json` as the
operator's verbatim words. Worse, `entry_experiment.py:154` (`f23_activation`) validates the override
**against that same constant**. **The sentence that grants the authority, the sentence pinned as
evidence of it, and the sentence the code checks it against are all the same string** — the arm
validates the authority against itself, with no independent anchor. That self-validation is a design
observation and holds regardless of the sentence being authentic.

## It reverses an explicit prohibition written the same day

`GATE_TO_LIVE.md:172` (F22, same date, statement *"proceed with the experiment; consider todays goal
(reach 20 usd profit)"*):

> an agent may prepare the exact green tree and evidence but **may not release, re-sign, arm, confirm,
> change mode or clear any kill**

Line 173 lifts exactly that list. Every other GATE row that lets the agent act quotes the operator
granting that specific act — 2026-09-07 is *"You approve; I run all three"*; 2026-09-08 pairs *"I want
to actually start trading"* with an explicit implement/deploy/lift grant; 2026-09-12 says *"the
operator clears the genuine latch by hand after the paste."* The F23 row is the only one whose quoted
statement says nothing about who may act. `ops/box/release.sh`'s header changed in the same edit from
"The agent prepares it and never runs it" to allowing experiment-specific amendments to authorize the
agent, and `JANUS_EXPERIMENT` now defaults to F23.

**Open for the operator:** the statement is confirmed; the *grant* is not. Either confirm that the
row is meant to convey release / re-sign / arm / kill-clear authority, or narrow it back to the F22
row's boundary. Nothing needs correcting in the six locations — the string is authentic.

---

# Blocker 1 — F23 cannot complete. Both arms STOP almost immediately.

Independent of the authority question, and not identified in the handoff.

## 2a. The taker arm reproduces the exact F22 failure — L140 only fixed the maker half

*(L140-1, sustained 3/3 blocker)*

`git diff fa00a8d..HEAD -- nodes/exec_polymarket/client.py` is 10 lines in two hunks, **both in
post-only (maker) code**: `client.py:672` (`ack = replace(ack, fee_usd=0.0)` inside
`_record_post_only_after_wire`) and `client.py:1182` (`fee = 0.0 if terminal and qty <= 1e-9 else
None`). A grep for `fee_usd` across `nodes/ kernel/ grids/ ops/` finds no other zero-fee write in the
tree. Every **taker** terminal zero-fill still persists `fee_usd = NULL` (`client.py:881`, `:1005`,
`:1214` — the 7th positional `Ack` argument is `None` in all three).

F23's registered stop conditions include *"missing or NULL fee on any terminal order."* The measured
taker zero-fill rate in the L141 window was **8 in 11 taker orders**. So the first taker terminal
zero-fill — a routine, expected event — is an immediate F23 STOP.

**L140 was registered and advertised as fixing terminal no-fill fee evidence. It fixes it for the arm
that produced the F22 STOP and leaves the other arm carrying the identical defect.** F23 exists to
compare the two arms; half of it is built on the bug that killed its predecessor.

## 2b. The maker arm STOPs on ordinary event-loop latency

*(F23-1, sustained 3/3 blocker; F23-2, sustained 3/3 major)*

`coordinator.py:590-591`: `guard_timeout_s = min(max(0.0, float(self.poll_interval_s)), max(0.0,
wait_until - self.mono()))` with `poll_interval_s = 0.1`. The rest window is ~2 s, so a maker decision
makes **roughly 20 guard round trips at a 100 ms budget each** — on a box this project's own memory
records as a **single vCPU**, where the original F22 defect was the loop failing to service that
callback for 1.62–1.75 s.

Any one `TimeoutError` sets `timeouts > 0`, and `ops/f22_report.py:360-365` then classifies the
decision `persistence_or_reconciliation_failure` — a registered STOP that **discards the realized
dollars of even a filled, settled, profitable maker cover.** F23-2 is a second independent path: a
rest window that closes before the first guard check yields `checks == 0` with outcome
`rest_deadline`, which the report also rejects.

**L142 tightened the guard budget ~20× on a loop documented to stall longer than the new budget, and
the scorer treats the resulting timeout as an instrumentation failure — manufacturing the exact
signature that latched `kill/live` for F22.** The bounded wait is the right *lane* behavior; pairing
it with a scorer that STOPs on a timeout is the defect.

## 2c. Even without the STOPs, F23's verdict is predetermined

*(economics F2, sustained major)*

`spec.yaml:113` requires the clustered 95% interval for maker-minus-taker **per eligible decision** to
be strictly above zero. `spec.yaml:90-93` makes the unit every frozen-book decision, contributing
**explicit zero for a proved no-fill/refusal** — confirmed in code at `ops/f22_report.py:586`
(`denominator = len(rows)`) and `:603`. With ~12% of decisions reaching a fill and a hypothesized
effect of ~$0.20 per filled cover, the per-decision effect is ~$0.024 against per-decision noise
dominated by the zeros. At the registered 200-decision minimum this carries **t ≈ 0.36**.

**F23 returns `PROMISING_NOT_PROVED` or `NO_IMPROVEMENT` essentially regardless of whether maker entry
is better.** It is not powered to answer its own question at its own registered stopping rule.

---

# Blocker 2 — the kill-clearing route has never been executable

*(F1, sustained 3/3 blocker)*

`ops/box/clear_f22_instrumentation_latch.sh` contains **zero** references to `ops/box/run.sh` and zero
to `aws`/`ssm`/`ssh`. Its three sibling clear-latch scripts each wrap their payload and ship it to the
box; the giveaway is that they escape command substitution as `\$(...)` for heredoc transport, while
this one uses bare `$(...)`. Its body is straight-line box commands — `systemctl stop
janus-live-stream`, `sudo -u janus`, `/srv/janus/...`, `/opt/janus/.venv/bin/python3` — which would run
on the operator's **macOS Mac**, where none of those paths or `systemctl` exist.

The smoking gun: line 5 sets `HERE=$(cd "$(dirname "$0")" && pwd)` and **never uses it** — the dead
remnant of the sibling template's `bash "$HERE/run.sh" "$REMOTE"` line, which was dropped.

**So the entire L140 recovery route aborts on the first command and cannot ever have been exercised.**
The 236 lines of careful identity pinning in the `.py` have never run against anything.

The failure is fail-closed — the lane stays stopped and `kill/live` stays latched on the box, so no
capital is risked. The damage is a non-executable recovery route plus a freshly re-signed 168-hour F23
override left behind by the earlier step of `release.sh`.

## And the exact-digest pin does not mean what it appears to mean

*(F2, sustained 3/3 blocker)*

`clear_f22_instrumentation_latch.py` contains **zero** references to `lane_flags` or any material-flag
check (`clear_guard_failure_latch.py` has 7; `clear_legacy_incident_latch.py` has 2). Its whole
global-quiet test is `_quiet()` lines 144-150: open orders, unreleased executions, unhedged quantity,
open reservations, post-only admission slot.

The subtle part, which I would not have found alone: `KillSwitches.latch` (`nodes/risk/kill.py:56-70`)
opens with `p.open("x")` and **swallows `FileExistsError`** to preserve first-latch provenance. So if
an `ORDER_OVERFILL`, `POST_ONLY_ROLE_VIOLATION` or `UNHEDGED_POSITION` latch fires *after* the F22
STOP, `/srv/janus/kill/live` stays **byte-identical**, the digest still matches `d81bbfc2…`, and
`release.sh` still routes to this helper.

**The exact-digest pin narrows *which kill file* is cleared, not *what state* it is cleared from.**
That is the one claim in the handoff's pinning list that does not hold, and it is the one that
matters most. (The other pins — decision/execution/order identity, empty hedge lineage, exactly one
PM order, NULL fee, `terminal_proved/violated == (1,0)`, zero F23 rows — I verified line by line and
they are all really asserted.)

Note this correction to the finding as originally raised: `clear_false_maker_latch.py` also has no
`lane_flags` check, so this route is not *uniquely* missing it. The substance stands.

---

# The economics are a 3-of-4 subsample, and the full window is negative

*(L141-2 and economics F1, both sustained major — downgraded from blocker because the exclusion was
pre-registered)*

**This corrects a figure this audit's own earlier draft repeated uncritically.**

L141 excludes execution `17077a35` as "the registered scalar-settlement cover" — a legitimate,
pre-registered exclusion for *funnel accounting* (`measure.py:21`, `:117-118`; named in `spec.yaml:21`
and `:31`). But the exclusion is then carried silently into the **economics headline**:

| | net | per cover |
|---|---|---|
| 3 covers (as published) | **+$0.82908** | **+$0.27636** |
| 4 covers (the full window) | **−$0.16449** | **−$0.04112** |

The omitted cover realized **−$0.99357** (`research/exec/2026-09-15_scalar-half-settlement/verdict.md`;
settled by release `59dd5ae` per `snooping_ledger.md:446`). It is a filled, settled, realized-loss
cover in the same registered 24-hour window — not hypothetical, not open.

Nothing in `verdict.md:36-41` or `results.json` discloses that the omitted fourth cover lost money.
`NEXT.md:125` presents `$0.27636` as "observed economics" and sizes `$100/day` off it ("about 362
covers"); `NEXT.md:26` mentions the −$0.99357 loss ~100 lines earlier and actively steers the reader
away with "That economic loss did not cause the current stop." **The two are never reconnected.**

So the honest statement is: **over its one complete registered window, the lane's realized net was
negative.** Every `$100/day` projection in the candidate — 362 covers, 209 with PM fees removed, the
$9.95/36-cover figure — rests on the positive 3-cover subsample. This is a disclosure and framing
defect, not a post-hoc criterion change, but it inverts the sign of the headline.

## What the 3/13 conversion actually is — verified, and one raised objection refuted

Re-derived read-only from production over L141's exact window:

```
included_executions 108
states {'BOOK_MOVED': 95, 'ORDER_UNFILLED': 10, 'RECONCILED': 3}
PM_FIRST_LEG_SUBMITTED 13     PM_FIRST_LEG_FILLED 3     CONVERSION 0.23076923076923078
```

Exact match to `results.json`. It is **not** an artifact of the `10+3` coincidence: `measure.py:239`
counts real `orders` rows (`venue == "polymarket"`, `side` starting `buy_`), and independently no
`BOOK_MOVED` execution has any order row, so `BOOK_MOVED` genuinely is pre-wire. The three PM fees sum
to `$0.60932` exactly.

An audit dimension argued the 13 pools two F22 **maker** rests into a taker denominator, making the
role-consistent figure 3/11 = 27.3% or 4/12 = 33.3% — "exactly the one-third the verdict calls NOT
IDENTIFIABLE." **All three verifiers refuted this, correctly.** `spec.yaml:45` pre-registers
"observed fill conversion per submitted first-leg order" — role-agnostic by registration — and the
verdict never labels the denominator "taker". Re-scoping after seeing results, in the direction of the
operator's favored hypothesis, would be exactly the snooping AGENTS.md forbids; and reaching 33.3%
additionally requires un-excluding the pre-registered scalar cover. The conclusion is invariant
anyway: Wilson 95% CIs are 3/13 → [8.2, 50.3], 3/11 → [9.7, 56.6], 4/12 → [13.8, 60.9]. **All contain
33.3%.** "NOT IDENTIFIABLE" is right under every scoping.

Worth noting for transparency only: 2 of the 13 *are* maker rests (executions `785f1ce6…`, `9c19f3de…`,
the two pinned F22 sources). The verdict does not say so; the ledger's L102 note does.

### The cross-document number conflicts all reconcile

| Figure | Value | Reconciliation |
|---|---|---|
| Order rows incl. excluded exec | 18 | |
| Fees over all 18 | `$2.14449` | = GATE's four-cover figure |
| Excluded exec `17077a35` fees | `$0.74357` | |
| `2.14449 − 0.74357` | `$1.40092` | = L141's figure ✓ |
| Filled order rows, both legs | 8 | = spec's "eight filled orders" |
| PM first legs filled, excl. scalar | 3 | = L141's figure ✓ |

No number is wrong. But three documents use "submitted orders" and "filled" for three different
denominators — PM-first-leg-only, both-legs, with/without the scalar cover — without saying which,
and `spec.yaml`'s `known_at_registration` mixes two of them inside one sentence.

---

# The ~181 ms confirmation: already overlapped; removal saves ~65 ms

*(LAT-1, sustained)*

`nodes/execute/coordinator.py:218-222` submits the hedge read to a `ThreadPoolExecutor` and runs the
first-leg read on the calling thread. L141's own numbers prove it without reading code:
`first_leg_confirmation` p50 `168.42` + `hedge_confirmation` p50 `102.87` = `271.29`, against an
observed `decision_to_confirmation` p50 of `180.429`. That is `max()`, not `sum()`.

**The handoff's proposal to "overlap" the confirmation describes work already done.** And because the
hedge read remains on the critical path, *removing* the PM confirmation saves only the difference —
**~65 ms at p50 and ~0 ms at p90** — not 181 ms.

Removal is also EV-negative for a reason more specific than "bad-price fills": the FAK limit already
bounds the entry price, so the confirmation's real value is **L83's collateral ceiling**
(`coordinator.py:244`), the L95 downsize, the reprice, and the L102 evidence. Delete it and, because
Polymarket delivers collateral/`fill_price` shares, every price-improved taker fill over-delivers and
trips `_check_overfill`, which latches `kill/live`.

Both proposed successors were examined and neither is available as described:

- **(a) authenticated socket snapshot** — the only authenticated PM socket in this client
  (`client.py:90`, `PM_USER_WS`) carries order/trade events, not books. The book channel is the public
  one already supplying the stale ladder. There is nothing to snapshot.
- **(b) hedge-first / strict-limit IOC** — creates an over-hedged position the protection layer has no
  enabled path to close (`unwind_enabled = false`).

Finally, the 548 ms book age is **not** simply websocket-to-venue staleness — a verifier established
that a large part of it is Janus's own asyncio-loop work between snapshotting the book and entering
the machine. That is a different, more tractable target than either successor design, and no proposed
design touches it.

## A confound the spec does not acknowledge

The confirmation block is gated on `if not plan.first.post_only` (`coordinator.py:207`), so the maker
arm takes neither fresh read. It is not unguarded — it uses `grid._hedge_capacity_ok`
(`grid.py:1421`) — but that differs on **both** axes:

| | taker arm | maker arm |
|---|---|---|
| hedge book | fresh REST, venue-authoritative | loop-owned websocket replica |
| acceptance test | VWAP vs **break-even** (`coordinator.py:283`) | marginal vs `limit_price` **and** gross vs `hedge_budget` |

The comment at `coordinator.py:265-271` argues explicitly that break-even is the correct test and that
gating on budget "would refuse covers that still MAKE money." So the maker arm is held to a *stricter*
economic test on a *staler* book. The spec files hedging under `common:`, which is true of hedge
*execution* but not of the pre-entry *proof*. Since the spec is immutable, resolving this means a new
spec, not an edit.

---

# What passed

All three gates re-run in this tree, green:

| Gate | Result |
|---|---|
| Focused (7 files) | 172 passed, exit 0 |
| Full suite | passed, exit 0 |
| Replay rows digest | `13e4fb08a76c920f` — unchanged (9 columns of 1,093 `stream_evaluations` rows on a 63 s fixture) |
| Replay selections digest | `4f53cda18c2baa0c` — this is `sha256("[]")`: zero selections, so it checks nothing (corrected 2026-09-17) |

Verified sound:

- **Historical F22 evidence is not weakened.** `ops/f22_report.py:272` still returns
  `persistence_or_reconciliation_failure` on NULL fee, untouched by the diff.
- **Limits did not move.** `limits.toml` and `thresholds.py` byte-identical to `fa00a8d`;
  `release.sh` caps remain `"30 25 500 168"`.
- **Cohort separation holds.** Separate tables, separate assignment versions hashed into the digest,
  `_identity_matches` requires matching `forward_row_id`. No F22 row can enter an F23 estimate.
- **F22 is permanently disabled in capital mode** — `grid.py:877` is a hardcoded literal, and
  `f22_activation` is now called nowhere.
- **No crossover.** The maker path returns terminally on refusal/unfill; `plan_from_cover` is
  unreachable once `arm == "maker"`.
- **F23 minimums match the spec exactly** (200/80/50/5/3, seed 230915), and `_clustered_interval` is a
  genuine event-cluster bootstrap, with `PROVED_IMPROVEMENT` requiring `lower_95 > 0` strictly.
- **Venue-date handling is genuinely America/New_York and DST-correct** (both 2026 transitions
  checked); a malformed date leaves the five-day minimum unscored.
- **Layering holds.** Nothing under `nodes/` or `kernel/` imports `grids`.
- **`__pycache__` correctly not committed** — and already covered by `.gitignore:2`.

---

# Coverage gaps — read before relying on this

- **50 of 214 agents died on the token budget.** All 12 contradiction verifiers, three speed-path
  verifiers, the full three-way keep-or-kill panel, and the completeness critic never ran.
- Because of how the harness scores a finding with zero surviving verifiers, **C1–C12 and LAT-6/7/8
  appear as "refuted" in the raw output but were in fact never verified.** Do not read them as
  disproven. C1, C2 and C12 are reported above because I proved them directly myself; the remaining
  contradiction findings (C3–C11) are **unverified** and are not relied on here.
- **Two production reads were blocked** by this session's permission policy: the exact F22 decision
  rows 1/3, and the zero-F23-rows / quiet-capital state. Both are preconditions for a release this
  audit recommends against, but they remain unproven and must be proved before any future release.
- The keep-or-kill panel never ran, so the recommendation below is this agent's own judgment on the
  verified findings, not a synthesized panel verdict.

---

# Recommendations, in order

1. **Operator decides the authority question first.** Confirm the statement and the grant, or strike
   `GATE_TO_LIVE.md:173`. Nothing else should move before this.
2. **If struck:** correct all six locations in one change (`test_box.py:286` pins the string) and
   restore `release.sh`'s "the agent prepares it and never runs it" default.
3. **Do not run `ops/box/release.sh` under any authority until Blocker 3 is fixed.** The F22
   instrumentation route is not executable, and the digest pin does not protect against a later
   material-flag latch that leaves the kill file byte-identical. Add the `run.sh` wrapper and a
   `lane_flags` check before this route is ever trusted.
4. **Keep L140 and L142 — they fix real defects — but neither is finished.** L140 covers only the
   maker path; L142's bounded wait is correct but its scorer treats an ordinary timeout as an
   instrumentation STOP. Both must be completed before any cohort could run.

   The code does allow keeping them without starting F23, and this was verified rather than assumed:
   `grid.py:877` hard-disables F22; `grid.py:874` activates F23 only if the override matches
   `F23_OPERATOR_STATEMENT`. With both false, `grid.py:633` gives `active_row = None` and the lane runs
   the ordinary taker path with no cohort and no refusal. **The only action that starts F23 is writing
   an override containing that exact statement.**
5. **Do not re-register the "overlap the confirmation" work** — it exists. If latency is the target,
   aim at the asyncio-loop time inside the 548 ms book age, which nothing currently addresses.
6. **Correct the economics disclosure.** The one complete registered window realized **−$0.16449**
   across four settled covers. Any `$100/day` sizing should start there, not from the positive 3-cover
   subsample.
7. **Treat F23 as not worth preserving in its current form.** Even with authority granted and both
   blockers fixed, it is unpowered at its own registered stopping rule (t ≈ 0.36) and answers a
   ~$0.20-per-cover question. A redesign would need a different estimand — per *filled cover*, not per
   eligible decision — and a sample size derived from the effect it hopes to detect.
8. **For the $100/day objective, the two-leg co-listed sports surface is the wrong instrument** —
   closing the gap needs a ~77× product increase in (windows/day × conversion × net/cover), and fees
   plus conversion together supply at most ~10×.

   > **CORRECTION 2026-09-16 — MM-at-open is not the answer either. This recommendation originally
   > called it "plausibly $100/day-scale" and repeated a verifier's "$39/day, raise per-venue
   > capital." Both are wrong.**
   >
   > Worked from `nodes/risk/limits.toml` and `nodes/risk/clearance.py`: a pair costs ~$0.9625 and
   > earns 3.75c. `CAP_CONTRACTS=25` binds candidate size at $0.9375; `day_notional_usd=500` caps the
   > day near **$19.48**; `events.max_simultaneous=6` binds standing capital at $144.4 — under the
   > $250 per-venue Kalshi cap, **which never binds**, so raising it changes nothing. Capital releases
   > only after `nodes/reconcile` settles both sides, so the realistic ceiling is **$5.63/day at one
   > turn, $11.25/day at two.** The $39 figure reconciles only by double-counting +4.10c on both fills
   > of a pair, when `AGENTS.md:106` gives the both-sides number separately as +3.75c/pair.
   >
   > The evidence is also thinner than the one-liner suggests. Per `git show bd00b85`: **KXBTC15M
   > only**, a **~5-second** window, and *"the fill layer is MODELLED"* — an explicit upper bound at
   > tier MOD, whose own brief says *"declare the BTC episode set unreadable for Janus."* Its paired
   > Polymarket control had filled windows settle **−22c against +9.4c unfilled**, a 31c gap that is
   > precisely the adverse selection the headline assumes is ≈0. Source tables are gone from Kilos.
   >
   > And it is a large build, not a variation: `plan.py:45` hardcodes the venue pair,
   > `capacity.py:162` drops single-venue covers, Kalshi `post_only` is hardcoded `False`
   > (`exec_kalshi/client.py:72`), `execution_protocol.py:78` forbids `post_only` on `buy_no` — half
   > of any two-sided quote — and the Kalshi demo round-trip has never run. Worst: 35.8% both-sided
   > means **64.2% of quotes leave a naked position**, which under `unwind_enabled=false` +
   > `protect_kill_on_failure=true` **latches `kill/live`**.
   >
   > The next step is therefore neither lane, but the diagnostic that decides whether *any* two-leg
   > path exists: is the 6c decline gap latency or adverse selection? Registered as L143.
