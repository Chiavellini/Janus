#!/bin/zsh
set -eu
umask 077
cd /Users/bernardodelrio/Code/Janus
# Research-only IBKR archive: read-only client, no credentials, no login. Data on /Volumes/Kilos only.
#
# LOGGING: the redirect lives HERE, not in the plist. launchd (gui agent) cannot create
# StandardOutPath/StandardErrorPath files on the external /Volumes/Kilos volume -- it fails the job
# with EX_CONFIG (78) before exec, producing no logs at all to explain itself. The shell opens them
# fine. com.janus.track-b-collector avoids this by declaring no log paths; we keep the logs instead.
LOG=/Volumes/Kilos/janus/logs
mkdir -p "$LOG"
exec /opt/homebrew/bin/python3 collectors/collect_ibkr_archive.py \
  --db /Volumes/Kilos/janus/ibkr/archive.sqlite \
  >>"$LOG/ibkr_archive.stdout.log" 2>>"$LOG/ibkr_archive.stderr.log"
