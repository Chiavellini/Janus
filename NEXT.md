# NEXT

*An opinion, not a record. Overwrite this file; never append to it and never create a second one.
What changed is `git log`. Where we are is the run index. Why a decision was made belongs in a
commit message.*

Updated 2026-09-02.

## Done

Substrate. Version control, the crash-loop fix, the watchdog, a visible test suite, and the node
layout. Four legacy tracks and six collectors removed; ledger rows F1/F2/L24 closed.

## Now

1. **`kernel/grid.py`** — `Fault`, `Cell`, `Node`, `fanout`, the run manifest. No callers at first.
   Node boundaries return typed faults as values instead of raising, so a run yields a fault map
   rather than a traceback and one league's ESPN 500 stops being fatal.
2. **Strangle `grids/live_sports`** onto it. No existing function body gets rewritten — nodes are
   thin adapters that translate existing failure modes into declared fault codes.
3. **`nodes/rules_exhaustive`** — mint `ExhaustiveOutcomeSet` from a rule table that requires a
   citation. `nodes/cover.price_combination` takes the token instead of a bool. EPL and NFL start
   faulting loudly instead of printing +31% covers.
4. **`nodes/settle_wedge`** — the classifier `kernel/schema.py` already claims exists.
5. **Coverage** — per-league slug patterns, widen the window, wire `venue_sxbet` into the live
   grid. Only after 3.

## Not now, deliberately

Ashburn/EC2, any order path, and `venue_cloudbet`. Cloudbet's acceptance-before-pricing sequencing
makes its leg a naked directional bet; SX Bet is the cheaper, two-sided replacement and its parser
already exists.

## The question that actually matters

Not "did we find an arb". It is: **what is the distribution of cover cost?** A binary
ACTIONABLE/NO_EDGE collapses four different conclusions — no price edge, no depth, stale quotes,
unproven rules — into one uninformative null. Capture, replay, and a CDF per league and quantity
answer it. That needs a new pre-registered row before it runs.
