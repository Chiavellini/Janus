#!/bin/zsh
set -eu
umask 077
cd /Users/bernardodelrio/Code/Janus
# L22 forward capture. Research-only: read-only IBKR client, public Kalshi API, no credentials.
#
# LOGGING: the redirect lives HERE, not in the plist. A gui LaunchAgent cannot create
# StandardOutPath/StandardErrorPath on the external /Volumes/Kilos volume -- it fails the job with
# EX_CONFIG(78) BEFORE exec, with no logs to explain itself. Learned on com.janus.ibkr-archive.
LOG=/Volumes/Kilos/janus/logs
mkdir -p "$LOG"
exec /opt/homebrew/bin/python3 collectors/collect_wti_ladder.py \
  >>"$LOG/wti_ladder.stdout.log" 2>>"$LOG/wti_ladder.stderr.log"
