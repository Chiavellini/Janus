# ops/box — the Ashburn box

The box is in Mexico since 2026-09-07 (`mx-central-1`, `i-0a8c073c72dcdae11`; Polymarket geoblocks US addresses) and every script here defaults to it; `JANUS_BOX_REGION` / `JANUS_BOX_ID` point elsewhere (the Virginia box `i-0c86891ee306de0b8`, `us-east-1`, is stopped). `write_override.sh` defaults to the 2026-09-07 evening GATE caps: $12 / 10 contracts / $250 a day.

| File | What |
|---|---|
| `launch.sh` | Prints the launch plan; `--go` runs `aws ec2 run-instances` (operator; billable). |
| `user-data.sh` | cloud-init: packages, the data volume at `/srv/janus`, the repo at `/opt/janus` at the sha in SSM, a venv, the systemd units. |
| `creds.py` | At every boot: SSM SecureStrings under `/janus/` into `/run/janus` (tmpfs, 700/600) and the env file the lane sources. Prints names, never values. |
| `latency.py` | Ledger L34: connect / TLS / first byte to the three venue hosts, the same on the Mac and the box. |
| `systemd/` | `janus-creds.service`, `janus-live-stream.service`, `janus-watchdog.timer`, `janus-census.timer`, `janus.env` (the roots; no secrets). |
| `release.sh`, `arm_statement.txt` | The operator's daily paste under the arm: `update.sh <sha> --no-restart`, `write_override.sh` at the F8 caps with the standing statement, `mode.sh LIMITED_LIVE`. Refuses while a co-listed game is in play (`--now` overrides). |
| `update.sh`, `mode.sh`, `write_override.sh` | The three steps on their own. `update.sh` refuses to check out under a `LIMITED_LIVE` drop-in without `--no-restart`. |
| `kill.sh`, `kill_sync.py` | The cross-host kill: `kill.sh all\|live [--clear]` sets or clears `/janus/kill/{all,live}` in SSM; the box's watchdog job runs `kill_sync.py` (`JANUS_HOST=box` only) and mirrors them into `/srv/janus/kill`, never lifting a breaker's or a human's file. |
| `tests/` | The materialiser's modes and names, the latency arithmetic, the kill mirror. |

The contract is `ops/ASHBURN_SPORTS_RUNBOOK.md`.
