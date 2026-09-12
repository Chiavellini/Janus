# L78 verdict (in progress) — where the loop thread's time goes

## Instrument 1 — py-spy on the live lane

Sample 1, 2026-09-12 01:57:31Z, 60 s at 100 Hz, 5,946 samples, lane at 79 % CPU, 34 pollers,
loop lag 1.8 s at the tick (`results_live_busy_01.json`; raw on the box at
`/srv/janus/research/l78/sample_20260912T015731Z.raw`). Inclusive shares of the loop thread:

| bucket | share |
|---|---|
| sizing sweep (`_execute_sized`) | 54.9 % (choose_live_size 48.7; day_notional/refusals 11.6; fingerprint 4.5; audit 1.1) |
| ladder projection and replica rebuild (`project`, `_quoted_side`, `project_in`, `ladders`, `snapshot`) | 21.4 % |
| evaluation (`on_event` pricing, `_record`) | 11.7 % (frontier 0.1; store writes 1.6) |
| capture write (gzip + json.dumps) | 4.2 % |
| frame decode (json.loads, websockets) | 2.5 % |
| Polymarket reconciler | 1.3 % |
| heartbeat sweep | 1.1 % |
| guard / report tick / retention | 1.0 % |
| sqlite commit/execute | 0.2 % |

Leaf self-time is led by `day_notional_usd` (9.5 % across three lines), dataclass `__init__`
(16.3 %: `Quote`/`Fill`/`Leg` construction inside `best_cover` and `snapshot`), `assert_price_range`,
`params_for`, `_quoted_side`, `project_in`, `iterencode`, `_hour_key`.

Attributed: ≥ 98 % of samples to named buckets (criterion 1 met for the busy sample). The heartbeat
sweep L51 measured at 216 pollers is ~1 % at 34: L80 moves to the end of the queue. The quiet-hour
sample is still to be taken.

## Instrument 2 — offline full-pipeline replay

`measure.py`: L51's 10k-frame prefix per venue through a real Supervisor with LIMITED_LIVE sizing on
the 234-event slate exported from the box (`/Volumes/Kilos/janus/research/l78-slate-20260909T04`).
Baseline (`27c4549`): median 23.079 CPU s for 20,000 frames, 11,884 evaluations, 2,234 rows,
digests stable across runs. Used as the paired instrument by L79 (−56 %).
