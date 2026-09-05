# L40 — a SUSPECT rule that can be false (descriptive, re-runnable)

Definitions in `spec.yaml`, immutable after the first run.

## Run 20260905T075919Z — since the seal 2026-09-04 00:25Z

292 profitable prints; **15 clean, 277 suspect** under SUSPECT_V2. Clauses fired: flapping 120, end 58, stale_before_60s 243, no mapped replica 0. 1203 flap windows.

| cell | prints | clean | clean median return | clean sigma |
|---|---|---|---|---|
| cfb | 172 | 12 | 0.02458 | 0.00972 |
| cfb|100 | 89 | 10 | 0.02174 | 0.00873 |
| cfb|25 | 61 | 2 | 0.03589 | 0.00546 |
| cfb|5 | 22 | 0 | None | None |
| cfb|end | 33 | 0 | None | None |
| cfb|in | 139 | 12 | 0.02458 | 0.00972 |
| mlb | 120 | 3 | 0.02669 | 0.00724 |
| mlb|100 | 65 | 2 | 0.01902 | 0.00768 |
| mlb|25 | 54 | 1 | 0.02669 | None |
| mlb|5 | 1 | 0 | None | None |
| mlb|end | 25 | 0 | None | None |
| mlb|in | 95 | 3 | 0.02669 | 0.00724 |

### Clean prints (15)

| seen | game | league | q | phase | cost | locked return | replicas |
|---|---|---|---|---|---|---|---|
| 09-04 00:36:15Z | espn:cfb:401858423 | cfb | 100 | in | 0.9859 | +0.0143 | 2 |
| 09-04 23:16:15Z | espn:cfb:401864495 | cfb | 25 | in | 0.9603 | +0.0414 | 2 |
| 09-04 23:16:15Z | espn:cfb:401864495 | cfb | 100 | in | 0.9611 | +0.0404 | 2 |
| 09-05 00:46:45Z | espn:cfb:401864495 | cfb | 25 | in | 0.9705 | +0.0304 | 2 |
| 09-05 00:46:45Z | espn:cfb:401864495 | cfb | 100 | in | 0.9773 | +0.0232 | 2 |
| 09-05 00:46:45Z | espn:cfb:401864495 | cfb | 100 | in | 0.9747 | +0.0259 | 2 |
| 09-05 00:46:45Z | espn:cfb:401864495 | cfb | 100 | in | 0.9732 | +0.0275 | 2 |
| 09-05 00:46:45Z | espn:cfb:401864495 | cfb | 100 | in | 0.9705 | +0.0304 | 2 |
| 09-05 01:20:59Z | espn:cfb:401864495 | cfb | 100 | in | 0.9866 | +0.0136 | 2 |
| 09-05 01:20:59Z | espn:cfb:401864495 | cfb | 100 | in | 0.9801 | +0.0203 | 2 |
| 09-05 01:21:03Z | espn:cfb:401864495 | cfb | 100 | in | 0.9895 | +0.0106 | 2 |
| 09-05 01:57:38Z | espn:cfb:401864495 | cfb | 100 | in | 0.9846 | +0.0156 | 2 |
| 09-05 04:42:16Z | espn:mlb:401816809 | mlb | 25 | in | 0.9740 | +0.0267 | 2 |
| 09-05 04:42:16Z | espn:mlb:401816809 | mlb | 100 | in | 0.9740 | +0.0267 | 2 |
| 09-05 04:45:57Z | espn:mlb:401816811 | mlb | 100 | in | 0.9888 | +0.0113 | 2 |

Descriptive. A clean print is a priced book no recorded fault contradicts: not a fill, not a return. Claims no edge.
