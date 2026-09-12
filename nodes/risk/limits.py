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
class ProtectLimits:
    """[protect]: the hedge protection layer's bounds (2026-09-08). Every field has a default so
    a limits file from before the section still loads; the sha moves either way."""
    hedge_protect_window_s: float = 30.0
    unwind_reserve_s: float = 10.0
    max_protect_loss_usd: float = 2.50
    max_protect_loss_per_contract_usd: float = 0.10
    max_protect_submits: int = 12
    protect_resubmit_ms: int = 400
    unwind_enabled: bool = False
    protect_auto: bool = False
    protect_kill_on_failure: bool = True
    protect_dust_contracts: float = 1.0
    guard_period_s: float = 30.0
    #: L76 (2026-09-12): a position the layer left naked is re-run every `protect_retry_s` for
    #: `protect_fast_window_s` after the failure, instead of once per guard pass. 0 disables.
    protect_retry_s: float = 3.0
    protect_fast_window_s: float = 60.0
    #: L85 (2026-09-12): how long the entry check's hedge-book reading may still be used to skip a
    #: walked send it says will miss. Leg A's ack and settle sit between the two (0.4-1.3 s on the
    #: live covers), so this only has to outlast that; past it the layer reads its own book as
    #: before. 0 disables the skip.
    entry_book_trust_s: float = 2.0


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
    max_stale_book_age_s: float
    min_net_profit_usd: float
    min_locked_return: float
    clearance_ttl_ms: int
    sha: str                      # of the file bytes these were read from
    max_hedge_submits: int = 3
    protect: ProtectLimits = ProtectLimits()

    def venue_cap(self, venue: str) -> float:
        """A venue with no cap has a cap of zero. Absent is not unlimited."""
        return float(self.per_venue_usd.get(venue, 0.0))

    def league_cap(self, league: str) -> float:
        return float(self.per_league_usd.get(league, 0.0))


def load_limits(path: Path | str = LIMITS_PATH) -> RiskLimits:
    raw = Path(path).read_bytes()
    d = tomllib.loads(raw.decode("utf-8"))
    cap, ev, loss, ex = d["capital"], d["events"], d["loss"], d["execution"]
    pr = d.get("protect") or {}
    protect = ProtectLimits(
        hedge_protect_window_s=float(pr.get("hedge_protect_window_s", 30.0)),
        unwind_reserve_s=float(pr.get("unwind_reserve_s", 10.0)),
        max_protect_loss_usd=float(pr.get("max_protect_loss_usd", 2.50)),
        max_protect_loss_per_contract_usd=float(pr.get("max_protect_loss_per_contract_usd", 0.10)),
        max_protect_submits=int(pr.get("max_protect_submits", 12)),
        protect_resubmit_ms=int(pr.get("protect_resubmit_ms", 400)),
        unwind_enabled=bool(pr.get("unwind_enabled", False)),
        protect_auto=bool(pr.get("protect_auto", False)),
        protect_kill_on_failure=bool(pr.get("protect_kill_on_failure", True)),
        protect_dust_contracts=float(pr.get("protect_dust_contracts", 1.0)),
        guard_period_s=float(pr.get("guard_period_s", 30.0)),
        protect_retry_s=float(pr.get("protect_retry_s", 3.0)),
        protect_fast_window_s=float(pr.get("protect_fast_window_s", 60.0)),
        entry_book_trust_s=float(pr.get("entry_book_trust_s", 2.0)))
    return RiskLimits(
        max_total_usd=float(cap["max_total_usd"]), max_unresolved_usd=float(cap["max_unresolved_usd"]),
        per_venue_usd={k: float(v) for k, v in cap["per_venue_usd"].items()},
        max_simultaneous_events=int(ev["max_simultaneous"]),
        max_event_notional_usd=float(ev["max_event_notional_usd"]),
        per_league_usd={k: float(v) for k, v in ev["per_league_usd"].items()},
        max_daily_realized_loss_usd=float(loss["max_daily_realized_usd"]),
        max_hedge_latency_ms=int(ex["max_hedge_latency_ms"]),
        max_unhedged_contracts=float(ex["max_unhedged_contracts"]),
        max_stale_book_age_s=float(ex["max_stale_book_age_s"]),
        min_net_profit_usd=float(ex["min_net_profit_usd"]),
        min_locked_return=float(ex["min_locked_return"]),
        clearance_ttl_ms=int(ex["clearance_ttl_ms"]),
        sha=hashlib.sha256(raw).hexdigest()[:16],
        max_hedge_submits=int(ex.get("max_hedge_submits", 3)),
        protect=protect)
