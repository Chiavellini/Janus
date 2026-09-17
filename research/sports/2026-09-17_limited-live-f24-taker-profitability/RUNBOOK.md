# F24 runbook — test whether the system makes money

**Status: prepared, not started.** Nothing here runs until you approve it in your own words.

## What this test is

The system trades the way it did before the maker/taker experiments: it buys on Polymarket, hedges on
Kalshi, and re-checks the Polymarket price right before every order. **Your current limits stay
exactly as they are.** No code is deployed.

It stops at the **first** of:

- **30 completed trades**, or
- **7 days**, or
- **$50 of total losses**, or
- the **$25 daily loss limit** tripping, or
- any safety alarm.

It does not stop early on a good result, and it is not extended on a promising one.

## What it can cost

- At most **$25 in any single day**, because the existing daily limit stops trading.
- At most about **$50 in total**, because the test stops there.
- Each trade commits at most **$30**, and at most **$500** is committed per day.

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

### 1. Approve it in your own words

Write one sentence saying you approve this test. For example:

> *"I approve F24: run the plain taker lane at the current limits for up to 7 days or 30 completed
> trades, stopping at $50 of total losses."*

Your exact words go into the project's authorisation log, word for word, and into the arming file on
the box. **Nothing is written on your behalf.**

### 2. Decide who runs the arming step

- **You run it** (the project's default), or
- **You authorise me to run it.** The authorisation log will say so in your words, as it did on
  2026-09-07.

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

It prints `F24_ARMED` and a `start_utc=` time on success, or `F24_ARM_ABORTED: <reason>` and changes
nothing else.

## Checking progress

```bash
bash research/sports/2026-09-17_limited-live-f24-taker-profitability/check_f24.sh START_UTC
```

Replace `START_UTC` with the `start_utc` number printed at arming. It only reads data and changes
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

## Draft authorisation entry

This is **not yet in `GATE_TO_LIVE.md`.** It is added only after you give your sentence, with that
sentence pasted in exactly.

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
