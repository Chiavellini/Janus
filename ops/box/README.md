# ops/box — the Ashburn box

| File | What |
|---|---|
| `launch.sh` | Prints the launch plan; `--go` runs `aws ec2 run-instances` (operator; billable). |
| `user-data.sh` | cloud-init: packages, the data volume at `/srv/janus`, the repo at `/opt/janus` at the sha in SSM, a venv, the systemd units. |
| `creds.py` | At every boot: SSM SecureStrings under `/janus/` into `/run/janus` (tmpfs, 700/600) and the env file the lane sources. Prints names, never values. |
| `latency.py` | Ledger L34: connect / TLS / first byte to the three venue hosts, the same on the Mac and the box. |
| `systemd/` | `janus-creds.service`, `janus-live-stream.service`, `janus-watchdog.timer`, `janus-census.timer`, `janus.env` (the roots; no secrets). |
| `tests/` | The materialiser's modes and names, the latency arithmetic. |

The contract is `ops/ASHBURN_SPORTS_RUNBOOK.md`.
