#!/bin/zsh
set -eu
umask 077

set -a
source /Volumes/Kilos/janus/credentials/track_b.env
set +a

cd /Users/bernardodelrio/Code/Janus
exec /opt/homebrew/bin/python3 collectors/collect_track_b.py
