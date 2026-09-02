#!/bin/zsh
set -eu
umask 077

# 2026-08-18: this 8 GB host runs memory/CPU-starved. The gateway proxies every /v1/api call to
# api.ibkr.com and Vert.x's outbound TLS handshake times out at 10 s (hard-coded); a cold, paged-out
# JVM missed that budget repeatedly. Trim the JVM so it warms fast and stays resident:
#   C1-only JIT (fast compile), serial GC (no GC thread fleet), small heap/stack/code cache.
export JAVA_TOOL_OPTIONS="-XX:TieredStopAtLevel=1 -XX:+UseSerialGC -Xms128m -Xmx640m -Xss512k -XX:ReservedCodeCacheSize=64m -XX:+AlwaysPreTouch"

cd /Volumes/Kilos/janus/tools/clientportal.gw
exec /bin/zsh bin/run.sh root/conf.yaml
