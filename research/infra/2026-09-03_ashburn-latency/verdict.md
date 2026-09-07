# L34 — Ashburn latency: is the box an execution host? (descriptive)

Definitions and the bar in `spec.yaml`, immutable.

## Run 2026-09-07 — Mac 2026-09-07T05:57:53Z, box 2026-09-07T05:58:10Z (same hour), 100 samples each at 1 s

| venue | Mac p50 | Mac p90 | box p50 | box p90 | box connect / tls / first byte p50 | box n | box statuses | errors |
|---|---|---|---|---|---|---|---|---|
| kalshi | 184.4 | 380.5 | 51.1 | 65.9 | 2.3 / 27.7 / 7.8 | 100 | {'200': 100} | 0 |
| polymarket_clob | 308.9 | 572.8 | 183.7 | 333.8 | 2.5 / 30.9 / 138.2 | 100 | {'200': 100} | 0 |
| polymarket_gamma | 174.2 | 295.1 | 91.2 | 112.6 | 2.4 / 29.9 / 53.0 | 100 | {'200': 100} | 0 |

**Bar (spec):** box total p50 to Kalshi AND to the CLOB under half the Mac's in the same hour, AND the CLOB answering 200 from the box.
polymarket_clob: box p50 183.7 ms is not under half the Mac's 308.9 ms (154.4).

**Verdict: OBSERVATION_HOST.** The box captures frames and runs the paper series (F7) as a labelled series; execution stays where it is until a later row says otherwise. Claims nothing about edge.
