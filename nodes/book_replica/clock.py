#!/usr/bin/env python3
"""Local clock versus the venue's: the one health check a book cannot make for itself.

Every freshness bound in the system is `now - updated_utc`. If the local wall clock steps, every
book is simultaneously "stale" or "fresh" by the size of the step, and the cover engine prices
on fiction either way. Both venues stamp their frames (Kalshi deltas `ts_ms`, Polymarket events
`timestamp`), so the offset `received_utc - server_utc` is observable on every message.

Measured 2026-09-02 on both sockets: the venue stamp runs 30-70 ms AHEAD of local receipt (the
venue stamps late, or the clocks differ by that much). That is the normal band. A skew of seconds
is a fault, and the supervisor halts pricing on it (spec §13: fail closed on an unhealthy clock).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ClockMonitor:
    """EWMA of (received - server) per socket. Pure; the stream feeds it."""
    alpha: float = 0.05
    max_skew_s: float = 5.0
    samples: int = 0
    offset_s: float | None = None
    worst_s: float = 0.0

    def observe(self, received_utc: float, server_utc: float | None) -> None:
        if server_utc is None:
            return
        d = received_utc - server_utc
        self.samples += 1
        self.offset_s = d if self.offset_s is None else (1 - self.alpha) * self.offset_s + self.alpha * d
        if abs(d) > abs(self.worst_s):
            self.worst_s = d

    @property
    def healthy(self) -> bool:
        """Unknown is healthy: a venue that never stamps cannot be judged by this check."""
        return self.offset_s is None or abs(self.offset_s) <= self.max_skew_s

    def stats(self) -> dict:
        return {"samples": self.samples,
                "offset_s": None if self.offset_s is None else round(self.offset_s, 4),
                "worst_s": round(self.worst_s, 4), "healthy": self.healthy}
