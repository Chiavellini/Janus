# Mentions corpus — holdout declaration

> **Written 2026-07-25, BEFORE any mention-market outcome was read.** That ordering is the whole
> point; a holdout declared after looking is not a holdout.

## Why this exists

An overnight autonomous research loop is about to run over the mentions corpus. Testing many
hypotheses and reporting the best one is the single most reliable way to manufacture a false
positive, and this program has already been burned by it (Kilos row 8 sign-flipped −7.95pp on test
after looking strong on dev; the pooled HC arm went 0-for-2 out-of-sample). Unlimited descriptive
work is fine and cheap. Unlimited *adjudication* is not.

## The split

| Era | Definition | Use |
|---|---|---|
| **CHARACTERIZATION** | every mention market whose `close_time` is **strictly before 2026-07-25T00:00:00Z** | unlimited reading, base rates, calibration, hypothesis generation |
| **HOLDOUT (sealed)** | every mention market settling **on or after 2026-07-25T00:00:00Z** | **NEVER read** without an explicit per-run user approval naming this holdout |

The holdout is **forward-growing**, which is the cheapest possible design here: mention markets
settle continuously (Trump speaks daily, earnings calls run weekly, FOMC monthly), so power accrues
by itself at zero cost and nothing has to be withheld from the characterization corpus.

## Rules

1. The characterization era may be read without limit. It generates hypotheses; it **cannot
   confirm** one. Any number produced from it is descriptive and belongs in an `L#` ledger row.
2. A hypothesis is promoted only by a **numbered test look** against the holdout, with a
   `spec.yaml` whose criteria are written before the run and are immutable thereafter, and a
   `PENDING` row appended to `snooping_ledger.md` before the run.
3. BH-FDR threshold = `0.1 / m`, m = total rows in the Janus ledger at the time of the look. The
   overnight loop may queue as many candidate hypotheses as it likes; **each one it eventually
   spends makes the bar stricter for all the others.** That is the intended cost.
4. The overnight loop's output is a **ranked, pre-registered hypothesis queue** plus
   characterization — never a verdict.
5. "Proceed" / "go ahead" does **not** unseal the holdout. Approval must name it specifically.

## Enforcement

`lib/mentions_data.py` takes an explicit `era` argument and **defaults to `characterization`**.
Loading the holdout requires `era="holdout"` plus `allow_holdout=True`, and every such call is
appended to `research/mentions/holdout_access.log`. A read that does not appear in that log did
not happen through the sanctioned path.

## Status

| | |
|---|---|
| Declared | 2026-07-25 |
| Holdout reads to date | **0** |
| Test looks spent on mentions | **0** |
