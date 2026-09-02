# Track B episode collector

Research-only collector for the Phase A capture gate and Phase B open-spread characterization.
There is no order-placement code in this surface.

## Preconditions

- `data` must resolve under `/Volumes/Kilos/janus` and the volume must have at least 2 GB free.
- Provision a Janus-specific Kalshi read key. Do not reuse/import Kilos configuration.
- Export only the key id and private-key path; the collector never prints either value.

```bash
export JANUS_KALSHI_API_KEY='...'
export JANUS_KALSHI_PRIVATE_KEY_PATH='/absolute/path/to/janus-read-key.pem'
```

### IBKR hedge-data gateway

IBKR is a hedge-instrument access layer, not an independent prediction venue. Its authenticated
session may be a live account, so every Janus request must go through `lib/ibkr_readonly.py`.
That client is fail-closed: loopback only, no redirects, exact research endpoints, quote-only
fields, and no order/trade/account-management path or topic.

The persistent gateway job is `com.janus.ibkr-gateway`; it keeps the Java process alive but cannot
and must not automate authentication. After the daily IBKR reset, visit
`https://localhost:5055`, complete 2FA manually, and verify `authenticated=true` before collection.
The registered capability probe is L13 at
`research/exec/2026-08-18_ibkr-readonly-capability/spec.yaml`.

## Verify, collect, report

```bash
python3 collectors/collect_track_b.py --self-test
python3 collectors/collect_track_b.py --public-probe
nice -n 19 python3 collectors/collect_track_b.py --duration-s 259200
python3 collectors/report_track_b.py --phase all
```

For the registered unattended soak, install `collectors/com.janus.track-b-collector.plist` as a
per-user LaunchAgent. It invokes `collectors/run_track_b.sh`, which reads the owner-only credential
file from `/Volumes/Kilos/janus/credentials/track_b.env`; no credential is embedded in the plist or
repository. The job is deliberately research-only and restarts after collector failures.

The 72-hour run writes `data/track_b/episodes.sqlite`, which resolves to the external volume.
Every expected `(venue, series, quarter-hour, offset)` has an independent row in `expectations`.
A market-discovery failure therefore becomes `market_not_discovered`; it cannot disappear from the
denominator. The report remains `PENDING_INSUFFICIENT_DURATION` until 72 hours exist and Phase B is
structurally blocked until Phase A passes.

## Evidence boundaries

- Quotes, spreads, trades, and displayed depth are M1 after output inspection.
- Displayed depth is not a realized fill rate.
- Queue position, own impact, quote-induced fading, maker-tier realization, and both-sides fill
  rate require resting orders and remain out of scope.
- `lib/kilos_data.py` denies SQLite reads of `kalshi_open_episode_samples`; the inherited BTC
  episode population is prior-only.

## IBKR gateway operations (updated 2026-08-18/19)

- **Service:** `com.janus.ibkr-gateway` (plist in `collectors/`, installed at `~/Library/LaunchAgents/`).
  It MUST run as `ProcessType Interactive` on this 8 GB host: as `Background` (priority 4) the JVM is
  compressed out and its outbound TLS handshake to `api.ibkr.com` misses Vert.x's hard-coded 10 s
  limit, so every `/v1/api` call hangs while TCP still accepts. `collectors/run_ibkr_gateway.sh`
  also sets `JAVA_TOOL_OPTIONS` (C1-only JIT, serial GC, small heap) so a cold JVM warms in <1 s.
- **Diagnose before blaming auth:** `sysctl vm.swapusage`, `uptime`, `ps -o pri -p <java pid>`,
  and `grep -c "handshake timed out" /Volumes/Kilos/janus/tools/clientportal.gw/logs/gw.message.*.log`.
  The gateway logs contain user/account/MAC identifiers — grep with redaction, never copy them.
- **Restart** (kills the brokerage session; the human must re-login + 2FA at https://localhost:5055):
  `launchctl bootout gui/$(id -u)/com.janus.ibkr-gateway; pkill -f GatewayStart;
  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.janus.ibkr-gateway.plist`
  (`bin/run.sh` does not `exec` java, so `bootout` alone orphans the JVM).
- **Health check (client only):** `python3 -c "from lib.ibkr_readonly import IBKRReadOnlyClient as C; print(C().auth_status())"`
  → HTTP 401 before login, `{authenticated: true, connected: true, competing: false}` after.
- **L13 (registered capability probe):** `python3 collectors/probe_ibkr.py` from the repo root.
  **WARNING: the probe OVERWRITES `verdict.md` with a short stub every run.** Copy it aside first
  (`cp verdict.md /tmp/verdict_before_run.md`); the `results_run*.json` files are the durable
  artifacts. Also `cp results.json results_run<N>_<utc>.json` after each run. Inspect
  `research/exec/2026-08-18_ibkr-readonly-capability/results.json` for redaction before quoting.
  2026-08-19 run 3 result: **PASS_HFT_READY** — MBT/ZQ `RB`, SPX/XSP options `RpBd`, after
  subscribing CME+CBOT+OPRA Real-Time (NP,L1) at $4.60/mo list. SPX/XSP *index* underlyings
  stay `Z` (CME S&P Indices not bought) and their `last` is stale AND wrong — do not use it
  as an underlying level. Runs 1-2 (pre-subscription) were `D*`. See `verdict.md`.
- **launchd + external volume:** a gui LaunchAgent CANNOT create `StandardOutPath`/`StandardErrorPath`
  on `/Volumes/Kilos` — the job dies with `EX_CONFIG` (exit 78) *before exec*, so there are no logs to
  explain it. Do the redirect inside the runner script instead (`run_ibkr_archive.sh`). Diagnose with
  `launchctl print gui/$(id -u)/<label> | grep "last exit code"`.
- **Forward archive (L16, REGISTERED 2026-08-19):** `collectors/collect_ibkr_archive.py --self-test`,
  then `--families <R* families only>`; plist `collectors/com.janus.ibkr-archive.plist` (not installed).
  Registered: `research/exec/2026-08-18_ibkr-forward-archive/spec.yaml`, ledger row L16.
  Requires a live gateway login; it records `AUTH_EXPIRED_MANUAL_LOGIN_REQUIRED` and self-heals when
  a human logs in. Login is NEVER automated.
  Report/gate: `python3 collectors/report_ibkr_archive.py`.
