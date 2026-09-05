# F3 — PAPER_EXECUTION, first window: STOPPED by its own rule (2026-09-05)

Window: first `[mode] PAPER_EXECUTION` line, 2026-09-03 23:36Z, to the STOP at 2026-09-05 00:49:35Z.
Declared n 30, extended to 33 by L36's 2026-09-04 04:28Z run. Reads no outcome as a result; this
verdict records why the window closed and what it exposed.

## The STOP

Spec criterion 2: "Every cleared cover is paper-hedged: `unhedged == 0` for all n. One unhedged
paper leg is a STOP and a design finding, not a statistic."

Execution `69852b86` (MIL @ CIN, `espn:mlb:401816802`, q=100, 2026-09-05 00:49:35Z): Polymarket
CIN YES 100 @ 0.13 FILLED; Kalshi MIL YES hedge at limit 0.8452 filled 64.18 @ 0.84 (attempt 1),
attempts 2 and 3 UNFILLED; state PARTIAL_FILL, **35.82 contracts unhedged**, reservation held
(watchdog UNRECONCILED_TOO_LONG for three hours).

**The design finding.** The pricer walked the Kalshi ladder `[0.84 x 64.18, 0.85 x 155, 0.86 x 10]`
to the 0.85 level for q=100 (VWAP 0.8436) and recorded `plan.hedge.limit_price = 0.85`. The
coordinator sent `plan.hedge_limit(first_paid)` = 1/1.01 − fee − 0.13 = **0.8452** as the IOC's
limit. That number is the most the hedge may AVERAGE for the cover to clear the hurdle -- a VWAP
budget -- but an IOC limit is per level: the paper venue (and any real one) fills nothing above
it. The 0.84 level filled, the 0.85 level did not, and attempts 2 and 3 resent the same limit
against the same consumed book. Fixed at `30c8511`: the hedge limit is the walked level less any
leg-A overpay, floored to the tick; the budget is recorded beside every attempt; a hedge averaging
above it is labelled ABOVE_BUDGET. The exact ladders are the fixture `MIL_CIN_2026_09_04`; under
the fix the hedge fills 100 at 0.8436.

## What else the window exposed

- **The predicate was uncountable.** `cleared_cover` = an opportunity reaching EXECUTION_PENDING;
  `opportunity_transitions` held zero such rows against four executions, because the coordinator
  updated the opportunities row without its transition (`OpportunityStore.move`, `30c8511`).
- **Nothing settled a failed hedge.** The settlement pass selected HEDGED only; PARTIAL_FILL held
  its reservation indefinitely. Holding failures now settle (cover part + directional remainder).
- **The lane died once, unseen.** SIGBUS (exit 138; the host paging, 63 MB free, 5.5 GB swap) at
  2026-09-05 03:35:05Z after 24 h; launchd restarted it in 1 s; no alarm (`SIGNAL_EXIT`, `580e6c9`).
- **Paper fees were zero.** Every paper order recorded fee_usd 0.0; STL @ LAD's +$5.00 is gross.
- **142 LEAGUE_EXPOSURE refusals, all cfb**, as the spec said to expect; caps added 2026-09-05.
- **Soccer never spawned.** Two co-listed European games blocked at TEMPLATE_UNKNOWN (Polymarket
  changed its soccer text); the reason was never printed or persisted (`c80f5f3`).

## The executions (4, all MLB) -- reported, claimed as nothing

| execution | game | started (UTC) | q | state | leg A | leg B | unhedged | settled |
|---|---|---|---|---|---|---|---|---|
| de5e4aed | STL @ LAD | 2026-09-04 03:05:43 | 100 | RECONCILED | 100 @ 0.45 (PM LAD YES) | 100 @ 0.50 (K NO on LAD) | 0 | +$5.00 gross, 08:14:45Z |
| 69852b86 | MIL @ CIN | 2026-09-05 00:49:35 | 100 | PARTIAL_FILL | 100 @ 0.13 | 64.18 @ 0.84 | **35.82** | the settlement pass, after `30c8511` |
| e39daa29 | ATH @ SEA | 2026-09-05 02:40:21 | 100 | HEDGED | 100 @ 0.17 | 100 @ 0.80 | 0 | pending |
| c03fe4fb | TB @ TEX | 2026-09-05 03:05:58 | 5 | HEDGED | 5 @ 0.83 | 5 @ 0.02 | 0 | pending |

Refusals since the row opened: CLOCK_UNHEALTHY 10,739 (before the A1 clock fix), LEAGUE_EXPOSURE
142 (cfb), EVENT_IN_FLIGHT 91, MAX_EVENTS 9.

No mean paper return is reported: n is 3 hedged of 4, the STOP fired, and the window is void from
the SIGBUS gap regardless. The successor row is F5 (`research/sports/2026-09-05_paper-execution-f5`),
a new clock, n from L36's run at its registration.
