# Ashburn box — runbook (rewritten 2026-09-03)

The previous text launched the retired REST lane with flags the current grid does not have and
named a directory nothing uses. This is the deployment contract for the box the operator approved
on 2026-09-03: **one `c7g.medium` in us-east-1, SSM access only, the paper pilot's host (PAPER_EXECUTION, ledger F7), an
execution host only if ledger L34 says so.** Starting it is billable (~$0.036/h + 70 GB gp3);
`aws ec2 stop-instances` stops the bill and keeps the data volume.

## What exists in the account (read 2026-09-03)
Default VPC `vpc-0de2c8819be9c7353`; security group `janus-box` (`sg-061f3bb3a68d29f81`, no
ingress); IAM role + instance profile `janus-box` (SSM core, `/janus/*` parameters with KMS
decrypt, CloudWatch); Ubuntu 24.04 arm64 AMI from the public SSM parameter. No Janus instance yet.

## One-time, operator (2026-09-07: the exact list; nothing is retyped, nothing is echoed)

0. **IAM, once.** For this week's pilot the simplest path is to launch as the admin user: delete the
   admin's inline policy `EarshotDenyDirectBoxLaunch` (`aws iam delete-user-policy --user-name <admin>
   --policy-name EarshotDenyDirectBoxLaunch`). The alternative is to carve `iam:PassRole` for
   `arn:aws:iam::986420598115:role/janus-box` out of the `janus-scope` policy's `iam:*` Deny AND add an
   Allow for it (the committed `infra/iam/janus-agent-policy.json` has the Deny and no Allow). The
   instance profile must exist (each step tolerates "already exists"):
   ```bash
   cd /Users/bernardodelrio/Code/Janus && aws iam create-role --role-name janus-box --assume-role-policy-document file://infra/iam/janus-box-trust.json; aws iam put-role-policy --role-name janus-box --policy-name janus-box --policy-document file://infra/iam/janus-box-policy.json && aws iam create-instance-profile --instance-profile-name janus-box; aws iam add-role-to-instance-profile --instance-profile-name janus-box --role-name janus-box; aws iam attach-role-policy --role-name janus-box --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
   ```
1. **Push main** and create a read-only fine-grained GitHub token for the repo (Contents: read).
2. **SSM parameters.** The two pointers, then the six SecureStrings read from the local files so
   no value passes through a chat or a shell history:
   ```bash
   cd /Users/bernardodelrio/Code/Janus && aws ssm put-parameter --region us-east-1 --overwrite --name /janus/repo/url --type String --value https://github.com/Chiavellini/Janus.git && aws ssm put-parameter --region us-east-1 --overwrite --name /janus/repo/sha --type String --value "$(git rev-parse main)"
   ```
   ```bash
   set -a; source /Volumes/Kilos/janus/credentials/track_b.env; set +a; read -rs "T?GitHub read-only token: "; echo; aws ssm put-parameter --region us-east-1 --overwrite --type SecureString --name /janus/repo/token --value "$T" && aws ssm put-parameter --region us-east-1 --overwrite --type SecureString --name /janus/kalshi/api_key --value "$JANUS_KALSHI_API_KEY" && aws ssm put-parameter --region us-east-1 --overwrite --type SecureString --name /janus/kalshi/private_key --value "$(cat "$JANUS_KALSHI_PRIVATE_KEY_PATH")" && aws ssm put-parameter --region us-east-1 --overwrite --type SecureString --name /janus/polymarket/wallet_key --value "$(cat "$JANUS_PM_WALLET_KEY_PATH")" && aws ssm put-parameter --region us-east-1 --overwrite --type SecureString --name /janus/polymarket/funder --value "$JANUS_PM_FUNDER" && aws ssm put-parameter --region us-east-1 --overwrite --type SecureString --name /janus/polymarket/signature_type --value "$JANUS_PM_SIGNATURE_TYPE" && unset T && echo "six SecureStrings written"
   ```
   (`read -rs "T?…"` is zsh's silent prompt; in bash use `read -rs -p "…" T`.)
   `python3 ops/box/creds.py --dry-run` lists the names the box will read. Every time main moves,
   re-run the `/janus/repo/sha` line before a (re)launch: cloud-init checks out that sha.
3. **Launch** (billable; the operator says "launch"): `ops/box/launch.sh [--profile <name>]` prints
   the plan and the AMI it resolved and refuses to go without one; `--go` launches. When the
   launching principal cannot read public SSM parameters, pre-resolve
   `JANUS_BOX_AMI=$(aws ssm get-parameters --region us-east-1 --names /aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id --query 'Parameters[0].Value' --output text)`.
   cloud-init (`ops/box/user-data.sh`) installs packages (zsh included: every unit runs through it),
   the data volume at `/srv/janus`, the repo at `/opt/janus` at the pinned sha, a venv with the V2
   Polymarket client, the systemd units, and `janus-creds.service` (secrets into `/run/janus`,
   tmpfs, 700/600, at every boot). `/var/log/janus-bootstrap.log` says what happened.
4. **Session:** `aws ssm start-session --target <instance id>` (Mac side:
   `brew install --cask session-manager-plugin`).

## On the box, in order
1. `cd /opt/janus && sudo -u janus JANUS_DATA_ROOT=/srv/janus .venv/bin/python3 -m pytest -q` — green.
   `systemctl status janus-creds` — active (exit 2 names a missing SSM parameter).
2. **L34, the same hour on both hosts:** on the box
   `sudo -u janus .venv/bin/python3 ops/box/latency.py --host box --samples 100 --out /srv/janus/research/results_box_<ts>.json`,
   on the Mac `python3 ops/box/latency.py --host mac --samples 100 --out research/infra/2026-09-03_ashburn-latency/results_mac_<ts>.json`
   within the same hour; copy the box file into the research directory; write `verdict.md` against
   the bar in the spec (box p50 to Kalshi AND the CLOB under half the Mac's, the CLOB answering 200;
   a 403 from the CLOB is a finding and fails the bar). The 2026-09-03 Mac file is a reference, not
   the comparator.
3. `systemctl enable --now janus-live-stream` — **PAPER_EXECUTION** on the enabled leagues: the
   box's own paper series, ledger row F7 (registered before this line runs). `janus-watchdog.timer`
   and `janus-census.timer` are already enabled by cloud-init. The daily resolver and the
   football-data job stay on the Mac; the box's watchdog knows (`JANUS_HOST=box` selects its SLA set).
4. `journalctl -u janus-live-stream -f`, `/srv/janus/logs/*.log`, and
   `sudo -u janus .venv/bin/python3 ops/watchdog.py` quiet; `loop` on the report line under 0.1 s.
5. After 48 h without a `SIGNAL_EXIT` on the box: stop the Mac's lane
   (`launchctl bootout gui/$(id -u)/com.janus.live-stream`), close F5 with its count, keep the Mac's
   three daily jobs.

## Arming from the box
Only after: both Mac proofs reconciled, L34 = EXECUTION_HOST, and an override written ON THE BOX
(`ops/arming_override.py` pins the code tree of that checkout -- `kernel/code_sha`: nodes, grids,
kernel, the runner, the box units -- and its `limits.toml`; the file lives under
`/srv/janus/kill/`). The box's kill FILES are its own: `kill/all` on the Mac does not stop the
box. The shared kill is in SSM (below); the fast stop is `systemctl stop janus-live-stream`
(`ops/box/run.sh`) or `aws ec2 stop-instances`.

## The daily release under the arm (2026-09-07)
The override pins the executable tree, so a docs or research commit does not invalidate it and a
code commit does; the lane re-reads the override every report tick and refuses real orders
(`ARM_STALE`) the moment it stops matching. The operator's rule is one paste a day, whether or not
the tree moved, from the Mac, when no co-listed game is in play (the script checks; `--now` skips):

```bash
cd /Users/bernardodelrio/Code/Janus && git push origin main && bash ops/box/release.sh "$(git rev-parse main)"
```

That is (a) `ops/box/update.sh <sha> --no-restart`, (b) `ops/box/write_override.sh` with the
standing statement in `ops/box/arm_statement.txt` at the F8 caps ($12 / 25 / $60, 168 h), and
(c) `ops/box/mode.sh LIMITED_LIVE`. Between (b) and (c) the running lane refuses real orders (its
tree is not the one just pinned); (c) restarts it under the new tree. The last line of the paste
is `lane=active mode=LIMITED_LIVE` and a `[mode] LIMITED_LIVE` line; `[arm] STALE` or
`mode refused: OVERRIDE_CODE_SHA` means (b) and (c) did not happen in that order -- run them again.
`ops/box/update.sh <sha>` alone (with its restart) is refused under the LIMITED_LIVE drop-in.

The box's watchdog says `OVERRIDE_EXPIRING` under 24 h and `OVERRIDE_STALE` once the arm no
longer authorises the checkout; both read the drop-in, so the Mac's watchdog never says either.

## Mexico: moving the box (2026-09-07) — done 20:22Z: `i-0a8c073c72dcdae11` in `mx-central-1a`; Virginia `i-0c86891ee306de0b8` stopped

The Virginia box's first real order was refused by the Polymarket CLOB with HTTP 403 "Trading
restricted in your region": order entry is geoblocked from a US address (reads were always fine).
The proofs succeeded from the operator's Mac, whose egress is Mexico City, so the box moves to
AWS `mx-central-1` (Querétaro; c7g.medium, SSM and the Ubuntu arm64 image are all offered there,
checked 2026-09-07). Everything below is the operator's, in order; every script now takes the
region from `JANUS_BOX_REGION` and the instance from `JANUS_BOX_ID`.

1. **IAM names the region** (admin credentials; the committed files already carry both regions):
   ```bash
   cd /Users/bernardodelrio/Code/Janus && aws iam put-role-policy --role-name janus-box --policy-name janus-box --policy-document file://infra/iam/janus-box-policy.json
   ```
   and the same for the policy that carries `infra/iam/janus-agent-policy.json` (`janus-scope` on
   the agent's role/user, see the one-time list above): its `TwoRegionsOnly` Deny now allows
   `mx-central-1` beside `us-east-1`, and every resource ARN exists for both.
2. **The parameters travel** (your secrets; nothing is printed):
   ```bash
   bash ops/box/copy_params.sh mx-central-1 && bash ops/box/copy_params.sh mx-central-1 --go
   ```
   then re-point the sha there: `aws ssm put-parameter --region mx-central-1 --overwrite --name /janus/repo/sha --type String --value "$(git rev-parse main)"`.
3. **Launch** (billable):
   ```bash
   JANUS_BOX_REGION=mx-central-1 bash ops/box/launch.sh && JANUS_BOX_REGION=mx-central-1 bash ops/box/launch.sh --go
   ```
   If the region has no default VPC the script says so (`aws ec2 create-default-vpc --region mx-central-1`).
   Note the instance id it prints; from here on in every shell:
   ```bash
   export JANUS_BOX_REGION=mx-central-1 JANUS_BOX_ID=<the new id>
   ```
   (Done: the ops/box scripts default to `mx-central-1` / `i-0a8c073c72dcdae11` since 2026-09-07; the export is only for another box.)
4. **Bootstrap** takes ~4 min (cloud-init: apt, venv, clone at the pinned sha, the units). Then
   `bash ops/box/status.sh` shows `creds=active`; the lane is not enabled yet.
5. **L34 again from Mexico** (the latency row; read-only against the venues):
   `bash ops/box/run.sh 'sudo -u janus /opt/janus/.venv/bin/python3 /opt/janus/ops/box/latency.py --rounds 100'` and the same on the Mac in the same hour; the verdict is appended to L34's row by the agent.
6. **Paper first**: `bash ops/box/run.sh 'systemctl enable --now janus-live-stream'` (the unit ships PAPER_EXECUTION); watch one discovery pass with `status.sh`.
7. **Then the arm**, as before: `bash ops/box/write_override.sh "$(cat ops/box/arm_statement.txt)" 12 10 250 168` (the 2026-09-07 evening GATE caps, the script's defaults) and `bash ops/box/mode.sh LIMITED_LIVE`. The first real order's `[exec]` line is the proof the geoblock is behind us.
8. **Virginia**: `aws ec2 stop-instances --region us-east-1 --instance-ids i-0c86891ee306de0b8` once Mexico runs (its 50 GB data volume keeps F7's records; terminate only after they are copied off if wanted).

## The cross-host kill
```bash
bash ops/box/kill.sh live            # LIMITED_LIVE and PRODUCTION; the box latches kill/live within 5 min
bash ops/box/kill.sh all             # everything that sends or simulates an order
bash ops/box/kill.sh live --clear    # lifts only what SSM latched; a breaker's file stays until a human removes it on the box
```
The parameters are `/janus/kill/all` and `/janus/kill/live`; `ops/box/kill_sync.py` runs from the
box's watchdog job (`ops/run_watchdog.sh`, `JANUS_HOST=box`). For an immediate stop pair it with
`bash ops/box/run.sh 'systemctl stop janus-live-stream'`.

## The data root
Everything the tree writes lives under `JANUS_DATA_ROOT` (`kernel/paths.py`), `/srv/janus` here
and `/Volumes/Kilos/janus` on the Mac. `ops/run_node.sh` aborts when either volume has under 2 GB
free.
