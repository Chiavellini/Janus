# slate

**Kind:** `pure` (`slate.py`) + `source` (`monitor.py` reads ESPN)
**Implements:** `slate.py`, `monitor.py`

Decides **when the box needs to be awake**. The capture lane has nothing to watch unless a
co-listed game is in play, so this turns the schedule into contiguous wake/drain windows a
scheduler can act on days ahead.

## Position in the grid

```
ESPN ──▶ [schedule_espn] ──▶ games ──▶ [slate] ──▶ Window[] ──▶ box scheduler (wake / drain)
                                                        │
                                                        └──▶ cost estimate
```

**Upstream:** `nodes/schedule_espn`. **Downstream:** the EC2 scheduler; nothing in the pricing path.

## Contract

`windows_for(games, lead_s, settle_s)` merges per-game spans into the fewest contiguous windows.
`next_transition(windows, now)` → `("wake"|"drain", epoch)`. `cost_estimate(windows, usd_per_hour)`.

```
python3 -m nodes.slate.monitor --days 3          # the schedule and what it costs
python3 -m nodes.slate.monitor --now --json      # {"state": "WAKE"|"DRAIN", "next": ...}
```

Windows are deliberately wider than the game: 30 min before first pitch, because a market is
thinnest and most dislocated at the open, and 45 min after the nominal end, to cover overrun and
record the settle transition. Durations are nominal, not predictions — a game running very long
ends up as a recorded miss, which is the honest outcome.

## What it measured

3-day slate on 2026-09-02: **44 games across 6 leagues collapse to 6 windows, 46.3 h of uptime.**

At c7g.medium ($0.0361/h) that is **$1.67 scheduled against $2.67 always-on — only 37% saved**,
because US sports run most of the day and MLB clusters into long evening blocks. Roughly $16/month
versus $26/month.

**Read that before building a scheduler.** At this instance size the wake/drain machinery saves
about $10 a month, which is unlikely to pay for the complexity of getting it wrong — and getting it
wrong means missing capture, which is the expensive failure. The saving only becomes real on a
larger instance. Scheduling here is worth more as a *monitor* (what is on, when) than as a cost
control.

## Failure modes

One league's ESPN failure is recorded and skipped, never fatal. An off-day produces zero windows,
not a 24-hour one. An unregistered league gets a default duration rather than a zero-length window
that would never wake the box.

## Tests

`tests/test_slate.py` — 9 tests, including boundary merging (two abutting games must not flap
drain/wake for one second) and the empty-slate case.
