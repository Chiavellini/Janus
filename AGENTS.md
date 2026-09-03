# AGENTS.md — Janus cold start

> Everything you need to work this repo end-to-end. ~90 seconds.
> **This file contains no status.** Status goes stale; invariants do not. For where things stand,
> read `NEXT.md` (an opinion), `git log` (what changed), and `python3 ops/watchdog.py` (what is
> running).

## What Janus is

Executable **two-leg pure arbitrage on sports** across independent venues. Buy one outcome on
venue A, the complementary outcome on venue B, and require the combined cost — after fees,
executable depth, quote freshness and settlement rules — to guarantee a return.

It is **not** a forecast of the winner, and **not** a one-legged convergence bet on midpoint
divergence. If you find yourself scoring a mid, stop.

## Read order

1. This file
2. `README.md` — the grid map and the state of the evidence
3. `NEXT.md` — what to do next, and what is deliberately deferred
4. The `README.md` of whichever node you are touching
5. `GATE_TO_LIVE.md` — the promotion sequence to real capital
6. `snooping_ledger.md` — the multiple-testing ledger

## Sacred rules

### Pre-registration — always, before running anything
1. Write `research/<track>/YYYY-MM-DD_<slug>/spec.yaml` with success criteria **before** you run.
2. Append a `PENDING` row to `snooping_ledger.md` **before** you run.
3. Criteria in `spec.yaml` are **immutable**. Never edit them after seeing results.

Ledger rows are immutable too: correct one with a new row or an appended note, never in place.
BH-FDR threshold = `0.1 / m`, m = total rows at the time of the look. Forward-eval (`F#`) and
descriptive (`L#`) rows cost no look.

**Pre-registration guarantees the criteria are honest. It guarantees nothing about whether the
data is arriving.** Row F2 read `PENDING` for six days while its collector was crash-looping and
collecting nothing. Every forward row now carries an SLA in `ops/watchdog.py`.

### Never quote a mid
Every tradeability claim uses **executable prices** and walks the ladder. Mid-price scoring
produced phase 1's 47¢ ghost and 24 fictional arbitrages. `nodes/cover` never quotes the touch.

### Never compare two prices without measuring the basis between their settlement references
Stated as a venue rule it is too narrow — the real hazard is a settlement-reference rule, and it
applies **within** a venue too. An unmeasured basis is a BLOCK, not zero.

### An unknown ruleset is a BLOCK, not zero risk
The sports settlement wedge — cancellation → LFMP vs void-at-par; tie → $0.50 vs push; tennis
retirement; OT included except soccer — is the direct analogue of the measured 5.70%
opposite-settle rate that killed the crypto two-leg.

Enforced in code since 2026-09-02: `nodes/settle_wedge` harvests both venues' rules text, matches it
against reviewed templates, rules on twelve settlement dimensions per pair, prices the bounded ones
from registered measurements, and mints the `CoverProof` that `nodes/cover` requires. A template
nobody has read, a dimension nobody has ruled on, or a rate nobody has measured is a BLOCK.

### Match on a canonical key, never on title similarity
`league + {sorted participants} + start_time(±window) + market_type + period + line + side`. Both
venues anchor to an **external schedule** independently, turning an O(n·m) fuzzy problem into two
O(n) exact joins. Jaccard is *anti*-correlated with truth here: "Lakers vs Celtics Nov 3" and
"Lakers vs Celtics Nov 17" share nearly every token.

### `liquidity_source` deduplicates
Robinhood, Webull and IBKR all route to Kalshi's CLOB. Two legs sharing a liquidity source are an
accounting error, not an arbitrage.

### Disk safety
All Janus data goes to `data -> /Volumes/Kilos/janus/` — **never the root disk** (~10 GB free).
Check `df -h` before any bulk write. Never `rm` or `DROP TABLE` without explicit approval.

### Nothing is armed
No orders, no capital, `submit_enabled=False`. Starting the Ashburn EC2 instance is billable and
requires explicit operator approval.

## The 5 gates

G1 no structural/lookahead leak · G2 IC significance screen on train · G3 permutation test on the
test split (block-shuffle by `open_date`) · G4 robustness / 2× fee stress (CI excludes 0 at
stressed fees) · G5 sacred one-shot holdout.
**A gate fail is a STOP.** Never weaken a criterion or lower a threshold after seeing results.

## Architecture

Read `README.md` for the grid map. The layering rule, which is what makes failure attributable:

> **Grids import nodes. Nodes import the kernel. Nodes never import grids, and no grid imports
> another grid.**

Each node owns a directory, its tests, and a `README.md` describing its contract, its failure
modes and its position in the grid. Add a node the same way.

## Inherited findings — do not re-derive these

Measured and paid for in Kilos. They constrain the design; they are not Janus results.

- **Kalshi leads Polymarket by ~5–10 s.** PM reprices a ≥10 bps spot jump in median 2.2 s, and
  **36% of jumps are unrepriced within 60 s.** This is why a two-leg fill is not simultaneous.
- **Backtest EV does not carry to live 1:1.** Live basis entries tracked +3.05¢, not +4.45¢.
- **Filters do not transfer across mechanisms.** Never assemble a composite post-hoc.
- **An unresolved poll is not a no-fill.** Execution logs must separate a venue-authoritative
  no-fill from "no answer". Collapsing them overstates PnL and makes retries double-buy.
- **The two-leg fee floor is a venue-pair choice spanning 7.5×** — from 3.75¢ (Kalshi+PM, the most
  expensive pair available) down to 0.50¢. The sports lane still scans the expensive pair.
- **Kalshi MM-at-open**: +4.10¢/fill (n=3,196), adverse selection ≈ 0, **35.8% of markets fill both
  sides for a riskless +3.75¢/pair.** Never tested beyond BTC. This is the highest-evidence
  untested lead in the project and it needs no second venue.

## Working alongside other agents

Several agents share this repo. Before planning anything:

```bash
git status && git log --oneline -5
find . -newermt "-2 hours" -name "*.py" -not -path "./data/*"
```

A status summary handed to you — including the operator's — may describe the tree as it was. Prefer
`git worktree add` over sharing one working directory. State file ownership explicitly when working
in parallel.

## Objective

**EV¢ per trade + Sharpe per trade.** Volume and coverage are means, never ends. State the expected
EV effect of every proposed change.
