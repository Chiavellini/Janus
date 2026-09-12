#!/usr/bin/env bash
# Install release-owned runtime pieces that a git checkout alone cannot change.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
read -r -d '' REMOTE <<'EOS' || true
set -euo pipefail
test "$(id -un)" = root
if [ ! -x /opt/janus/.redeem-venv/bin/python3 ]; then
  sudo -u janus python3 -m venv /opt/janus/.redeem-venv
fi
sudo -u janus /opt/janus/.redeem-venv/bin/pip install -q --upgrade pip
sudo -u janus /opt/janus/.redeem-venv/bin/pip install -q 'polymarket-client==0.9.0'
test "$(sudo -u janus /opt/janus/.redeem-venv/bin/python3 -c 'import importlib.metadata; print(importlib.metadata.version("polymarket-client"))')" = 0.9.0
install -m 644 /opt/janus/ops/box/systemd/*.service /opt/janus/ops/box/systemd/*.timer /etc/systemd/system/
install -m 644 /opt/janus/ops/box/systemd/janus.env /etc/janus.env
echo "JANUS_BOX_REGION=${JANUS_BOX_REGION:-mx-central-1}" >> /etc/janus.env
mkdir -p /srv/janus/redemptions /srv/janus/release-audit/L64
chown janus:janus /srv/janus/redemptions /srv/janus/release-audit/L64
chmod 700 /srv/janus/redemptions /srv/janus/release-audit/L64
systemctl daemon-reload
systemctl restart janus-creds.service
systemctl enable --now janus-pm-redeem.timer
systemctl enable --now janus-board.service
systemctl restart janus-board.service
echo "redemption_runtime=0.9.0 timer=$(systemctl is-active janus-pm-redeem.timer) creds=$(systemctl is-active janus-creds.service) board=$(systemctl is-active janus-board.service)"
EOS
bash "$HERE/run.sh" "$REMOTE"
