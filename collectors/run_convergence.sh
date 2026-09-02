#!/bin/zsh
set -eu
umask 077
cd /Users/bernardodelrio/Code/Janus
export PYTHONPATH=/Users/bernardodelrio/Code/Janus
LOG=/Volumes/Kilos/janus/logs
mkdir -p "$LOG"
exec /opt/homebrew/bin/python3 collectors/collect_convergence.py \
  >>"$LOG/convergence.stdout.log" 2>>"$LOG/convergence.stderr.log"
