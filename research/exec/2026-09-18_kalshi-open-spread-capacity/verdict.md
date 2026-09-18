# L152 + L153 verdict — market making at Kalshi's sports open is dead on this data

**L152: `STRONG_LEAD` by its registered rule (CEILING $51.43/day at 25 %). L153: `ARTIFACT`.** The first
number said yes; checking the trades it rested on said no. Free and read-only throughout: local files and
Kalshi's public trade history; no box, no AWS, no orders.

Data: 248 MLB markets (`KXMLBGAME`), 2026-08-21 04:30 → 08-27 15:09 UTC (6.44 days), both venues sampled
~every 69 s from ~4 min after Kalshi's open (`track.sqlite`, 462,258 rows), 82 open snapshots
(`kalshi_open.sqlite`), and **1,639,802 Kalshi public trades** (310,587,116 contracts) in the window.

## 1. Kalshi does open very wide — and almost nobody trades while it is

| Since Kalshi's open | Samples | Kalshi spread median [p25, p75] | Spread ≥ 6c | Contracts traded while quotable (6c) |
|---|---|---|---|---|
| **at open** (n=52) | — | **87c** [70c, 87c] | — | — |
| 0–5 min | 6 | 11c | 100 % | 0 |
| 5–30 min | 818 | 11c [6c, 11c] | 81 % | 7 |
| 30 min–2 h | 3,886 | 7c [5c, 10c] | 71 % | 202 |
| 2–6 h | 12,178 | 5c [4c, 7c] | 44 % | 785 |
| 6–24 h | 58,206 | 3c [2c, 4c] | 8 % | 7 |
| >24 h | 277,894 | **1c** [1c, 1c] | 0.01 % | 247,222 |

The spread is wide exactly when there is no interest in the market, and the flow arrives only once the
spread has closed to a cent. **Pre-game, the whole opportunity is a CEILING of $1.56/day even at 100 %
capture** (and $1.24/day on trades consistent with their sample). That is the "market making at the open"
idea, and it is dead on this data.

## 2. L152's $51.43 was the sampling rule, not the market

99.6 % of L152's capturable volume was **in-play**, in the bucket where the median spread is 1c and wide
samples are one in ten thousand. With samples ~69 s apart and a 120 s match window, an instant of wide
spread at sample time (a run scores, the book gaps) was credited with the minute of heavy trading that
followed — which printed at a normal spread.

L153 tested that directly. A Kalshi trade prints **at** a touch (a YES-taker lifts the ask, a NO-taker
hits the bid), so a trade is consistent with its sample only if it printed within a tick of that
sample's touch:

| | 6c threshold | 10c threshold |
|---|---|---|
| L152 capturable contracts | 248,223 | 119,499 |
| **consistent with their sample** | **32,637 (13.2 %)** | **525 (0.4 %)** |
| L152 CEILING at 25 % | $51.43/day | $13.93/day |
| **CEILING on consistent trades, 25 %** | **$7.29/day** | **$0.28/day** |
| … and within 10 s of the sample, 25 % | $0.22/day | $0.16/day |

Registered bars: ≥ $50 SURVIVES, $15–50 WEAKENED, **< $15 ARTIFACT**. The best consistent CEILING is
$7.29/day. **L152's STRONG_LEAD must not be used to justify spending money.**

And even that $7.29 is a ceiling in the most generous sense: zero adverse selection, at the moment when
it is worst — in-play, quoting around a Polymarket mid that L143/L144 showed runs stale, while the price
is moving. The tightening from $7.29 to $0.22 when the window shrinks to 10 s says the same thing: the
"consistent" trades are mostly still far in time from the book that was seen.

## 3. What this closes and what it does not

- **Closes:** market making inside Kalshi's post-open sports spreads, as a route to $50/day, on MLB. Wide
  spreads carry no flow; flow happens at a one-cent spread, where there is nothing to capture after the
  maker fee.
- **Does not measure:** fills against OUR quotes, queue position, adverse selection (all of which could
  only lower the numbers above), or any league other than MLB and any season other than late August.
  NFL and NBA volumes are larger; the structural finding — wide spreads mean no interest — is the kind of
  thing that tends to generalise, but it has not been measured there.
- The Bitcoin figures this lead came from (+4.10c/fill, 35.8 % both-sides) were simulated fills on one
  crypto market. Sports did not reproduce the opportunity they described.

## Reproduce

```bash
python3 research/exec/2026-09-18_kalshi-open-spread-capacity/measure.py --offline --out results_20260918.json
python3 research/exec/2026-09-18_kalshi-open-spread-capacity/robustness.py
python3 -m pytest -q -o addopts="" research/exec/2026-09-18_kalshi-open-spread-capacity/
```

`--offline` needs the cached Kalshi trades from the first (online) run; without them, run `measure.py`
once without `--offline` to re-fetch Kalshi's public history (no account required).
