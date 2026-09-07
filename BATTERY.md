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
| Kalshi execution proof (demo waived 2026-09-03) | **green** — second run 2026-09-07 02:56Z (`proofs/kalshi_20260907T025629Z.json`): 2 @ 0.78, resting bid cancelled and confirmed on the venue, fee charged 0.0241 = pinned, balance to the cent, settled +$0.4159 on the result, reservation released; **7 of 7 checks**. The first run's two failures (cancel shard routing, fee pin) stayed fixed. | `python3 ops/kalshi_live_proof.py --check proofs/kalshi_20260907T025629Z.json` |
| Live shadow evidence | **time** | `SHADOW_LIVE` (the default) under launchd on this tree, with frame capture, for the pre-computed n. Every row before 2026-09-02 carries a 2× Kalshi fee and does not count. |
| Fees reconciled against actual charges | **green** — Kalshi: 0.0241 charged vs 0.0241 pinned (2026-09-07). Polymarket, the venue's first real order (`proofs/polymarket_20260907T044255Z.json`, CLOB V2, pUSD): FOK 5 @ 0.39 filled 5.131577 @ 0.38 by notional; the balance moved by fills + exactly the pinned 0.0604 while the trade record reports fee_rate_bps 0; settled +$3.1816 on the result, reservation released; **7 of 7 checks**. | `python3 ops/polymarket_live_proof.py --check proofs/polymarket_20260907T044255Z.json` |
| Settlement equivalence measured | **code + ledger** | `nodes/settle_wedge` with ledger L26 (2,100 games; 0.476% late makeups; 0 cancellations). MLB certifies live. NFL templates reviewed 2026-09-03 (tie pays $0.50 a side on both venues) and its rates registered the same day (ledger L30: 4 of 2,640 games moved >48 h, 1 cancelled; 2020 excluded by decision) — NFL certifies. EPL, La Liga and the Bundesliga certify on ledger L33 (a round-window proxy over openfootball, labelled FLOOR: EPL 3.8%, La Liga 1.4%, Bundesliga 0.3% of matches played >48 h after their round). College football certifies on L32 (6 of 9,529 games moved >48 h, 17 cancelled; FLOOR for FCS). MLS has cited rules and reviewed templates and blocks at `EVIDENCE_UNMEASURED` (no round structure, no original-date source). NHL: Polymarket lists, Kalshi does not yet. |
| Pre-registered research and promotion gates | **operator** | GATE_TO_LIVE with its 2026-09-02 sports amendment; the arming override is a human artefact. |
| Slippage buffer measured | **ledger L27, re-runnable** | p95 adverse move at 3 s = one tick (2,152 samples, 8 tickers, one MLB evening). Registered as the frontier's default with `slippage_modelled=True`. Re-run after NFL/NBA traffic. |

## The clock is running

Since 2026-09-03 main carries this tree and `com.janus.live-stream` runs it. To redeploy after a
change on the branch:

```bash
cd /Users/bernardodelrio/Code/Janus && git merge --ff-only claude/janus-arbitrage-trader-4e6d4d
```

```bash
launchctl kickstart -k gui/$(id -u)/com.janus.live-stream
```

Then `python3 ops/watchdog.py` should be quiet, `/Volumes/Kilos/janus/frames/` should grow, and
`socket_health`, `events`, `equivalence_records` and `stream_evaluations` should fill with the
new vocabulary.
