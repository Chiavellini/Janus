#!/bin/zsh
set -eu
umask 077
cd /Users/bernardodelrio/Code/Janus
# F1 shadow trading. Research-only: public Kalshi + Polymarket HTTP, no credentials, no orders.
# Logging redirect lives HERE, not in the plist -- a gui LaunchAgent cannot create StandardOutPath
# on /Volumes/Kilos and fails EX_CONFIG(78) before exec (learned on com.janus.ibkr-archive).
export PYTHONPATH=/Users/bernardodelrio/Code/Janus
LOG=/Volumes/Kilos/janus/logs
mkdir -p "$LOG"
exec /opt/homebrew/bin/python3 collectors/collect_shadow.py \
  >>"$LOG/shadow.stdout.log" 2>>"$LOG/shadow.stderr.log"
