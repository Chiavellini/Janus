# L37 — Kalshi socket cadence (descriptive)

Bound under test: 15 s without any frame = HEARTBEAT_LOST. Run 2026-09-04T00:21:00.306808+00:00.

| window | frames | by kind | gap p50 / p90 / p99 / max (s) | gaps > bound | share of hour past bound | heartbeat n / p50 / p99 / max (s) |
|---|---|---|---|---|---|---|
| clean_2026-09-03T2330Z | 915247 | {"orderbook_delta": 914529, "orderbook_snapshot": 704, "subscribed": 14} | 0.001 / 0.003 / 0.017 / 106.646 | 10 | 0.1324 | 0 / None / None / None |
| flapping_2026-09-03T1700Z | 21359 | {"orderbook_delta": 19637, "orderbook_snapshot": 866, "subscribed": 856} | 0.004 / 0.039 / 1.995 / 27.658 | 7 | 0.0105 | 0 / None / None / None |

## Reading

Kalshi sends no heartbeat frames on this subscription: liveness can only be inferred from
deltas, and the clean hour carried 915,247 of them at a 1 ms median gap. Yet the socket went
silent ten times, 43–107 s each, 13.2% of the hour past the 15 s bound. Every silence begins at a
report tick that is followed by a `[slate]` line — the discovery pass, whose ESPN, Kalshi and
Polymarket HTTP calls run synchronously inside the asyncio loop, so `ws.recv()` is not called
while it runs and every replica on both sockets decays to HEARTBEAT_LOST. The flapping hour shows
the other failure (856 `subscribed` frames in an hour: the reconnect loop).

| silence starts | length | preceding tick | `[slate]` follows |
|---|---|---|---|
| 23:31:43 | 54 s | 23:31:19 | yes |
| 23:36:24 | 43 s | 23:35:43 | yes |
| 23:42:07 | 44 s | 23:41:45 | yes |
| 23:47:39 | 68 s | 23:46:53 | yes |
| 23:53:39 | 69 s | 23:53:07 | yes |
| 23:59:33 | 107 s | 23:58:51 | yes |
| 00:01:47 | 48 s | — (watch sync) | — |
| 00:06:08 | 46 s | 00:05:20 | yes |
| 00:11:54 | 50 s | 00:11:04 | yes |
| 00:16:14 | 100 s | 00:16:02 | yes |

**Verdict: the bound stays at 15 s.** The venue's cadence is not the problem; the lane blocks its
own receive loop. The fix is the discovery pass off the loop (the same shape as the reconciler
fix of 2026-09-03), after which this row re-runs on a clean hour. Claims nothing about edge.
