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
digests stable across runs. Used as the paired instrument by L79–L81. Median CPU seconds for the same 20,000 frames and
234-poller slate, evaluation rows and selections byte-identical throughout (digests
`9f41923b8cf055a1` / `4f53cda18c2baa0c`):

| tree | median CPU s | vs baseline |
|---|---|---|
| baseline `27c4549` | 23.079 | — |
| + L79 (sizing gate) | 10.109 | −56 % |
| + L81 only (ladder memo etc.; the instrument cannot see decode or capture) | 10.530 | within noise |
| + L80 + L81 (socket pulse) | 3.798 | −84 % |

A profiled offline run after L79 (`--profile`) attributed the remaining time to the heartbeat
sweep (~30 % at this slate: `handle` self 16.7 %, `replica.heartbeat` 11.4 %, `_beat` 7.1 %), the
Kalshi identity scan and sort (~6 %), and pricing (`price_combination`, `assert_price_range`,
`params_for`, `_fills_for`, ~15 %). The live confirmation of each is L82.


## Live after the paste (the plan's L82, instrument 1 again)

`cf9770b` (L77, L79–L83) released 2026-09-12 05:20Z; sample at 05:23:40Z, 60 s at 100 Hz
(`results_live_after_01.json`): **1,618 on-CPU samples vs 5,946** in the baseline, the lane at
**28 % CPU vs 79 %**, loop lag **0.2–0.3 s vs 1.8 s**, 39 pollers vs 34, at about half the
baseline's Kalshi frame rate (a quieter hour: 4 live games). Per frame ≈ 0.37 ms vs 0.94 ms. Of the
busy time: ladder 37.5 %, evaluation 20.8 %, capture enqueue on the loop 10.2 %, Polymarket
reconciler 8.6 %, sizing sweep 4.0 %, decode 2.0 %, heartbeat 0.0 %. The evening-slate sample
(00–04Z) is still owed for the like-for-like comparison; the command is in NEXT.md. L78 PASS as an
attribution; L79–L81 confirmed in direction live, magnitude pending the evening slate.
