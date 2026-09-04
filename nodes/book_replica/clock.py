#!/usr/bin/env python3
"""Local clock versus the venue's: the one health check a book cannot make for itself.

Every freshness bound in the system is `now - updated_utc`. If the local wall clock steps, every
book is simultaneously "stale" or "fresh" by the size of the step, and the cover engine prices
on fiction either way. Both venues stamp their frames (Kalshi deltas `ts_ms`, Polymarket events
`timestamp`), so the offset `received_utc - server_utc` is observable on every message.

Measured 2026-09-02 on both sockets: the venue stamp runs 30-70 ms AHEAD of local receipt (the
venue stamps late, or the clocks differ by that much). That is the normal band. A skew of seconds
is a fault, and the supervisor halts pricing on it (spec §13: fail closed on an unhealthy clock).

ONLY EVENTS STAMPED AT SEND TIME ARE EVIDENCE. A Polymarket `book` snapshot carries the book's
LAST-CHANGE time, which on a quiet pre-game market is hours old (found live 2026-09-03: three
pre-game pollers halted on it). `price_change` and Kalshi deltas are stamped when they happen;
snapshots are not fed to the monitor, and a verdict needs `min_samples` first.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from statistics import median


@dataclass
class ClockMonitor:
    """Windowed median of (received - server) per socket. Pure; the stream feeds it.

    Windowed, not an EWMA (changed 2026-09-04): the EWMA never forgot and flipped around the bound
    once a minute for hours, and a Polymarket frame carrying twenty price changes was fed twenty
    times. Samples older than `window_s` drop out, the verdict needs `min_samples` INSIDE the
    window (so it re-arms after a quiet spell or a reconnect), and one frame is one sample.

    What this measures is receipt-time skew, which a stalled event loop produces on BOTH sockets
    at once (the receive timestamp is taken after `ws.recv()` returns). The supervisor tells the
    two apart with its loop-lag probe; this monitor only says how far the stamps are from now.
    """
    window_s: float = 60.0
    max_skew_s: float = 5.0
    #: No verdict on fewer samples than this inside the window: one stale stamp must not halt the lane.
    min_samples: int = 20
    max_samples: int = 2000
    samples: int = 0
    worst_s: float = 0.0
    _win: deque = field(default_factory=deque, repr=False)

    def observe(self, received_utc: float, server_utc: float | None) -> None:
        if server_utc is None:
            return
        d = received_utc - server_utc
        self.samples += 1
        self._win.append((received_utc, d))
        if len(self._win) > self.max_samples:
            self._win.popleft()
        self._expire(received_utc)
        if abs(d) > abs(self.worst_s):
            self.worst_s = d

    def _expire(self, now: float) -> None:
        cut = now - self.window_s
        while self._win and self._win[0][0] < cut:
            self._win.popleft()

    @property
    def window_n(self) -> int:
        return len(self._win)

    @property
    def offset_s(self) -> float | None:
        """Median skew over the window; None when the window is empty."""
        if not self._win:
            return None
        return median(d for _, d in self._win)

    @property
    def healthy(self) -> bool:
        """Unknown is healthy: a venue that never stamps cannot be judged by this check, and
        neither can one that has stamped only a few frames in the window."""
        off = self.offset_s
        return off is None or len(self._win) < self.min_samples or abs(off) <= self.max_skew_s

    def stats(self) -> dict:
        off = self.offset_s
        return {"samples": self.samples, "window_n": len(self._win),
                "offset_s": None if off is None else round(off, 4),
                "worst_s": round(self.worst_s, 4), "healthy": self.healthy}
