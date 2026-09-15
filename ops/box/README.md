# ops/box — the Ashburn box

The box is in Mexico since 2026-09-07 (`mx-central-1`, `i-0a8c073c72dcdae11`; Polymarket geoblocks US addresses) and every script here defaults to it; `JANUS_BOX_REGION` / `JANUS_BOX_ID` point elsewhere (the Virginia box `i-0c86891ee306de0b8`, `us-east-1`, is stopped). `write_override.sh` defaults to the 2026-09-07 evening GATE caps: $12 / 10 contracts / $250 a day.

| File | What |
|---|---|
| `launch.sh` | Prints the launch plan; `--go` runs `aws ec2 run-instances` (operator; billable). |
| `user-data.sh` | cloud-init: packages, the data volume at `/srv/janus`, the repo at `/opt/janus` at the sha in SSM, a venv, the systemd units. |
| `creds.py`, `provision_redemption.py` | At every boot: SSM SecureStrings under `/janus/` into `/run/janus` (tmpfs, 700/600). The operator release provisions a complete PM builder credential once for gasless redemption. Values are never printed. |
| `latency.py` | Ledger L34: connect / TLS / first byte to the three venue hosts, the same on the Mac and the box. |
| `systemd/` | Credentials, live lane, watchdog, census and ten-minute PM redemption units; `janus.env` contains roots only, no secrets. |
| `release.sh`, `arm_statement.txt`, `write_f23_override.sh` | The operator's one paste: provision redemption, checkout, sync runtime/units, re-sign unchanged caps plus the exact registered experiment spec/assignment/statement, restart LIMITED_LIVE, route only the three reviewed latch signatures to their independent helpers, verify streams, then run redemption. `write_f23_override.sh` only prepares the exact F23 authority and does not release or submit. The L133 guard route stays stopped until its helper owns the proof and restart. Unknown or malformed kill reasons hard-fail. Money in flight refuses (`--now` overrides). |
| `sync_runtime.sh` | Installs the pinned official redemption SDK in a separate venv and refreshes systemd/credentials without changing the trading venv. |
| `clear_false_maker_latch.py/.sh` | Stops the lane, requires the exact captured false-latch digest plus terminal-zero journal/execution and globally quiet state, archives it, restarts, and restores the kill if streams fail. Not a general kill-clear command. |
| `clear_legacy_incident_latch.py/.sh` | Operator-only L122 path for the one exact `flag=211` invalidation reason. Requires full kill/release SHAs, exact checkout, `match_incident(211)`, expected schema, all-venue/global quiet state and two stopped-lane guard passes; warms under the retained kill, then exclusively archives exact bytes. Never clears SSM or any other kill. |
| `clear_guard_failure_latch.py/.sh` | Operator-only L133 path for the one exact guard-failure kill and exact unresolved `GUARD_FAILED` set `{1169,1170}`. Requires the complete schema, zero money/admission/role/quantity/material-flag state, exact resolution of retained post-only history, two stopped credentialed complete-quiet guards with a fresh three-stream warm-up under the retained kill, then appends one joint `GUARD_FAILED_RESOLVED_EXACT` and exclusively archives unchanged kill bytes. Any failure restores exact bytes and leaves the lane stopped. |
| `update.sh`, `mode.sh`, `write_override.sh` | The three steps on their own. `update.sh` refuses to check out under a `LIMITED_LIVE` drop-in without `--no-restart`. |
| `kill.sh`, `kill_sync.py` | The cross-host kill: `kill.sh all\|live [--clear]` sets or clears `/janus/kill/{all,live}` in SSM; the box's watchdog job runs `kill_sync.py` (`JANUS_HOST=box` only) and mirrors them into `/srv/janus/kill`, never lifting a breaker's or a human's file. |
| `tests/` | The materialiser's modes and names, the latency arithmetic, the kill mirror. |

The contract is `ops/ASHBURN_SPORTS_RUNBOOK.md`.

`python3 ops/launchpad.py` — the launchpad: one read-only snapshot (`launchpad_extract.py` sent on stdin through run.sh, compressed under SSM's 24 KB output cap) rendered as a dark single page under `data/launchpad/`; `--every 300` refreshes, `--from FILE` renders a saved snapshot.

`bash ops/box/board.sh` — the board, live: an SSM port-forward to the box's loopback board service (`board_server.py`, unit `janus-board.service`, installed by the release) and the page at http://localhost:8797 (local port; the box side is 8787) — P&L strip, the games being polled with both books' best bid/ask refreshed every second, upcoming games, and one row per filled bundle.
F22 is closed for new live entries after the terminal maker zero-fill instrumentation STOP. The
historical F22 report remains read-only. `release.sh` and `write_override.sh` default to the fresh
F23 authority; the legacy F22 override is accepted only when explicitly named for a reviewed
read/recovery operation. The exact L140 recovery route is
`clear_f22_instrumentation_latch.sh`, pinned to kill SHA
`d81bbfc267a235ca7f268e7317d77ee7e83c65f5263117590e4e86d1552b1636`; it proves rows 1 and 3,
NULL fees, F23 absence and quiet capital while stopped, warms under the retained kill, reruns
complete guards, then archives only that kill before restarting under F23.
