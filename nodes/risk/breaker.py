#!/usr/bin/env python3
"""The latching daily realized-loss breaker.

Realized PnL for the UTC day is computed from a FIFO of fills. Every fill must be in a terminal,
venue-authoritative state -- FILLED, UNFILLED or REJECTED. An UNCONFIRMED fill makes the day's
PnL UNKNOWN, and unknown fails closed: the breaker refuses to clear anything until the caller
has re-polled the venue (GATE_TO_LIVE: "a FIFO ledger that re-polls unconfirmed fills BEFORE
computing the day's PnL"). Collapsing UNCONFIRMED into UNFILLED overstates PnL and blinds this.

Once latched the breaker stays latched across restarts (its state is a file on the volume) and
also latches the `live` kill switch. Only a human resets it, by name.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from kernel.schema import FillState

from kernel.paths import BREAKER_PATH, guard  # noqa: E402


@dataclass(frozen=True)
class RealizedFill:
    """One venue-authoritative fill outcome, as the reconcile node reports it."""
    fill_id: str
    state: FillState
    realized_usd: float        # signed; 0.0 for UNFILLED/REJECTED
    day: str                   # UTC date "YYYY-MM-DD" the PnL belongs to


def day_of(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).strftime("%Y-%m-%d")


class LossBreaker:
    def __init__(self, path: Path | str = BREAKER_PATH, *, kill=None, enforce_volume: bool = True):
        self.path = Path(path)
        if enforce_volume:
            guard(self.path, "breaker state")
        self.kill = kill
        self.latched: bool = False
        self.latch_reason: str = ""
        self.latched_utc: float | None = None
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            d = json.loads(self.path.read_text() or "{}")
            self.latched = bool(d.get("latched"))
            self.latch_reason = d.get("reason", "")
            self.latched_utc = d.get("latched_utc")

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"latched": self.latched, "reason": self.latch_reason,
                                         "latched_utc": self.latched_utc}) + "\n")

    def day_pnl(self, fills: Sequence[RealizedFill], day: str) -> float | None:
        """Realized PnL for `day`, or None if any fill that day is UNCONFIRMED (unknown = closed)."""
        todays = [f for f in fills if f.day == day]
        if any(f.state is FillState.UNCONFIRMED for f in todays):
            return None
        return sum(f.realized_usd for f in todays if f.state in (FillState.FILLED, FillState.PARTIAL))

    def evaluate(self, fills: Sequence[RealizedFill], *, max_daily_loss_usd: float,
                 day: str | None = None) -> str | None:
        """Latch if the day's realized loss breaches the limit. Returns the reason it is closed
        (already latched, breached now, or PnL unknown), or None if trading may continue."""
        if self.latched:
            return f"BREAKER_LATCHED: {self.latch_reason}"
        d = day or day_of()
        pnl = self.day_pnl(fills, d)
        if pnl is None:
            return "PNL_UNKNOWN: an UNCONFIRMED fill must be re-polled before the day's PnL can be computed"
        if pnl <= -abs(max_daily_loss_usd):
            self.latch(f"daily realized loss {pnl:.2f} USD breached {max_daily_loss_usd:.2f} on {d}")
            return f"BREAKER_LATCHED: {self.latch_reason}"
        return None

    def latch(self, reason: str) -> None:
        self.latched, self.latch_reason, self.latched_utc = True, reason, time.time()
        self._save()
        if self.kill is not None:
            self.kill.latch("live", f"breaker: {reason}")

    def reset(self, *, by: str) -> None:
        """A human decision, recorded by name. Never called from a trading path."""
        if not by:
            raise ValueError("a breaker reset must name who reset it")
        self.latched, self.latch_reason, self.latched_utc = False, "", None
        self._save()
