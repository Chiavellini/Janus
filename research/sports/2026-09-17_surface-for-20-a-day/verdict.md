# L147 verdict — the markets exist; the cap and conversion are what bind

**Registered verdict: `SURFACE_INSUFFICIENT_FOR_20`.** Median two-sided co-listed events came to
**28.2 a day**, below the registered 72.

**That verdict is not robust, and the evidence points the other way.** It is reported as registered
and not changed, but it should not be relied on.

Source: all **13** L28 census runs on the box, 2026-09-03 to 2026-09-16, none partial. The census job
is still running daily; the latest run finished 2026-09-16 18:06 UTC. Per-day figures scale the
census's 51-hour window by 24/51.

## Why the registered number is an artifact

The count the rule used, `two_sided_both`, can only include events whose Polymarket book the census
actually sampled — and it samples a bounded set each run. In every one of the 13 runs, the two-sided
count was **79–98% of the books sampled** (median 92%), and across runs it tracked that number with
**Pearson r = 0.94**. When the census sampled 88 books it found 86 two-sided events; when it sampled
59 it found 56.

So `two_sided_both` measures how many books were sampled, not how many two-sided markets exist. The
field was chosen from the census spec's definition before its population method was checked. This
is the third time in four rows that a registered statistic was right in intent and wrong in how it
was populated (L143's pooled rho, L144's favourable fraction, this).

## What the data does support

**Co-listed events are plentiful.** Median **116 a day**, ranging 101–309 across runs. And about
**92% of the events the census did sample were two-sided on both venues.** Applied to all co-listed
events, that suggests roughly **107 two-sided events a day** — *above* the 72 threshold. This is an
estimate: it assumes the round-robin sample represents the whole.

**So the surface is probably not the binding limit for $20/day.** Three other things are, each on
its own:

| Limit | What it allows | $20/day needs | $50/day needs |
|---|---|---|---|
| **Daily notional cap** ($500, filled covers count after settling) | ~24 covers → **~$6.67/day** at best | ~3× the cap | ~7–8× the cap |
| **Conversion** (observed ~0.08 profitable covers per engaged event) | ~4.7 covers/day | **0.61 per co-listed event — ~8× observed** | **1.5 per event — every event, more than once** |
| **Depth at the touch** (median per competition) | Kalshi $3–$33, Polymarket $5–$17 | ~$21 committed per cover | same, 2.5× as often |

The cap binds first: even with perfect conversion, the current signed limits stop the lane near
$6.67/day at the best observed profit per cover. Raising the cap alone does nothing while the lane
converts ~0.08 covers per event. And a ~$21 cover cannot be filled from a few dollars at the touch —
it must walk down the book, which is precisely where L146 showed the Polymarket replica can carry
levels that do not exist.

## Plain reading

- **$20/day:** the markets are probably there. Reaching it needs roughly 8× the lane's current
  ability to turn a co-listed event into a profitable cover, *and* a higher daily cap. Neither is
  established.
- **$50/day:** needs more than one profitable cover on every co-listed event every day. That is not
  plausible on this mechanism.
- **Under the current limits:** about $6.67/day is the ceiling, and only if every allowed cover were
  profitable. The one fully measured day was a loss.

All profit-per-cover figures use $0.28, **a best case**: including the one losing scalar cover, the
L141 window netted −$0.16 over four covers.

## Limits of this row

A co-listed event is necessary for a cover, not sufficient. This row says nothing about whether
covers on these events would be profitable — only whether enough events exist. The two-sided
estimate rests on the census's sample being representative. Touch notional is the best level only;
depth below it is unmeasured here.

Read-only. No order, cap, code or production state changed. Raw output: `results_20260917.json`,
schema `janus.l147.surface_for_20_a_day.v1`, matching `measure.py`.
