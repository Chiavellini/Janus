# L26 — MLB settlement-wedge rates (descriptive)

Window 2026-03-25 → 2026-09-02, MLB Stats API regular-season schedule, retrieved 2026-09-03T05:12:42.678946+00:00.
Games seen 2101; denominator (not pre-game) **2100** — sufficient (≥1,500).

| state | n |
|---|---|
| Completed Early | 2 |
| Final | 2071 |
| Postponed | 27 |

| rate | value | count |
|---|---|---|
| mlb.postponed_rate | 0.01286 | 27 |
| mlb.postponed_gt2d_rate | 0.00476 | 10 (exact) |
| mlb.cancelled_rate | 0.00000 | 0 |
| mlb.suspended_rate | 0.00048 | 1 |

Completed-early (rain-shortened, official on both venues): 2.

Registered in `nodes/settle_wedge/evidence.py` as `mlb.postponed_gt2d_rate` and `mlb.cancelled_rate` verbatim. This row claims nothing about edge; it prices a reserve. NFL/NHL need their own rows.
