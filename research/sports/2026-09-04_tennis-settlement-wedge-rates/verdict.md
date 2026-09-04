# L39 — tennis settlement-wedge rates (descriptive)

ATP from Tennismylife/TML-Database and WTA from VictorSquidWei/tennis_wta (both the Sackmann layout; commits in `inputs/PROVENANCE.md`), seasons 2021–2025, run 2026-09-04T01:00:41.400314+00:00.

| rate | value | count / population |
|---|---|---|
| walkover_rate (pooled, REGISTERED) | 0.007955 | 210 / 26398 |
| walkover_rate atp | 0.007207 | 98 / 13598 |
| walkover_rate wta | 0.00875 | 112 / 12800 |
| retirements (context, ruled SAME) | — | 789 |
| defaults (context, ruled SAME) | — | 4 |
| delayed_gt7d_rate | NOT MEASURABLE | see spec: no results archive keeps match dates; forward row F4 |

| season file | rows | walkovers | population | rate | gate |
|---|---|---|---|---|---|
| atp_2021 | 2735 | 20 | 2606 | 0.007675 | PASSED |
| atp_2022 | 2918 | 17 | 2710 | 0.006273 | PASSED |
| atp_2023 | 2995 | 19 | 2772 | 0.006854 | PASSED |
| atp_2024 | 3076 | 20 | 2816 | 0.007102 | PASSED |
| atp_2025 | 2944 | 22 | 2694 | 0.008166 | PASSED |
| wta_2021 | 2597 | 27 | 2538 | 0.010638 | PASSED |
| wta_2022 | 2594 | 27 | 2369 | 0.011397 | PASSED |
| wta_2023 | 2810 | 22 | 2538 | 0.008668 | PASSED |
| wta_2024 | 2689 | 18 | 2610 | 0.006897 | PASSED |
| wta_2025 | 2795 | 18 | 2745 | 0.006557 | PASSED |

Parse gate: PASSED on every file; team ties (level D) excluded: 1755.

Verdict: **REGISTERED** for `tennis.walkover_rate` in `nodes/settle_wedge/evidence.py` with this row as `research_ref`. `tennis.delayed_gt7d_rate` stays EVIDENCE_UNMEASURED; tennis keeps blocking by name until the forward row F4 accrues. Claims nothing about edge.
