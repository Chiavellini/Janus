# F24 pre-flight, read-only, 2026-09-17T19:05:31Z

Repeated with the box's own code, immediately after the GATE amendment was appended and before any
arming. Nothing was written to the box.

| Check | Reading |
|---|---|
| `systemctl is-active janus-live-stream` | `active`, `SubState=running`, `NRestarts=0`, main process up since 2026-09-15 20:24:07 UTC |
| Mode | `ExecStart ... --mode LIMITED_LIVE --report-period 60` |
| `kill/live` | present, SHA-256 `d81bbfc267a235ca7f268e7317d77ee7e83c65f5263117590e4e86d1552b1636` — the exact F22 STOP, latched `1789504505.261733` |
| Override (`/srv/janus/kill/arming_override.json`) | still pinned to **F22**: `experiment.row_id=F22`, `mode=LIMITED_LIVE`, caps `stake 30 / contracts 25 / day notional 500`, `runner_sha=59dd5ae2ce3619104aa95d127d1b115d7c0702a9`, `signed_by=Bernardo`, expires `2026-09-22T20:22:36Z` |
| Lane log | last authority markers are `[f22] ENABLED: F22 authority matches preregistration`; no later `[arm] STALE` |
| Quiet check (the identical block `arm_f24.sh` runs, via `nodes/risk/flags.unresolved_flag_rows` on the box's deployed code) | `unreleased 0, unhedged 0, open_orders 0, open_reservations 0`; **all thirteen material flag kinds unresolved-count 0** → `quiet check: OK`, exit 0 |
| Activity since the kill latched | **0** executions and **0** orders submitted |
| Unsettled covers | 0; `settlement_pending` 0 |

The two `PARTIAL` order rows in the store are historical (2026-09-12 Kalshi, 2026-09-13 Polymarket),
both `open=0` and `settlement_pending=0`, from the earlier `guard_fills` FIFO episode; they are
closed and are not open exposure.

The override expires **2026-09-22T20:22:36Z**. `arm_f24.sh` writes a fresh 168-hour override, so the
F24 window is governed by the new expiry, not this one.
