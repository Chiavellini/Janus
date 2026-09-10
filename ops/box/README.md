# ops/box — the Ashburn box

The box is in Mexico since 2026-09-07 (`mx-central-1`, `i-0a8c073c72dcdae11`; Polymarket geoblocks US addresses) and every script here defaults to it; `JANUS_BOX_REGION` / `JANUS_BOX_ID` point elsewhere (the Virginia box `i-0c86891ee306de0b8`, `us-east-1`, is stopped). `write_override.sh` defaults to the 2026-09-07 evening GATE caps: $12 / 10 contracts / $250 a day.

| File | What |
|---|---|
| `launch.sh` | Prints the launch plan; `--go` runs `aws ec2 run-instances` (operator; billable). |
| `user-data.sh` | cloud-init: packages, the data volume at `/srv/janus`, the repo at `/opt/janus` at the sha in SSM, a venv, the systemd units. |
| `creds.py`, `provision_redemption.py` | At every boot: SSM SecureStrings under `/janus/` into `/run/janus` (tmpfs, 700/600). The operator release provisions a complete PM builder credential once for gasless redemption. Values are never printed. |
| `latency.py` | Ledger L34: connect / TLS / first byte to the three venue hosts, the same on the Mac and the box. |
| `systemd/` | Credentials, live lane, watchdog, census and ten-minute PM redemption units; `janus.env` contains roots only, no secrets. |
| `release.sh`, `arm_statement.txt` | The operator's one paste: provision redemption, checkout, sync runtime/units, re-sign unchanged caps, restart LIMITED_LIVE, clear only a captured and fully proved false maker latch, verify streams, then run redemption. Money in flight refuses (`--now` overrides). |
| `sync_runtime.sh` | Installs the pinned official redemption SDK in a separate venv and refreshes systemd/credentials without changing the trading venv. |
| `clear_false_maker_latch.py/.sh` | Stops the lane, requires the exact captured false-latch digest plus terminal-zero journal/execution and globally quiet state, archives it, restarts, and restores the kill if streams fail. Not a general kill-clear command. |
| `update.sh`, `mode.sh`, `write_override.sh` | The three steps on their own. `update.sh` refuses to check out under a `LIMITED_LIVE` drop-in without `--no-restart`. |
| `kill.sh`, `kill_sync.py` | The cross-host kill: `kill.sh all\|live [--clear]` sets or clears `/janus/kill/{all,live}` in SSM; the box's watchdog job runs `kill_sync.py` (`JANUS_HOST=box` only) and mirrors them into `/srv/janus/kill`, never lifting a breaker's or a human's file. |
| `tests/` | The materialiser's modes and names, the latency arithmetic, the kill mirror. |

The contract is `ops/ASHBURN_SPORTS_RUNBOOK.md`.
