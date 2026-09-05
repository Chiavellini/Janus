# L36 — the recorded cover-cost distribution (descriptive, re-runnable)

Dwell-weighted over the material-change series in `stream_evaluations` since the 2026-09-02 seal; cells are (league | quantity | phase | flap or clean). Definitions are in `spec.yaml` and are immutable.

## Run 20260903T233018Z

89121 rows in the lane's vocabulary since the seal over 34 games; 6025 rows of the old vocabulary excluded; 1095 flap windows (92548 s).

| cell | rows | dwell s | priced | near 1¢ | profitable | cost p50 | p90 | min | statuses (dwell share) | blocked reasons (dwell share) |
|---|---|---|---|---|---|---|---|---|---|---|
| cfb|5|end|clean | 486 | 1672 | 0.20 | 0.000 | 0.000 | 1.0180 | 1.0560 | 1.0011 | BLOCKED_DEPTH 0.01, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.11, BLOCKED_STALE 0.79, NO_EDGE 0.09 | (none) 0.12, kalshi:NO_ASKS 0.01, kalshi:STALE 0.10, polymarket:HASH_MISMATCH 0.07, polymarket:HEARTBEAT_LOST 0.00, polymarket:STALE 0.08, supervisor:CLOCK_UNHEALTHY 0.53 |
| cfb|5|end|flap | 101 | 2830 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_STALE 1.00 | supervisor:CLOCK_UNHEALTHY 1.00 |
| cfb|5|in|clean | 1047 | 5826 | 0.17 | 0.030 | 0.000 | 1.0228 | 1.0340 | 0.9977 | BLOCKED_DEPTH 0.01, BLOCKED_FEES 0.03, BLOCKED_MATCH 0.09, BLOCKED_STALE 0.82, DISCOVERED 0.00, NO_EDGE 0.05 | (none) 0.12, kalshi:HEARTBEAT_LOST 0.72, kalshi:NO_ASKS 0.01, kalshi:STALE 0.04, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.00, polymarket:STALE 0.02, supervisor:CLOCK_UNHEALTHY 0.04 |
| cfb|5|in|flap | 921 | 10294 | 0.01 | 0.002 | 0.000 | 1.0418 | 1.0540 | 1.0022 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.01, BLOCKED_STALE 0.99, NO_EDGE 0.00 | (none) 0.01, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.00, kalshi:STALE 0.00, polymarket:HASH_MISMATCH 0.00, polymarket:NOT_SYNCED 0.00, polymarket:UNVERIFIED_TOO_LONG 0.00, supervisor:CLOCK_UNHEALTHY 0.97 |
| cfb|5|pre|clean | 6026 | 116303 | 0.07 | 0.000 | 0.000 | 1.0133 | 1.0377 | 0.9893 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.93, DISCOVERED 0.00, NO_EDGE 0.02 | (none) 0.04, kalshi:HEARTBEAT_LOST 0.15, kalshi:NOT_SYNCED 0.03, kalshi:NO_ASKS 0.00, kalshi:STALE 0.27, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.10, polymarket:STALE 0.15, polymarket:UNVERIFIED_TOO_LONG 0.11, supervisor:CLOCK_UNHEALTHY 0.13 |
| cfb|5|pre|flap | 773 | 19768 | 0.01 | 0.000 | 0.000 | 1.0301 | 1.0403 | 1.0032 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.00, BLOCKED_STALE 0.98, NO_EDGE 0.01 | (none) 0.01, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.22, kalshi:NO_ASKS 0.00, kalshi:STALE 0.04, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.02, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.66 |
| cfb|25|end|clean | 651 | 1672 | 0.20 | 0.000 | 0.000 | 1.0152 | 1.0652 | 1.0007 | BLOCKED_DEPTH 0.01, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.11, BLOCKED_STALE 0.79, NO_EDGE 0.09 | (none) 0.12, kalshi:NO_ASKS 0.01, kalshi:STALE 0.10, polymarket:HASH_MISMATCH 0.07, polymarket:HEARTBEAT_LOST 0.00, polymarket:STALE 0.08, supervisor:CLOCK_UNHEALTHY 0.53 |
| cfb|25|end|flap | 85 | 2455 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_STALE 1.00 | supervisor:CLOCK_UNHEALTHY 1.00 |
| cfb|25|in|clean | 1195 | 5826 | 0.17 | 0.016 | 0.000 | 1.0231 | 1.0376 | 1.0018 | BLOCKED_DEPTH 0.01, BLOCKED_FEES 0.03, BLOCKED_MATCH 0.08, BLOCKED_STALE 0.82, NO_EDGE 0.05 | (none) 0.12, kalshi:HEARTBEAT_LOST 0.72, kalshi:NO_ASKS 0.01, kalshi:STALE 0.04, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.00, polymarket:STALE 0.02, supervisor:CLOCK_UNHEALTHY 0.04 |
| cfb|25|in|flap | 2009 | 8663 | 0.02 | 0.001 | 0.000 | 1.0384 | 1.0704 | 1.0018 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.98, NO_EDGE 0.00 | (none) 0.02, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.00, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.00, polymarket:NOT_SYNCED 0.00, polymarket:UNVERIFIED_TOO_LONG 0.00, supervisor:CLOCK_UNHEALTHY 0.97 |
| cfb|25|pre|clean | 6101 | 116303 | 0.07 | 0.000 | 0.000 | 1.0144 | 1.0372 | 0.9893 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.93, DISCOVERED 0.00, NO_EDGE 0.02 | (none) 0.04, kalshi:HEARTBEAT_LOST 0.15, kalshi:NOT_SYNCED 0.03, kalshi:NO_ASKS 0.00, kalshi:STALE 0.27, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.10, polymarket:STALE 0.15, polymarket:UNVERIFIED_TOO_LONG 0.11, supervisor:CLOCK_UNHEALTHY 0.13 |
| cfb|25|pre|flap | 773 | 19768 | 0.01 | 0.000 | 0.000 | 1.0285 | 1.0387 | 1.0028 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.01, BLOCKED_STALE 0.98, NO_EDGE 0.01 | (none) 0.01, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.22, kalshi:NO_ASKS 0.00, kalshi:STALE 0.04, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.02, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.66 |
| cfb|100|end|clean | 902 | 1672 | 0.20 | 0.000 | 0.000 | 1.0148 | 1.0710 | 1.0034 | BLOCKED_DEPTH 0.01, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.16, BLOCKED_STALE 0.79, NO_EDGE 0.04 | (none) 0.17, kalshi:NO_ASKS 0.01, kalshi:STALE 0.10, polymarket:HASH_MISMATCH 0.07, polymarket:HEARTBEAT_LOST 0.00, polymarket:STALE 0.08, supervisor:CLOCK_UNHEALTHY 0.53 |
| cfb|100|end|flap | 85 | 2455 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_STALE 1.00 | supervisor:CLOCK_UNHEALTHY 1.00 |
| cfb|100|in|clean | 1716 | 5829 | 0.17 | 0.000 | 0.000 | 1.0239 | 1.0373 | 1.0028 | BLOCKED_DEPTH 0.01, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.08, BLOCKED_STALE 0.82, NO_EDGE 0.09 | (none) 0.08, kalshi:HEARTBEAT_LOST 0.72, kalshi:NO_ASKS 0.01, kalshi:STALE 0.04, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.00, polymarket:STALE 0.02, supervisor:CLOCK_UNHEALTHY 0.04 |
| cfb|100|in|flap | 3291 | 8660 | 0.02 | 0.000 | 0.000 | 1.0425 | 1.0915 | 1.0085 | BLOCKED_DEPTH 0.00, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.98, NO_EDGE 0.00 | (none) 0.02, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.00, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.00, polymarket:NOT_SYNCED 0.00, polymarket:UNVERIFIED_TOO_LONG 0.00, supervisor:CLOCK_UNHEALTHY 0.97 |
| cfb|100|pre|clean | 6093 | 116303 | 0.07 | 0.000 | 0.000 | 1.0151 | 1.0370 | 0.9891 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.05, BLOCKED_STALE 0.93, NO_EDGE 0.02, PROFITABLE_UNEXECUTED 0.00 | (none) 0.05, kalshi:HEARTBEAT_LOST 0.15, kalshi:NOT_SYNCED 0.03, kalshi:NO_ASKS 0.00, kalshi:STALE 0.27, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.10, polymarket:STALE 0.15, polymarket:UNVERIFIED_TOO_LONG 0.11, supervisor:CLOCK_UNHEALTHY 0.13 |
| cfb|100|pre|flap | 773 | 19768 | 0.01 | 0.000 | 0.000 | 1.0323 | 1.0425 | 1.0055 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.01, BLOCKED_STALE 0.98, NO_EDGE 0.01 | (none) 0.01, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.22, kalshi:NO_ASKS 0.00, kalshi:STALE 0.04, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.02, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.66 |
| lal|5|end|clean | 118 | 338 | 0.15 | 0.000 | 0.000 | 1.0331 | 1.0356 | 0.9956 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.03, BLOCKED_STALE 0.85, DISCOVERED 0.00, NO_EDGE 0.11 | (none) 0.03, kalshi:NOT_SYNCED 0.78, polymarket:HASH_MISMATCH 0.07 |
| lal|5|end|flap | 15 | 321 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_STALE 1.00 | kalshi:HEARTBEAT_LOST 0.07, kalshi:NOT_SYNCED 0.93 |
| lal|5|in|clean | 924 | 4208 | 0.22 | 0.000 | 0.000 | 1.0547 | 1.0682 | 1.0067 | BLOCKED_FEES 0.01, BLOCKED_MATCH 0.11, BLOCKED_STALE 0.78, NO_EDGE 0.10 | (none) 0.11, kalshi:HEARTBEAT_LOST 0.00, kalshi:NOT_SYNCED 0.00, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.47, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.25 |
| lal|5|pre|flap | 77 | 1338 | 0.01 | 0.000 | 0.000 | 1.0451 | 1.0543 | 1.0451 | BLOCKED_MATCH 0.00, BLOCKED_STALE 0.99, NO_EDGE 0.01 | (none) 0.00, kalshi:NOT_SYNCED 0.54, kalshi:STALE 0.13, polymarket:HEARTBEAT_LOST 0.18, polymarket:NOT_SYNCED 0.05, polymarket:STALE 0.09 |
| lal|25|end|clean | 143 | 109 | 0.99 | 0.000 | 0.000 | 1.0208 | 1.0336 | 1.0028 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.64, BLOCKED_STALE 0.01, NO_EDGE 0.35 | (none) 0.64, polymarket:HASH_MISMATCH 0.01 |
| lal|25|in|clean | 1252 | 4208 | 0.22 | 0.000 | 0.000 | 1.0547 | 1.0727 | 1.0113 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.11, BLOCKED_STALE 0.78, NO_EDGE 0.11 | (none) 0.11, kalshi:HEARTBEAT_LOST 0.00, kalshi:NOT_SYNCED 0.00, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.47, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.25 |
| lal|25|pre|flap | 77 | 1338 | 0.01 | 0.000 | 0.000 | 1.0443 | 1.0543 | 1.0443 | BLOCKED_MATCH 0.00, BLOCKED_STALE 0.99, NO_EDGE 0.01 | (none) 0.00, kalshi:NOT_SYNCED 0.54, kalshi:STALE 0.13, polymarket:HEARTBEAT_LOST 0.18, polymarket:NOT_SYNCED 0.05, polymarket:STALE 0.09 |
| lal|100|end|clean | 144 | 109 | 0.99 | 0.000 | 0.000 | 1.0201 | 1.0332 | 1.0076 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.64, BLOCKED_STALE 0.01, NO_EDGE 0.35 | (none) 0.64, polymarket:HASH_MISMATCH 0.01 |
| lal|100|in|clean | 1750 | 4208 | 0.22 | 0.000 | 0.000 | 1.0546 | 1.0732 | 1.0111 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.05, BLOCKED_STALE 0.78, NO_EDGE 0.16 | (none) 0.05, kalshi:HEARTBEAT_LOST 0.00, kalshi:NOT_SYNCED 0.00, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.47, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.25 |
| lal|100|pre|flap | 77 | 1338 | 0.01 | 0.000 | 0.000 | 1.0443 | 1.0543 | 1.0443 | BLOCKED_MATCH 0.00, BLOCKED_STALE 0.99, NO_EDGE 0.01 | (none) 0.00, kalshi:NOT_SYNCED 0.54, kalshi:STALE 0.13, polymarket:HEARTBEAT_LOST 0.18, polymarket:NOT_SYNCED 0.05, polymarket:STALE 0.09 |
| mlb|5|end|clean | 1961 | 7828 | 0.81 | 0.001 | 0.000 | 1.0302 | 1.0346 | 0.8740 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.19, NO_EDGE 0.78 | (none) 0.02, kalshi:NO_ASKS 0.00, kalshi:STALE 0.02, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.00, polymarket:STALE 0.01, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.13 |
| mlb|5|end|flap | 60 | 1364 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_STALE 1.00 | kalshi:NOT_SYNCED 0.11, kalshi:STALE 0.07, polymarket:HEARTBEAT_LOST 0.23, polymarket:NOT_SYNCED 0.07, supervisor:CLOCK_UNHEALTHY 0.52 |
| mlb|5|in|clean | 4401 | 16798 | 0.71 | 0.012 | 0.000 | 1.0301 | 1.0350 | 0.7700 | BLOCKED_DEPTH 0.01, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.09, BLOCKED_STALE 0.28, DISCOVERED 0.00, NO_EDGE 0.62 | (none) 0.10, kalshi:HEARTBEAT_LOST 0.00, kalshi:STALE 0.00, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.00, polymarket:NO_ASKS 0.01, polymarket:STALE 0.15, polymarket:UNVERIFIED_TOO_LONG 0.08, supervisor:CLOCK_UNHEALTHY 0.04 |
| mlb|5|in|flap | 917 | 14160 | 0.00 | 0.002 | 0.000 | 0.9722 | 1.0260 | 0.8482 | BLOCKED_DEPTH 0.02, BLOCKED_MATCH 0.00, BLOCKED_STALE 0.98, DISCOVERED 0.00, PROFITABLE_UNEXECUTED 0.00 | (none) 0.00, kalshi:HEARTBEAT_LOST 0.00, kalshi:NOT_SYNCED 0.32, kalshi:STALE 0.07, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.09, polymarket:NOT_SYNCED 0.09, polymarket:NO_ASKS 0.02, polymarket:STALE 0.22, polymarket:UNVERIFIED_TOO_LONG 0.15, supervisor:CLOCK_UNHEALTHY 0.05 |
| mlb|5|pre|clean | 6400 | 69350 | 0.21 | 0.000 | 0.000 | 1.0300 | 1.0300 | 1.0160 | BLOCKED_FEES 0.02, BLOCKED_MATCH 0.16, BLOCKED_STALE 0.79, NO_EDGE 0.02 | (none) 0.19, kalshi:HEARTBEAT_LOST 0.29, kalshi:NOT_SYNCED 0.02, kalshi:STALE 0.15, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.17, polymarket:UNVERIFIED_TOO_LONG 0.04, supervisor:CLOCK_UNHEALTHY 0.12 |
| mlb|5|pre|flap | 995 | 21478 | 0.02 | 0.000 | 0.000 | 1.0300 | 1.0300 | 1.0175 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.01, BLOCKED_STALE 0.98, NO_EDGE 0.00 | (none) 0.01, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.35, kalshi:STALE 0.04, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.52 |
| mlb|25|end|clean | 2716 | 7829 | 0.81 | 0.001 | 0.000 | 1.0294 | 1.0343 | 0.8886 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.19, NO_EDGE 0.78 | (none) 0.02, kalshi:NO_ASKS 0.00, kalshi:STALE 0.02, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.00, polymarket:STALE 0.01, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.13 |
| mlb|25|end|flap | 28 | 714 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_STALE 1.00 | supervisor:CLOCK_UNHEALTHY 1.00 |
| mlb|25|in|clean | 5649 | 16789 | 0.71 | 0.014 | 0.000 | 1.0294 | 1.0350 | 0.8647 | BLOCKED_DEPTH 0.01, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.09, BLOCKED_STALE 0.28, DISCOVERED 0.00, NO_EDGE 0.62 | (none) 0.09, kalshi:HEARTBEAT_LOST 0.00, kalshi:STALE 0.00, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.00, polymarket:NO_ASKS 0.01, polymarket:STALE 0.15, polymarket:UNVERIFIED_TOO_LONG 0.08, supervisor:CLOCK_UNHEALTHY 0.04 |
| mlb|25|in|flap | 655 | 9735 | 0.02 | 0.003 | 0.003 | 1.0232 | 1.0236 | 0.8482 | BLOCKED_DEPTH 0.02, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.96, DISCOVERED 0.00, PROFITABLE_UNEXECUTED 0.00 | (none) 0.02, kalshi:HEARTBEAT_LOST 0.00, kalshi:NOT_SYNCED 0.32, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.12, polymarket:NO_ASKS 0.02, polymarket:STALE 0.24, polymarket:UNVERIFIED_TOO_LONG 0.19, supervisor:CLOCK_UNHEALTHY 0.07 |
| mlb|25|pre|clean | 6397 | 69350 | 0.21 | 0.000 | 0.000 | 1.0268 | 1.0276 | 1.0144 | BLOCKED_FEES 0.02, BLOCKED_MATCH 0.17, BLOCKED_STALE 0.79, NO_EDGE 0.02 | (none) 0.19, kalshi:HEARTBEAT_LOST 0.29, kalshi:NOT_SYNCED 0.02, kalshi:STALE 0.15, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.17, polymarket:UNVERIFIED_TOO_LONG 0.04, supervisor:CLOCK_UNHEALTHY 0.12 |
| mlb|25|pre|flap | 995 | 21478 | 0.02 | 0.000 | 0.000 | 1.0268 | 1.0276 | 1.0163 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.01, BLOCKED_STALE 0.98, NO_EDGE 0.00 | (none) 0.01, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.35, kalshi:STALE 0.04, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.52 |
| mlb|100|end|clean | 4209 | 7831 | 0.81 | 0.000 | 0.000 | 1.0293 | 1.0346 | 0.9921 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.19, NO_EDGE 0.79 | (none) 0.02, kalshi:NO_ASKS 0.00, kalshi:STALE 0.02, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.00, polymarket:STALE 0.01, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.13 |
| mlb|100|end|flap | 28 | 714 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_STALE 1.00 | supervisor:CLOCK_UNHEALTHY 1.00 |
| mlb|100|in|clean | 8059 | 16795 | 0.71 | 0.009 | 0.000 | 1.0293 | 1.0350 | 0.9903 | BLOCKED_DEPTH 0.01, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.10, BLOCKED_STALE 0.28, DISCOVERED 0.00, NO_EDGE 0.62 | (none) 0.10, kalshi:HEARTBEAT_LOST 0.00, kalshi:STALE 0.00, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.00, polymarket:NO_ASKS 0.01, polymarket:STALE 0.15, polymarket:UNVERIFIED_TOO_LONG 0.08, supervisor:CLOCK_UNHEALTHY 0.04 |
| mlb|100|in|flap | 653 | 9735 | 0.02 | 0.003 | 0.003 | 1.0230 | 1.0234 | 0.8482 | BLOCKED_DEPTH 0.02, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.96, DISCOVERED 0.00, PROFITABLE_UNEXECUTED 0.00 | (none) 0.02, kalshi:HEARTBEAT_LOST 0.00, kalshi:NOT_SYNCED 0.32, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.12, polymarket:NO_ASKS 0.02, polymarket:STALE 0.24, polymarket:UNVERIFIED_TOO_LONG 0.19, supervisor:CLOCK_UNHEALTHY 0.07 |
| mlb|100|pre|clean | 6398 | 69350 | 0.21 | 0.000 | 0.000 | 1.0268 | 1.0276 | 1.0142 | BLOCKED_FEES 0.02, BLOCKED_MATCH 0.17, BLOCKED_STALE 0.79, NO_EDGE 0.01 | (none) 0.20, kalshi:HEARTBEAT_LOST 0.29, kalshi:NOT_SYNCED 0.02, kalshi:STALE 0.15, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.17, polymarket:UNVERIFIED_TOO_LONG 0.04, supervisor:CLOCK_UNHEALTHY 0.12 |
| mlb|100|pre|flap | 995 | 21478 | 0.02 | 0.000 | 0.000 | 1.0268 | 1.0276 | 1.0162 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.01, BLOCKED_STALE 0.98, NO_EDGE 0.00 | (none) 0.01, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.35, kalshi:STALE 0.04, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.52 |

### Profitable rows (19)

| seen | game | q | phase | flapping | stale within 60 s | cost | locked return | label |
|---|---|---|---|---|---|---|---|---|
| 09-03 18:08:40Z | espn:mlb:401816789 | 25 | in | True | True | 0.9714 | +0.0295 | SUSPECT |
| 09-03 18:08:40Z | espn:mlb:401816789 | 100 | in | True | True | 0.9714 | +0.0295 | SUSPECT |
| 09-03 18:10:28Z | espn:mlb:401816789 | 25 | in | True | True | 0.9306 | +0.0746 | SUSPECT |
| 09-03 18:10:28Z | espn:mlb:401816789 | 100 | in | True | True | 0.9305 | +0.0747 | SUSPECT |
| 09-03 18:12:32Z | espn:mlb:401816789 | 25 | in | True | True | 0.9202 | +0.0867 | SUSPECT |
| 09-03 18:12:32Z | espn:mlb:401816789 | 100 | in | True | True | 0.9202 | +0.0867 | SUSPECT |
| 09-03 18:18:17Z | espn:mlb:401816789 | 5 | in | True | True | 0.8482 | +0.1790 | SUSPECT |
| 09-03 18:18:17Z | espn:mlb:401816789 | 25 | in | True | True | 0.8482 | +0.1790 | SUSPECT |
| 09-03 18:18:17Z | espn:mlb:401816789 | 100 | in | True | True | 0.8482 | +0.1790 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 25 | in | True | True | 0.8546 | +0.1702 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 100 | in | True | True | 0.8575 | +0.1662 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 25 | in | True | True | 0.8526 | +0.1729 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 100 | in | True | True | 0.8585 | +0.1648 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 25 | in | True | True | 0.8546 | +0.1702 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 5 | in | True | True | 0.8602 | +0.1625 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 25 | in | True | True | 0.8586 | +0.1647 | SUSPECT |
| 09-03 18:32:36Z | espn:mlb:401816789 | 25 | in | True | True | 0.9306 | +0.0746 | SUSPECT |
| 09-03 18:32:36Z | espn:mlb:401816789 | 100 | in | True | True | 0.9305 | +0.0747 | SUSPECT |
| 09-03 19:42:31Z | espn:cfb:401867889 | 100 | pre | False | True | 0.9891 | +0.0110 | SUSPECT |

**n for the forward paper row: 30** (basis: declared; 0 in-play, clean actionable rows; fewer than 5 in-play, non-flapping actionable rows: sigma undefined, n = 30 by declaration).

Descriptive. Reads no outcome, claims no edge.

## Run 20260904T042839Z

147325 rows in the lane's vocabulary since the seal over 34 games; 6025 rows of the old vocabulary excluded; 1199 flap windows (109007 s).

| cell (league, q, phase, flap, fee era) | rows | dwell s | priced | near 1¢ | profitable | cost p50 | p90 | min | statuses (dwell share) | blocked reasons (dwell share) |
|---|---|---|---|---|---|---|---|---|---|---|
| cfb|5|end|clean|fee-repinned+probe | 592 | 2953 | 0.08 | 0.003 | 0.001 | 1.0287 | 1.0371 | 0.8595 | BLOCKED_DEPTH 0.13, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.79, DISCOVERED 0.00, NO_EDGE 0.04, PROFITABLE_UNEXECUTED 0.00 | (none) 0.04, kalshi:NO_ASKS 0.13, kalshi:STALE 0.73, polymarket:HASH_MISMATCH 0.00, polymarket:STALE 0.06 |
| cfb|5|end|flap|fee-repinned+probe | 57 | 1487 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_DEPTH 0.29, BLOCKED_STALE 0.71 | kalshi:HEARTBEAT_LOST 0.13, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.29, kalshi:STALE 0.08, supervisor:CLOCK_UNHEALTHY 0.49 |
| cfb|5|in|clean|fee-half | 3228 | 21553 | 0.20 | 0.010 | 0.000 | 1.0220 | 1.0509 | 0.9725 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.03, BLOCKED_MATCH 0.10, BLOCKED_STALE 0.78, DISCOVERED 0.00, NO_EDGE 0.07 | (none) 0.13, kalshi:HEARTBEAT_LOST 0.19, kalshi:NO_ASKS 0.02, kalshi:STALE 0.10, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.01, polymarket:STALE 0.06, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.40 |
| cfb|5|in|clean|fee-repinned | 1781 | 18612 | 0.14 | 0.001 | 0.000 | 1.0228 | 1.0350 | 0.9833 | BLOCKED_DEPTH 0.08, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.08, BLOCKED_STALE 0.78, DISCOVERED 0.00, NO_EDGE 0.05 | (none) 0.09, kalshi:NO_ASKS 0.08, kalshi:STALE 0.13, polymarket:HASH_MISMATCH 0.05, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.05, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.51 |
| cfb|5|in|clean|fee-repinned+probe | 1759 | 12116 | 0.18 | 0.002 | 0.000 | 1.0134 | 1.0332 | 0.9549 | BLOCKED_DEPTH 0.16, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.09, BLOCKED_STALE 0.66, DISCOVERED 0.00, NO_EDGE 0.08 | (none) 0.10, kalshi:NO_ASKS 0.16, kalshi:STALE 0.34, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.09, polymarket:UNVERIFIED_TOO_LONG 0.00, supervisor:CLOCK_UNHEALTHY 0.06, supervisor:LOOP_STALLED 0.15 |
| cfb|5|in|flap|fee-half | 1963 | 23358 | 0.06 | 0.002 | 0.000 | 1.0225 | 1.0460 | 0.9854 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.03, BLOCKED_STALE 0.92, DISCOVERED 0.00, NO_EDGE 0.02 | (none) 0.04, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.02, kalshi:STALE 0.05, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.02, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.81 |
| cfb|5|in|flap|fee-repinned | 415 | 6613 | 0.03 | 0.001 | 0.000 | 1.0197 | 1.0349 | 0.9794 | BLOCKED_DEPTH 0.02, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.94, DISCOVERED 0.00, NO_EDGE 0.01 | (none) 0.02, kalshi:NO_ASKS 0.02, kalshi:STALE 0.05, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.03, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.03, polymarket:UNVERIFIED_TOO_LONG 0.00, supervisor:CLOCK_UNHEALTHY 0.81 |
| cfb|5|in|flap|fee-repinned+probe | 1757 | 24094 | 0.07 | 0.004 | 0.000 | 1.0170 | 1.0349 | 0.8534 | BLOCKED_DEPTH 0.06, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.87, DISCOVERED 0.00, NO_EDGE 0.02, PROFITABLE_UNEXECUTED 0.00 | (none) 0.05, kalshi:HEARTBEAT_LOST 0.04, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.06, kalshi:STALE 0.13, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.02, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.53, supervisor:LOOP_STALLED 0.09 |
| cfb|5|pre|clean|fee-half | 6508 | 123774 | 0.07 | 0.000 | 0.000 | 1.0133 | 1.0332 | 0.9893 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.93, DISCOVERED 0.00, NO_EDGE 0.03 | (none) 0.04, kalshi:HEARTBEAT_LOST 0.14, kalshi:NOT_SYNCED 0.03, kalshi:NO_ASKS 0.00, kalshi:STALE 0.25, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.10, polymarket:STALE 0.16, polymarket:UNVERIFIED_TOO_LONG 0.10, supervisor:CLOCK_UNHEALTHY 0.15 |
| cfb|5|pre|clean|fee-repinned | 219 | 3424 | 0.10 | 0.000 | 0.000 | 1.0067 | 1.0097 | 1.0054 | BLOCKED_MATCH 0.04, BLOCKED_STALE 0.90, NO_EDGE 0.06 | (none) 0.04, kalshi:STALE 0.15, polymarket:HEARTBEAT_LOST 0.10, polymarket:STALE 0.09, polymarket:UNVERIFIED_TOO_LONG 0.06, supervisor:CLOCK_UNHEALTHY 0.50 |
| cfb|5|pre|clean|fee-repinned+probe | 16 | 283 | 0.05 | 0.000 | 0.000 | 1.0078 | 1.0078 | 1.0078 | BLOCKED_STALE 0.95, NO_EDGE 0.05 | polymarket:STALE 0.07, supervisor:CLOCK_UNHEALTHY 0.40, supervisor:LOOP_STALLED 0.49 |
| cfb|5|pre|flap|fee-half | 1010 | 23070 | 0.03 | 0.000 | 0.000 | 1.0127 | 1.0332 | 1.0032 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.01, BLOCKED_STALE 0.97, NO_EDGE 0.01 | (none) 0.01, kalshi:HEARTBEAT_LOST 0.02, kalshi:NOT_SYNCED 0.19, kalshi:NO_ASKS 0.00, kalshi:STALE 0.05, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.03, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.64 |
| cfb|5|pre|flap|fee-repinned | 75 | 1242 | 0.04 | 0.000 | 0.000 | 1.0088 | 1.0088 | 1.0057 | BLOCKED_MATCH 0.04, BLOCKED_STALE 0.96, NO_EDGE 0.00 | (none) 0.04, kalshi:STALE 0.06, polymarket:HEARTBEAT_LOST 0.03, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.82 |
| cfb|5|pre|flap|fee-repinned+probe | 16 | 225 | 0.11 | 0.000 | 0.000 | 1.0078 | 1.0088 | 1.0078 | BLOCKED_MATCH 0.02, BLOCKED_STALE 0.89, NO_EDGE 0.09 | (none) 0.02, kalshi:STALE 0.13, polymarket:HEARTBEAT_LOST 0.07, polymarket:STALE 0.16, supervisor:CLOCK_UNHEALTHY 0.52 |
| cfb|25|end|clean|fee-repinned+probe | 611 | 2953 | 0.08 | 0.002 | 0.001 | 1.0312 | 1.0397 | 0.8837 | BLOCKED_DEPTH 0.13, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.79, DISCOVERED 0.00, NO_EDGE 0.04, PROFITABLE_UNEXECUTED 0.00 | (none) 0.04, kalshi:NO_ASKS 0.13, kalshi:STALE 0.73, polymarket:HASH_MISMATCH 0.00, polymarket:STALE 0.06 |
| cfb|25|end|flap|fee-repinned+probe | 57 | 1487 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_DEPTH 0.29, BLOCKED_STALE 0.71 | kalshi:HEARTBEAT_LOST 0.13, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.29, kalshi:STALE 0.08, supervisor:CLOCK_UNHEALTHY 0.49 |
| cfb|25|in|clean|fee-half | 4398 | 21554 | 0.20 | 0.006 | 0.001 | 1.0225 | 1.0564 | 0.9719 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.03, BLOCKED_MATCH 0.11, BLOCKED_STALE 0.78, DISCOVERED 0.00, NO_EDGE 0.07, PROFITABLE_UNEXECUTED 0.00 | (none) 0.13, kalshi:HEARTBEAT_LOST 0.19, kalshi:NO_ASKS 0.02, kalshi:STALE 0.10, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.01, polymarket:STALE 0.06, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.40 |
| cfb|25|in|clean|fee-repinned | 2275 | 18614 | 0.14 | 0.000 | 0.000 | 1.0261 | 1.0372 | 0.9853 | BLOCKED_DEPTH 0.08, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.08, BLOCKED_STALE 0.78, DISCOVERED 0.00, NO_EDGE 0.06 | (none) 0.08, kalshi:NO_ASKS 0.08, kalshi:STALE 0.13, polymarket:HASH_MISMATCH 0.05, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.05, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.51 |
| cfb|25|in|clean|fee-repinned+probe | 1826 | 12116 | 0.18 | 0.002 | 0.000 | 1.0140 | 1.0342 | 0.9596 | BLOCKED_DEPTH 0.16, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.09, BLOCKED_STALE 0.66, DISCOVERED 0.00, NO_EDGE 0.08, PROFITABLE_UNEXECUTED 0.00 | (none) 0.10, kalshi:NO_ASKS 0.16, kalshi:STALE 0.34, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.09, polymarket:UNVERIFIED_TOO_LONG 0.00, supervisor:CLOCK_UNHEALTHY 0.06, supervisor:LOOP_STALLED 0.15 |
| cfb|25|in|flap|fee-half | 3227 | 21352 | 0.06 | 0.001 | 0.000 | 1.0280 | 1.0500 | 0.9838 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.92, DISCOVERED 0.00, NO_EDGE 0.02 | (none) 0.04, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.02, kalshi:STALE 0.06, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.02, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.79 |
| cfb|25|in|flap|fee-repinned | 466 | 6613 | 0.03 | 0.001 | 0.001 | 1.0209 | 1.0349 | 0.9794 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.94, NO_EDGE 0.01, PROFITABLE_UNEXECUTED 0.00 | (none) 0.02, kalshi:NO_ASKS 0.02, kalshi:STALE 0.05, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.03, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.03, polymarket:UNVERIFIED_TOO_LONG 0.00, supervisor:CLOCK_UNHEALTHY 0.81 |
| cfb|25|in|flap|fee-repinned+probe | 1942 | 24095 | 0.07 | 0.003 | 0.002 | 1.0173 | 1.0389 | 0.8534 | BLOCKED_DEPTH 0.06, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.87, DISCOVERED 0.00, NO_EDGE 0.02, PROFITABLE_UNEXECUTED 0.00 | (none) 0.05, kalshi:HEARTBEAT_LOST 0.04, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.06, kalshi:STALE 0.13, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.02, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.53, supervisor:LOOP_STALLED 0.09 |
| cfb|25|pre|clean|fee-half | 6583 | 123774 | 0.07 | 0.000 | 0.000 | 1.0144 | 1.0349 | 0.9893 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.93, DISCOVERED 0.00, NO_EDGE 0.02 | (none) 0.04, kalshi:HEARTBEAT_LOST 0.14, kalshi:NOT_SYNCED 0.03, kalshi:NO_ASKS 0.00, kalshi:STALE 0.25, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.10, polymarket:STALE 0.16, polymarket:UNVERIFIED_TOO_LONG 0.10, supervisor:CLOCK_UNHEALTHY 0.15 |
| cfb|25|pre|clean|fee-repinned | 219 | 3424 | 0.10 | 0.000 | 0.000 | 1.0066 | 1.0097 | 1.0054 | BLOCKED_MATCH 0.04, BLOCKED_STALE 0.90, NO_EDGE 0.06 | (none) 0.04, kalshi:STALE 0.15, polymarket:HEARTBEAT_LOST 0.10, polymarket:STALE 0.09, polymarket:UNVERIFIED_TOO_LONG 0.06, supervisor:CLOCK_UNHEALTHY 0.50 |
| cfb|25|pre|clean|fee-repinned+probe | 16 | 283 | 0.05 | 0.000 | 0.000 | 1.0078 | 1.0078 | 1.0078 | BLOCKED_STALE 0.95, NO_EDGE 0.05 | polymarket:STALE 0.07, supervisor:CLOCK_UNHEALTHY 0.40, supervisor:LOOP_STALLED 0.49 |
| cfb|25|pre|flap|fee-half | 1010 | 23070 | 0.03 | 0.000 | 0.000 | 1.0118 | 1.0332 | 1.0028 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.01, BLOCKED_STALE 0.97, NO_EDGE 0.02 | (none) 0.01, kalshi:HEARTBEAT_LOST 0.02, kalshi:NOT_SYNCED 0.19, kalshi:NO_ASKS 0.00, kalshi:STALE 0.05, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.03, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.64 |
| cfb|25|pre|flap|fee-repinned | 75 | 1242 | 0.04 | 0.000 | 0.000 | 1.0088 | 1.0088 | 1.0057 | BLOCKED_MATCH 0.04, BLOCKED_STALE 0.96, NO_EDGE 0.00 | (none) 0.04, kalshi:STALE 0.06, polymarket:HEARTBEAT_LOST 0.03, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.82 |
| cfb|25|pre|flap|fee-repinned+probe | 16 | 225 | 0.11 | 0.000 | 0.000 | 1.0078 | 1.0088 | 1.0078 | BLOCKED_MATCH 0.02, BLOCKED_STALE 0.89, NO_EDGE 0.09 | (none) 0.02, kalshi:STALE 0.13, polymarket:HEARTBEAT_LOST 0.07, polymarket:STALE 0.16, supervisor:CLOCK_UNHEALTHY 0.52 |
| cfb|100|end|clean|fee-repinned+probe | 601 | 2953 | 0.08 | 0.001 | 0.001 | 1.0322 | 1.0449 | 0.8984 | BLOCKED_DEPTH 0.13, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.79, DISCOVERED 0.00, NO_EDGE 0.04, PROFITABLE_UNEXECUTED 0.00 | (none) 0.05, kalshi:NO_ASKS 0.13, kalshi:STALE 0.73, polymarket:HASH_MISMATCH 0.00, polymarket:STALE 0.06 |
| cfb|100|end|flap|fee-repinned+probe | 57 | 1487 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_DEPTH 0.29, BLOCKED_STALE 0.71 | kalshi:HEARTBEAT_LOST 0.13, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.29, kalshi:STALE 0.08, supervisor:CLOCK_UNHEALTHY 0.49 |
| cfb|100|in|clean|fee-half | 6442 | 21552 | 0.20 | 0.002 | 0.001 | 1.0231 | 1.0630 | 0.9722 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.02, BLOCKED_MATCH 0.11, BLOCKED_STALE 0.78, DISCOVERED 0.00, NO_EDGE 0.07, PROFITABLE_UNEXECUTED 0.00 | (none) 0.13, kalshi:HEARTBEAT_LOST 0.19, kalshi:NO_ASKS 0.02, kalshi:STALE 0.10, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.01, polymarket:STALE 0.06, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.40 |
| cfb|100|in|clean|fee-repinned | 2767 | 18614 | 0.14 | 0.000 | 0.000 | 1.0269 | 1.0431 | 0.9859 | BLOCKED_DEPTH 0.08, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.08, BLOCKED_STALE 0.78, DISCOVERED 0.00, NO_EDGE 0.06, PROFITABLE_UNEXECUTED 0.00 | (none) 0.09, kalshi:NO_ASKS 0.08, kalshi:STALE 0.13, polymarket:HASH_MISMATCH 0.05, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.05, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.51 |
| cfb|100|in|clean|fee-repinned+probe | 1902 | 12116 | 0.18 | 0.001 | 0.000 | 1.0147 | 1.0349 | 0.9749 | BLOCKED_DEPTH 0.16, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.10, BLOCKED_STALE 0.66, DISCOVERED 0.00, NO_EDGE 0.08, PROFITABLE_UNEXECUTED 0.00 | (none) 0.10, kalshi:NO_ASKS 0.16, kalshi:STALE 0.34, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.09, polymarket:UNVERIFIED_TOO_LONG 0.00, supervisor:CLOCK_UNHEALTHY 0.06, supervisor:LOOP_STALLED 0.15 |
| cfb|100|in|flap|fee-half | 4838 | 21349 | 0.06 | 0.000 | 0.000 | 1.0304 | 1.0598 | 1.0042 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.05, BLOCKED_STALE 0.92, NO_EDGE 0.02 | (none) 0.05, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.02, kalshi:STALE 0.06, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.02, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.79 |
| cfb|100|in|flap|fee-repinned | 529 | 6613 | 0.03 | 0.001 | 0.001 | 1.0252 | 1.0392 | 0.9794 | BLOCKED_DEPTH 0.02, BLOCKED_MATCH 0.03, BLOCKED_STALE 0.94, NO_EDGE 0.01, PROFITABLE_UNEXECUTED 0.00 | (none) 0.03, kalshi:NO_ASKS 0.02, kalshi:STALE 0.05, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.03, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.03, polymarket:UNVERIFIED_TOO_LONG 0.00, supervisor:CLOCK_UNHEALTHY 0.81 |
| cfb|100|in|flap|fee-repinned+probe | 2183 | 24095 | 0.07 | 0.003 | 0.003 | 1.0195 | 1.0402 | 0.8584 | BLOCKED_DEPTH 0.06, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.87, DISCOVERED 0.00, NO_EDGE 0.03, PROFITABLE_UNEXECUTED 0.00 | (none) 0.04, kalshi:HEARTBEAT_LOST 0.04, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.06, kalshi:STALE 0.13, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.02, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.53, supervisor:LOOP_STALLED 0.09 |
| cfb|100|pre|clean|fee-half | 6575 | 123774 | 0.07 | 0.000 | 0.000 | 1.0151 | 1.0370 | 0.9891 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.93, NO_EDGE 0.02, PROFITABLE_UNEXECUTED 0.00 | (none) 0.05, kalshi:HEARTBEAT_LOST 0.14, kalshi:NOT_SYNCED 0.03, kalshi:NO_ASKS 0.00, kalshi:STALE 0.25, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.10, polymarket:STALE 0.16, polymarket:UNVERIFIED_TOO_LONG 0.10, supervisor:CLOCK_UNHEALTHY 0.15 |
| cfb|100|pre|clean|fee-repinned | 219 | 3424 | 0.10 | 0.000 | 0.000 | 1.0066 | 1.0097 | 1.0054 | BLOCKED_MATCH 0.04, BLOCKED_STALE 0.90, NO_EDGE 0.06 | (none) 0.04, kalshi:STALE 0.15, polymarket:HEARTBEAT_LOST 0.10, polymarket:STALE 0.09, polymarket:UNVERIFIED_TOO_LONG 0.06, supervisor:CLOCK_UNHEALTHY 0.50 |
| cfb|100|pre|clean|fee-repinned+probe | 16 | 283 | 0.05 | 0.000 | 0.000 | 1.0085 | 1.0085 | 1.0085 | BLOCKED_STALE 0.95, NO_EDGE 0.05 | polymarket:STALE 0.07, supervisor:CLOCK_UNHEALTHY 0.40, supervisor:LOOP_STALLED 0.49 |
| cfb|100|pre|flap|fee-half | 1010 | 23070 | 0.03 | 0.000 | 0.000 | 1.0117 | 1.0332 | 1.0055 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.01, BLOCKED_STALE 0.97, NO_EDGE 0.02 | (none) 0.01, kalshi:HEARTBEAT_LOST 0.02, kalshi:NOT_SYNCED 0.19, kalshi:NO_ASKS 0.00, kalshi:STALE 0.05, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.03, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.64 |
| cfb|100|pre|flap|fee-repinned | 75 | 1242 | 0.04 | 0.000 | 0.000 | 1.0088 | 1.0088 | 1.0057 | BLOCKED_MATCH 0.04, BLOCKED_STALE 0.96, NO_EDGE 0.00 | (none) 0.04, kalshi:STALE 0.06, polymarket:HEARTBEAT_LOST 0.03, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.82 |
| cfb|100|pre|flap|fee-repinned+probe | 16 | 225 | 0.11 | 0.000 | 0.000 | 1.0086 | 1.0088 | 1.0086 | BLOCKED_MATCH 0.02, BLOCKED_STALE 0.89, NO_EDGE 0.09 | (none) 0.02, kalshi:STALE 0.13, polymarket:HEARTBEAT_LOST 0.07, polymarket:STALE 0.16, supervisor:CLOCK_UNHEALTHY 0.52 |
| lal|5|end|clean|fee-half | 118 | 338 | 0.15 | 0.000 | 0.000 | 1.0331 | 1.0356 | 0.9956 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.03, BLOCKED_STALE 0.85, DISCOVERED 0.00, NO_EDGE 0.11 | (none) 0.03, kalshi:NOT_SYNCED 0.78, polymarket:HASH_MISMATCH 0.07 |
| lal|5|end|flap|fee-half | 15 | 321 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_STALE 1.00 | kalshi:HEARTBEAT_LOST 0.07, kalshi:NOT_SYNCED 0.93 |
| lal|5|in|clean|fee-half | 924 | 4208 | 0.22 | 0.000 | 0.000 | 1.0547 | 1.0682 | 1.0067 | BLOCKED_FEES 0.01, BLOCKED_MATCH 0.11, BLOCKED_STALE 0.78, NO_EDGE 0.10 | (none) 0.11, kalshi:HEARTBEAT_LOST 0.00, kalshi:NOT_SYNCED 0.00, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.47, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.25 |
| lal|5|pre|flap|fee-half | 77 | 1338 | 0.01 | 0.000 | 0.000 | 1.0451 | 1.0543 | 1.0451 | BLOCKED_MATCH 0.00, BLOCKED_STALE 0.99, NO_EDGE 0.01 | (none) 0.00, kalshi:NOT_SYNCED 0.54, kalshi:STALE 0.13, polymarket:HEARTBEAT_LOST 0.18, polymarket:NOT_SYNCED 0.05, polymarket:STALE 0.09 |
| lal|25|end|clean|fee-half | 143 | 109 | 0.99 | 0.000 | 0.000 | 1.0208 | 1.0336 | 1.0028 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.64, BLOCKED_STALE 0.01, NO_EDGE 0.35 | (none) 0.64, polymarket:HASH_MISMATCH 0.01 |
| lal|25|in|clean|fee-half | 1252 | 4208 | 0.22 | 0.000 | 0.000 | 1.0547 | 1.0727 | 1.0113 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.11, BLOCKED_STALE 0.78, NO_EDGE 0.11 | (none) 0.11, kalshi:HEARTBEAT_LOST 0.00, kalshi:NOT_SYNCED 0.00, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.47, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.25 |
| lal|25|pre|flap|fee-half | 77 | 1338 | 0.01 | 0.000 | 0.000 | 1.0443 | 1.0543 | 1.0443 | BLOCKED_MATCH 0.00, BLOCKED_STALE 0.99, NO_EDGE 0.01 | (none) 0.00, kalshi:NOT_SYNCED 0.54, kalshi:STALE 0.13, polymarket:HEARTBEAT_LOST 0.18, polymarket:NOT_SYNCED 0.05, polymarket:STALE 0.09 |
| lal|100|end|clean|fee-half | 144 | 109 | 0.99 | 0.000 | 0.000 | 1.0201 | 1.0332 | 1.0076 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.64, BLOCKED_STALE 0.01, NO_EDGE 0.35 | (none) 0.64, polymarket:HASH_MISMATCH 0.01 |
| lal|100|in|clean|fee-half | 1750 | 4208 | 0.22 | 0.000 | 0.000 | 1.0546 | 1.0732 | 1.0111 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.05, BLOCKED_STALE 0.78, NO_EDGE 0.16 | (none) 0.05, kalshi:HEARTBEAT_LOST 0.00, kalshi:NOT_SYNCED 0.00, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.47, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.25 |
| lal|100|pre|flap|fee-half | 77 | 1338 | 0.01 | 0.000 | 0.000 | 1.0443 | 1.0543 | 1.0443 | BLOCKED_MATCH 0.00, BLOCKED_STALE 0.99, NO_EDGE 0.01 | (none) 0.00, kalshi:NOT_SYNCED 0.54, kalshi:STALE 0.13, polymarket:HEARTBEAT_LOST 0.18, polymarket:NOT_SYNCED 0.05, polymarket:STALE 0.09 |
| mlb|5|end|clean|fee-half | 1903 | 7398 | 0.83 | 0.001 | 0.000 | 1.0302 | 1.0346 | 0.8740 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.00, BLOCKED_STALE 0.16, NO_EDGE 0.83 | (none) 0.00, kalshi:NO_ASKS 0.00, kalshi:STALE 0.03, polymarket:HASH_MISMATCH 0.00, polymarket:STALE 0.00, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.11 |
| mlb|5|end|clean|fee-repinned+probe | 409 | 1441 | 0.88 | 0.000 | 0.000 | 1.0372 | 1.0439 | 0.9823 | BLOCKED_FEES 0.01, BLOCKED_MATCH 0.14, BLOCKED_STALE 0.12, DISCOVERED 0.00, NO_EDGE 0.74 | (none) 0.15, kalshi:STALE 0.00, polymarket:HASH_MISMATCH 0.01, polymarket:STALE 0.00, supervisor:LOOP_STALLED 0.10 |
| mlb|5|end|flap|fee-half | 32 | 649 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_STALE 1.00 | kalshi:NOT_SYNCED 0.24, kalshi:STALE 0.14, polymarket:HEARTBEAT_LOST 0.47, polymarket:NOT_SYNCED 0.15 |
| mlb|5|end|flap|fee-repinned+probe | 28 | 888 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_DEPTH 0.17, BLOCKED_STALE 0.83 | kalshi:HEARTBEAT_LOST 0.09, kalshi:NO_ASKS 0.17, kalshi:STALE 0.10, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.29, supervisor:LOOP_STALLED 0.33 |
| mlb|5|in|clean|fee-half | 5103 | 21836 | 0.64 | 0.009 | 0.000 | 1.0299 | 1.0350 | 0.7700 | BLOCKED_DEPTH 0.01, BLOCKED_FEES 0.02, BLOCKED_MATCH 0.12, BLOCKED_STALE 0.35, DISCOVERED 0.00, NO_EDGE 0.51 | (none) 0.14, kalshi:HEARTBEAT_LOST 0.00, kalshi:STALE 0.00, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.00, polymarket:NO_ASKS 0.01, polymarket:STALE 0.12, polymarket:UNVERIFIED_TOO_LONG 0.06, supervisor:CLOCK_UNHEALTHY 0.16 |
| mlb|5|in|clean|fee-repinned | 1007 | 6884 | 0.39 | 0.005 | 0.000 | 1.0349 | 1.0443 | 0.9357 | BLOCKED_FEES 0.02, BLOCKED_MATCH 0.03, BLOCKED_STALE 0.61, DISCOVERED 0.00, NO_EDGE 0.33 | (none) 0.05, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.06, polymarket:HEARTBEAT_LOST 0.00, polymarket:STALE 0.03, supervisor:CLOCK_UNHEALTHY 0.51 |
| mlb|5|in|clean|fee-repinned+probe | 1719 | 7618 | 0.80 | 0.000 | 0.000 | 1.0417 | 1.0441 | 0.9844 | BLOCKED_FEES 0.02, BLOCKED_MATCH 0.10, BLOCKED_STALE 0.20, DISCOVERED 0.00, NO_EDGE 0.68 | (none) 0.12, kalshi:CROSSED_BOOK 0.03, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.02, supervisor:CLOCK_UNHEALTHY 0.03, supervisor:LOOP_STALLED 0.11 |
| mlb|5|in|flap|fee-half | 1355 | 18429 | 0.05 | 0.003 | 0.000 | 1.0260 | 1.0300 | 0.8482 | BLOCKED_DEPTH 0.01, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.93, DISCOVERED 0.00, NO_EDGE 0.00, PROFITABLE_UNEXECUTED 0.00 | (none) 0.05, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.24, kalshi:STALE 0.06, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.07, polymarket:NOT_SYNCED 0.07, polymarket:NO_ASKS 0.01, polymarket:STALE 0.18, polymarket:UNVERIFIED_TOO_LONG 0.12, supervisor:CLOCK_UNHEALTHY 0.19 |
| mlb|5|in|flap|fee-repinned | 223 | 2452 | 0.08 | 0.001 | 0.000 | 1.0329 | 1.0443 | 1.0040 | BLOCKED_FEES 0.01, BLOCKED_MATCH 0.01, BLOCKED_STALE 0.92, NO_EDGE 0.06 | (none) 0.02, kalshi:STALE 0.00, polymarket:HASH_MISMATCH 0.02, polymarket:HEARTBEAT_LOST 0.04, polymarket:NOT_SYNCED 0.02, polymarket:STALE 0.02, supervisor:CLOCK_UNHEALTHY 0.81 |
| mlb|5|in|flap|fee-repinned+probe | 875 | 8731 | 0.21 | 0.004 | 0.000 | 1.0352 | 1.0445 | 0.9341 | BLOCKED_FEES 0.01, BLOCKED_MATCH 0.03, BLOCKED_STALE 0.79, DISCOVERED 0.00, NO_EDGE 0.17 | (none) 0.04, kalshi:HEARTBEAT_LOST 0.04, kalshi:STALE 0.03, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.03, polymarket:STALE 0.05, supervisor:CLOCK_UNHEALTHY 0.53, supervisor:LOOP_STALLED 0.09 |
| mlb|5|pre|clean|fee-half | 6836 | 74750 | 0.20 | 0.000 | 0.000 | 1.0300 | 1.0300 | 1.0160 | BLOCKED_FEES 0.02, BLOCKED_MATCH 0.16, BLOCKED_STALE 0.80, NO_EDGE 0.02 | (none) 0.18, kalshi:HEARTBEAT_LOST 0.27, kalshi:NOT_SYNCED 0.02, kalshi:STALE 0.15, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.16, polymarket:UNVERIFIED_TOO_LONG 0.04, supervisor:CLOCK_UNHEALTHY 0.14 |
| mlb|5|pre|clean|fee-repinned | 299 | 3327 | 0.15 | 0.000 | 0.000 | 1.0282 | 1.0399 | 1.0269 | BLOCKED_MATCH 0.08, BLOCKED_STALE 0.85, NO_EDGE 0.07 | (none) 0.08, kalshi:STALE 0.12, polymarket:HEARTBEAT_LOST 0.01, polymarket:STALE 0.18, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.51 |
| mlb|5|pre|clean|fee-repinned+probe | 30 | 448 | 0.03 | 0.000 | 0.000 | 1.0269 | 1.0269 | 1.0269 | BLOCKED_STALE 0.97, NO_EDGE 0.03 | kalshi:STALE 0.00, polymarket:STALE 0.03, supervisor:CLOCK_UNHEALTHY 0.34, supervisor:LOOP_STALLED 0.60 |
| mlb|5|pre|flap|fee-half | 1219 | 24133 | 0.03 | 0.000 | 0.000 | 1.0260 | 1.0300 | 1.0160 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.97, NO_EDGE 0.00 | (none) 0.02, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.31, kalshi:STALE 0.04, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.52 |
| mlb|5|pre|flap|fee-repinned | 78 | 1263 | 0.02 | 0.000 | 0.000 | 1.0399 | 1.0399 | 1.0282 | BLOCKED_MATCH 0.00, BLOCKED_STALE 0.98, NO_EDGE 0.02 | (none) 0.00, kalshi:STALE 0.05, polymarket:HEARTBEAT_LOST 0.07, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.01, supervisor:CLOCK_UNHEALTHY 0.83 |
| mlb|5|pre|flap|fee-repinned+probe | 66 | 1064 | 0.09 | 0.000 | 0.000 | 1.0269 | 1.0399 | 1.0269 | BLOCKED_STALE 0.91, NO_EDGE 0.09 | kalshi:STALE 0.32, polymarket:HEARTBEAT_LOST 0.02, polymarket:STALE 0.06, supervisor:CLOCK_UNHEALTHY 0.21, supervisor:LOOP_STALLED 0.29 |
| mlb|25|end|clean|fee-half | 2652 | 7398 | 0.83 | 0.001 | 0.000 | 1.0294 | 1.0343 | 0.8886 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.00, BLOCKED_STALE 0.16, NO_EDGE 0.83 | (none) 0.00, kalshi:NO_ASKS 0.00, kalshi:STALE 0.03, polymarket:HASH_MISMATCH 0.00, polymarket:STALE 0.00, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.11 |
| mlb|25|end|clean|fee-repinned+probe | 447 | 1441 | 0.88 | 0.000 | 0.000 | 1.0383 | 1.0439 | 0.9870 | BLOCKED_FEES 0.02, BLOCKED_MATCH 0.15, BLOCKED_STALE 0.12, DISCOVERED 0.00, NO_EDGE 0.71 | (none) 0.17, kalshi:STALE 0.00, polymarket:HASH_MISMATCH 0.01, polymarket:STALE 0.00, supervisor:LOOP_STALLED 0.10 |
| mlb|25|end|flap|fee-repinned+probe | 28 | 888 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_DEPTH 0.17, BLOCKED_STALE 0.83 | kalshi:HEARTBEAT_LOST 0.09, kalshi:NO_ASKS 0.17, kalshi:STALE 0.10, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.29, supervisor:LOOP_STALLED 0.33 |
| mlb|25|in|clean|fee-half | 6571 | 21827 | 0.64 | 0.011 | 0.000 | 1.0276 | 1.0350 | 0.8647 | BLOCKED_DEPTH 0.01, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.13, BLOCKED_STALE 0.35, DISCOVERED 0.00, NO_EDGE 0.51 | (none) 0.13, kalshi:HEARTBEAT_LOST 0.00, kalshi:STALE 0.00, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.00, polymarket:NO_ASKS 0.01, polymarket:STALE 0.12, polymarket:UNVERIFIED_TOO_LONG 0.06, supervisor:CLOCK_UNHEALTHY 0.16 |
| mlb|25|in|clean|fee-repinned | 1225 | 6884 | 0.39 | 0.005 | 0.004 | 1.0383 | 1.0443 | 0.9388 | BLOCKED_FEES 0.02, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.61, DISCOVERED 0.00, NO_EDGE 0.32, PROFITABLE_UNEXECUTED 0.00 | (none) 0.06, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.06, polymarket:HEARTBEAT_LOST 0.00, polymarket:STALE 0.03, supervisor:CLOCK_UNHEALTHY 0.51 |
| mlb|25|in|clean|fee-repinned+probe | 1992 | 7618 | 0.80 | 0.000 | 0.000 | 1.0419 | 1.0443 | 1.0045 | BLOCKED_FEES 0.02, BLOCKED_MATCH 0.11, BLOCKED_STALE 0.20, NO_EDGE 0.67 | (none) 0.13, kalshi:CROSSED_BOOK 0.03, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.02, supervisor:CLOCK_UNHEALTHY 0.03, supervisor:LOOP_STALLED 0.11 |
| mlb|25|in|flap|fee-half | 1199 | 14004 | 0.08 | 0.003 | 0.003 | 1.0260 | 1.0276 | 0.8482 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.07, BLOCKED_STALE 0.90, DISCOVERED 0.00, NO_EDGE 0.00, PROFITABLE_UNEXECUTED 0.00 | (none) 0.07, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.23, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.09, polymarket:NOT_SYNCED 0.00, polymarket:NO_ASKS 0.02, polymarket:STALE 0.18, polymarket:UNVERIFIED_TOO_LONG 0.14, supervisor:CLOCK_UNHEALTHY 0.25 |
| mlb|25|in|flap|fee-repinned | 251 | 2452 | 0.08 | 0.001 | 0.000 | 1.0329 | 1.0443 | 1.0040 | BLOCKED_FEES 0.01, BLOCKED_MATCH 0.01, BLOCKED_STALE 0.92, NO_EDGE 0.06 | (none) 0.02, kalshi:STALE 0.00, polymarket:HASH_MISMATCH 0.02, polymarket:HEARTBEAT_LOST 0.04, polymarket:NOT_SYNCED 0.02, polymarket:STALE 0.02, supervisor:CLOCK_UNHEALTHY 0.81 |
| mlb|25|in|flap|fee-repinned+probe | 976 | 8731 | 0.21 | 0.003 | 0.001 | 1.0370 | 1.0445 | 0.9341 | BLOCKED_FEES 0.01, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.79, DISCOVERED 0.00, NO_EDGE 0.16, PROFITABLE_UNEXECUTED 0.00 | (none) 0.05, kalshi:HEARTBEAT_LOST 0.04, kalshi:STALE 0.03, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.03, polymarket:STALE 0.05, supervisor:CLOCK_UNHEALTHY 0.53, supervisor:LOOP_STALLED 0.09 |
| mlb|25|pre|clean|fee-half | 6833 | 74750 | 0.20 | 0.000 | 0.000 | 1.0268 | 1.0276 | 1.0144 | BLOCKED_FEES 0.02, BLOCKED_MATCH 0.16, BLOCKED_STALE 0.80, NO_EDGE 0.02 | (none) 0.18, kalshi:HEARTBEAT_LOST 0.27, kalshi:NOT_SYNCED 0.02, kalshi:STALE 0.15, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.16, polymarket:UNVERIFIED_TOO_LONG 0.04, supervisor:CLOCK_UNHEALTHY 0.14 |
| mlb|25|pre|clean|fee-repinned | 299 | 3327 | 0.15 | 0.000 | 0.000 | 1.0282 | 1.0399 | 1.0269 | BLOCKED_MATCH 0.08, BLOCKED_STALE 0.85, NO_EDGE 0.07 | (none) 0.08, kalshi:STALE 0.12, polymarket:HEARTBEAT_LOST 0.01, polymarket:STALE 0.18, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.51 |
| mlb|25|pre|clean|fee-repinned+probe | 30 | 448 | 0.03 | 0.000 | 0.000 | 1.0269 | 1.0269 | 1.0269 | BLOCKED_STALE 0.97, NO_EDGE 0.03 | kalshi:STALE 0.00, polymarket:STALE 0.03, supervisor:CLOCK_UNHEALTHY 0.34, supervisor:LOOP_STALLED 0.60 |
| mlb|25|pre|flap|fee-half | 1219 | 24133 | 0.03 | 0.000 | 0.000 | 1.0260 | 1.0276 | 1.0144 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.97, NO_EDGE 0.00 | (none) 0.02, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.31, kalshi:STALE 0.04, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.52 |
| mlb|25|pre|flap|fee-repinned | 78 | 1263 | 0.02 | 0.000 | 0.000 | 1.0399 | 1.0399 | 1.0282 | BLOCKED_MATCH 0.00, BLOCKED_STALE 0.98, NO_EDGE 0.02 | (none) 0.00, kalshi:STALE 0.05, polymarket:HEARTBEAT_LOST 0.07, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.01, supervisor:CLOCK_UNHEALTHY 0.83 |
| mlb|25|pre|flap|fee-repinned+probe | 66 | 1064 | 0.09 | 0.000 | 0.000 | 1.0269 | 1.0399 | 1.0269 | BLOCKED_STALE 0.91, NO_EDGE 0.09 | kalshi:STALE 0.32, polymarket:HEARTBEAT_LOST 0.02, polymarket:STALE 0.06, supervisor:CLOCK_UNHEALTHY 0.21, supervisor:LOOP_STALLED 0.29 |
| mlb|100|end|clean|fee-half | 4110 | 7401 | 0.83 | 0.000 | 0.000 | 1.0293 | 1.0346 | 0.9921 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.00, BLOCKED_STALE 0.16, NO_EDGE 0.83 | (none) 0.00, kalshi:NO_ASKS 0.00, kalshi:STALE 0.03, polymarket:HASH_MISMATCH 0.00, polymarket:STALE 0.00, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.11 |
| mlb|100|end|clean|fee-repinned+probe | 511 | 1442 | 0.88 | 0.000 | 0.000 | 1.0383 | 1.0439 | 1.0157 | BLOCKED_FEES 0.02, BLOCKED_MATCH 0.20, BLOCKED_STALE 0.12, NO_EDGE 0.66 | (none) 0.22, kalshi:STALE 0.00, polymarket:HASH_MISMATCH 0.01, polymarket:STALE 0.00, supervisor:LOOP_STALLED 0.10 |
| mlb|100|end|flap|fee-repinned+probe | 28 | 888 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_DEPTH 0.17, BLOCKED_STALE 0.83 | kalshi:HEARTBEAT_LOST 0.09, kalshi:NO_ASKS 0.17, kalshi:STALE 0.10, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.29, supervisor:LOOP_STALLED 0.33 |
| mlb|100|in|clean|fee-half | 9052 | 21834 | 0.64 | 0.007 | 0.000 | 1.0276 | 1.0350 | 0.9903 | BLOCKED_DEPTH 0.01, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.13, BLOCKED_STALE 0.35, DISCOVERED 0.00, NO_EDGE 0.50 | (none) 0.14, kalshi:HEARTBEAT_LOST 0.00, kalshi:STALE 0.00, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.00, polymarket:NO_ASKS 0.01, polymarket:STALE 0.12, polymarket:UNVERIFIED_TOO_LONG 0.06, supervisor:CLOCK_UNHEALTHY 0.16 |
| mlb|100|in|clean|fee-repinned | 1425 | 6884 | 0.39 | 0.004 | 0.004 | 1.0389 | 1.0445 | 0.9388 | BLOCKED_FEES 0.02, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.61, DISCOVERED 0.00, NO_EDGE 0.32, PROFITABLE_UNEXECUTED 0.00 | (none) 0.07, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.06, polymarket:HEARTBEAT_LOST 0.00, polymarket:STALE 0.03, supervisor:CLOCK_UNHEALTHY 0.51 |
| mlb|100|in|clean|fee-repinned+probe | 2225 | 7629 | 0.80 | 0.000 | 0.000 | 1.0421 | 1.0446 | 1.0047 | BLOCKED_FEES 0.02, BLOCKED_MATCH 0.13, BLOCKED_STALE 0.20, NO_EDGE 0.65 | (none) 0.15, kalshi:CROSSED_BOOK 0.03, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.02, supervisor:CLOCK_UNHEALTHY 0.03, supervisor:LOOP_STALLED 0.11 |
| mlb|100|in|flap|fee-half | 1199 | 14004 | 0.08 | 0.003 | 0.003 | 1.0257 | 1.0276 | 0.8482 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.07, BLOCKED_STALE 0.90, DISCOVERED 0.00, NO_EDGE 0.00, PROFITABLE_UNEXECUTED 0.00 | (none) 0.07, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.23, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.09, polymarket:NOT_SYNCED 0.00, polymarket:NO_ASKS 0.02, polymarket:STALE 0.18, polymarket:UNVERIFIED_TOO_LONG 0.14, supervisor:CLOCK_UNHEALTHY 0.25 |
| mlb|100|in|flap|fee-repinned | 269 | 2452 | 0.08 | 0.000 | 0.000 | 1.0336 | 1.0443 | 1.0061 | BLOCKED_FEES 0.01, BLOCKED_MATCH 0.01, BLOCKED_STALE 0.92, NO_EDGE 0.06 | (none) 0.03, kalshi:STALE 0.00, polymarket:HASH_MISMATCH 0.02, polymarket:HEARTBEAT_LOST 0.04, polymarket:NOT_SYNCED 0.02, polymarket:STALE 0.02, supervisor:CLOCK_UNHEALTHY 0.81 |
| mlb|100|in|flap|fee-repinned+probe | 1008 | 8735 | 0.21 | 0.003 | 0.002 | 1.0390 | 1.0445 | 0.9341 | BLOCKED_FEES 0.01, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.79, DISCOVERED 0.00, NO_EDGE 0.15, PROFITABLE_UNEXECUTED 0.00 | (none) 0.05, kalshi:HEARTBEAT_LOST 0.04, kalshi:STALE 0.03, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.03, polymarket:STALE 0.05, supervisor:CLOCK_UNHEALTHY 0.53, supervisor:LOOP_STALLED 0.09 |
| mlb|100|pre|clean|fee-half | 6834 | 74750 | 0.20 | 0.000 | 0.000 | 1.0268 | 1.0276 | 1.0142 | BLOCKED_FEES 0.02, BLOCKED_MATCH 0.17, BLOCKED_STALE 0.80, NO_EDGE 0.01 | (none) 0.19, kalshi:HEARTBEAT_LOST 0.27, kalshi:NOT_SYNCED 0.02, kalshi:STALE 0.15, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.16, polymarket:UNVERIFIED_TOO_LONG 0.04, supervisor:CLOCK_UNHEALTHY 0.14 |
| mlb|100|pre|clean|fee-repinned | 299 | 3327 | 0.15 | 0.000 | 0.000 | 1.0282 | 1.0399 | 1.0269 | BLOCKED_MATCH 0.08, BLOCKED_STALE 0.85, NO_EDGE 0.07 | (none) 0.08, kalshi:STALE 0.12, polymarket:HEARTBEAT_LOST 0.01, polymarket:STALE 0.18, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.51 |
| mlb|100|pre|clean|fee-repinned+probe | 30 | 448 | 0.03 | 0.000 | 0.000 | 1.0269 | 1.0269 | 1.0269 | BLOCKED_STALE 0.97, NO_EDGE 0.03 | kalshi:STALE 0.00, polymarket:STALE 0.03, supervisor:CLOCK_UNHEALTHY 0.34, supervisor:LOOP_STALLED 0.60 |
| mlb|100|pre|flap|fee-half | 1219 | 24133 | 0.03 | 0.000 | 0.000 | 1.0257 | 1.0275 | 1.0142 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.97, NO_EDGE 0.00 | (none) 0.02, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.31, kalshi:STALE 0.04, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.52 |
| mlb|100|pre|flap|fee-repinned | 78 | 1263 | 0.02 | 0.000 | 0.000 | 1.0399 | 1.0399 | 1.0282 | BLOCKED_MATCH 0.00, BLOCKED_STALE 0.98, NO_EDGE 0.02 | (none) 0.00, kalshi:STALE 0.05, polymarket:HEARTBEAT_LOST 0.07, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.01, supervisor:CLOCK_UNHEALTHY 0.83 |
| mlb|100|pre|flap|fee-repinned+probe | 66 | 1064 | 0.09 | 0.000 | 0.000 | 1.0269 | 1.0399 | 1.0269 | BLOCKED_STALE 0.91, NO_EDGE 0.09 | kalshi:STALE 0.32, polymarket:HEARTBEAT_LOST 0.02, polymarket:STALE 0.06, supervisor:CLOCK_UNHEALTHY 0.21, supervisor:LOOP_STALLED 0.29 |

### Profitable rows (270)

| seen | game | q | phase | flapping | stale within 60 s | cost | locked return | label |
|---|---|---|---|---|---|---|---|---|
| 09-03 18:08:40Z | espn:mlb:401816789 | 25 | in | True | True | 0.9714 | +0.0295 | SUSPECT |
| 09-03 18:08:40Z | espn:mlb:401816789 | 100 | in | True | True | 0.9714 | +0.0295 | SUSPECT |
| 09-03 18:10:28Z | espn:mlb:401816789 | 25 | in | True | True | 0.9306 | +0.0746 | SUSPECT |
| 09-03 18:10:28Z | espn:mlb:401816789 | 100 | in | True | True | 0.9305 | +0.0747 | SUSPECT |
| 09-03 18:12:32Z | espn:mlb:401816789 | 25 | in | True | True | 0.9202 | +0.0867 | SUSPECT |
| 09-03 18:12:32Z | espn:mlb:401816789 | 100 | in | True | True | 0.9202 | +0.0867 | SUSPECT |
| 09-03 18:18:17Z | espn:mlb:401816789 | 5 | in | True | True | 0.8482 | +0.1790 | SUSPECT |
| 09-03 18:18:17Z | espn:mlb:401816789 | 25 | in | True | True | 0.8482 | +0.1790 | SUSPECT |
| 09-03 18:18:17Z | espn:mlb:401816789 | 100 | in | True | True | 0.8482 | +0.1790 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 25 | in | True | True | 0.8546 | +0.1702 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 100 | in | True | True | 0.8575 | +0.1662 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 25 | in | True | True | 0.8526 | +0.1729 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 100 | in | True | True | 0.8585 | +0.1648 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 25 | in | True | True | 0.8546 | +0.1702 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 5 | in | True | True | 0.8602 | +0.1625 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 25 | in | True | True | 0.8586 | +0.1647 | SUSPECT |
| 09-03 18:32:36Z | espn:mlb:401816789 | 25 | in | True | True | 0.9306 | +0.0746 | SUSPECT |
| 09-03 18:32:36Z | espn:mlb:401816789 | 100 | in | True | True | 0.9305 | +0.0747 | SUSPECT |
| 09-03 19:42:31Z | espn:cfb:401867889 | 100 | pre | False | True | 0.9891 | +0.0110 | SUSPECT |
| 09-03 23:51:35Z | espn:cfb:401858423 | 100 | in | False | True | 0.9896 | +0.0105 | SUSPECT |
| 09-03 23:51:35Z | espn:cfb:401858423 | 100 | in | False | True | 0.9826 | +0.0177 | SUSPECT |
| 09-03 23:51:36Z | espn:cfb:401858423 | 25 | in | False | True | 0.9791 | +0.0213 | SUSPECT |
| 09-03 23:51:36Z | espn:cfb:401858423 | 25 | in | False | True | 0.9719 | +0.0289 | SUSPECT |
| 09-03 23:51:36Z | espn:cfb:401858423 | 100 | in | False | True | 0.9722 | +0.0286 | SUSPECT |
| 09-03 23:51:44Z | espn:cfb:401858423 | 25 | in | False | True | 0.9719 | +0.0289 | SUSPECT |
| 09-03 23:51:44Z | espn:cfb:401858423 | 100 | in | False | True | 0.9722 | +0.0286 | SUSPECT |
| 09-03 23:51:49Z | espn:cfb:401858423 | 25 | in | False | True | 0.9723 | +0.0285 | SUSPECT |
| 09-03 23:51:49Z | espn:cfb:401858423 | 100 | in | False | True | 0.9723 | +0.0285 | SUSPECT |
| 09-03 23:51:55Z | espn:cfb:401858423 | 25 | in | False | True | 0.9723 | +0.0285 | SUSPECT |
| 09-03 23:51:55Z | espn:cfb:401858423 | 100 | in | False | True | 0.9723 | +0.0285 | SUSPECT |
| 09-03 23:52:03Z | espn:cfb:401858423 | 25 | in | False | True | 0.9723 | +0.0285 | SUSPECT |
| 09-03 23:52:03Z | espn:cfb:401858423 | 100 | in | False | True | 0.9723 | +0.0285 | SUSPECT |
| 09-04 00:07:13Z | espn:mlb:401816793 | 25 | in | True | True | 0.9198 | +0.0872 | SUSPECT |
| 09-04 00:07:13Z | espn:mlb:401816793 | 100 | in | True | True | 0.9198 | +0.0872 | SUSPECT |
| 09-04 00:07:38Z | espn:mlb:401816793 | 25 | in | True | True | 0.9301 | +0.0752 | SUSPECT |
| 09-04 00:07:38Z | espn:mlb:401816793 | 100 | in | True | True | 0.9301 | +0.0752 | SUSPECT |
| 09-04 00:07:39Z | espn:mlb:401816793 | 100 | in | True | True | 0.9332 | +0.0716 | SUSPECT |
| 09-04 00:07:40Z | espn:mlb:401816793 | 25 | in | True | True | 0.9354 | +0.0691 | SUSPECT |
| 09-04 00:07:40Z | espn:mlb:401816793 | 100 | in | True | True | 0.9392 | +0.0648 | SUSPECT |
| 09-04 00:07:40Z | espn:mlb:401816793 | 25 | in | True | True | 0.9365 | +0.0678 | SUSPECT |
| 09-04 00:07:40Z | espn:mlb:401816793 | 100 | in | True | True | 0.9472 | +0.0557 | SUSPECT |
| 09-04 00:07:40Z | espn:mlb:401816793 | 25 | in | True | True | 0.9412 | +0.0625 | SUSPECT |
| 09-04 00:07:40Z | espn:mlb:401816793 | 25 | in | True | True | 0.9423 | +0.0612 | SUSPECT |
| 09-04 00:07:40Z | espn:mlb:401816793 | 25 | in | True | True | 0.9446 | +0.0586 | SUSPECT |
| 09-04 00:36:15Z | espn:cfb:401858423 | 100 | in | False | False | 0.9859 | +0.0143 | clean |
| 09-04 00:43:09Z | espn:mlb:401816788 | 25 | in | False | True | 0.9388 | +0.0652 | SUSPECT |
| 09-04 00:43:09Z | espn:mlb:401816788 | 100 | in | False | True | 0.9388 | +0.0652 | SUSPECT |
| 09-04 00:43:13Z | espn:mlb:401816788 | 25 | in | False | True | 0.9388 | +0.0652 | SUSPECT |
| 09-04 00:43:13Z | espn:mlb:401816788 | 100 | in | False | True | 0.9388 | +0.0652 | SUSPECT |
| 09-04 00:43:20Z | espn:mlb:401816788 | 25 | in | False | True | 0.9471 | +0.0558 | SUSPECT |
| 09-04 00:43:20Z | espn:mlb:401816788 | 100 | in | False | True | 0.9623 | +0.0392 | SUSPECT |
| 09-04 00:43:21Z | espn:mlb:401816788 | 25 | in | False | True | 0.9496 | +0.0531 | SUSPECT |
| 09-04 00:43:21Z | espn:mlb:401816788 | 100 | in | False | True | 0.9638 | +0.0375 | SUSPECT |
| 09-04 00:43:22Z | espn:mlb:401816788 | 25 | in | False | True | 0.9583 | +0.0435 | SUSPECT |
| 09-04 00:43:22Z | espn:mlb:401816788 | 100 | in | False | True | 0.9670 | +0.0341 | SUSPECT |
| 09-04 00:43:22Z | espn:mlb:401816788 | 25 | in | False | True | 0.9600 | +0.0417 | SUSPECT |
| 09-04 00:43:23Z | espn:mlb:401816788 | 25 | in | False | True | 0.9546 | +0.0476 | SUSPECT |
| 09-04 00:43:25Z | espn:mlb:401816788 | 25 | in | False | True | 0.9596 | +0.0421 | SUSPECT |
| 09-04 00:43:26Z | espn:mlb:401816788 | 25 | in | False | True | 0.9596 | +0.0421 | SUSPECT |
| 09-04 00:43:26Z | espn:mlb:401816788 | 100 | in | False | True | 0.9666 | +0.0345 | SUSPECT |
| 09-04 00:43:31Z | espn:mlb:401816788 | 25 | in | False | True | 0.9492 | +0.0535 | SUSPECT |
| 09-04 00:43:31Z | espn:mlb:401816788 | 100 | in | False | True | 0.9492 | +0.0535 | SUSPECT |
| 09-04 00:43:33Z | espn:mlb:401816788 | 100 | in | False | True | 0.9502 | +0.0524 | SUSPECT |
| 09-04 00:43:35Z | espn:mlb:401816788 | 25 | in | False | True | 0.9517 | +0.0508 | SUSPECT |
| 09-04 00:43:35Z | espn:mlb:401816788 | 100 | in | False | True | 0.9606 | +0.0410 | SUSPECT |
| 09-04 00:43:36Z | espn:mlb:401816788 | 100 | in | False | True | 0.9684 | +0.0326 | SUSPECT |
| 09-04 00:43:37Z | espn:mlb:401816788 | 25 | in | False | True | 0.9616 | +0.0399 | SUSPECT |
| 09-04 00:43:37Z | espn:mlb:401816788 | 25 | in | False | True | 0.9658 | +0.0354 | SUSPECT |
| 09-04 00:43:37Z | espn:mlb:401816788 | 100 | in | False | True | 0.9699 | +0.0310 | SUSPECT |
| 09-04 00:43:37Z | espn:mlb:401816788 | 25 | in | False | True | 0.9699 | +0.0310 | SUSPECT |
| 09-04 00:43:37Z | espn:mlb:401816788 | 100 | in | False | True | 0.9713 | +0.0296 | SUSPECT |
| 09-04 00:43:38Z | espn:mlb:401816788 | 25 | in | False | True | 0.9576 | +0.0443 | SUSPECT |
| 09-04 00:43:39Z | espn:mlb:401816788 | 100 | in | False | True | 0.9900 | +0.0101 | SUSPECT |
| 09-04 00:43:39Z | espn:mlb:401816788 | 100 | in | False | True | 0.9862 | +0.0140 | SUSPECT |
| 09-04 00:43:39Z | espn:mlb:401816788 | 100 | in | False | True | 0.9862 | +0.0140 | SUSPECT |
| 09-04 00:43:40Z | espn:mlb:401816788 | 100 | in | False | True | 0.9826 | +0.0177 | SUSPECT |
| 09-04 00:43:40Z | espn:mlb:401816788 | 100 | in | False | True | 0.9862 | +0.0140 | SUSPECT |
| 09-04 00:43:40Z | espn:mlb:401816788 | 25 | in | False | True | 0.9621 | +0.0394 | SUSPECT |
| 09-04 00:43:40Z | espn:mlb:401816788 | 100 | in | False | True | 0.9887 | +0.0115 | SUSPECT |
| 09-04 00:43:40Z | espn:mlb:401816788 | 25 | in | False | True | 0.9661 | +0.0351 | SUSPECT |
| 09-04 00:43:40Z | espn:mlb:401816788 | 100 | in | False | True | 0.9900 | +0.0101 | SUSPECT |
| 09-04 00:43:40Z | espn:mlb:401816788 | 25 | in | False | True | 0.9683 | +0.0328 | SUSPECT |
| 09-04 00:44:09Z | espn:mlb:401816788 | 25 | in | False | True | 0.9564 | +0.0456 | SUSPECT |
| 09-04 00:44:09Z | espn:mlb:401816788 | 100 | in | False | True | 0.9709 | +0.0300 | SUSPECT |
| 09-04 00:44:09Z | espn:mlb:401816788 | 100 | in | False | True | 0.9678 | +0.0333 | SUSPECT |
| 09-04 00:44:09Z | espn:mlb:401816788 | 100 | in | False | True | 0.9709 | +0.0300 | SUSPECT |
| 09-04 00:44:09Z | espn:mlb:401816788 | 25 | in | False | True | 0.9460 | +0.0571 | SUSPECT |
| 09-04 00:44:09Z | espn:mlb:401816788 | 100 | in | False | True | 0.9460 | +0.0571 | SUSPECT |
| 09-04 00:44:09Z | espn:mlb:401816788 | 25 | in | False | True | 0.9564 | +0.0456 | SUSPECT |
| 09-04 00:44:09Z | espn:mlb:401816788 | 100 | in | False | True | 0.9564 | +0.0456 | SUSPECT |
| 09-04 00:44:09Z | espn:mlb:401816788 | 25 | in | False | True | 0.9522 | +0.0502 | SUSPECT |
| 09-04 00:44:09Z | espn:mlb:401816788 | 100 | in | False | True | 0.9553 | +0.0467 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 25 | in | False | True | 0.9770 | +0.0235 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 25 | in | False | True | 0.9729 | +0.0278 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 100 | in | False | True | 0.9838 | +0.0165 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 100 | in | False | True | 0.9864 | +0.0138 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 25 | in | False | True | 0.9791 | +0.0213 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 100 | in | False | True | 0.9853 | +0.0149 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 25 | in | False | True | 0.9771 | +0.0235 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 100 | in | False | True | 0.9843 | +0.0160 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 100 | in | False | True | 0.9771 | +0.0235 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 25 | in | False | True | 0.9667 | +0.0344 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 100 | in | False | True | 0.9667 | +0.0344 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 100 | in | False | True | 0.9745 | +0.0262 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 100 | in | False | True | 0.9900 | +0.0101 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 100 | in | False | True | 0.9859 | +0.0143 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 25 | in | False | True | 0.9647 | +0.0366 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 100 | in | False | True | 0.9834 | +0.0169 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 100 | in | False | True | 0.9869 | +0.0133 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 100 | in | False | True | 0.9869 | +0.0133 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 25 | in | False | True | 0.9754 | +0.0252 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 25 | in | False | True | 0.9655 | +0.0357 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 25 | in | False | True | 0.9696 | +0.0313 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 25 | in | False | True | 0.9721 | +0.0287 | SUSPECT |
| 09-04 00:49:22Z | espn:cfb:401856776 | 25 | in | True | True | 0.9794 | +0.0210 | SUSPECT |
| 09-04 00:49:22Z | espn:cfb:401856776 | 100 | in | True | True | 0.9794 | +0.0210 | SUSPECT |
| 09-04 00:56:32Z | espn:cfb:401866622 | 100 | in | True | True | 0.9899 | +0.0102 | SUSPECT |
| 09-04 00:56:33Z | espn:cfb:401866622 | 100 | in | True | True | 0.9895 | +0.0106 | SUSPECT |
| 09-04 00:56:33Z | espn:cfb:401866622 | 100 | in | True | True | 0.9900 | +0.0101 | SUSPECT |
| 09-04 01:00:48Z | espn:cfb:401866622 | 100 | in | True | True | 0.9899 | +0.0102 | SUSPECT |
| 09-04 01:00:57Z | espn:cfb:401866622 | 100 | in | True | True | 0.9900 | +0.0101 | SUSPECT |
| 09-04 01:00:58Z | espn:cfb:401866622 | 25 | in | True | True | 0.9662 | +0.0350 | SUSPECT |
| 09-04 01:00:58Z | espn:cfb:401866622 | 100 | in | True | True | 0.9662 | +0.0350 | SUSPECT |
| 09-04 01:00:58Z | espn:cfb:401866622 | 25 | in | True | True | 0.9558 | +0.0463 | SUSPECT |
| 09-04 01:00:58Z | espn:cfb:401866622 | 100 | in | True | True | 0.9558 | +0.0463 | SUSPECT |
| 09-04 02:46:16Z | espn:cfb:401858424 | 100 | in | True | True | 0.9857 | +0.0145 | SUSPECT |
| 09-04 02:46:19Z | espn:cfb:401858424 | 25 | in | True | True | 0.9751 | +0.0255 | SUSPECT |
| 09-04 02:46:19Z | espn:cfb:401858424 | 100 | in | True | True | 0.9751 | +0.0255 | SUSPECT |
| 09-04 02:46:20Z | espn:cfb:401858424 | 25 | in | True | True | 0.9645 | +0.0368 | SUSPECT |
| 09-04 02:46:20Z | espn:cfb:401858424 | 100 | in | True | True | 0.9645 | +0.0368 | SUSPECT |
| 09-04 02:46:24Z | espn:cfb:401858424 | 25 | in | True | True | 0.9645 | +0.0368 | SUSPECT |
| 09-04 02:46:24Z | espn:cfb:401858424 | 100 | in | True | True | 0.9645 | +0.0368 | SUSPECT |
| 09-04 03:00:40Z | espn:cfb:401856776 | 100 | in | True | True | 0.9885 | +0.0117 | SUSPECT |
| 09-04 03:00:42Z | espn:cfb:401856776 | 25 | in | True | True | 0.9786 | +0.0219 | SUSPECT |
| 09-04 03:00:42Z | espn:cfb:401856776 | 100 | in | True | True | 0.9818 | +0.0186 | SUSPECT |
| 09-04 03:00:43Z | espn:cfb:401856776 | 100 | in | True | True | 0.9856 | +0.0146 | SUSPECT |
| 09-04 03:00:43Z | espn:cfb:401856776 | 100 | in | True | True | 0.9786 | +0.0219 | SUSPECT |
| 09-04 03:05:43Z | espn:mlb:401816796 | 100 | in | True | True | 0.9842 | +0.0161 | SUSPECT |
| 09-04 03:05:44Z | espn:mlb:401816796 | 25 | in | True | True | 0.9641 | +0.0372 | SUSPECT |
| 09-04 03:05:44Z | espn:mlb:401816796 | 100 | in | True | True | 0.9641 | +0.0372 | SUSPECT |
| 09-04 03:05:44Z | espn:mlb:401816796 | 25 | in | True | True | 0.9541 | +0.0481 | SUSPECT |
| 09-04 03:05:44Z | espn:mlb:401816796 | 100 | in | True | True | 0.9541 | +0.0481 | SUSPECT |
| 09-04 03:05:49Z | espn:mlb:401816796 | 25 | in | True | True | 0.9641 | +0.0372 | SUSPECT |
| 09-04 03:05:49Z | espn:mlb:401816796 | 100 | in | True | True | 0.9641 | +0.0372 | SUSPECT |
| 09-04 03:05:49Z | espn:mlb:401816796 | 25 | in | True | True | 0.9754 | +0.0253 | SUSPECT |
| 09-04 03:05:49Z | espn:mlb:401816796 | 100 | in | True | True | 0.9820 | +0.0184 | SUSPECT |
| 09-04 03:07:20Z | espn:cfb:401856776 | 25 | in | True | True | 0.9364 | +0.0679 | SUSPECT |
| 09-04 03:07:20Z | espn:cfb:401856776 | 100 | in | True | True | 0.9364 | +0.0680 | SUSPECT |
| 09-04 03:07:21Z | espn:cfb:401856776 | 25 | in | True | True | 0.9157 | +0.0921 | SUSPECT |
| 09-04 03:07:21Z | espn:cfb:401856776 | 100 | in | True | True | 0.9157 | +0.0921 | SUSPECT |
| 09-04 03:07:21Z | espn:cfb:401856776 | 25 | in | True | True | 0.9053 | +0.1046 | SUSPECT |
| 09-04 03:07:21Z | espn:cfb:401856776 | 100 | in | True | True | 0.9053 | +0.1046 | SUSPECT |
| 09-04 03:07:22Z | espn:cfb:401856776 | 100 | in | True | True | 0.9082 | +0.1010 | SUSPECT |
| 09-04 03:07:22Z | espn:cfb:401856776 | 100 | in | True | True | 0.9053 | +0.1046 | SUSPECT |
| 09-04 03:07:22Z | espn:cfb:401856776 | 5 | in | True | True | 0.8950 | +0.1173 | SUSPECT |
| 09-04 03:07:22Z | espn:cfb:401856776 | 25 | in | True | True | 0.8950 | +0.1173 | SUSPECT |
| 09-04 03:07:22Z | espn:cfb:401856776 | 100 | in | True | True | 0.8974 | +0.1144 | SUSPECT |
| 09-04 03:07:23Z | espn:cfb:401856776 | 100 | in | True | True | 0.8960 | +0.1161 | SUSPECT |
| 09-04 03:07:23Z | espn:cfb:401856776 | 5 | in | True | True | 0.8846 | +0.1305 | SUSPECT |
| 09-04 03:07:23Z | espn:cfb:401856776 | 25 | in | True | True | 0.8970 | +0.1148 | SUSPECT |
| 09-04 03:07:23Z | espn:cfb:401856776 | 100 | in | True | True | 0.9033 | +0.1071 | SUSPECT |
| 09-04 03:07:23Z | espn:cfb:401856776 | 5 | in | True | True | 0.8950 | +0.1173 | SUSPECT |
| 09-04 03:07:23Z | espn:cfb:401856776 | 25 | in | True | True | 0.8950 | +0.1173 | SUSPECT |
| 09-04 03:07:23Z | espn:cfb:401856776 | 100 | in | True | True | 0.8950 | +0.1174 | SUSPECT |
| 09-04 03:07:23Z | espn:cfb:401856776 | 5 | in | True | True | 0.8846 | +0.1305 | SUSPECT |
| 09-04 03:07:23Z | espn:cfb:401856776 | 25 | in | True | True | 0.8846 | +0.1305 | SUSPECT |
| 09-04 03:07:23Z | espn:cfb:401856776 | 100 | in | True | True | 0.8846 | +0.1305 | SUSPECT |
| 09-04 03:07:24Z | espn:cfb:401856776 | 100 | in | True | True | 0.8887 | +0.1252 | SUSPECT |
| 09-04 03:07:24Z | espn:cfb:401856776 | 5 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:24Z | espn:cfb:401856776 | 25 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:24Z | espn:cfb:401856776 | 100 | in | True | True | 0.8767 | +0.1407 | SUSPECT |
| 09-04 03:07:24Z | espn:cfb:401856776 | 5 | in | True | True | 0.8680 | +0.1521 | SUSPECT |
| 09-04 03:07:24Z | espn:cfb:401856776 | 25 | in | True | True | 0.8729 | +0.1456 | SUSPECT |
| 09-04 03:07:24Z | espn:cfb:401856776 | 100 | in | True | True | 0.8778 | +0.1392 | SUSPECT |
| 09-04 03:07:24Z | espn:cfb:401856776 | 5 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:24Z | espn:cfb:401856776 | 25 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:24Z | espn:cfb:401856776 | 100 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:25Z | espn:cfb:401856776 | 5 | in | True | True | 0.8638 | +0.1577 | SUSPECT |
| 09-04 03:07:25Z | espn:cfb:401856776 | 25 | in | True | True | 0.8638 | +0.1577 | SUSPECT |
| 09-04 03:07:25Z | espn:cfb:401856776 | 100 | in | True | True | 0.8638 | +0.1577 | SUSPECT |
| 09-04 03:07:26Z | espn:cfb:401856776 | 5 | in | True | True | 0.8534 | +0.1718 | SUSPECT |
| 09-04 03:07:26Z | espn:cfb:401856776 | 25 | in | True | True | 0.8534 | +0.1718 | SUSPECT |
| 09-04 03:07:26Z | espn:cfb:401856776 | 100 | in | True | True | 0.8584 | +0.1650 | SUSPECT |
| 09-04 03:07:27Z | espn:cfb:401856776 | 25 | in | True | True | 0.8596 | +0.1633 | SUSPECT |
| 09-04 03:07:27Z | espn:cfb:401856776 | 100 | in | True | True | 0.8627 | +0.1591 | SUSPECT |
| 09-04 03:07:27Z | espn:cfb:401856776 | 5 | in | True | True | 0.8638 | +0.1577 | SUSPECT |
| 09-04 03:07:27Z | espn:cfb:401856776 | 25 | in | True | True | 0.8638 | +0.1577 | SUSPECT |
| 09-04 03:07:27Z | espn:cfb:401856776 | 100 | in | True | True | 0.8638 | +0.1577 | SUSPECT |
| 09-04 03:07:28Z | espn:cfb:401856776 | 5 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:28Z | espn:cfb:401856776 | 25 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:28Z | espn:cfb:401856776 | 100 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:30Z | espn:cfb:401856776 | 5 | in | True | True | 0.8846 | +0.1305 | SUSPECT |
| 09-04 03:07:30Z | espn:cfb:401856776 | 25 | in | True | True | 0.8846 | +0.1305 | SUSPECT |
| 09-04 03:07:30Z | espn:cfb:401856776 | 100 | in | True | True | 0.8846 | +0.1305 | SUSPECT |
| 09-04 03:07:30Z | espn:cfb:401856776 | 5 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:30Z | espn:cfb:401856776 | 25 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:30Z | espn:cfb:401856776 | 100 | in | True | True | 0.8794 | +0.1372 | SUSPECT |
| 09-04 03:07:30Z | espn:cfb:401856776 | 100 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:31Z | espn:cfb:401856776 | 5 | in | True | True | 0.8643 | +0.1570 | SUSPECT |
| 09-04 03:07:31Z | espn:cfb:401856776 | 25 | in | True | True | 0.8643 | +0.1570 | SUSPECT |
| 09-04 03:07:31Z | espn:cfb:401856776 | 100 | in | True | True | 0.8643 | +0.1570 | SUSPECT |
| 09-04 03:07:31Z | espn:cfb:401856776 | 100 | in | True | True | 0.8677 | +0.1525 | SUSPECT |
| 09-04 03:07:32Z | espn:cfb:401856776 | 5 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:32Z | espn:cfb:401856776 | 25 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:32Z | espn:cfb:401856776 | 100 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:32Z | espn:cfb:401856776 | 5 | in | True | True | 0.8846 | +0.1305 | SUSPECT |
| 09-04 03:07:32Z | espn:cfb:401856776 | 25 | in | True | True | 0.8846 | +0.1305 | SUSPECT |
| 09-04 03:07:32Z | espn:cfb:401856776 | 100 | in | True | True | 0.8893 | +0.1245 | SUSPECT |
| 09-04 03:07:32Z | espn:cfb:401856776 | 5 | in | True | True | 0.8945 | +0.1180 | SUSPECT |
| 09-04 03:07:32Z | espn:cfb:401856776 | 25 | in | True | True | 0.8945 | +0.1180 | SUSPECT |
| 09-04 03:07:32Z | espn:cfb:401856776 | 100 | in | True | True | 0.8945 | +0.1180 | SUSPECT |
| 09-04 03:07:33Z | espn:cfb:401856776 | 5 | in | True | True | 0.8841 | +0.1311 | SUSPECT |
| 09-04 03:07:33Z | espn:cfb:401856776 | 25 | in | True | True | 0.8841 | +0.1311 | SUSPECT |
| 09-04 03:07:33Z | espn:cfb:401856776 | 100 | in | True | True | 0.8841 | +0.1311 | SUSPECT |
| 09-04 03:07:33Z | espn:cfb:401856776 | 25 | in | True | True | 0.9038 | +0.1064 | SUSPECT |
| 09-04 03:07:33Z | espn:cfb:401856776 | 100 | in | True | True | 0.9038 | +0.1064 | SUSPECT |
| 09-04 03:07:33Z | espn:cfb:401856776 | 25 | in | True | True | 0.9196 | +0.0875 | SUSPECT |
| 09-04 03:07:33Z | espn:cfb:401856776 | 100 | in | True | True | 0.9225 | +0.0840 | SUSPECT |
| 09-04 03:07:34Z | espn:cfb:401856776 | 25 | in | True | True | 0.9117 | +0.0968 | SUSPECT |
| 09-04 03:07:34Z | espn:cfb:401856776 | 100 | in | True | True | 0.9196 | +0.0875 | SUSPECT |
| 09-04 03:07:35Z | espn:cfb:401856776 | 25 | in | True | True | 0.9196 | +0.0875 | SUSPECT |
| 09-04 03:07:35Z | espn:cfb:401856776 | 100 | in | True | True | 0.9225 | +0.0840 | SUSPECT |
| 09-04 03:07:51Z | espn:mlb:401816796 | 100 | in | True | True | 0.9846 | +0.0157 | SUSPECT |
| 09-04 03:12:37Z | espn:mlb:401816796 | 25 | in | True | True | 0.9442 | +0.0591 | SUSPECT |
| 09-04 03:12:37Z | espn:mlb:401816796 | 100 | in | True | True | 0.9442 | +0.0591 | SUSPECT |
| 09-04 03:12:38Z | espn:mlb:401816796 | 25 | in | True | True | 0.9341 | +0.0706 | SUSPECT |
| 09-04 03:12:38Z | espn:mlb:401816796 | 100 | in | True | True | 0.9341 | +0.0706 | SUSPECT |
| 09-04 03:12:41Z | espn:mlb:401816796 | 100 | in | True | True | 0.9845 | +0.0157 | SUSPECT |
| 09-04 03:12:44Z | espn:mlb:401816796 | 25 | in | True | True | 0.9744 | +0.0263 | SUSPECT |
| 09-04 03:12:44Z | espn:mlb:401816796 | 100 | in | True | True | 0.9744 | +0.0263 | SUSPECT |
| 09-04 03:29:19Z | espn:cfb:401856776 | 100 | in | False | True | 0.9855 | +0.0148 | SUSPECT |
| 09-04 03:29:19Z | espn:cfb:401856776 | 25 | in | False | True | 0.9749 | +0.0257 | SUSPECT |
| 09-04 03:29:19Z | espn:cfb:401856776 | 100 | in | False | True | 0.9816 | +0.0188 | SUSPECT |
| 09-04 03:29:20Z | espn:cfb:401856776 | 100 | in | False | True | 0.9878 | +0.0124 | SUSPECT |
| 09-04 03:29:20Z | espn:cfb:401856776 | 100 | in | False | True | 0.9855 | +0.0148 | SUSPECT |
| 09-04 03:29:20Z | espn:cfb:401856776 | 25 | in | False | True | 0.9749 | +0.0257 | SUSPECT |
| 09-04 03:29:20Z | espn:cfb:401856776 | 100 | in | False | True | 0.9749 | +0.0257 | SUSPECT |
| 09-04 03:29:23Z | espn:cfb:401856776 | 100 | in | False | True | 0.9855 | +0.0148 | SUSPECT |
| 09-04 03:30:41Z | espn:cfb:401856776 | 100 | in | False | True | 0.9861 | +0.0141 | SUSPECT |
| 09-04 03:35:50Z | espn:cfb:401856776 | 25 | in | False | True | 0.9781 | +0.0224 | SUSPECT |
| 09-04 03:38:24Z | espn:cfb:401856776 | 25 | in | False | True | 0.9596 | +0.0421 | SUSPECT |
| 09-04 03:38:24Z | espn:cfb:401856776 | 100 | in | False | True | 0.9887 | +0.0114 | SUSPECT |
| 09-04 03:41:45Z | espn:cfb:401856776 | 5 | end | False | True | 0.8595 | +0.1634 | SUSPECT |
| 09-04 03:41:45Z | espn:cfb:401856776 | 25 | end | False | True | 0.8837 | +0.1316 | SUSPECT |
| 09-04 03:41:45Z | espn:cfb:401856776 | 100 | end | False | True | 0.8984 | +0.1131 | SUSPECT |
| 09-04 03:41:46Z | espn:cfb:401856776 | 5 | end | False | True | 0.8798 | +0.1366 | SUSPECT |
| 09-04 03:41:46Z | espn:cfb:401856776 | 25 | end | False | True | 0.9039 | +0.1063 | SUSPECT |
| 09-04 03:41:46Z | espn:cfb:401856776 | 100 | end | False | True | 0.9600 | +0.0417 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 25 | end | False | True | 0.9501 | +0.0525 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 100 | end | False | True | 0.9550 | +0.0472 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 25 | end | False | True | 0.9433 | +0.0601 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 100 | end | False | True | 0.9587 | +0.0431 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 25 | end | False | True | 0.9226 | +0.0839 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 100 | end | False | True | 0.9380 | +0.0661 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 5 | end | False | True | 0.8950 | +0.1173 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 25 | end | False | True | 0.9019 | +0.1088 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 100 | end | False | True | 0.9180 | +0.0893 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 25 | end | False | True | 0.9147 | +0.0932 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 100 | end | False | True | 0.9681 | +0.0329 | SUSPECT |
| 09-04 03:41:49Z | espn:cfb:401856776 | 25 | end | False | True | 0.9759 | +0.0247 | SUSPECT |
| 09-04 03:41:51Z | espn:cfb:401856776 | 25 | end | False | True | 0.9662 | +0.0350 | SUSPECT |
| 09-04 03:41:51Z | espn:cfb:401856776 | 100 | end | False | True | 0.9734 | +0.0273 | SUSPECT |
| 09-04 03:44:34Z | espn:cfb:401856776 | 25 | end | False | True | 0.9487 | +0.0541 | SUSPECT |
| 09-04 03:44:34Z | espn:cfb:401856776 | 100 | end | False | True | 0.9487 | +0.0541 | SUSPECT |
| 09-04 03:44:34Z | espn:cfb:401856776 | 25 | end | False | True | 0.9695 | +0.0315 | SUSPECT |
| 09-04 03:44:34Z | espn:cfb:401856776 | 100 | end | False | True | 0.9775 | +0.0230 | SUSPECT |
| 09-04 03:44:34Z | espn:cfb:401856776 | 25 | end | False | True | 0.9198 | +0.0872 | SUSPECT |
| 09-04 03:44:34Z | espn:cfb:401856776 | 100 | end | False | True | 0.9397 | +0.0642 | SUSPECT |
| 09-04 03:44:35Z | espn:cfb:401856776 | 5 | end | False | True | 0.8726 | +0.1460 | SUSPECT |
| 09-04 03:44:35Z | espn:cfb:401856776 | 25 | end | False | True | 0.9153 | +0.0925 | SUSPECT |

**n for the forward paper row: 33** (basis: power; 95 in-play, clean actionable rows; sigma 0.01458, median locked return 0.02888).

Descriptive. Reads no outcome, claims no edge.

## Run 20260905T074457Z

502773 rows in the lane's vocabulary since the seal over 56 games; 6025 rows of the old vocabulary excluded; 1205 flap windows (109708 s).

| cell (league, q, phase, flap, fee era) | rows | dwell s | priced | near 1¢ | profitable | cost p50 | p90 | min | statuses (dwell share) | blocked reasons (dwell share) |
|---|---|---|---|---|---|---|---|---|---|---|
| cfb|5|end|clean|fee-repinned+probe | 1369 | 8171 | 0.05 | 0.001 | 0.000 | 1.0261 | 1.0363 | 0.8595 | BLOCKED_DEPTH 0.15, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.80, DISCOVERED 0.00, NO_EDGE 0.03, PROFITABLE_UNEXECUTED 0.00 | (none) 0.02, kalshi:CROSSED_BOOK 0.02, kalshi:NO_ASKS 0.15, kalshi:STALE 0.73, polymarket:HASH_MISMATCH 0.00, polymarket:STALE 0.05 |
| cfb|5|end|flap|fee-repinned+probe | 57 | 1487 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_DEPTH 0.29, BLOCKED_STALE 0.71 | kalshi:HEARTBEAT_LOST 0.13, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.29, kalshi:STALE 0.08, supervisor:CLOCK_UNHEALTHY 0.49 |
| cfb|5|in|clean|fee-half | 3228 | 21553 | 0.20 | 0.010 | 0.000 | 1.0220 | 1.0509 | 0.9725 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.03, BLOCKED_MATCH 0.10, BLOCKED_STALE 0.78, DISCOVERED 0.00, NO_EDGE 0.07 | (none) 0.13, kalshi:HEARTBEAT_LOST 0.19, kalshi:NO_ASKS 0.02, kalshi:STALE 0.10, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.01, polymarket:STALE 0.06, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.40 |
| cfb|5|in|clean|fee-repinned | 1781 | 18612 | 0.14 | 0.001 | 0.000 | 1.0228 | 1.0350 | 0.9833 | BLOCKED_DEPTH 0.08, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.08, BLOCKED_STALE 0.78, DISCOVERED 0.00, NO_EDGE 0.05 | (none) 0.09, kalshi:NO_ASKS 0.08, kalshi:STALE 0.13, polymarket:HASH_MISMATCH 0.05, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.05, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.51 |
| cfb|5|in|clean|fee-repinned+probe | 21371 | 105379 | 0.34 | 0.001 | 0.000 | 1.0281 | 1.0455 | 0.9040 | BLOCKED_DEPTH 0.19, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.21, BLOCKED_STALE 0.47, DISCOVERED 0.00, NO_EDGE 0.12 | (none) 0.22, kalshi:CROSSED_BOOK 0.10, kalshi:HEARTBEAT_LOST 0.00, kalshi:NO_ASKS 0.19, kalshi:STALE 0.27, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.06, polymarket:UNVERIFIED_TOO_LONG 0.00, supervisor:CLOCK_UNHEALTHY 0.01, supervisor:LOOP_STALLED 0.02 |
| cfb|5|in|flap|fee-half | 1963 | 23358 | 0.06 | 0.002 | 0.000 | 1.0225 | 1.0460 | 0.9854 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.03, BLOCKED_STALE 0.92, DISCOVERED 0.00, NO_EDGE 0.02 | (none) 0.04, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.02, kalshi:STALE 0.05, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.02, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.81 |
| cfb|5|in|flap|fee-repinned | 415 | 6613 | 0.03 | 0.001 | 0.000 | 1.0197 | 1.0349 | 0.9794 | BLOCKED_DEPTH 0.02, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.94, DISCOVERED 0.00, NO_EDGE 0.01 | (none) 0.02, kalshi:NO_ASKS 0.02, kalshi:STALE 0.05, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.03, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.03, polymarket:UNVERIFIED_TOO_LONG 0.00, supervisor:CLOCK_UNHEALTHY 0.81 |
| cfb|5|in|flap|fee-repinned+probe | 1824 | 24552 | 0.08 | 0.004 | 0.000 | 1.0173 | 1.0349 | 0.8534 | BLOCKED_DEPTH 0.06, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.86, DISCOVERED 0.00, NO_EDGE 0.02, PROFITABLE_UNEXECUTED 0.00 | (none) 0.05, kalshi:CROSSED_BOOK 0.00, kalshi:HEARTBEAT_LOST 0.04, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.06, kalshi:STALE 0.13, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.02, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.52, supervisor:LOOP_STALLED 0.09 |
| cfb|5|pre|clean|fee-half | 6508 | 123774 | 0.07 | 0.000 | 0.000 | 1.0133 | 1.0332 | 0.9893 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.93, DISCOVERED 0.00, NO_EDGE 0.03 | (none) 0.04, kalshi:HEARTBEAT_LOST 0.14, kalshi:NOT_SYNCED 0.03, kalshi:NO_ASKS 0.00, kalshi:STALE 0.25, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.10, polymarket:STALE 0.16, polymarket:UNVERIFIED_TOO_LONG 0.10, supervisor:CLOCK_UNHEALTHY 0.15 |
| cfb|5|pre|clean|fee-repinned | 219 | 3424 | 0.10 | 0.000 | 0.000 | 1.0067 | 1.0097 | 1.0054 | BLOCKED_MATCH 0.04, BLOCKED_STALE 0.90, NO_EDGE 0.06 | (none) 0.04, kalshi:STALE 0.15, polymarket:HEARTBEAT_LOST 0.10, polymarket:STALE 0.09, polymarket:UNVERIFIED_TOO_LONG 0.06, supervisor:CLOCK_UNHEALTHY 0.50 |
| cfb|5|pre|clean|fee-repinned+probe | 17175 | 170766 | 0.22 | 0.000 | 0.000 | 1.0292 | 1.0494 | 0.9973 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.02, BLOCKED_MATCH 0.08, BLOCKED_STALE 0.76, DISCOVERED 0.00, NO_EDGE 0.13 | (none) 0.09, kalshi:CROSSED_BOOK 0.01, kalshi:NO_ASKS 0.02, kalshi:STALE 0.49, polymarket:HASH_MISMATCH 0.00, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.25, supervisor:CLOCK_UNHEALTHY 0.00, supervisor:LOOP_STALLED 0.00 |
| cfb|5|pre|flap|fee-half | 1010 | 23070 | 0.03 | 0.000 | 0.000 | 1.0127 | 1.0332 | 1.0032 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.01, BLOCKED_STALE 0.97, NO_EDGE 0.01 | (none) 0.01, kalshi:HEARTBEAT_LOST 0.02, kalshi:NOT_SYNCED 0.19, kalshi:NO_ASKS 0.00, kalshi:STALE 0.05, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.03, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.64 |
| cfb|5|pre|flap|fee-repinned | 75 | 1242 | 0.04 | 0.000 | 0.000 | 1.0088 | 1.0088 | 1.0057 | BLOCKED_MATCH 0.04, BLOCKED_STALE 0.96, NO_EDGE 0.00 | (none) 0.04, kalshi:STALE 0.06, polymarket:HEARTBEAT_LOST 0.03, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.82 |
| cfb|5|pre|flap|fee-repinned+probe | 79 | 963 | 0.20 | 0.000 | 0.000 | 1.0304 | 1.0362 | 1.0068 | BLOCKED_DEPTH 0.01, BLOCKED_MATCH 0.01, BLOCKED_STALE 0.79, NO_EDGE 0.19 | (none) 0.01, kalshi:NO_ASKS 0.01, kalshi:STALE 0.43, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.22, supervisor:CLOCK_UNHEALTHY 0.12 |
| cfb|25|end|clean|fee-repinned+probe | 1404 | 8169 | 0.05 | 0.001 | 0.001 | 1.0263 | 1.0375 | 0.8837 | BLOCKED_DEPTH 0.15, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.80, DISCOVERED 0.00, NO_EDGE 0.03, PROFITABLE_UNEXECUTED 0.00 | (none) 0.02, kalshi:CROSSED_BOOK 0.02, kalshi:NO_ASKS 0.15, kalshi:STALE 0.73, polymarket:HASH_MISMATCH 0.00, polymarket:STALE 0.05 |
| cfb|25|end|flap|fee-repinned+probe | 57 | 1487 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_DEPTH 0.29, BLOCKED_STALE 0.71 | kalshi:HEARTBEAT_LOST 0.13, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.29, kalshi:STALE 0.08, supervisor:CLOCK_UNHEALTHY 0.49 |
| cfb|25|in|clean|fee-half | 4398 | 21554 | 0.20 | 0.006 | 0.001 | 1.0225 | 1.0564 | 0.9719 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.03, BLOCKED_MATCH 0.11, BLOCKED_STALE 0.78, DISCOVERED 0.00, NO_EDGE 0.07, PROFITABLE_UNEXECUTED 0.00 | (none) 0.13, kalshi:HEARTBEAT_LOST 0.19, kalshi:NO_ASKS 0.02, kalshi:STALE 0.10, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.01, polymarket:STALE 0.06, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.40 |
| cfb|25|in|clean|fee-repinned | 2275 | 18614 | 0.14 | 0.000 | 0.000 | 1.0261 | 1.0372 | 0.9853 | BLOCKED_DEPTH 0.08, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.08, BLOCKED_STALE 0.78, DISCOVERED 0.00, NO_EDGE 0.06 | (none) 0.08, kalshi:NO_ASKS 0.08, kalshi:STALE 0.13, polymarket:HASH_MISMATCH 0.05, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.05, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.51 |
| cfb|25|in|clean|fee-repinned+probe | 23425 | 105380 | 0.34 | 0.001 | 0.000 | 1.0287 | 1.0501 | 0.9328 | BLOCKED_DEPTH 0.19, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.21, BLOCKED_STALE 0.47, DISCOVERED 0.00, NO_EDGE 0.12, PROFITABLE_UNEXECUTED 0.00 | (none) 0.22, kalshi:CROSSED_BOOK 0.10, kalshi:HEARTBEAT_LOST 0.00, kalshi:NO_ASKS 0.19, kalshi:STALE 0.27, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.06, polymarket:UNVERIFIED_TOO_LONG 0.00, supervisor:CLOCK_UNHEALTHY 0.01, supervisor:LOOP_STALLED 0.02 |
| cfb|25|in|flap|fee-half | 3227 | 21352 | 0.06 | 0.001 | 0.000 | 1.0280 | 1.0500 | 0.9838 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.92, DISCOVERED 0.00, NO_EDGE 0.02 | (none) 0.04, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.02, kalshi:STALE 0.06, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.02, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.79 |
| cfb|25|in|flap|fee-repinned | 466 | 6613 | 0.03 | 0.001 | 0.001 | 1.0209 | 1.0349 | 0.9794 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.94, NO_EDGE 0.01, PROFITABLE_UNEXECUTED 0.00 | (none) 0.02, kalshi:NO_ASKS 0.02, kalshi:STALE 0.05, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.03, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.03, polymarket:UNVERIFIED_TOO_LONG 0.00, supervisor:CLOCK_UNHEALTHY 0.81 |
| cfb|25|in|flap|fee-repinned+probe | 2017 | 24553 | 0.08 | 0.003 | 0.002 | 1.0179 | 1.0379 | 0.8534 | BLOCKED_DEPTH 0.06, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.86, DISCOVERED 0.00, NO_EDGE 0.02, PROFITABLE_UNEXECUTED 0.00 | (none) 0.05, kalshi:CROSSED_BOOK 0.00, kalshi:HEARTBEAT_LOST 0.04, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.06, kalshi:STALE 0.13, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.02, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.52, supervisor:LOOP_STALLED 0.09 |
| cfb|25|pre|clean|fee-half | 6583 | 123774 | 0.07 | 0.000 | 0.000 | 1.0144 | 1.0349 | 0.9893 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.93, DISCOVERED 0.00, NO_EDGE 0.02 | (none) 0.04, kalshi:HEARTBEAT_LOST 0.14, kalshi:NOT_SYNCED 0.03, kalshi:NO_ASKS 0.00, kalshi:STALE 0.25, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.10, polymarket:STALE 0.16, polymarket:UNVERIFIED_TOO_LONG 0.10, supervisor:CLOCK_UNHEALTHY 0.15 |
| cfb|25|pre|clean|fee-repinned | 219 | 3424 | 0.10 | 0.000 | 0.000 | 1.0066 | 1.0097 | 1.0054 | BLOCKED_MATCH 0.04, BLOCKED_STALE 0.90, NO_EDGE 0.06 | (none) 0.04, kalshi:STALE 0.15, polymarket:HEARTBEAT_LOST 0.10, polymarket:STALE 0.09, polymarket:UNVERIFIED_TOO_LONG 0.06, supervisor:CLOCK_UNHEALTHY 0.50 |
| cfb|25|pre|clean|fee-repinned+probe | 18427 | 170766 | 0.22 | 0.000 | 0.000 | 1.0301 | 1.0555 | 0.9973 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.08, BLOCKED_STALE 0.76, DISCOVERED 0.00, NO_EDGE 0.12 | (none) 0.10, kalshi:CROSSED_BOOK 0.01, kalshi:NO_ASKS 0.02, kalshi:STALE 0.49, polymarket:HASH_MISMATCH 0.00, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.25, supervisor:CLOCK_UNHEALTHY 0.00, supervisor:LOOP_STALLED 0.00 |
| cfb|25|pre|flap|fee-half | 1010 | 23070 | 0.03 | 0.000 | 0.000 | 1.0118 | 1.0332 | 1.0028 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.01, BLOCKED_STALE 0.97, NO_EDGE 0.02 | (none) 0.01, kalshi:HEARTBEAT_LOST 0.02, kalshi:NOT_SYNCED 0.19, kalshi:NO_ASKS 0.00, kalshi:STALE 0.05, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.03, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.64 |
| cfb|25|pre|flap|fee-repinned | 75 | 1242 | 0.04 | 0.000 | 0.000 | 1.0088 | 1.0088 | 1.0057 | BLOCKED_MATCH 0.04, BLOCKED_STALE 0.96, NO_EDGE 0.00 | (none) 0.04, kalshi:STALE 0.06, polymarket:HEARTBEAT_LOST 0.03, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.82 |
| cfb|25|pre|flap|fee-repinned+probe | 95 | 963 | 0.20 | 0.000 | 0.000 | 1.0304 | 1.0486 | 1.0068 | BLOCKED_DEPTH 0.01, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.79, NO_EDGE 0.18 | (none) 0.02, kalshi:NO_ASKS 0.01, kalshi:STALE 0.43, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.22, supervisor:CLOCK_UNHEALTHY 0.12 |
| cfb|100|end|clean|fee-repinned+probe | 1405 | 8183 | 0.05 | 0.001 | 0.001 | 1.0263 | 1.0407 | 0.8984 | BLOCKED_DEPTH 0.15, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.80, DISCOVERED 0.00, NO_EDGE 0.02, PROFITABLE_UNEXECUTED 0.00 | (none) 0.02, kalshi:CROSSED_BOOK 0.02, kalshi:NO_ASKS 0.15, kalshi:STALE 0.72, polymarket:HASH_MISMATCH 0.00, polymarket:STALE 0.05 |
| cfb|100|end|flap|fee-repinned+probe | 57 | 1487 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_DEPTH 0.29, BLOCKED_STALE 0.71 | kalshi:HEARTBEAT_LOST 0.13, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.29, kalshi:STALE 0.08, supervisor:CLOCK_UNHEALTHY 0.49 |
| cfb|100|in|clean|fee-half | 6442 | 21552 | 0.20 | 0.002 | 0.001 | 1.0231 | 1.0630 | 0.9722 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.02, BLOCKED_MATCH 0.11, BLOCKED_STALE 0.78, DISCOVERED 0.00, NO_EDGE 0.07, PROFITABLE_UNEXECUTED 0.00 | (none) 0.13, kalshi:HEARTBEAT_LOST 0.19, kalshi:NO_ASKS 0.02, kalshi:STALE 0.10, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.01, polymarket:STALE 0.06, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.40 |
| cfb|100|in|clean|fee-repinned | 2767 | 18614 | 0.14 | 0.000 | 0.000 | 1.0269 | 1.0431 | 0.9859 | BLOCKED_DEPTH 0.08, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.08, BLOCKED_STALE 0.78, DISCOVERED 0.00, NO_EDGE 0.06, PROFITABLE_UNEXECUTED 0.00 | (none) 0.09, kalshi:NO_ASKS 0.08, kalshi:STALE 0.13, polymarket:HASH_MISMATCH 0.05, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.05, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.51 |
| cfb|100|in|clean|fee-repinned+probe | 25778 | 105373 | 0.34 | 0.001 | 0.000 | 1.0301 | 1.0574 | 0.9575 | BLOCKED_DEPTH 0.19, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.21, BLOCKED_STALE 0.47, DISCOVERED 0.00, NO_EDGE 0.12, PROFITABLE_UNEXECUTED 0.00 | (none) 0.22, kalshi:CROSSED_BOOK 0.10, kalshi:HEARTBEAT_LOST 0.00, kalshi:NO_ASKS 0.19, kalshi:STALE 0.27, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.06, polymarket:UNVERIFIED_TOO_LONG 0.00, supervisor:CLOCK_UNHEALTHY 0.01, supervisor:LOOP_STALLED 0.02 |
| cfb|100|in|flap|fee-half | 4838 | 21349 | 0.06 | 0.000 | 0.000 | 1.0304 | 1.0598 | 1.0042 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.05, BLOCKED_STALE 0.92, NO_EDGE 0.02 | (none) 0.05, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.02, kalshi:STALE 0.06, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.02, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.79 |
| cfb|100|in|flap|fee-repinned | 529 | 6613 | 0.03 | 0.001 | 0.001 | 1.0252 | 1.0392 | 0.9794 | BLOCKED_DEPTH 0.02, BLOCKED_MATCH 0.03, BLOCKED_STALE 0.94, NO_EDGE 0.01, PROFITABLE_UNEXECUTED 0.00 | (none) 0.03, kalshi:NO_ASKS 0.02, kalshi:STALE 0.05, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.03, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.03, polymarket:UNVERIFIED_TOO_LONG 0.00, supervisor:CLOCK_UNHEALTHY 0.81 |
| cfb|100|in|flap|fee-repinned+probe | 2266 | 24557 | 0.08 | 0.003 | 0.003 | 1.0179 | 1.0402 | 0.8584 | BLOCKED_DEPTH 0.06, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.86, DISCOVERED 0.00, NO_EDGE 0.03, PROFITABLE_UNEXECUTED 0.00 | (none) 0.05, kalshi:CROSSED_BOOK 0.00, kalshi:HEARTBEAT_LOST 0.04, kalshi:NOT_SYNCED 0.00, kalshi:NO_ASKS 0.06, kalshi:STALE 0.13, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.02, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.52, supervisor:LOOP_STALLED 0.09 |
| cfb|100|pre|clean|fee-half | 6575 | 123774 | 0.07 | 0.000 | 0.000 | 1.0151 | 1.0370 | 0.9891 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.93, NO_EDGE 0.02, PROFITABLE_UNEXECUTED 0.00 | (none) 0.05, kalshi:HEARTBEAT_LOST 0.14, kalshi:NOT_SYNCED 0.03, kalshi:NO_ASKS 0.00, kalshi:STALE 0.25, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.10, polymarket:STALE 0.16, polymarket:UNVERIFIED_TOO_LONG 0.10, supervisor:CLOCK_UNHEALTHY 0.15 |
| cfb|100|pre|clean|fee-repinned | 219 | 3424 | 0.10 | 0.000 | 0.000 | 1.0066 | 1.0097 | 1.0054 | BLOCKED_MATCH 0.04, BLOCKED_STALE 0.90, NO_EDGE 0.06 | (none) 0.04, kalshi:STALE 0.15, polymarket:HEARTBEAT_LOST 0.10, polymarket:STALE 0.09, polymarket:UNVERIFIED_TOO_LONG 0.06, supervisor:CLOCK_UNHEALTHY 0.50 |
| cfb|100|pre|clean|fee-repinned+probe | 20235 | 170757 | 0.22 | 0.000 | 0.000 | 1.0306 | 1.0647 | 1.0026 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.10, BLOCKED_STALE 0.76, NO_EDGE 0.11 | (none) 0.11, kalshi:CROSSED_BOOK 0.01, kalshi:NO_ASKS 0.02, kalshi:STALE 0.49, polymarket:HASH_MISMATCH 0.00, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.25, supervisor:CLOCK_UNHEALTHY 0.00, supervisor:LOOP_STALLED 0.00 |
| cfb|100|pre|flap|fee-half | 1010 | 23070 | 0.03 | 0.000 | 0.000 | 1.0117 | 1.0332 | 1.0055 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.01, BLOCKED_STALE 0.97, NO_EDGE 0.02 | (none) 0.01, kalshi:HEARTBEAT_LOST 0.02, kalshi:NOT_SYNCED 0.19, kalshi:NO_ASKS 0.00, kalshi:STALE 0.05, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.03, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.64 |
| cfb|100|pre|flap|fee-repinned | 75 | 1242 | 0.04 | 0.000 | 0.000 | 1.0088 | 1.0088 | 1.0057 | BLOCKED_MATCH 0.04, BLOCKED_STALE 0.96, NO_EDGE 0.00 | (none) 0.04, kalshi:STALE 0.06, polymarket:HEARTBEAT_LOST 0.03, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.01, supervisor:CLOCK_UNHEALTHY 0.82 |
| cfb|100|pre|flap|fee-repinned+probe | 84 | 963 | 0.20 | 0.000 | 0.000 | 1.0304 | 1.0493 | 1.0068 | BLOCKED_DEPTH 0.01, BLOCKED_MATCH 0.03, BLOCKED_STALE 0.79, NO_EDGE 0.17 | (none) 0.03, kalshi:NO_ASKS 0.01, kalshi:STALE 0.43, polymarket:HEARTBEAT_LOST 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.22, supervisor:CLOCK_UNHEALTHY 0.12 |
| lal|5|end|clean|fee-half | 118 | 338 | 0.15 | 0.000 | 0.000 | 1.0331 | 1.0356 | 0.9956 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.03, BLOCKED_STALE 0.85, DISCOVERED 0.00, NO_EDGE 0.11 | (none) 0.03, kalshi:NOT_SYNCED 0.78, polymarket:HASH_MISMATCH 0.07 |
| lal|5|end|flap|fee-half | 15 | 321 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_STALE 1.00 | kalshi:HEARTBEAT_LOST 0.07, kalshi:NOT_SYNCED 0.93 |
| lal|5|in|clean|fee-half | 924 | 4208 | 0.22 | 0.000 | 0.000 | 1.0547 | 1.0682 | 1.0067 | BLOCKED_FEES 0.01, BLOCKED_MATCH 0.11, BLOCKED_STALE 0.78, NO_EDGE 0.10 | (none) 0.11, kalshi:HEARTBEAT_LOST 0.00, kalshi:NOT_SYNCED 0.00, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.47, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.25 |
| lal|5|pre|flap|fee-half | 77 | 1338 | 0.01 | 0.000 | 0.000 | 1.0451 | 1.0543 | 1.0451 | BLOCKED_MATCH 0.00, BLOCKED_STALE 0.99, NO_EDGE 0.01 | (none) 0.00, kalshi:NOT_SYNCED 0.54, kalshi:STALE 0.13, polymarket:HEARTBEAT_LOST 0.18, polymarket:NOT_SYNCED 0.05, polymarket:STALE 0.09 |
| lal|25|end|clean|fee-half | 143 | 109 | 0.99 | 0.000 | 0.000 | 1.0208 | 1.0336 | 1.0028 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.64, BLOCKED_STALE 0.01, NO_EDGE 0.35 | (none) 0.64, polymarket:HASH_MISMATCH 0.01 |
| lal|25|in|clean|fee-half | 1252 | 4208 | 0.22 | 0.000 | 0.000 | 1.0547 | 1.0727 | 1.0113 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.11, BLOCKED_STALE 0.78, NO_EDGE 0.11 | (none) 0.11, kalshi:HEARTBEAT_LOST 0.00, kalshi:NOT_SYNCED 0.00, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.47, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.25 |
| lal|25|pre|flap|fee-half | 77 | 1338 | 0.01 | 0.000 | 0.000 | 1.0443 | 1.0543 | 1.0443 | BLOCKED_MATCH 0.00, BLOCKED_STALE 0.99, NO_EDGE 0.01 | (none) 0.00, kalshi:NOT_SYNCED 0.54, kalshi:STALE 0.13, polymarket:HEARTBEAT_LOST 0.18, polymarket:NOT_SYNCED 0.05, polymarket:STALE 0.09 |
| lal|100|end|clean|fee-half | 144 | 109 | 0.99 | 0.000 | 0.000 | 1.0201 | 1.0332 | 1.0076 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.64, BLOCKED_STALE 0.01, NO_EDGE 0.35 | (none) 0.64, polymarket:HASH_MISMATCH 0.01 |
| lal|100|in|clean|fee-half | 1750 | 4208 | 0.22 | 0.000 | 0.000 | 1.0546 | 1.0732 | 1.0111 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.05, BLOCKED_STALE 0.78, NO_EDGE 0.16 | (none) 0.05, kalshi:HEARTBEAT_LOST 0.00, kalshi:NOT_SYNCED 0.00, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.02, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.47, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.25 |
| lal|100|pre|flap|fee-half | 77 | 1338 | 0.01 | 0.000 | 0.000 | 1.0443 | 1.0543 | 1.0443 | BLOCKED_MATCH 0.00, BLOCKED_STALE 0.99, NO_EDGE 0.01 | (none) 0.00, kalshi:NOT_SYNCED 0.54, kalshi:STALE 0.13, polymarket:HEARTBEAT_LOST 0.18, polymarket:NOT_SYNCED 0.05, polymarket:STALE 0.09 |
| mlb|5|end|clean|fee-half | 1903 | 7398 | 0.83 | 0.001 | 0.000 | 1.0302 | 1.0346 | 0.8740 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.00, BLOCKED_STALE 0.16, NO_EDGE 0.83 | (none) 0.00, kalshi:NO_ASKS 0.00, kalshi:STALE 0.03, polymarket:HASH_MISMATCH 0.00, polymarket:STALE 0.00, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.11 |
| mlb|5|end|clean|fee-repinned+probe | 2874 | 10634 | 0.19 | 0.001 | 0.000 | 1.0234 | 1.0359 | 0.8663 | BLOCKED_DEPTH 0.25, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.05, BLOCKED_STALE 0.56, DISCOVERED 0.00, NO_EDGE 0.13, PROFITABLE_UNEXECUTED 0.00 | (none) 0.06, kalshi:CROSSED_BOOK 0.04, kalshi:NO_ASKS 0.25, kalshi:STALE 0.48, polymarket:HASH_MISMATCH 0.02, polymarket:NO_ASKS 0.00, polymarket:STALE 0.02, supervisor:LOOP_STALLED 0.01 |
| mlb|5|end|flap|fee-half | 32 | 649 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_STALE 1.00 | kalshi:NOT_SYNCED 0.24, kalshi:STALE 0.14, polymarket:HEARTBEAT_LOST 0.47, polymarket:NOT_SYNCED 0.15 |
| mlb|5|end|flap|fee-repinned+probe | 28 | 888 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_DEPTH 0.17, BLOCKED_STALE 0.83 | kalshi:HEARTBEAT_LOST 0.09, kalshi:NO_ASKS 0.17, kalshi:STALE 0.10, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.29, supervisor:LOOP_STALLED 0.33 |
| mlb|5|in|clean|fee-half | 5103 | 21836 | 0.64 | 0.009 | 0.000 | 1.0299 | 1.0350 | 0.7700 | BLOCKED_DEPTH 0.01, BLOCKED_FEES 0.02, BLOCKED_MATCH 0.12, BLOCKED_STALE 0.35, DISCOVERED 0.00, NO_EDGE 0.51 | (none) 0.14, kalshi:HEARTBEAT_LOST 0.00, kalshi:STALE 0.00, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.00, polymarket:NO_ASKS 0.01, polymarket:STALE 0.12, polymarket:UNVERIFIED_TOO_LONG 0.06, supervisor:CLOCK_UNHEALTHY 0.16 |
| mlb|5|in|clean|fee-repinned | 1007 | 6884 | 0.39 | 0.005 | 0.000 | 1.0349 | 1.0443 | 0.9357 | BLOCKED_FEES 0.02, BLOCKED_MATCH 0.03, BLOCKED_STALE 0.61, DISCOVERED 0.00, NO_EDGE 0.33 | (none) 0.05, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.06, polymarket:HEARTBEAT_LOST 0.00, polymarket:STALE 0.03, supervisor:CLOCK_UNHEALTHY 0.51 |
| mlb|5|in|clean|fee-repinned+probe | 37075 | 150100 | 0.77 | 0.002 | 0.000 | 1.0329 | 1.0437 | 0.9329 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.03, BLOCKED_MATCH 0.11, BLOCKED_STALE 0.21, DISCOVERED 0.00, NO_EDGE 0.63 | (none) 0.13, kalshi:CROSSED_BOOK 0.15, kalshi:HEARTBEAT_LOST 0.00, kalshi:NO_ASKS 0.02, kalshi:STALE 0.02, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.03, supervisor:CLOCK_UNHEALTHY 0.00, supervisor:LOOP_STALLED 0.01 |
| mlb|5|in|flap|fee-half | 1355 | 18429 | 0.05 | 0.003 | 0.000 | 1.0260 | 1.0300 | 0.8482 | BLOCKED_DEPTH 0.01, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.93, DISCOVERED 0.00, NO_EDGE 0.00, PROFITABLE_UNEXECUTED 0.00 | (none) 0.05, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.24, kalshi:STALE 0.06, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.07, polymarket:NOT_SYNCED 0.07, polymarket:NO_ASKS 0.01, polymarket:STALE 0.18, polymarket:UNVERIFIED_TOO_LONG 0.12, supervisor:CLOCK_UNHEALTHY 0.19 |
| mlb|5|in|flap|fee-repinned | 223 | 2452 | 0.08 | 0.001 | 0.000 | 1.0329 | 1.0443 | 1.0040 | BLOCKED_FEES 0.01, BLOCKED_MATCH 0.01, BLOCKED_STALE 0.92, NO_EDGE 0.06 | (none) 0.02, kalshi:STALE 0.00, polymarket:HASH_MISMATCH 0.02, polymarket:HEARTBEAT_LOST 0.04, polymarket:NOT_SYNCED 0.02, polymarket:STALE 0.02, supervisor:CLOCK_UNHEALTHY 0.81 |
| mlb|5|in|flap|fee-repinned+probe | 1007 | 9278 | 0.23 | 0.003 | 0.000 | 1.0345 | 1.0445 | 0.9341 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.03, BLOCKED_STALE 0.76, DISCOVERED 0.00, NO_EDGE 0.19 | (none) 0.04, kalshi:CROSSED_BOOK 0.01, kalshi:HEARTBEAT_LOST 0.03, kalshi:NO_ASKS 0.00, kalshi:STALE 0.03, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.03, polymarket:STALE 0.05, supervisor:CLOCK_UNHEALTHY 0.50, supervisor:LOOP_STALLED 0.09 |
| mlb|5|pre|clean|fee-half | 6836 | 74750 | 0.20 | 0.000 | 0.000 | 1.0300 | 1.0300 | 1.0160 | BLOCKED_FEES 0.02, BLOCKED_MATCH 0.16, BLOCKED_STALE 0.80, NO_EDGE 0.02 | (none) 0.18, kalshi:HEARTBEAT_LOST 0.27, kalshi:NOT_SYNCED 0.02, kalshi:STALE 0.15, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.16, polymarket:UNVERIFIED_TOO_LONG 0.04, supervisor:CLOCK_UNHEALTHY 0.14 |
| mlb|5|pre|clean|fee-repinned | 299 | 3327 | 0.15 | 0.000 | 0.000 | 1.0282 | 1.0399 | 1.0269 | BLOCKED_MATCH 0.08, BLOCKED_STALE 0.85, NO_EDGE 0.07 | (none) 0.08, kalshi:STALE 0.12, polymarket:HEARTBEAT_LOST 0.01, polymarket:STALE 0.18, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.51 |
| mlb|5|pre|clean|fee-repinned+probe | 35848 | 298887 | 0.31 | 0.000 | 0.000 | 1.0399 | 1.0446 | 1.0244 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.09, BLOCKED_STALE 0.69, NO_EDGE 0.23 | (none) 0.09, kalshi:CROSSED_BOOK 0.00, kalshi:STALE 0.34, polymarket:HASH_MISMATCH 0.00, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.34, supervisor:CLOCK_UNHEALTHY 0.00, supervisor:LOOP_STALLED 0.00 |
| mlb|5|pre|flap|fee-half | 1219 | 24133 | 0.03 | 0.000 | 0.000 | 1.0260 | 1.0300 | 1.0160 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.97, NO_EDGE 0.00 | (none) 0.02, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.31, kalshi:STALE 0.04, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.52 |
| mlb|5|pre|flap|fee-repinned | 78 | 1263 | 0.02 | 0.000 | 0.000 | 1.0399 | 1.0399 | 1.0282 | BLOCKED_MATCH 0.00, BLOCKED_STALE 0.98, NO_EDGE 0.02 | (none) 0.00, kalshi:STALE 0.05, polymarket:HEARTBEAT_LOST 0.07, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.01, supervisor:CLOCK_UNHEALTHY 0.83 |
| mlb|5|pre|flap|fee-repinned+probe | 228 | 2492 | 0.21 | 0.000 | 0.000 | 1.0399 | 1.0446 | 1.0244 | BLOCKED_FEES 0.01, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.79, NO_EDGE 0.17 | (none) 0.05, kalshi:STALE 0.33, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.23, supervisor:CLOCK_UNHEALTHY 0.09, supervisor:LOOP_STALLED 0.12 |
| mlb|25|end|clean|fee-half | 2652 | 7398 | 0.83 | 0.001 | 0.000 | 1.0294 | 1.0343 | 0.8886 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.00, BLOCKED_STALE 0.16, NO_EDGE 0.83 | (none) 0.00, kalshi:NO_ASKS 0.00, kalshi:STALE 0.03, polymarket:HASH_MISMATCH 0.00, polymarket:STALE 0.00, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.11 |
| mlb|25|end|clean|fee-repinned+probe | 3022 | 10645 | 0.19 | 0.000 | 0.000 | 1.0242 | 1.0394 | 0.8663 | BLOCKED_DEPTH 0.25, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.06, BLOCKED_STALE 0.56, DISCOVERED 0.00, NO_EDGE 0.13, PROFITABLE_UNEXECUTED 0.00 | (none) 0.06, kalshi:CROSSED_BOOK 0.04, kalshi:NO_ASKS 0.25, kalshi:STALE 0.48, polymarket:HASH_MISMATCH 0.02, polymarket:NO_ASKS 0.00, polymarket:STALE 0.02, supervisor:LOOP_STALLED 0.01 |
| mlb|25|end|flap|fee-repinned+probe | 28 | 888 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_DEPTH 0.17, BLOCKED_STALE 0.83 | kalshi:HEARTBEAT_LOST 0.09, kalshi:NO_ASKS 0.17, kalshi:STALE 0.10, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.29, supervisor:LOOP_STALLED 0.33 |
| mlb|25|in|clean|fee-half | 6571 | 21827 | 0.64 | 0.011 | 0.000 | 1.0276 | 1.0350 | 0.8647 | BLOCKED_DEPTH 0.01, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.13, BLOCKED_STALE 0.35, DISCOVERED 0.00, NO_EDGE 0.51 | (none) 0.13, kalshi:HEARTBEAT_LOST 0.00, kalshi:STALE 0.00, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.00, polymarket:NO_ASKS 0.01, polymarket:STALE 0.12, polymarket:UNVERIFIED_TOO_LONG 0.06, supervisor:CLOCK_UNHEALTHY 0.16 |
| mlb|25|in|clean|fee-repinned | 1225 | 6884 | 0.39 | 0.005 | 0.004 | 1.0383 | 1.0443 | 0.9388 | BLOCKED_FEES 0.02, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.61, DISCOVERED 0.00, NO_EDGE 0.32, PROFITABLE_UNEXECUTED 0.00 | (none) 0.06, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.06, polymarket:HEARTBEAT_LOST 0.00, polymarket:STALE 0.03, supervisor:CLOCK_UNHEALTHY 0.51 |
| mlb|25|in|clean|fee-repinned+probe | 40228 | 150089 | 0.77 | 0.001 | 0.000 | 1.0331 | 1.0439 | 0.9329 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.03, BLOCKED_MATCH 0.12, BLOCKED_STALE 0.21, DISCOVERED 0.00, NO_EDGE 0.62, PROFITABLE_UNEXECUTED 0.00 | (none) 0.15, kalshi:CROSSED_BOOK 0.15, kalshi:HEARTBEAT_LOST 0.00, kalshi:NO_ASKS 0.02, kalshi:STALE 0.02, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.03, supervisor:CLOCK_UNHEALTHY 0.00, supervisor:LOOP_STALLED 0.01 |
| mlb|25|in|flap|fee-half | 1199 | 14004 | 0.08 | 0.003 | 0.003 | 1.0260 | 1.0276 | 0.8482 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.07, BLOCKED_STALE 0.90, DISCOVERED 0.00, NO_EDGE 0.00, PROFITABLE_UNEXECUTED 0.00 | (none) 0.07, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.23, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.09, polymarket:NOT_SYNCED 0.00, polymarket:NO_ASKS 0.02, polymarket:STALE 0.18, polymarket:UNVERIFIED_TOO_LONG 0.14, supervisor:CLOCK_UNHEALTHY 0.25 |
| mlb|25|in|flap|fee-repinned | 251 | 2452 | 0.08 | 0.001 | 0.000 | 1.0329 | 1.0443 | 1.0040 | BLOCKED_FEES 0.01, BLOCKED_MATCH 0.01, BLOCKED_STALE 0.92, NO_EDGE 0.06 | (none) 0.02, kalshi:STALE 0.00, polymarket:HASH_MISMATCH 0.02, polymarket:HEARTBEAT_LOST 0.04, polymarket:NOT_SYNCED 0.02, polymarket:STALE 0.02, supervisor:CLOCK_UNHEALTHY 0.81 |
| mlb|25|in|flap|fee-repinned+probe | 1111 | 9278 | 0.23 | 0.003 | 0.001 | 1.0352 | 1.0445 | 0.9341 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.76, DISCOVERED 0.00, NO_EDGE 0.18, PROFITABLE_UNEXECUTED 0.00 | (none) 0.05, kalshi:CROSSED_BOOK 0.01, kalshi:HEARTBEAT_LOST 0.03, kalshi:NO_ASKS 0.00, kalshi:STALE 0.03, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.03, polymarket:STALE 0.05, supervisor:CLOCK_UNHEALTHY 0.50, supervisor:LOOP_STALLED 0.09 |
| mlb|25|pre|clean|fee-half | 6833 | 74750 | 0.20 | 0.000 | 0.000 | 1.0268 | 1.0276 | 1.0144 | BLOCKED_FEES 0.02, BLOCKED_MATCH 0.16, BLOCKED_STALE 0.80, NO_EDGE 0.02 | (none) 0.18, kalshi:HEARTBEAT_LOST 0.27, kalshi:NOT_SYNCED 0.02, kalshi:STALE 0.15, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.16, polymarket:UNVERIFIED_TOO_LONG 0.04, supervisor:CLOCK_UNHEALTHY 0.14 |
| mlb|25|pre|clean|fee-repinned | 299 | 3327 | 0.15 | 0.000 | 0.000 | 1.0282 | 1.0399 | 1.0269 | BLOCKED_MATCH 0.08, BLOCKED_STALE 0.85, NO_EDGE 0.07 | (none) 0.08, kalshi:STALE 0.12, polymarket:HEARTBEAT_LOST 0.01, polymarket:STALE 0.18, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.51 |
| mlb|25|pre|clean|fee-repinned+probe | 35856 | 298887 | 0.31 | 0.000 | 0.000 | 1.0409 | 1.0446 | 1.0244 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.09, BLOCKED_STALE 0.69, NO_EDGE 0.23 | (none) 0.09, kalshi:CROSSED_BOOK 0.00, kalshi:STALE 0.34, polymarket:HASH_MISMATCH 0.00, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.34, supervisor:CLOCK_UNHEALTHY 0.00, supervisor:LOOP_STALLED 0.00 |
| mlb|25|pre|flap|fee-half | 1219 | 24133 | 0.03 | 0.000 | 0.000 | 1.0260 | 1.0276 | 1.0144 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.97, NO_EDGE 0.00 | (none) 0.02, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.31, kalshi:STALE 0.04, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.52 |
| mlb|25|pre|flap|fee-repinned | 78 | 1263 | 0.02 | 0.000 | 0.000 | 1.0399 | 1.0399 | 1.0282 | BLOCKED_MATCH 0.00, BLOCKED_STALE 0.98, NO_EDGE 0.02 | (none) 0.00, kalshi:STALE 0.05, polymarket:HEARTBEAT_LOST 0.07, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.01, supervisor:CLOCK_UNHEALTHY 0.83 |
| mlb|25|pre|flap|fee-repinned+probe | 228 | 2492 | 0.21 | 0.000 | 0.000 | 1.0399 | 1.0446 | 1.0244 | BLOCKED_FEES 0.01, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.79, NO_EDGE 0.17 | (none) 0.05, kalshi:STALE 0.33, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.23, supervisor:CLOCK_UNHEALTHY 0.09, supervisor:LOOP_STALLED 0.12 |
| mlb|100|end|clean|fee-half | 4110 | 7401 | 0.83 | 0.000 | 0.000 | 1.0293 | 1.0346 | 0.9921 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.00, BLOCKED_STALE 0.16, NO_EDGE 0.83 | (none) 0.00, kalshi:NO_ASKS 0.00, kalshi:STALE 0.03, polymarket:HASH_MISMATCH 0.00, polymarket:STALE 0.00, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.11 |
| mlb|100|end|clean|fee-repinned+probe | 3161 | 10645 | 0.19 | 0.000 | 0.000 | 1.0243 | 1.0413 | 0.8727 | BLOCKED_DEPTH 0.25, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.06, BLOCKED_STALE 0.56, DISCOVERED 0.00, NO_EDGE 0.12, PROFITABLE_UNEXECUTED 0.00 | (none) 0.07, kalshi:CROSSED_BOOK 0.04, kalshi:NO_ASKS 0.25, kalshi:STALE 0.48, polymarket:HASH_MISMATCH 0.02, polymarket:NO_ASKS 0.00, polymarket:STALE 0.02, supervisor:LOOP_STALLED 0.01 |
| mlb|100|end|flap|fee-repinned+probe | 28 | 888 | 0.00 | 0.000 | 0.000 | — | — | — | BLOCKED_DEPTH 0.17, BLOCKED_STALE 0.83 | kalshi:HEARTBEAT_LOST 0.09, kalshi:NO_ASKS 0.17, kalshi:STALE 0.10, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.29, supervisor:LOOP_STALLED 0.33 |
| mlb|100|in|clean|fee-half | 9052 | 21834 | 0.64 | 0.007 | 0.000 | 1.0276 | 1.0350 | 0.9903 | BLOCKED_DEPTH 0.01, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.13, BLOCKED_STALE 0.35, DISCOVERED 0.00, NO_EDGE 0.50 | (none) 0.14, kalshi:HEARTBEAT_LOST 0.00, kalshi:STALE 0.00, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.00, polymarket:NO_ASKS 0.01, polymarket:STALE 0.12, polymarket:UNVERIFIED_TOO_LONG 0.06, supervisor:CLOCK_UNHEALTHY 0.16 |
| mlb|100|in|clean|fee-repinned | 1425 | 6884 | 0.39 | 0.004 | 0.004 | 1.0389 | 1.0445 | 0.9388 | BLOCKED_FEES 0.02, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.61, DISCOVERED 0.00, NO_EDGE 0.32, PROFITABLE_UNEXECUTED 0.00 | (none) 0.07, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.06, polymarket:HEARTBEAT_LOST 0.00, polymarket:STALE 0.03, supervisor:CLOCK_UNHEALTHY 0.51 |
| mlb|100|in|clean|fee-repinned+probe | 44344 | 150125 | 0.77 | 0.001 | 0.000 | 1.0335 | 1.0441 | 0.9329 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.02, BLOCKED_MATCH 0.15, BLOCKED_STALE 0.21, DISCOVERED 0.00, NO_EDGE 0.60, PROFITABLE_UNEXECUTED 0.00 | (none) 0.17, kalshi:CROSSED_BOOK 0.15, kalshi:HEARTBEAT_LOST 0.00, kalshi:NO_ASKS 0.02, kalshi:STALE 0.02, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.03, supervisor:CLOCK_UNHEALTHY 0.00, supervisor:LOOP_STALLED 0.01 |
| mlb|100|in|flap|fee-half | 1199 | 14004 | 0.08 | 0.003 | 0.003 | 1.0257 | 1.0276 | 0.8482 | BLOCKED_DEPTH 0.02, BLOCKED_FEES 0.00, BLOCKED_MATCH 0.07, BLOCKED_STALE 0.90, DISCOVERED 0.00, NO_EDGE 0.00, PROFITABLE_UNEXECUTED 0.00 | (none) 0.07, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.23, kalshi:STALE 0.01, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.09, polymarket:NOT_SYNCED 0.00, polymarket:NO_ASKS 0.02, polymarket:STALE 0.18, polymarket:UNVERIFIED_TOO_LONG 0.14, supervisor:CLOCK_UNHEALTHY 0.25 |
| mlb|100|in|flap|fee-repinned | 269 | 2452 | 0.08 | 0.000 | 0.000 | 1.0336 | 1.0443 | 1.0061 | BLOCKED_FEES 0.01, BLOCKED_MATCH 0.01, BLOCKED_STALE 0.92, NO_EDGE 0.06 | (none) 0.03, kalshi:STALE 0.00, polymarket:HASH_MISMATCH 0.02, polymarket:HEARTBEAT_LOST 0.04, polymarket:NOT_SYNCED 0.02, polymarket:STALE 0.02, supervisor:CLOCK_UNHEALTHY 0.81 |
| mlb|100|in|flap|fee-repinned+probe | 1141 | 9282 | 0.23 | 0.003 | 0.002 | 1.0352 | 1.0445 | 0.9341 | BLOCKED_DEPTH 0.00, BLOCKED_FEES 0.01, BLOCKED_MATCH 0.05, BLOCKED_STALE 0.76, DISCOVERED 0.00, NO_EDGE 0.17, PROFITABLE_UNEXECUTED 0.00 | (none) 0.06, kalshi:CROSSED_BOOK 0.01, kalshi:HEARTBEAT_LOST 0.03, kalshi:NO_ASKS 0.00, kalshi:STALE 0.03, polymarket:HASH_MISMATCH 0.01, polymarket:HEARTBEAT_LOST 0.00, polymarket:NOT_SYNCED 0.03, polymarket:STALE 0.05, supervisor:CLOCK_UNHEALTHY 0.50, supervisor:LOOP_STALLED 0.09 |
| mlb|100|pre|clean|fee-half | 6834 | 74750 | 0.20 | 0.000 | 0.000 | 1.0268 | 1.0276 | 1.0142 | BLOCKED_FEES 0.02, BLOCKED_MATCH 0.17, BLOCKED_STALE 0.80, NO_EDGE 0.01 | (none) 0.19, kalshi:HEARTBEAT_LOST 0.27, kalshi:NOT_SYNCED 0.02, kalshi:STALE 0.15, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.16, polymarket:UNVERIFIED_TOO_LONG 0.04, supervisor:CLOCK_UNHEALTHY 0.14 |
| mlb|100|pre|clean|fee-repinned | 299 | 3327 | 0.15 | 0.000 | 0.000 | 1.0282 | 1.0399 | 1.0269 | BLOCKED_MATCH 0.08, BLOCKED_STALE 0.85, NO_EDGE 0.07 | (none) 0.08, kalshi:STALE 0.12, polymarket:HEARTBEAT_LOST 0.01, polymarket:STALE 0.18, polymarket:UNVERIFIED_TOO_LONG 0.03, supervisor:CLOCK_UNHEALTHY 0.51 |
| mlb|100|pre|clean|fee-repinned+probe | 35862 | 298862 | 0.31 | 0.000 | 0.000 | 1.0409 | 1.0446 | 1.0244 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.09, BLOCKED_STALE 0.69, NO_EDGE 0.22 | (none) 0.09, kalshi:CROSSED_BOOK 0.00, kalshi:STALE 0.34, polymarket:HASH_MISMATCH 0.00, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.34, supervisor:CLOCK_UNHEALTHY 0.00, supervisor:LOOP_STALLED 0.00 |
| mlb|100|pre|flap|fee-half | 1219 | 24133 | 0.03 | 0.000 | 0.000 | 1.0257 | 1.0275 | 1.0142 | BLOCKED_FEES 0.00, BLOCKED_MATCH 0.02, BLOCKED_STALE 0.97, NO_EDGE 0.00 | (none) 0.02, kalshi:HEARTBEAT_LOST 0.01, kalshi:NOT_SYNCED 0.31, kalshi:STALE 0.04, polymarket:HASH_MISMATCH 0.00, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.04, polymarket:UNVERIFIED_TOO_LONG 0.02, supervisor:CLOCK_UNHEALTHY 0.52 |
| mlb|100|pre|flap|fee-repinned | 78 | 1263 | 0.02 | 0.000 | 0.000 | 1.0399 | 1.0399 | 1.0282 | BLOCKED_MATCH 0.00, BLOCKED_STALE 0.98, NO_EDGE 0.02 | (none) 0.00, kalshi:STALE 0.05, polymarket:HEARTBEAT_LOST 0.07, polymarket:NOT_SYNCED 0.01, polymarket:STALE 0.01, supervisor:CLOCK_UNHEALTHY 0.83 |
| mlb|100|pre|flap|fee-repinned+probe | 228 | 2492 | 0.21 | 0.000 | 0.000 | 1.0399 | 1.0446 | 1.0244 | BLOCKED_FEES 0.01, BLOCKED_MATCH 0.04, BLOCKED_STALE 0.79, NO_EDGE 0.17 | (none) 0.05, kalshi:STALE 0.33, polymarket:HEARTBEAT_LOST 0.01, polymarket:NOT_SYNCED 0.00, polymarket:STALE 0.23, supervisor:CLOCK_UNHEALTHY 0.09, supervisor:LOOP_STALLED 0.12 |

### Profitable rows (336)

| seen | game | q | phase | flapping | stale within 60 s | cost | locked return | label |
|---|---|---|---|---|---|---|---|---|
| 09-03 18:08:40Z | espn:mlb:401816789 | 25 | in | True | True | 0.9714 | +0.0295 | SUSPECT |
| 09-03 18:08:40Z | espn:mlb:401816789 | 100 | in | True | True | 0.9714 | +0.0295 | SUSPECT |
| 09-03 18:10:28Z | espn:mlb:401816789 | 25 | in | True | True | 0.9306 | +0.0746 | SUSPECT |
| 09-03 18:10:28Z | espn:mlb:401816789 | 100 | in | True | True | 0.9305 | +0.0747 | SUSPECT |
| 09-03 18:12:32Z | espn:mlb:401816789 | 25 | in | True | True | 0.9202 | +0.0867 | SUSPECT |
| 09-03 18:12:32Z | espn:mlb:401816789 | 100 | in | True | True | 0.9202 | +0.0867 | SUSPECT |
| 09-03 18:18:17Z | espn:mlb:401816789 | 5 | in | True | True | 0.8482 | +0.1790 | SUSPECT |
| 09-03 18:18:17Z | espn:mlb:401816789 | 25 | in | True | True | 0.8482 | +0.1790 | SUSPECT |
| 09-03 18:18:17Z | espn:mlb:401816789 | 100 | in | True | True | 0.8482 | +0.1790 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 25 | in | True | True | 0.8546 | +0.1702 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 100 | in | True | True | 0.8575 | +0.1662 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 25 | in | True | True | 0.8526 | +0.1729 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 100 | in | True | True | 0.8585 | +0.1648 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 25 | in | True | True | 0.8546 | +0.1702 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 5 | in | True | True | 0.8602 | +0.1625 | SUSPECT |
| 09-03 18:18:20Z | espn:mlb:401816789 | 25 | in | True | True | 0.8586 | +0.1647 | SUSPECT |
| 09-03 18:32:36Z | espn:mlb:401816789 | 25 | in | True | True | 0.9306 | +0.0746 | SUSPECT |
| 09-03 18:32:36Z | espn:mlb:401816789 | 100 | in | True | True | 0.9305 | +0.0747 | SUSPECT |
| 09-03 19:42:31Z | espn:cfb:401867889 | 100 | pre | False | True | 0.9891 | +0.0110 | SUSPECT |
| 09-03 23:51:35Z | espn:cfb:401858423 | 100 | in | False | True | 0.9896 | +0.0105 | SUSPECT |
| 09-03 23:51:35Z | espn:cfb:401858423 | 100 | in | False | True | 0.9826 | +0.0177 | SUSPECT |
| 09-03 23:51:36Z | espn:cfb:401858423 | 25 | in | False | True | 0.9791 | +0.0213 | SUSPECT |
| 09-03 23:51:36Z | espn:cfb:401858423 | 25 | in | False | True | 0.9719 | +0.0289 | SUSPECT |
| 09-03 23:51:36Z | espn:cfb:401858423 | 100 | in | False | True | 0.9722 | +0.0286 | SUSPECT |
| 09-03 23:51:44Z | espn:cfb:401858423 | 25 | in | False | True | 0.9719 | +0.0289 | SUSPECT |
| 09-03 23:51:44Z | espn:cfb:401858423 | 100 | in | False | True | 0.9722 | +0.0286 | SUSPECT |
| 09-03 23:51:49Z | espn:cfb:401858423 | 25 | in | False | True | 0.9723 | +0.0285 | SUSPECT |
| 09-03 23:51:49Z | espn:cfb:401858423 | 100 | in | False | True | 0.9723 | +0.0285 | SUSPECT |
| 09-03 23:51:55Z | espn:cfb:401858423 | 25 | in | False | True | 0.9723 | +0.0285 | SUSPECT |
| 09-03 23:51:55Z | espn:cfb:401858423 | 100 | in | False | True | 0.9723 | +0.0285 | SUSPECT |
| 09-03 23:52:03Z | espn:cfb:401858423 | 25 | in | False | True | 0.9723 | +0.0285 | SUSPECT |
| 09-03 23:52:03Z | espn:cfb:401858423 | 100 | in | False | True | 0.9723 | +0.0285 | SUSPECT |
| 09-04 00:07:13Z | espn:mlb:401816793 | 25 | in | True | True | 0.9198 | +0.0872 | SUSPECT |
| 09-04 00:07:13Z | espn:mlb:401816793 | 100 | in | True | True | 0.9198 | +0.0872 | SUSPECT |
| 09-04 00:07:38Z | espn:mlb:401816793 | 25 | in | True | True | 0.9301 | +0.0752 | SUSPECT |
| 09-04 00:07:38Z | espn:mlb:401816793 | 100 | in | True | True | 0.9301 | +0.0752 | SUSPECT |
| 09-04 00:07:39Z | espn:mlb:401816793 | 100 | in | True | True | 0.9332 | +0.0716 | SUSPECT |
| 09-04 00:07:40Z | espn:mlb:401816793 | 25 | in | True | True | 0.9354 | +0.0691 | SUSPECT |
| 09-04 00:07:40Z | espn:mlb:401816793 | 100 | in | True | True | 0.9392 | +0.0648 | SUSPECT |
| 09-04 00:07:40Z | espn:mlb:401816793 | 25 | in | True | True | 0.9365 | +0.0678 | SUSPECT |
| 09-04 00:07:40Z | espn:mlb:401816793 | 100 | in | True | True | 0.9472 | +0.0557 | SUSPECT |
| 09-04 00:07:40Z | espn:mlb:401816793 | 25 | in | True | True | 0.9412 | +0.0625 | SUSPECT |
| 09-04 00:07:40Z | espn:mlb:401816793 | 25 | in | True | True | 0.9423 | +0.0612 | SUSPECT |
| 09-04 00:07:40Z | espn:mlb:401816793 | 25 | in | True | True | 0.9446 | +0.0586 | SUSPECT |
| 09-04 00:36:15Z | espn:cfb:401858423 | 100 | in | False | False | 0.9859 | +0.0143 | clean |
| 09-04 00:43:09Z | espn:mlb:401816788 | 25 | in | False | True | 0.9388 | +0.0652 | SUSPECT |
| 09-04 00:43:09Z | espn:mlb:401816788 | 100 | in | False | True | 0.9388 | +0.0652 | SUSPECT |
| 09-04 00:43:13Z | espn:mlb:401816788 | 25 | in | False | True | 0.9388 | +0.0652 | SUSPECT |
| 09-04 00:43:13Z | espn:mlb:401816788 | 100 | in | False | True | 0.9388 | +0.0652 | SUSPECT |
| 09-04 00:43:20Z | espn:mlb:401816788 | 25 | in | False | True | 0.9471 | +0.0558 | SUSPECT |
| 09-04 00:43:20Z | espn:mlb:401816788 | 100 | in | False | True | 0.9623 | +0.0392 | SUSPECT |
| 09-04 00:43:21Z | espn:mlb:401816788 | 25 | in | False | True | 0.9496 | +0.0531 | SUSPECT |
| 09-04 00:43:21Z | espn:mlb:401816788 | 100 | in | False | True | 0.9638 | +0.0375 | SUSPECT |
| 09-04 00:43:22Z | espn:mlb:401816788 | 25 | in | False | True | 0.9583 | +0.0435 | SUSPECT |
| 09-04 00:43:22Z | espn:mlb:401816788 | 100 | in | False | True | 0.9670 | +0.0341 | SUSPECT |
| 09-04 00:43:22Z | espn:mlb:401816788 | 25 | in | False | True | 0.9600 | +0.0417 | SUSPECT |
| 09-04 00:43:23Z | espn:mlb:401816788 | 25 | in | False | True | 0.9546 | +0.0476 | SUSPECT |
| 09-04 00:43:25Z | espn:mlb:401816788 | 25 | in | False | True | 0.9596 | +0.0421 | SUSPECT |
| 09-04 00:43:26Z | espn:mlb:401816788 | 25 | in | False | True | 0.9596 | +0.0421 | SUSPECT |
| 09-04 00:43:26Z | espn:mlb:401816788 | 100 | in | False | True | 0.9666 | +0.0345 | SUSPECT |
| 09-04 00:43:31Z | espn:mlb:401816788 | 25 | in | False | True | 0.9492 | +0.0535 | SUSPECT |
| 09-04 00:43:31Z | espn:mlb:401816788 | 100 | in | False | True | 0.9492 | +0.0535 | SUSPECT |
| 09-04 00:43:33Z | espn:mlb:401816788 | 100 | in | False | True | 0.9502 | +0.0524 | SUSPECT |
| 09-04 00:43:35Z | espn:mlb:401816788 | 25 | in | False | True | 0.9517 | +0.0508 | SUSPECT |
| 09-04 00:43:35Z | espn:mlb:401816788 | 100 | in | False | True | 0.9606 | +0.0410 | SUSPECT |
| 09-04 00:43:36Z | espn:mlb:401816788 | 100 | in | False | True | 0.9684 | +0.0326 | SUSPECT |
| 09-04 00:43:37Z | espn:mlb:401816788 | 25 | in | False | True | 0.9616 | +0.0399 | SUSPECT |
| 09-04 00:43:37Z | espn:mlb:401816788 | 25 | in | False | True | 0.9658 | +0.0354 | SUSPECT |
| 09-04 00:43:37Z | espn:mlb:401816788 | 100 | in | False | True | 0.9699 | +0.0310 | SUSPECT |
| 09-04 00:43:37Z | espn:mlb:401816788 | 25 | in | False | True | 0.9699 | +0.0310 | SUSPECT |
| 09-04 00:43:37Z | espn:mlb:401816788 | 100 | in | False | True | 0.9713 | +0.0296 | SUSPECT |
| 09-04 00:43:38Z | espn:mlb:401816788 | 25 | in | False | True | 0.9576 | +0.0443 | SUSPECT |
| 09-04 00:43:39Z | espn:mlb:401816788 | 100 | in | False | True | 0.9900 | +0.0101 | SUSPECT |
| 09-04 00:43:39Z | espn:mlb:401816788 | 100 | in | False | True | 0.9862 | +0.0140 | SUSPECT |
| 09-04 00:43:39Z | espn:mlb:401816788 | 100 | in | False | True | 0.9862 | +0.0140 | SUSPECT |
| 09-04 00:43:40Z | espn:mlb:401816788 | 100 | in | False | True | 0.9826 | +0.0177 | SUSPECT |
| 09-04 00:43:40Z | espn:mlb:401816788 | 100 | in | False | True | 0.9862 | +0.0140 | SUSPECT |
| 09-04 00:43:40Z | espn:mlb:401816788 | 25 | in | False | True | 0.9621 | +0.0394 | SUSPECT |
| 09-04 00:43:40Z | espn:mlb:401816788 | 100 | in | False | True | 0.9887 | +0.0115 | SUSPECT |
| 09-04 00:43:40Z | espn:mlb:401816788 | 25 | in | False | True | 0.9661 | +0.0351 | SUSPECT |
| 09-04 00:43:40Z | espn:mlb:401816788 | 100 | in | False | True | 0.9900 | +0.0101 | SUSPECT |
| 09-04 00:43:40Z | espn:mlb:401816788 | 25 | in | False | True | 0.9683 | +0.0328 | SUSPECT |
| 09-04 00:44:09Z | espn:mlb:401816788 | 25 | in | False | True | 0.9564 | +0.0456 | SUSPECT |
| 09-04 00:44:09Z | espn:mlb:401816788 | 100 | in | False | True | 0.9709 | +0.0300 | SUSPECT |
| 09-04 00:44:09Z | espn:mlb:401816788 | 100 | in | False | True | 0.9678 | +0.0333 | SUSPECT |
| 09-04 00:44:09Z | espn:mlb:401816788 | 100 | in | False | True | 0.9709 | +0.0300 | SUSPECT |
| 09-04 00:44:09Z | espn:mlb:401816788 | 25 | in | False | True | 0.9460 | +0.0571 | SUSPECT |
| 09-04 00:44:09Z | espn:mlb:401816788 | 100 | in | False | True | 0.9460 | +0.0571 | SUSPECT |
| 09-04 00:44:09Z | espn:mlb:401816788 | 25 | in | False | True | 0.9564 | +0.0456 | SUSPECT |
| 09-04 00:44:09Z | espn:mlb:401816788 | 100 | in | False | True | 0.9564 | +0.0456 | SUSPECT |
| 09-04 00:44:09Z | espn:mlb:401816788 | 25 | in | False | True | 0.9522 | +0.0502 | SUSPECT |
| 09-04 00:44:09Z | espn:mlb:401816788 | 100 | in | False | True | 0.9553 | +0.0467 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 25 | in | False | True | 0.9770 | +0.0235 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 25 | in | False | True | 0.9729 | +0.0278 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 100 | in | False | True | 0.9838 | +0.0165 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 100 | in | False | True | 0.9864 | +0.0138 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 25 | in | False | True | 0.9791 | +0.0213 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 100 | in | False | True | 0.9853 | +0.0149 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 25 | in | False | True | 0.9771 | +0.0235 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 100 | in | False | True | 0.9843 | +0.0160 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 100 | in | False | True | 0.9771 | +0.0235 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 25 | in | False | True | 0.9667 | +0.0344 | SUSPECT |
| 09-04 00:44:10Z | espn:mlb:401816788 | 100 | in | False | True | 0.9667 | +0.0344 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 100 | in | False | True | 0.9745 | +0.0262 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 100 | in | False | True | 0.9900 | +0.0101 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 100 | in | False | True | 0.9859 | +0.0143 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 25 | in | False | True | 0.9647 | +0.0366 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 100 | in | False | True | 0.9834 | +0.0169 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 100 | in | False | True | 0.9869 | +0.0133 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 100 | in | False | True | 0.9869 | +0.0133 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 25 | in | False | True | 0.9754 | +0.0252 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 25 | in | False | True | 0.9655 | +0.0357 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 25 | in | False | True | 0.9696 | +0.0313 | SUSPECT |
| 09-04 00:44:11Z | espn:mlb:401816788 | 25 | in | False | True | 0.9721 | +0.0287 | SUSPECT |
| 09-04 00:49:22Z | espn:cfb:401856776 | 25 | in | True | True | 0.9794 | +0.0210 | SUSPECT |
| 09-04 00:49:22Z | espn:cfb:401856776 | 100 | in | True | True | 0.9794 | +0.0210 | SUSPECT |
| 09-04 00:56:32Z | espn:cfb:401866622 | 100 | in | True | True | 0.9899 | +0.0102 | SUSPECT |
| 09-04 00:56:33Z | espn:cfb:401866622 | 100 | in | True | True | 0.9895 | +0.0106 | SUSPECT |
| 09-04 00:56:33Z | espn:cfb:401866622 | 100 | in | True | True | 0.9900 | +0.0101 | SUSPECT |
| 09-04 01:00:48Z | espn:cfb:401866622 | 100 | in | True | True | 0.9899 | +0.0102 | SUSPECT |
| 09-04 01:00:57Z | espn:cfb:401866622 | 100 | in | True | True | 0.9900 | +0.0101 | SUSPECT |
| 09-04 01:00:58Z | espn:cfb:401866622 | 25 | in | True | True | 0.9662 | +0.0350 | SUSPECT |
| 09-04 01:00:58Z | espn:cfb:401866622 | 100 | in | True | True | 0.9662 | +0.0350 | SUSPECT |
| 09-04 01:00:58Z | espn:cfb:401866622 | 25 | in | True | True | 0.9558 | +0.0463 | SUSPECT |
| 09-04 01:00:58Z | espn:cfb:401866622 | 100 | in | True | True | 0.9558 | +0.0463 | SUSPECT |
| 09-04 02:46:16Z | espn:cfb:401858424 | 100 | in | True | True | 0.9857 | +0.0145 | SUSPECT |
| 09-04 02:46:19Z | espn:cfb:401858424 | 25 | in | True | True | 0.9751 | +0.0255 | SUSPECT |
| 09-04 02:46:19Z | espn:cfb:401858424 | 100 | in | True | True | 0.9751 | +0.0255 | SUSPECT |
| 09-04 02:46:20Z | espn:cfb:401858424 | 25 | in | True | True | 0.9645 | +0.0368 | SUSPECT |
| 09-04 02:46:20Z | espn:cfb:401858424 | 100 | in | True | True | 0.9645 | +0.0368 | SUSPECT |
| 09-04 02:46:24Z | espn:cfb:401858424 | 25 | in | True | True | 0.9645 | +0.0368 | SUSPECT |
| 09-04 02:46:24Z | espn:cfb:401858424 | 100 | in | True | True | 0.9645 | +0.0368 | SUSPECT |
| 09-04 03:00:40Z | espn:cfb:401856776 | 100 | in | True | True | 0.9885 | +0.0117 | SUSPECT |
| 09-04 03:00:42Z | espn:cfb:401856776 | 25 | in | True | True | 0.9786 | +0.0219 | SUSPECT |
| 09-04 03:00:42Z | espn:cfb:401856776 | 100 | in | True | True | 0.9818 | +0.0186 | SUSPECT |
| 09-04 03:00:43Z | espn:cfb:401856776 | 100 | in | True | True | 0.9856 | +0.0146 | SUSPECT |
| 09-04 03:00:43Z | espn:cfb:401856776 | 100 | in | True | True | 0.9786 | +0.0219 | SUSPECT |
| 09-04 03:05:43Z | espn:mlb:401816796 | 100 | in | True | True | 0.9842 | +0.0161 | SUSPECT |
| 09-04 03:05:44Z | espn:mlb:401816796 | 25 | in | True | True | 0.9641 | +0.0372 | SUSPECT |
| 09-04 03:05:44Z | espn:mlb:401816796 | 100 | in | True | True | 0.9641 | +0.0372 | SUSPECT |
| 09-04 03:05:44Z | espn:mlb:401816796 | 25 | in | True | True | 0.9541 | +0.0481 | SUSPECT |
| 09-04 03:05:44Z | espn:mlb:401816796 | 100 | in | True | True | 0.9541 | +0.0481 | SUSPECT |
| 09-04 03:05:49Z | espn:mlb:401816796 | 25 | in | True | True | 0.9641 | +0.0372 | SUSPECT |
| 09-04 03:05:49Z | espn:mlb:401816796 | 100 | in | True | True | 0.9641 | +0.0372 | SUSPECT |
| 09-04 03:05:49Z | espn:mlb:401816796 | 25 | in | True | True | 0.9754 | +0.0253 | SUSPECT |
| 09-04 03:05:49Z | espn:mlb:401816796 | 100 | in | True | True | 0.9820 | +0.0184 | SUSPECT |
| 09-04 03:07:20Z | espn:cfb:401856776 | 25 | in | True | True | 0.9364 | +0.0679 | SUSPECT |
| 09-04 03:07:20Z | espn:cfb:401856776 | 100 | in | True | True | 0.9364 | +0.0680 | SUSPECT |
| 09-04 03:07:21Z | espn:cfb:401856776 | 25 | in | True | True | 0.9157 | +0.0921 | SUSPECT |
| 09-04 03:07:21Z | espn:cfb:401856776 | 100 | in | True | True | 0.9157 | +0.0921 | SUSPECT |
| 09-04 03:07:21Z | espn:cfb:401856776 | 25 | in | True | True | 0.9053 | +0.1046 | SUSPECT |
| 09-04 03:07:21Z | espn:cfb:401856776 | 100 | in | True | True | 0.9053 | +0.1046 | SUSPECT |
| 09-04 03:07:22Z | espn:cfb:401856776 | 100 | in | True | True | 0.9082 | +0.1010 | SUSPECT |
| 09-04 03:07:22Z | espn:cfb:401856776 | 100 | in | True | True | 0.9053 | +0.1046 | SUSPECT |
| 09-04 03:07:22Z | espn:cfb:401856776 | 5 | in | True | True | 0.8950 | +0.1173 | SUSPECT |
| 09-04 03:07:22Z | espn:cfb:401856776 | 25 | in | True | True | 0.8950 | +0.1173 | SUSPECT |
| 09-04 03:07:22Z | espn:cfb:401856776 | 100 | in | True | True | 0.8974 | +0.1144 | SUSPECT |
| 09-04 03:07:23Z | espn:cfb:401856776 | 100 | in | True | True | 0.8960 | +0.1161 | SUSPECT |
| 09-04 03:07:23Z | espn:cfb:401856776 | 5 | in | True | True | 0.8846 | +0.1305 | SUSPECT |
| 09-04 03:07:23Z | espn:cfb:401856776 | 25 | in | True | True | 0.8970 | +0.1148 | SUSPECT |
| 09-04 03:07:23Z | espn:cfb:401856776 | 100 | in | True | True | 0.9033 | +0.1071 | SUSPECT |
| 09-04 03:07:23Z | espn:cfb:401856776 | 5 | in | True | True | 0.8950 | +0.1173 | SUSPECT |
| 09-04 03:07:23Z | espn:cfb:401856776 | 25 | in | True | True | 0.8950 | +0.1173 | SUSPECT |
| 09-04 03:07:23Z | espn:cfb:401856776 | 100 | in | True | True | 0.8950 | +0.1174 | SUSPECT |
| 09-04 03:07:23Z | espn:cfb:401856776 | 5 | in | True | True | 0.8846 | +0.1305 | SUSPECT |
| 09-04 03:07:23Z | espn:cfb:401856776 | 25 | in | True | True | 0.8846 | +0.1305 | SUSPECT |
| 09-04 03:07:23Z | espn:cfb:401856776 | 100 | in | True | True | 0.8846 | +0.1305 | SUSPECT |
| 09-04 03:07:24Z | espn:cfb:401856776 | 100 | in | True | True | 0.8887 | +0.1252 | SUSPECT |
| 09-04 03:07:24Z | espn:cfb:401856776 | 5 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:24Z | espn:cfb:401856776 | 25 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:24Z | espn:cfb:401856776 | 100 | in | True | True | 0.8767 | +0.1407 | SUSPECT |
| 09-04 03:07:24Z | espn:cfb:401856776 | 5 | in | True | True | 0.8680 | +0.1521 | SUSPECT |
| 09-04 03:07:24Z | espn:cfb:401856776 | 25 | in | True | True | 0.8729 | +0.1456 | SUSPECT |
| 09-04 03:07:24Z | espn:cfb:401856776 | 100 | in | True | True | 0.8778 | +0.1392 | SUSPECT |
| 09-04 03:07:24Z | espn:cfb:401856776 | 5 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:24Z | espn:cfb:401856776 | 25 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:24Z | espn:cfb:401856776 | 100 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:25Z | espn:cfb:401856776 | 5 | in | True | True | 0.8638 | +0.1577 | SUSPECT |
| 09-04 03:07:25Z | espn:cfb:401856776 | 25 | in | True | True | 0.8638 | +0.1577 | SUSPECT |
| 09-04 03:07:25Z | espn:cfb:401856776 | 100 | in | True | True | 0.8638 | +0.1577 | SUSPECT |
| 09-04 03:07:26Z | espn:cfb:401856776 | 5 | in | True | True | 0.8534 | +0.1718 | SUSPECT |
| 09-04 03:07:26Z | espn:cfb:401856776 | 25 | in | True | True | 0.8534 | +0.1718 | SUSPECT |
| 09-04 03:07:26Z | espn:cfb:401856776 | 100 | in | True | True | 0.8584 | +0.1650 | SUSPECT |
| 09-04 03:07:27Z | espn:cfb:401856776 | 25 | in | True | True | 0.8596 | +0.1633 | SUSPECT |
| 09-04 03:07:27Z | espn:cfb:401856776 | 100 | in | True | True | 0.8627 | +0.1591 | SUSPECT |
| 09-04 03:07:27Z | espn:cfb:401856776 | 5 | in | True | True | 0.8638 | +0.1577 | SUSPECT |
| 09-04 03:07:27Z | espn:cfb:401856776 | 25 | in | True | True | 0.8638 | +0.1577 | SUSPECT |
| 09-04 03:07:27Z | espn:cfb:401856776 | 100 | in | True | True | 0.8638 | +0.1577 | SUSPECT |
| 09-04 03:07:28Z | espn:cfb:401856776 | 5 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:28Z | espn:cfb:401856776 | 25 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:28Z | espn:cfb:401856776 | 100 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:30Z | espn:cfb:401856776 | 5 | in | True | True | 0.8846 | +0.1305 | SUSPECT |
| 09-04 03:07:30Z | espn:cfb:401856776 | 25 | in | True | True | 0.8846 | +0.1305 | SUSPECT |
| 09-04 03:07:30Z | espn:cfb:401856776 | 100 | in | True | True | 0.8846 | +0.1305 | SUSPECT |
| 09-04 03:07:30Z | espn:cfb:401856776 | 5 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:30Z | espn:cfb:401856776 | 25 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:30Z | espn:cfb:401856776 | 100 | in | True | True | 0.8794 | +0.1372 | SUSPECT |
| 09-04 03:07:30Z | espn:cfb:401856776 | 100 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:31Z | espn:cfb:401856776 | 5 | in | True | True | 0.8643 | +0.1570 | SUSPECT |
| 09-04 03:07:31Z | espn:cfb:401856776 | 25 | in | True | True | 0.8643 | +0.1570 | SUSPECT |
| 09-04 03:07:31Z | espn:cfb:401856776 | 100 | in | True | True | 0.8643 | +0.1570 | SUSPECT |
| 09-04 03:07:31Z | espn:cfb:401856776 | 100 | in | True | True | 0.8677 | +0.1525 | SUSPECT |
| 09-04 03:07:32Z | espn:cfb:401856776 | 5 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:32Z | espn:cfb:401856776 | 25 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:32Z | espn:cfb:401856776 | 100 | in | True | True | 0.8742 | +0.1439 | SUSPECT |
| 09-04 03:07:32Z | espn:cfb:401856776 | 5 | in | True | True | 0.8846 | +0.1305 | SUSPECT |
| 09-04 03:07:32Z | espn:cfb:401856776 | 25 | in | True | True | 0.8846 | +0.1305 | SUSPECT |
| 09-04 03:07:32Z | espn:cfb:401856776 | 100 | in | True | True | 0.8893 | +0.1245 | SUSPECT |
| 09-04 03:07:32Z | espn:cfb:401856776 | 5 | in | True | True | 0.8945 | +0.1180 | SUSPECT |
| 09-04 03:07:32Z | espn:cfb:401856776 | 25 | in | True | True | 0.8945 | +0.1180 | SUSPECT |
| 09-04 03:07:32Z | espn:cfb:401856776 | 100 | in | True | True | 0.8945 | +0.1180 | SUSPECT |
| 09-04 03:07:33Z | espn:cfb:401856776 | 5 | in | True | True | 0.8841 | +0.1311 | SUSPECT |
| 09-04 03:07:33Z | espn:cfb:401856776 | 25 | in | True | True | 0.8841 | +0.1311 | SUSPECT |
| 09-04 03:07:33Z | espn:cfb:401856776 | 100 | in | True | True | 0.8841 | +0.1311 | SUSPECT |
| 09-04 03:07:33Z | espn:cfb:401856776 | 25 | in | True | True | 0.9038 | +0.1064 | SUSPECT |
| 09-04 03:07:33Z | espn:cfb:401856776 | 100 | in | True | True | 0.9038 | +0.1064 | SUSPECT |
| 09-04 03:07:33Z | espn:cfb:401856776 | 25 | in | True | True | 0.9196 | +0.0875 | SUSPECT |
| 09-04 03:07:33Z | espn:cfb:401856776 | 100 | in | True | True | 0.9225 | +0.0840 | SUSPECT |
| 09-04 03:07:34Z | espn:cfb:401856776 | 25 | in | True | True | 0.9117 | +0.0968 | SUSPECT |
| 09-04 03:07:34Z | espn:cfb:401856776 | 100 | in | True | True | 0.9196 | +0.0875 | SUSPECT |
| 09-04 03:07:35Z | espn:cfb:401856776 | 25 | in | True | True | 0.9196 | +0.0875 | SUSPECT |
| 09-04 03:07:35Z | espn:cfb:401856776 | 100 | in | True | True | 0.9225 | +0.0840 | SUSPECT |
| 09-04 03:07:51Z | espn:mlb:401816796 | 100 | in | True | True | 0.9846 | +0.0157 | SUSPECT |
| 09-04 03:12:37Z | espn:mlb:401816796 | 25 | in | True | True | 0.9442 | +0.0591 | SUSPECT |
| 09-04 03:12:37Z | espn:mlb:401816796 | 100 | in | True | True | 0.9442 | +0.0591 | SUSPECT |
| 09-04 03:12:38Z | espn:mlb:401816796 | 25 | in | True | True | 0.9341 | +0.0706 | SUSPECT |
| 09-04 03:12:38Z | espn:mlb:401816796 | 100 | in | True | True | 0.9341 | +0.0706 | SUSPECT |
| 09-04 03:12:41Z | espn:mlb:401816796 | 100 | in | True | True | 0.9845 | +0.0157 | SUSPECT |
| 09-04 03:12:44Z | espn:mlb:401816796 | 25 | in | True | True | 0.9744 | +0.0263 | SUSPECT |
| 09-04 03:12:44Z | espn:mlb:401816796 | 100 | in | True | True | 0.9744 | +0.0263 | SUSPECT |
| 09-04 03:29:19Z | espn:cfb:401856776 | 100 | in | False | True | 0.9855 | +0.0148 | SUSPECT |
| 09-04 03:29:19Z | espn:cfb:401856776 | 25 | in | False | True | 0.9749 | +0.0257 | SUSPECT |
| 09-04 03:29:19Z | espn:cfb:401856776 | 100 | in | False | True | 0.9816 | +0.0188 | SUSPECT |
| 09-04 03:29:20Z | espn:cfb:401856776 | 100 | in | False | True | 0.9878 | +0.0124 | SUSPECT |
| 09-04 03:29:20Z | espn:cfb:401856776 | 100 | in | False | True | 0.9855 | +0.0148 | SUSPECT |
| 09-04 03:29:20Z | espn:cfb:401856776 | 25 | in | False | True | 0.9749 | +0.0257 | SUSPECT |
| 09-04 03:29:20Z | espn:cfb:401856776 | 100 | in | False | True | 0.9749 | +0.0257 | SUSPECT |
| 09-04 03:29:23Z | espn:cfb:401856776 | 100 | in | False | True | 0.9855 | +0.0148 | SUSPECT |
| 09-04 03:30:41Z | espn:cfb:401856776 | 100 | in | False | True | 0.9861 | +0.0141 | SUSPECT |
| 09-04 03:35:50Z | espn:cfb:401856776 | 25 | in | False | True | 0.9781 | +0.0224 | SUSPECT |
| 09-04 03:38:24Z | espn:cfb:401856776 | 25 | in | False | True | 0.9596 | +0.0421 | SUSPECT |
| 09-04 03:38:24Z | espn:cfb:401856776 | 100 | in | False | True | 0.9887 | +0.0114 | SUSPECT |
| 09-04 03:41:45Z | espn:cfb:401856776 | 5 | end | False | True | 0.8595 | +0.1634 | SUSPECT |
| 09-04 03:41:45Z | espn:cfb:401856776 | 25 | end | False | True | 0.8837 | +0.1316 | SUSPECT |
| 09-04 03:41:45Z | espn:cfb:401856776 | 100 | end | False | True | 0.8984 | +0.1131 | SUSPECT |
| 09-04 03:41:46Z | espn:cfb:401856776 | 5 | end | False | True | 0.8798 | +0.1366 | SUSPECT |
| 09-04 03:41:46Z | espn:cfb:401856776 | 25 | end | False | True | 0.9039 | +0.1063 | SUSPECT |
| 09-04 03:41:46Z | espn:cfb:401856776 | 100 | end | False | True | 0.9600 | +0.0417 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 25 | end | False | True | 0.9501 | +0.0525 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 100 | end | False | True | 0.9550 | +0.0472 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 25 | end | False | True | 0.9433 | +0.0601 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 100 | end | False | True | 0.9587 | +0.0431 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 25 | end | False | True | 0.9226 | +0.0839 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 100 | end | False | True | 0.9380 | +0.0661 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 5 | end | False | True | 0.8950 | +0.1173 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 25 | end | False | True | 0.9019 | +0.1088 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 100 | end | False | True | 0.9180 | +0.0893 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 25 | end | False | True | 0.9147 | +0.0932 | SUSPECT |
| 09-04 03:41:48Z | espn:cfb:401856776 | 100 | end | False | True | 0.9681 | +0.0329 | SUSPECT |
| 09-04 03:41:49Z | espn:cfb:401856776 | 25 | end | False | True | 0.9759 | +0.0247 | SUSPECT |
| 09-04 03:41:51Z | espn:cfb:401856776 | 25 | end | False | True | 0.9662 | +0.0350 | SUSPECT |
| 09-04 03:41:51Z | espn:cfb:401856776 | 100 | end | False | True | 0.9734 | +0.0273 | SUSPECT |
| 09-04 03:44:34Z | espn:cfb:401856776 | 25 | end | False | True | 0.9487 | +0.0541 | SUSPECT |
| 09-04 03:44:34Z | espn:cfb:401856776 | 100 | end | False | True | 0.9487 | +0.0541 | SUSPECT |
| 09-04 03:44:34Z | espn:cfb:401856776 | 25 | end | False | True | 0.9695 | +0.0315 | SUSPECT |
| 09-04 03:44:34Z | espn:cfb:401856776 | 100 | end | False | True | 0.9775 | +0.0230 | SUSPECT |
| 09-04 03:44:34Z | espn:cfb:401856776 | 25 | end | False | True | 0.9198 | +0.0872 | SUSPECT |
| 09-04 03:44:34Z | espn:cfb:401856776 | 100 | end | False | True | 0.9397 | +0.0642 | SUSPECT |
| 09-04 03:44:35Z | espn:cfb:401856776 | 5 | end | False | True | 0.8726 | +0.1460 | SUSPECT |
| 09-04 03:44:35Z | espn:cfb:401856776 | 25 | end | False | True | 0.9153 | +0.0925 | SUSPECT |
| 09-04 04:40:34Z | espn:mlb:401816796 | 100 | in | False | True | 0.9822 | +0.0181 | SUSPECT |
| 09-04 05:04:50Z | espn:mlb:401816796 | 25 | end | False | True | 0.9768 | +0.0238 | SUSPECT |
| 09-04 05:04:50Z | espn:mlb:401816796 | 100 | end | False | True | 0.9836 | +0.0167 | SUSPECT |
| 09-04 23:16:15Z | espn:cfb:401864495 | 25 | in | False | True | 0.9603 | +0.0414 | SUSPECT |
| 09-04 23:16:15Z | espn:cfb:401864495 | 100 | in | False | True | 0.9611 | +0.0404 | SUSPECT |
| 09-04 23:49:24Z | espn:cfb:401864495 | 100 | in | False | True | 0.9893 | +0.0108 | SUSPECT |
| 09-05 00:46:45Z | espn:cfb:401864495 | 25 | in | False | True | 0.9705 | +0.0304 | SUSPECT |
| 09-05 00:46:45Z | espn:cfb:401864495 | 100 | in | False | True | 0.9773 | +0.0232 | SUSPECT |
| 09-05 00:46:45Z | espn:cfb:401864495 | 100 | in | False | True | 0.9747 | +0.0259 | SUSPECT |
| 09-05 00:46:45Z | espn:cfb:401864495 | 100 | in | False | True | 0.9732 | +0.0275 | SUSPECT |
| 09-05 00:46:45Z | espn:cfb:401864495 | 100 | in | False | True | 0.9705 | +0.0304 | SUSPECT |
| 09-05 00:49:35Z | espn:mlb:401816802 | 100 | in | False | True | 0.9897 | +0.0104 | SUSPECT |
| 09-05 01:02:52Z | espn:cfb:401864495 | 25 | in | False | True | 0.9698 | +0.0311 | SUSPECT |
| 09-05 01:02:52Z | espn:cfb:401864495 | 100 | in | False | True | 0.9698 | +0.0311 | SUSPECT |
| 09-05 01:02:52Z | espn:cfb:401864495 | 25 | in | False | True | 0.9596 | +0.0420 | SUSPECT |
| 09-05 01:02:52Z | espn:cfb:401864495 | 100 | in | False | True | 0.9596 | +0.0420 | SUSPECT |
| 09-05 01:02:53Z | espn:cfb:401864495 | 25 | in | False | True | 0.9696 | +0.0313 | SUSPECT |
| 09-05 01:02:53Z | espn:cfb:401864495 | 100 | in | False | True | 0.9696 | +0.0313 | SUSPECT |
| 09-05 01:03:28Z | espn:cfb:401868262 | 100 | in | False | True | 0.9880 | +0.0121 | SUSPECT |
| 09-05 01:20:59Z | espn:cfb:401864495 | 100 | in | False | True | 0.9866 | +0.0136 | SUSPECT |
| 09-05 01:20:59Z | espn:cfb:401864495 | 100 | in | False | True | 0.9801 | +0.0203 | SUSPECT |
| 09-05 01:21:03Z | espn:cfb:401864495 | 100 | in | False | True | 0.9895 | +0.0106 | SUSPECT |
| 09-05 01:41:02Z | espn:cfb:401864495 | 25 | in | False | True | 0.9328 | +0.0720 | SUSPECT |
| 09-05 01:41:02Z | espn:cfb:401864495 | 100 | in | False | True | 0.9575 | +0.0444 | SUSPECT |
| 09-05 01:41:02Z | espn:cfb:401864495 | 25 | in | False | True | 0.9657 | +0.0355 | SUSPECT |
| 09-05 01:41:02Z | espn:cfb:401864495 | 100 | in | False | True | 0.9868 | +0.0134 | SUSPECT |
| 09-05 01:52:22Z | espn:cfb:401864495 | 25 | in | True | True | 0.9564 | +0.0456 | SUSPECT |
| 09-05 01:52:22Z | espn:cfb:401864495 | 100 | in | True | True | 0.9637 | +0.0377 | SUSPECT |
| 09-05 01:52:23Z | espn:cfb:401864495 | 25 | in | True | True | 0.9132 | +0.0950 | SUSPECT |
| 09-05 01:52:23Z | espn:cfb:401864495 | 100 | in | True | True | 0.9132 | +0.0950 | SUSPECT |
| 09-05 01:57:38Z | espn:cfb:401864495 | 100 | in | False | True | 0.9846 | +0.0156 | SUSPECT |
| 09-05 02:03:38Z | espn:cfb:401864495 | 100 | end | False | True | 0.9864 | +0.0138 | SUSPECT |
| 09-05 02:03:39Z | espn:cfb:401864495 | 25 | end | False | True | 0.9757 | +0.0249 | SUSPECT |
| 09-05 02:03:39Z | espn:cfb:401864495 | 100 | end | False | True | 0.9757 | +0.0249 | SUSPECT |
| 09-05 02:03:39Z | espn:cfb:401864495 | 25 | end | False | True | 0.9651 | +0.0362 | SUSPECT |
| 09-05 02:03:39Z | espn:cfb:401864495 | 100 | end | False | True | 0.9651 | +0.0362 | SUSPECT |
| 09-05 02:40:21Z | espn:mlb:401816809 | 100 | in | False | True | 0.9899 | +0.0102 | SUSPECT |
| 09-05 03:05:58Z | espn:mlb:401816806 | 5 | end | False | True | 0.8663 | +0.1543 | SUSPECT |
| 09-05 03:05:58Z | espn:mlb:401816806 | 25 | end | False | True | 0.8663 | +0.1543 | SUSPECT |
| 09-05 03:05:58Z | espn:mlb:401816806 | 100 | end | False | True | 0.8727 | +0.1459 | SUSPECT |
| 09-05 03:05:59Z | espn:mlb:401816806 | 25 | end | False | True | 0.9150 | +0.0929 | SUSPECT |
| 09-05 03:05:59Z | espn:mlb:401816806 | 100 | end | False | True | 0.9624 | +0.0391 | SUSPECT |
| 09-05 03:28:12Z | espn:mlb:401816808 | 100 | end | False | True | 0.9883 | +0.0118 | SUSPECT |
| 09-05 03:30:35Z | espn:mlb:401816808 | 25 | end | False | True | 0.9486 | +0.0542 | SUSPECT |
| 09-05 03:30:35Z | espn:mlb:401816808 | 100 | end | False | True | 0.9548 | +0.0474 | SUSPECT |
| 09-05 03:30:35Z | espn:mlb:401816808 | 25 | end | False | True | 0.9486 | +0.0542 | SUSPECT |
| 09-05 03:30:35Z | espn:mlb:401816808 | 100 | end | False | True | 0.9548 | +0.0474 | SUSPECT |
| 09-05 03:30:36Z | espn:mlb:401816808 | 25 | end | False | True | 0.9490 | +0.0538 | SUSPECT |
| 09-05 03:30:36Z | espn:mlb:401816808 | 100 | end | False | True | 0.9558 | +0.0463 | SUSPECT |
| 09-05 03:30:36Z | espn:mlb:401816808 | 25 | end | False | True | 0.9780 | +0.0225 | SUSPECT |
| 09-05 03:30:36Z | espn:mlb:401816808 | 100 | end | False | True | 0.9799 | +0.0205 | SUSPECT |
| 09-05 04:11:11Z | espn:mlb:401816810 | 25 | end | False | True | 0.9655 | +0.0358 | SUSPECT |
| 09-05 04:11:11Z | espn:mlb:401816810 | 100 | end | False | True | 0.9655 | +0.0358 | SUSPECT |
| 09-05 04:36:32Z | espn:mlb:401816809 | 25 | in | False | True | 0.9329 | +0.0719 | SUSPECT |
| 09-05 04:36:32Z | espn:mlb:401816809 | 100 | in | False | True | 0.9329 | +0.0719 | SUSPECT |
| 09-05 04:42:16Z | espn:mlb:401816809 | 25 | in | False | True | 0.9740 | +0.0267 | SUSPECT |
| 09-05 04:42:16Z | espn:mlb:401816809 | 100 | in | False | True | 0.9740 | +0.0267 | SUSPECT |
| 09-05 04:45:52Z | espn:mlb:401816809 | 25 | in | False | True | 0.9517 | +0.0507 | SUSPECT |
| 09-05 04:45:57Z | espn:mlb:401816811 | 100 | in | False | True | 0.9888 | +0.0113 | SUSPECT |
| 09-05 05:00:59Z | espn:mlb:401816809 | 25 | end | False | True | 0.9573 | +0.0446 | SUSPECT |
| 09-05 05:00:59Z | espn:mlb:401816809 | 25 | end | False | True | 0.9701 | +0.0309 | SUSPECT |
| 09-05 05:00:59Z | espn:mlb:401816809 | 100 | end | False | True | 0.9857 | +0.0145 | SUSPECT |
| 09-05 05:01:00Z | espn:mlb:401816809 | 25 | end | False | True | 0.9757 | +0.0249 | SUSPECT |
| 09-05 05:01:00Z | espn:mlb:401816809 | 100 | end | False | True | 0.9866 | +0.0136 | SUSPECT |
| 09-05 05:01:04Z | espn:mlb:401816809 | 25 | end | False | True | 0.9344 | +0.0702 | SUSPECT |
| 09-05 05:01:04Z | espn:mlb:401816809 | 100 | end | False | True | 0.9417 | +0.0619 | SUSPECT |

**n for the forward paper row: 37** (basis: power; 127 in-play, clean actionable rows; sigma 0.01535, median locked return 0.02888).

Descriptive. Reads no outcome, claims no edge.
