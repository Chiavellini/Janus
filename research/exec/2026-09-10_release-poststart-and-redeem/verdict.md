# L68 verdict — release post-start and redemption integration

Status: **LOCAL AND ACTUAL-BOX READ-ONLY PASS; DEPLOYMENT PENDING**.

The d3237fa release failure had three independent causes. `sudo` removed
`JANUS_CLEAR_STARTED`, `ops/box/run.sh` printed a remote failure without returning nonzero, and the
redemption unit's `EnvironmentFile` replaced its earlier `JANUS_PYTHON` assignment so `run_node.sh`
used the trading interpreter. The last error was exactly `PackageNotFoundError` for
`polymarket-client`.

The candidate passes the epoch explicitly, returns nonzero for every non-Success SSM command,
shows the bounded redemption stderr log on failure, and overrides the redemption interpreter at
the final `zsh -c` execution boundary. Live-clear now retains the exact kill while warming,
rechecks its digest before activation, restores its byte-identical contents and lane ownership on
failure, and will not clear any concurrent stronger incident.

Actual-box checks performed without clearing the kill or changing account state:

- a deliberately failing remote read returned local nonzero;
- the explicit sudo epoch reached the Python child and all Kalshi, Polymarket market and
  authenticated-user streams were connected and fresh;
- `systemd-analyze verify` accepted the candidate redemption unit;
- `/opt/janus/.redeem-venv` reports `polymarket-client==0.9.0`;
- the candidate's `SdkAdapter` authenticated and read 75 positions, of which two had positive
  redeemable value, without invoking submission.

The complete repository suite, focused release/clear/recovery/redemption tests, watchdog selftest,
compileall, YAML parsing, shell syntax and `git diff --check` pass. Production still runs d3237fa;
the candidate service has not redeemed anything yet. Deployment and the service's first actual
idempotent pass remain pending.
