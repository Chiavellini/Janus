#!/usr/bin/env python3
"""The global limits, loaded from a checked-in file whose hash is pinned into every clearance.

Spec §13: maximum total capital, per-venue capital, simultaneous events, per-event notional,
per-league exposure, daily loss, unresolved exposure, hedge latency, stale-book age. They live in
`limits.toml` beside this file so a change is a commit, and the sha of the bytes actually loaded
travels with every `RiskClearance` and with the arming override -- a limit cannot move under a
running arm without the pin moving too.
"""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

LIMITS_PATH = Path(__file__).resolve().parent / "limits.toml"


@dataclass(frozen=True)
class RiskLimits:
    max_total_usd: float
    max_unresolved_usd: float
    per_venue_usd: Mapping[str, float]
    max_simultaneous_events: int
    max_event_notional_usd: float
    per_league_usd: Mapping[str, float]
    max_daily_realized_loss_usd: float
    max_hedge_latency_ms: int
    max_unhedged_contracts: float
    max_unhedged_duration_ms: int
    max_stale_book_age_s: float
    min_net_profit_usd: float
    min_locked_return: float
    clearance_ttl_ms: int
    sha: str                      # of the file bytes these were read from

    def venue_cap(self, venue: str) -> float:
        """A venue with no cap has a cap of zero. Absent is not unlimited."""
        return float(self.per_venue_usd.get(venue, 0.0))

    def league_cap(self, league: str) -> float:
        return float(self.per_league_usd.get(league, 0.0))


def load_limits(path: Path | str = LIMITS_PATH) -> RiskLimits:
    raw = Path(path).read_bytes()
    d = tomllib.loads(raw.decode("utf-8"))
    cap, ev, loss, ex = d["capital"], d["events"], d["loss"], d["execution"]
    return RiskLimits(
        max_total_usd=float(cap["max_total_usd"]), max_unresolved_usd=float(cap["max_unresolved_usd"]),
        per_venue_usd={k: float(v) for k, v in cap["per_venue_usd"].items()},
        max_simultaneous_events=int(ev["max_simultaneous"]),
        max_event_notional_usd=float(ev["max_event_notional_usd"]),
        per_league_usd={k: float(v) for k, v in ev["per_league_usd"].items()},
        max_daily_realized_loss_usd=float(loss["max_daily_realized_usd"]),
        max_hedge_latency_ms=int(ex["max_hedge_latency_ms"]),
        max_unhedged_contracts=float(ex["max_unhedged_contracts"]),
        max_unhedged_duration_ms=int(ex["max_unhedged_duration_ms"]),
        max_stale_book_age_s=float(ex["max_stale_book_age_s"]),
        min_net_profit_usd=float(ex["min_net_profit_usd"]),
        min_locked_return=float(ex["min_locked_return"]),
        clearance_ttl_ms=int(ex["clearance_ttl_ms"]),
        sha=hashlib.sha256(raw).hexdigest()[:16])
