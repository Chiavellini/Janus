# L29 — NFL settlement-wedge rates (descriptive)

nflverse `games.csv` REG rows for seasons [2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025] (2020 excluded by decision), retrieved 2026-09-03T17:20:39.774442+00:00.
Denominator **2640** = 2639 nflverse rows + 1 cancelled game(s) nflverse omits (sufficient).

| rate | value | count |
|---|---|---|
| postponed_gt48h_rate | 0.001515 | 4 |
| cancelled_rate | 0.000379 | 1 |

| season | REG rows | >48 h | ≤48 h moves | cancelled |
|---|---|---|---|---|
| 2015 | 256 | 0 | 0 | 0 |
| 2016 | 256 | 0 | 0 | 0 |
| 2017 | 256 | 1 | 0 | 0 |
| 2018 | 256 | 0 | 0 | 0 |
| 2019 | 256 | 0 | 0 | 0 |
| 2021 | 272 | 3 | 0 | 0 |
| 2022 | 271 | 0 | 0 | 1 |
| 2023 | 272 | 0 | 0 | 0 |
| 2024 | 272 | 0 | 0 | 0 |
| 2025 | 272 | 0 | 0 | 0 |

Completeness gate: FAILED — 2 unexplained Tue/Wed/Fri game(s), 0 table row(s) without a schedule game. ['2024 wk1 GB@PHI 2024-09-06 (Friday)', '2025 wk1 KC@LAC 2025-09-05 (Friday)']

Verdict: **INCOMPLETE**. Nothing registered.
