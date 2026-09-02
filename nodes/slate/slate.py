#!/usr/bin/env python3
"""When does the box need to be awake?

The lane only has anything to watch while a co-listed game is in play. A box running 24/7 costs
roughly 3x what it needs to, and a box started by hand gets left on. This turns the schedule into
a set of contiguous WINDOWS -- wake, drain -- that a scheduler can act on days in advance.

Two things make this cheap rather than fiddly:

1. Overlapping events share one box. Fifteen MLB games starting inside three hours is ONE window,
   not fifteen. Merging is most of the saving; on a normal MLB day the games are so clustered that
   coverage collapses to a couple of blocks.
2. The slate is knowable ~3 days out. ESPN publishes the schedule, Polymarket lists a game about
   82 hours before Kalshi opens it, so a 3-day horizon is comfortably inside what both venues will
   have listed by the time the window opens.

The window is deliberately WIDER than the game: `lead_s` before first pitch, because a market can
dislocate at open, and `settle_s` after the expected end, because the last minutes of a blowout
are where a book goes stale and because we want the settle transition recorded.

Durations are nominal, not predictions. A game running long is covered by `settle_s`; a game
running very long is a recorded miss, which is the honest outcome and shows up in the record as a
window that ended while the game was still `in`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

#: Nominal wall-clock length of a full game, in seconds. Used only to close a window.
TYPICAL_DURATION_S: dict[str, int] = {
    "mlb":  3 * 3600 + 600,      # ~3h10m including pitching changes
    "nfl":  3 * 3600 + 900,      # ~3h15m
    "nba":  2 * 3600 + 1800,     # ~2h30m
    "wnba": 2 * 3600,
    "nhl":  2 * 3600 + 1800,
    "epl":  2 * 3600,            # 90' + stoppage + half time
}
DEFAULT_DURATION_S = 3 * 3600

#: Wake this long before first pitch. The open is where a market is thinnest and most dislocated.
DEFAULT_LEAD_S = 30 * 60
#: Stay up this long past the nominal end, to cover overrun and record the settle transition.
DEFAULT_SETTLE_S = 45 * 60


@dataclass(frozen=True)
class Window:
    """One contiguous period the box must be awake."""
    start_utc: float
    end_utc: float
    game_ids: tuple[str, ...] = ()
    leagues: tuple[str, ...] = ()

    @property
    def hours(self) -> float:
        return (self.end_utc - self.start_utc) / 3600.0

    def covers(self, ts: float) -> bool:
        return self.start_utc <= ts <= self.end_utc

    def __str__(self) -> str:
        a = datetime.fromtimestamp(self.start_utc, timezone.utc).strftime("%a %m-%d %H:%M")
        b = datetime.fromtimestamp(self.end_utc, timezone.utc).strftime("%H:%M")
        return (f"{a}-{b}Z  {self.hours:4.1f}h  {len(self.game_ids):2} games  "
                f"{','.join(self.leagues)}")


def windows_for(games, *, lead_s: int = DEFAULT_LEAD_S, settle_s: int = DEFAULT_SETTLE_S,
                durations: dict[str, int] | None = None) -> list[Window]:
    """Merge per-game coverage spans into the fewest contiguous windows.

    `games` is any iterable of objects with `.start_utc`, `.league` and `.game_id` -- the
    ScheduledGame shape from `nodes/schedule_espn`.
    """
    dur = durations or TYPICAL_DURATION_S
    spans = []
    for g in games:
        length = dur.get(g.league, DEFAULT_DURATION_S)
        spans.append((g.start_utc - lead_s, g.start_utc + length + settle_s, g.game_id, g.league))
    if not spans:
        return []
    spans.sort()

    merged: list[list] = []
    for start, end, gid, lg in spans:
        if merged and start <= merged[-1][1]:          # overlaps the open window: extend it
            merged[-1][1] = max(merged[-1][1], end)
            merged[-1][2].append(gid)
            merged[-1][3].add(lg)
        else:
            merged.append([start, end, [gid], {lg}])
    return [Window(s, e, tuple(ids), tuple(sorted(lgs))) for s, e, ids, lgs in merged]


def next_transition(windows: list[Window], now: float) -> tuple[str, float] | None:
    """('wake'|'drain', epoch) for the next thing a scheduler must do, or None."""
    for w in windows:
        if now < w.start_utc:
            return ("wake", w.start_utc)
        if w.covers(now):
            return ("drain", w.end_utc)
    return None


def uptime_hours(windows: list[Window]) -> float:
    return sum(w.hours for w in windows)


def cost_estimate(windows: list[Window], usd_per_hour: float) -> dict:
    """What the schedule costs against running the same instance continuously."""
    if not windows:
        return {"hours": 0.0, "usd": 0.0, "always_on_usd": 0.0, "saving_pct": 0.0}
    span_h = (max(w.end_utc for w in windows) - min(w.start_utc for w in windows)) / 3600.0
    up = uptime_hours(windows)
    always = span_h * usd_per_hour
    return {"hours": round(up, 2), "usd": round(up * usd_per_hour, 2),
            "always_on_usd": round(always, 2),
            "saving_pct": round((1 - up / span_h) * 100.0, 1) if span_h else 0.0}
