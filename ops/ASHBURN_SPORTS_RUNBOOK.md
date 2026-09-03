# Ashburn box — runbook (rewritten 2026-09-03)

The previous text launched the retired REST lane with flags the current grid does not have and
named a directory nothing uses. This is the deployment contract for the box the operator approved
on 2026-09-03: **one `c7g.medium` in us-east-1, SSM access only, first an observation host, an
execution host only if ledger L34 says so.** Starting it is billable (~$0.036/h + 70 GB gp3);
`aws ec2 stop-instances` stops the bill and keeps the data volume.

## What exists in the account (read 2026-09-03)
Default VPC `vpc-0de2c8819be9c7353`; security group `janus-box` (`sg-061f3bb3a68d29f81`, no
ingress); IAM role + instance profile `janus-box` (SSM core, `/janus/*` parameters with KMS
decrypt, CloudWatch); Ubuntu 24.04 arm64 AMI from the public SSM parameter. No Janus instance yet.

## One-time, operator
1. Push main to GitHub (the box clones the pinned sha) and create a read-only fine-grained token
   for the repo. Put the non-secret and secret parameters in SSM (values never pass through an
   agent):
   ```bash
   aws ssm put-parameter --region us-east-1 --name /janus/repo/url --type String --value https://github.com/Chiavellini/Janus.git
   ```
   ```bash
   aws ssm put-parameter --region us-east-1 --name /janus/repo/sha --type String --value <sha of main>
   ```
   Then, each as `--type SecureString` (KMS-encrypted with the account's SSM key):
   `/janus/repo/token`, `/janus/kalshi/api_key`, `/janus/kalshi/private_key` (the PEM file's
   contents), `/janus/polymarket/wallet_key`, `/janus/polymarket/funder`,
   `/janus/polymarket/signature_type`. `python3 ops/box/creds.py --dry-run` lists the names.
2. Launch: `ops/box/launch.sh` prints the plan; `ops/box/launch.sh --go` launches. cloud-init runs
   `ops/box/user-data.sh`: packages, the data volume at `/srv/janus`, the repo at `/opt/janus`
   at the pinned sha, a venv, the systemd units, and `janus-creds.service`, which materialises
   the secrets into `/run/janus` (tmpfs, 700/600) at every boot. `/var/log/janus-bootstrap.log`
   says what happened.
3. Session: `aws ssm start-session --target <instance id>` (needs the session-manager-plugin on
   the Mac: `brew install --cask session-manager-plugin`).

## On the box, in order
1. `cd /opt/janus && sudo -u janus JANUS_DATA_ROOT=/srv/janus .venv/bin/python3 -m pytest -q` — green.
2. The latency row (L34): `sudo -u janus .venv/bin/python3 ops/box/latency.py --host box --samples 100 --out /srv/janus/research/results_box_<ts>.json`
   in the same hour as the Mac's run; copy the file into the research directory and write the
   verdict against the bar in `research/infra/2026-09-03_ashburn-latency/spec.yaml`.
3. `systemctl enable --now janus-live-stream` (SHADOW_LIVE with capture; `--leagues enabled`).
   `janus-watchdog.timer` and `janus-census.timer` are already enabled by cloud-init.
4. `journalctl -u janus-live-stream -f`, `/srv/janus/logs/*.log`, and
   `sudo -u janus .venv/bin/python3 ops/watchdog.py` must be quiet.

## Arming from the box
Only after: both Mac proofs reconciled, L34 = EXECUTION_HOST, and an override written ON THE BOX
(`ops/arming_override.py` pins the runner sha of that checkout; the file lives under
`/srv/janus/kill/`). The box's kill files are its own: `kill/all` on the Mac does not stop the
box. Until a shared kill exists in SSM, stopping the box is `systemctl stop janus-live-stream`
or `aws ec2 stop-instances`.

## The data root
Everything the tree writes lives under `JANUS_DATA_ROOT` (`kernel/paths.py`), `/srv/janus` here
and `/Volumes/Kilos/janus` on the Mac. `ops/run_node.sh` aborts when either volume has under 2 GB
free.
