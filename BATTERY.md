# BATTERY — the pre-capital tests, and who has to run them

Spec §14 lists what must pass before real capital. This file says, for each item, whether the
tree proves it on its own (`python3 -m pytest`, no network), whether it needs the live lane
running on this tree for a while, or whether it needs something only the operator has.

| Item | Status | What proves it |
|---|---|---|
| Frozen venue fixtures pass | **code** | Every venue node's `tests/` uses verbatim payloads captured 2026-09-02/03 (Kalshi orderbook and series, Gamma market and `feeSchedule`, both rules templates, socket frames). |
| WebSocket replay passes | **code + capture** | `nodes/replay`: a captured hour replays to the live rows with zero mismatches (done three times on 2026-09-03: 18, 40 and 27 rows). Needs the live lane running *this* tree so capture exists continuously. |
| Reconnect and sequence-gap tests | **code** | `nodes/stream_kalshi/tests` (gap → teardown → fresh subscription; per-sid sequencing; incremental subscription frames), `nodes/stream_polymarket/tests` (drift → forced resnapshot; reconnect marks replicas disconnected), `nodes/book_replica/tests`. |
| Partial-fill tests | **code** | `nodes/execute/tests`: the hedge is for exactly what leg A filled; a partial hedge leaves a recorded unhedged remainder and keeps the reservation. |
| Ambiguous-order recovery | **code** | `nodes/execute/tests`: an UNCONFIRMED leg A is polled, never resubmitted, kept if unknown, hedged if found filled. `nodes/exec_kalshi/tests`: recovery by client id. |
| Demo execution reconciled | **operator** | Needs Kalshi **demo credentials** (separate from production). Then `DEMO_EXECUTION` on the Kalshi leg: place → poll → cancel → settle, through `nodes/exec_kalshi` and `nodes/reconcile`. The grid refuses real-order modes until this is done once. |
| Live shadow evidence | **time** | `SHADOW_LIVE` (the default) under launchd on this tree, with frame capture, for the pre-computed n. Every row before 2026-09-02 carries a 2× Kalshi fee and does not count. |
| Fees reconciled against actual charges | **operator** | One $5 fill per venue under `LIMITED_LIVE` with the signed override; `nodes/reconcile.check_fees` compares the charged fee with the pinned curve at the series multiplier. An excess is a STOP and a re-pin. Polymarket additionally needs `pip install py-clob-client` and a 600-mode wallet key file. |
| Settlement equivalence measured | **code + ledger** | `nodes/settle_wedge` with ledger L26 (2,100 games; 0.476% late makeups; 0 cancellations). MLB certifies live; NFL/NHL block until their Polymarket game text is harvested and reviewed. |
| Pre-registered research and promotion gates | **operator** | GATE_TO_LIVE with its 2026-09-02 sports amendment; the arming override is a human artefact. |
| Slippage buffer measured | **capture + ledger row** | Not yet. `Frontier.slippage_modelled=False` caps the mode at PAPER. Needs a day of Kalshi frames from the live lane on this tree and a registered descriptive row (the distribution of best-ask moves inside the hedge window). |

## To start the clock

The launchd job `com.janus.live-stream` runs `/Users/bernardodelrio/Code/Janus` (main). This
work is on the branch `claude/janus-arbitrage-trader-4e6d4d`. Nothing accrues on this tree until
it is merged and the job restarted:

```bash
cd /Users/bernardodelrio/Code/Janus && git merge --ff-only claude/janus-arbitrage-trader-4e6d4d
```

```bash
launchctl kickstart -k gui/$(id -u)/com.janus.live-stream
```

Then `python3 ops/watchdog.py` should be quiet, `/Volumes/Kilos/janus/frames/` should grow, and
`socket_health`, `events`, `equivalence_records` and `stream_evaluations` should fill with the
new vocabulary.
