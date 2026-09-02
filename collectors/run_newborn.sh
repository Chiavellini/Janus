#!/bin/zsh
set -eu
umask 077
cd /Users/bernardodelrio/Code/Janus
# L24 newborn cross-venue capture. Research-only: public Kalshi + Polymarket HTTP, no credentials,
# no IBKR gateway dependency of any kind.
#
# LOGGING: the redirect lives HERE, not in the plist. A gui LaunchAgent cannot create
# StandardOutPath/StandardErrorPath on the external /Volumes/Kilos volume -- it fails the job with
# EX_CONFIG(78) BEFORE exec, with no logs to explain itself. Learned on com.janus.ibkr-archive.
#
# QoS: whatever runs this must be ProcessType Interactive with NO Nice/LowPriorityIO. Background QoS
# pinned two earlier Janus jobs at runtime priority 4 and broke both (the IBKR gateway's TLS
# timeouts, and Phase A's 19,843 scheduler_late gaps).
#
# HOST: the registered spec deploys this to a VPS. If it is run on the Mac instead, expect the
# DISK_FLOOR reason to fire -- the root disk hit 607 MB free on 2026-08-20 and killed two collectors
# that day. Gaps will be reason-coded rather than silent, but they will be gaps.
LOG=/Volumes/Kilos/janus/logs
mkdir -p "$LOG"
exec /opt/homebrew/bin/python3 collectors/collect_newborn.py \
  >>"$LOG/newborn.stdout.log" 2>>"$LOG/newborn.stderr.log"
