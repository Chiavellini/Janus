# Track B — launch prompt

Copy the block below into a fresh Claude Code session started in `/Users/bernardodelrio/Code/Janus`.

---

```
You are taking Track B of the Janus project: investigating high-frequency and quantitative
trading strategies on Kalshi, Polymarket and IBKR. Another agent is running Track A
(multi-venue sports arbitrage) in parallel. You share lib/ and the snooping ledger with it —
coordinate before editing shared modules.

READ THESE FIRST, IN ORDER:
1. handoffs/TRACK_B_BRIEF.md   <- your brief. Everything below is elaborated there.
   Read section 4b (ADDENDUM) too — the brief was issued 2026-08-14 and Track A has since
   completed Stages 0 and 1. lib/fees/, lib/schema.py and lib/venues/ now EXIST; do not
   rebuild them. lib/venue_costs.py is frozen as the regression anchor.
2. AGENTS.md                    <- the constitution: sacred rules, inherited findings, the 5 gates
3. 1ST_INVESTIGATION.md         <- what phase 1 killed and why. Read its §7 corrections table twice.
4. /Users/bernardodelrio/Downloads/quant_strategies_rentech_citadel.pdf  <- the source taxonomy

THE OPERATOR'S HYPOTHESIS, WHICH YOU ARE TESTING:
"HFT strategies in particular should be extremely inefficient in Kalshi and PM; they are
drastically different from regular exchanges yet offer somewhat similar instruments."

The brief argues this is half right, and that the correct scoping law is:

    These venues are inefficient in LIQUIDITY PROVISION, not in PRICE. The price is anchored
    by an underlying anyone can observe for free. What is missing is anyone willing to quote
    in the first five seconds.

That cut kills roughly two-thirds of the paper's ~25 strategy families. §5 of the brief gives
the full mapping with reasons. Do not accept it on my authority — it is an argument, and if
you find it wrong, say so and show why.

YOUR MANDATE IS RESEARCH AND BACKTEST ONLY.
state.yaml has arming_allowed: false. Nothing goes in a live book. Several questions you will
want to answer — queue position, realized fill rate, your own adverse selection — are
genuinely unanswerable without resting orders. §8 of the brief lists them. When you hit one,
name it as out of scope and add it to the costed Phase-F proposal. Do NOT model it silently
and report the model as a measurement.

BEFORE YOU START, RUN THESE — they should all be green, and if they are not, say so before
doing anything else:
    python3 tests/test_lib.py          # 13/13
    python3 tests/test_schema_fees.py  # ALL PASS
    python3 tests/test_spine.py        # 16/16

GOVERNANCE (binding):
- Pre-register: research/<track>/YYYY-MM-DD_<slug>/spec.yaml with success criteria BEFORE you
  run, plus a PENDING row in snooping_ledger.md BEFORE you run. Criteria are immutable after.
- Budget starts at 0 test looks. BH-FDR threshold = 0.1/m, m = ledger rows. Characterization
  rows (L#) are free; use them aggressively.
- A gate fail is a STOP. Never weaken a criterion after seeing results.
- Every claim carries an evidence tier: M1 (you measured it directly, output inspected) /
  M2 (a subagent measured it) / R (published source) / MOD (computed from assumed inputs) /
  U (unverified). TIERS PROPAGATE AS A MINIMUM. A number built from M1 quotes and a MODELLED
  fill is MOD, not M1. This project has already been burned once by a modelled number reported
  as a finding.
- All data to data -> /Volumes/Kilos/janus/. Never the root disk. Read-only toward ~/Code/Kilos.

START HERE — Phase A, then Phase B. Both spend ZERO snooping budget.

Phase A (days 1-4): Kalshi RSA-PSS auth + WebSocket, then an episode sampler across all 19
fifteen_min series. Note two things the brief establishes and that you should verify yourself:
only BTC Kalshi data currently exists, so every non-BTC question is a COLLECTION problem; and
the authenticated WebSocket is a precondition rather than an optimization, because 19 series
polling at 1 Hz is ~190 tokens/s against a 200/s Basic-tier ceiling and they all open on the
same :00/:15/:30/:45 instant.
Checkpoint: >=98% window capture on >=12 series over 72h, with capture completeness reported
CONDITIONAL ON REALIZED VOLATILITY (see trap 2 — this is not optional).

Phase B (days 4-10): does the opening spread collapse (24c -> 2c in 5s, measured on KXBTC15M)
occur on non-BTC series at all? Criterion: spread(t=0) - spread(t=5s) >= 10c on >=3 non-BTC
series with >=200 windows each.
If it does not, the flagship hypothesis is falsified in its strongest form, and you learned it
in ten days for zero budget. That is a good outcome. Report it plainly.

BEFORE YOU WRITE ANY IMBALANCE FEATURE, read trap 1 in §9. Kalshi's orderbook API returns BIDS
ONLY — YES asks exist only as NO bids — so a naive order-book-imbalance feature contains the
mid and will predict it circularly with a beautiful IC. The mandatory test is that imbalance
must be antisymmetric under the YES<->NO relabelling: I(yes) = -I(no). I rate this the single
most likely source of a confident false result in your program.

One inherited number you must treat carefully: MM-at-open on KXBTC15M measured +4.10c/fill
(n=3,196) with adverse selection near zero. That is your flagship lead AND an upper bound —
it assumes you were filled at an observed touch on a book you were not in. The quotes are M1;
the fill layer is MODELLED. The inherited Polymarket result is the proof this matters: filled
windows settled -22c while unfilled windows carried +9.4c, a 31c gap.

Finally: that BTC episode data is registered in the sibling Kilos project as its snooping row
20 with a forward clock from 2026-07-21, which overlaps it exactly. Declare it unreadable for
Janus, enforce that in lib/kilos_data.py, use the published BTC figures as a PRIOR only, and
collect fresh on the six untested series where Kilos has no claim.

Work carefully, verify your own claims against live APIs rather than relaying them, and tell
the operator when something is unknown rather than filling the gap with a plausible number.
```
