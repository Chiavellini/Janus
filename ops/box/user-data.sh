#!/bin/bash
# cloud-init user data for the Janus box (Ubuntu 24.04 arm64). Idempotent; logs to /var/log/janus-bootstrap.log.
# Parameters it reads from SSM (all under /janus/, the janus-box role may read them):
#   /janus/repo/url        https clone URL of the repo
#   /janus/repo/token      a read-only GitHub token (SecureString), or absent for a public repo
#   /janus/repo/sha        the commit to check out (the override pins the same sha)
# Secrets for the lane are NOT read here; ops/box/creds.py materialises them at every boot.
set -euo pipefail
exec >>/var/log/janus-bootstrap.log 2>&1
echo "== janus bootstrap $(date -u +%FT%TZ)"
export DEBIAN_FRONTEND=noninteractive
REGION=us-east-1
DATA=/srv/janus
JROOT=/opt/janus

apt-get update -q && apt-get install -y -q python3 python3-venv python3-pip git jq zsh    # zsh: every unit's ExecStart (2026-09-07)
snap install amazon-ssm-agent --classic 2>/dev/null || true
# The AWS CLI is not on the Ubuntu image; every SSM read below needs it (the first launch, 2026-09-07,
# read empty parameters, cloned nothing and died creating the venv under a missing /opt/janus).
command -v aws >/dev/null 2>&1 || snap install aws-cli --classic
systemctl enable --now snap.amazon-ssm-agent.amazon-ssm-agent.service 2>/dev/null || true

# the data volume: the second EBS disk, formatted once, mounted at /srv/janus (JANUS_DATA_ROOT)
DEV=$(lsblk -dn -o NAME,SIZE,TYPE | awk '$3=="disk" && $2!~/^8G|^20G/ {print "/dev/"$1; exit}')
if [ -n "${DEV:-}" ]; then
  blkid "$DEV" >/dev/null 2>&1 || mkfs.ext4 -q -L janusdata "$DEV"
  mkdir -p "$DATA"
  grep -q "LABEL=janusdata" /etc/fstab || echo "LABEL=janusdata $DATA ext4 defaults,nofail 0 2" >> /etc/fstab
  mountpoint -q "$DATA" || mount "$DATA"
fi
id janus >/dev/null 2>&1 || useradd -r -m -d /home/janus -s /bin/bash janus
mkdir -p "$DATA"/{tuples,kill,frames,proofs,runs,logs,catalog} && chown -R janus:janus "$DATA" && chmod 700 "$DATA"

# the repo, at the pinned sha
P() { aws ssm get-parameter --region $REGION --name "$1" --with-decryption --query Parameter.Value --output text 2>>/var/log/janus-bootstrap.log || true; }
URL=$(P /janus/repo/url); TOKEN=$(P /janus/repo/token); SHA=$(P /janus/repo/sha)
echo "repo url=${URL:-<empty>} sha=${SHA:-<empty>} token=$([ -n "$TOKEN" ] && echo present || echo absent)"
[ -n "$URL" ] || { echo "FATAL: /janus/repo/url is empty (is the AWS CLI installed and the instance profile attached?)"; exit 1; }
if [ -n "$URL" ]; then
  CLONE="$URL"; [ -n "$TOKEN" ] && CLONE="${URL/https:\/\//https://x-access-token:${TOKEN}@}"
  if [ ! -d "$JROOT/.git" ]; then git clone -q "$CLONE" "$JROOT" || { echo "FATAL: clone failed"; exit 1; }; fi
  git -C "$JROOT" remote set-url origin "$URL"          # the token never stays in .git/config
  git -C "$JROOT" -c "http.extraheader=Authorization: Bearer ${TOKEN}" fetch -q origin || true
  [ -n "$SHA" ] && git -C "$JROOT" checkout -q "$SHA"
  chown -R janus:janus "$JROOT"
fi
# python: a venv with the runtime deps (the tree pins none; these are what the Mac has)
sudo -u janus python3 -m venv "$JROOT/.venv"
sudo -u janus "$JROOT/.venv/bin/pip" install -q --upgrade pip
# py-clob-client-v2, not py-clob-client: Polymarket replaced its exchange on 2026-04-28 (CLOB V2, pUSD);
# the V1 client reads a balance of 0.00 and its orders are refused (CHANGELOG 2026-09-07).
sudo -u janus "$JROOT/.venv/bin/pip" install -q cryptography websockets pyyaml boto3 httpx eth-account py-clob-client-v2 pytest

# systemd units from the repo
install -m 644 "$JROOT"/ops/box/systemd/*.service "$JROOT"/ops/box/systemd/*.timer /etc/systemd/system/
install -m 644 "$JROOT"/ops/box/systemd/janus.env /etc/janus.env
systemctl daemon-reload
systemctl enable --now janus-creds.service janus-watchdog.timer janus-census.timer
# the lane itself is enabled by the operator once the latency row has run: systemctl enable --now janus-live-stream
echo "== bootstrap done $(date -u +%FT%TZ)"
