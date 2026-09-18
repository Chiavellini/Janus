# F24 runbook — test whether the system makes money

**Status: authorised, not armed (2026-09-17).** Both approvals are recorded in `GATE_TO_LIVE.md`:
the operator's *"I approve"*, and a second amendment, *"I authorize you to arm, and yes, commit and
push everything"*, which lets the agent run `arm_f24.sh`. Arming is currently **blocked** by an
unresolved `ORPHAN_FILL` from the operator's own manual Kalshi trade; the quiet check refuses while
it stands, and the F22 kill is untouched.

## What this test is

The system trades the way it did before the maker/taker experiments: it buys on Polymarket, hedges on
Kalshi, and re-checks the Polymarket price right before every order. **Your current limits stay
exactly as they are.** No code is deployed.

It ends at the **first** of: 30 completed trades, 7 days, $50 of total losses, the $25 daily loss
limit tripping, or any safety alarm. It does not stop early on a good result, and it is not extended
on a promising one.

## What it can cost — read this part twice

**Only two of those limits stop anything by themselves** (independent audit, 2026-09-17):

| Limit | Enforced by | Real? |
|---|---|---|
| **$25 realised loss in a day** | the lane's breaker — but see below: it is a **gate on starting new trades**, not a cap on a day's loss | **partly** |
| **The authorisation expires after 7 days** | the box refuses to trade without a live authorisation | **yes, automatic** |
| $50 of total losses | **nobody** — it is a number printed by the progress report | **no** |
| 30 completed trades | **nobody** — same | **no** |

**What the $25 limit actually does** (`nodes/risk/breaker.py` on the deployed code): before starting a
trade, it adds up the money **already settled** so far **today** (UTC). If that is −$25 or worse, it
stops trading and latches the stop. It therefore does **not** cap a day's loss:

- Positions that are open, or filled but not yet settled, count for **nothing** until they settle —
  and sports positions usually settle hours later, often on the **next** UTC day.
- It is checked *before* a trade. Trades already in flight are not called back.
- A seven-day window touches **eight** UTC days, not seven.

So the honest unattended worst case is **roughly $200 by that arithmetic, plus whatever is still open
when it finally stops** — not $175, and not $50. Earlier drafts of this runbook said $50 and then
$175; both were too favourable.

The $50 and 30-trade limits are real only because **someone reads the progress report and stops it**.
The operator chose to run the full seven days with daily checks, so that is the arrangement:
**the report must be read at least once a day, and the test stopped by hand at $50.**

Per trade the bounds are automatic: at most **$30** committed per trade and **$500** committed per day.

## What you will learn

One of five answers, decided by rules fixed before the test starts:

| Answer | Meaning |
|---|---|
| **Loses money** | Total after 30 trades or 7 days is negative. |
| **Makes money, proven** | Positive, and the statistics say it isn't luck. |
| **Makes money, not proven** | Positive, but too few trades to rule out luck. **This is the most likely outcome even if the system works**, because one badly settled game can wipe out several good trades. |
| **Not enough trades** | Fewer than 10 completed. |
| **Stopped** | A safety condition fired. |

Thirty trades is a **go/no-go signal, not a proof.**

## What is already checked (2026-09-17, read-only)

| Check | Result |
|---|---|
| Lane running, real-money mode | yes, `LIMITED_LIVE` |
| Open trades, unhedged positions, open orders, open reservations | **0 / 0 / 0 / 0** |
| Unresolved safety alarms | **none** |
| The current stop | exactly the old F22 stop, unchanged |
| Deployed code | clean, matches the current authorisation |
| Progress report | reproduces the last measured day exactly (−$0.16 over four trades) |

## What you need to do

### 1. Approve it in your own words — **done 2026-09-17**

The recorded statement is *"I approve"*. Kept for reference, the shape that was asked for:

> *"I approve F24: run the plain taker lane at the current limits for up to 7 days or 30 completed
> trades, stopping at $50 of total losses."*

Your exact words go into the project's authorisation log, word for word, and into the arming file on
the box. **Nothing is written on your behalf.**

### 2. Decide who runs the arming step — **done 2026-09-17**

The operator authorised the agent: *"I authorize you to arm, and yes, commit and push everything"*, so
the agent runs `arm_f24.sh`. The first amendment had explicitly withheld that until the operator said
it in their own words.

### 3. The arming step

From the repository, on the Mac:

```bash
bash research/sports/2026-09-17_limited-live-f24-taker-profitability/arm_f24.sh "YOUR EXACT SENTENCE"
```

That is a **dry run**: it only prints what it would do. Read it, then add `--send` to do it:

```bash
bash research/sports/2026-09-17_limited-live-f24-taker-profitability/arm_f24.sh "YOUR EXACT SENTENCE" --send
```

It does four things, **in this order**, and stops at the first problem:

1. Confirms the lane is live, the stop is exactly the old F22 stop, and the account is quiet.
2. Writes a new authorisation with **no experiment attached** and the same limits.
3. **Waits for the system to confirm it has switched F22 off.** If that confirmation doesn't come,
   it stops and **leaves the safety stop in place.**
4. Only then moves the old stop into an archive folder. It is never deleted.

**Why the order matters:** the current authorisation still names F22. Clearing the stop first would
restart F22, which stops itself on the first unfilled order.

Whatever it prints, **it then reads the box itself** and ends with one of three answers:

- **`F24 IS ARMED`** (exit 0) — with the `start_utc` you need for progress checks.
- **`F24 IS NOT ARMED`** (exit 2) — the stop is in place and the old authorisation is untouched.
- **`F24 STATE IS INDETERMINATE`** (exit 3) — **do not re-run it.** Read the evidence printed above it.

**Why the third answer exists.** The tool that talks to the box stops listening after a few minutes
while the command keeps running there, and a Ctrl-C or a dropped connection does the same. So a
failure on your screen does **not** prove the box is unchanged: it may have finished arming after
your end gave up. Never conclude "nothing happened" from a local error.

**To ask at any time whether it is armed** (read-only, safe to run whenever):

```bash
bash research/sports/2026-09-17_limited-live-f24-taker-profitability/verify_f24.sh
```

If it ever says `INDETERMINATE` and the lane might be trading, stop it first (below), then sort it out.

## Checking progress

```bash
bash research/sports/2026-09-17_limited-live-f24-taker-profitability/check_f24.sh START_UTC
```

Replace `START_UTC` with the `start_utc` number printed at arming. The arming step also pins that
number on the box, and the report **refuses to run** if the number you type disagrees with it, so a
mistyped start cannot produce a fake verdict.

**Run this at least once a day** while the test is live: that is what enforces the $50 stop. It only reads data and changes
nothing. The result says `IN_PROGRESS` until an end condition is reached. Only a result with
`"ended": true` is the test's answer.

This command has been run for real against the last measured day, and it reproduced that day
exactly: 4 trades, −$0.16449.

## Stopping it at any time

```bash
bash ops/box/kill.sh live
```

This takes effect within five minutes. For an immediate stop, also run:

```bash
bash ops/box/run.sh 'systemctl stop janus-live-stream'
```

## Do not use these for this test

- **`ops/box/release.sh`**: it attaches the F23 experiment by default, and its route for clearing this
  particular stop cannot run.
- **`ops/box/write_override.sh`**: it always attaches an experiment.
- **Deploying any code**, including the prepared L149 book-resync fix. That would change what is being tested mid-test.

## The authorisation entries (already recorded)

Both are in `GATE_TO_LIVE.md`, dated 2026-09-17, with the operator's words quoted exactly. The first
registers F24 at unchanged limits; the second authorises the agent to run `arm_f24.sh` and withholds
everything else (no limit may be raised, no code deployed, no other kill cleared). The draft below is
kept only to show the shape that was agreed.

> | 2026-09-17 | **F24 may test whether the plain taker lane makes money, at unchanged limits.**
> Operator statement, verbatim: *"‹YOUR EXACT SENTENCE›"*. The historical immediate Polymarket taker
> entry runs with no experiment arm; F22 and F23 stay disabled. Limits remain **$30 combined planned
> stake / 25 requested contracts per leg / $500 committed daily notional**, $25 realised-loss breaker,
> $0.05 and 0.5 % hurdles, $2.50 / $0.10-per-contract protection, `protect_auto=true`,
> `unwind_enabled=false`. F24 ends at the first of 30 settled covers, 7 days, $50 cumulative realised
> loss, the breaker latching, any stop condition or override expiry, with no stopping on profit.
> ‹WHO RUNS IT: "The operator writes the override and clears the kill" **or** "The agent may run
> arm_f24.sh, which writes the override without an experiment and archives only the exact F22 kill
> after the lane confirms F22 disabled; any mismatch leaves the kill in place."›
> No code is deployed during F24. | Known at registration: the only fully measured window realised
> −$0.16449 over four covers; the account was verified quiet with no unresolved safety flag. |
