#!/usr/bin/env python3
"""RiskClearance: the token an order adapter must be handed before it may submit.

A bool (`submit_enabled`) can be flipped by any caller; that is the shape the parked Cloudbet
client has. A clearance is minted only by `clear()`, after every fail-closed condition in spec
§13 has been checked in order, it names the reservation it carries, it expires in a few hundred
milliseconds, and it is consumed by exactly one submit. No adapter with submit capability exists
without this gate; that is the reason this node lands before any adapter does.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from kernel.schema import Mode
from nodes.risk.breaker import LossBreaker, RealizedFill
from nodes.risk.kill import KillSwitches
from nodes.risk.ledger import ExposureLedger, Refused, Reservation
from nodes.risk.limits import RiskLimits

_MINT = object()


@dataclass(frozen=True)
class Candidate:
    """What the coordinator asks to be cleared. Legs are (venue, contracts, price)."""
    opportunity_id: str
    event_id: str
    league: str
    legs: tuple[tuple[str, float, float], ...]
    net_profit_usd: float
    locked_return: float
    strategy_version: str
    max_book_age_s: float                 # the oldest book the candidate was priced from

    def per_venue_usd(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for venue, contracts, price in self.legs:
            out[venue] = out.get(venue, 0.0) + contracts * price
        return out


class RiskClearance:
    """Single-use, short-lived, minted only by clear()."""
    __slots__ = ("opportunity_id", "event_id", "mode", "reservation", "limits_sha", "issued_mono",
                 "expires_mono", "hedge_deadline_mono", "max_hedge_submits", "_first_used",
                 "_hedge_used", "_mint")

    def __init__(self, *, opportunity_id: str, event_id: str, mode: Mode, reservation: Reservation,
                 limits_sha: str, issued_mono: float, expires_mono: float,
                 hedge_deadline_mono: float, max_hedge_submits: int = 3, _mint=None):
        if _mint is not _MINT:
            raise TypeError("RiskClearance cannot be constructed directly; call clearance.clear().")
        self.opportunity_id, self.event_id, self.mode = opportunity_id, event_id, mode
        self.reservation, self.limits_sha = reservation, limits_sha
        self.issued_mono, self.expires_mono = issued_mono, expires_mono
        self.hedge_deadline_mono, self.max_hedge_submits = hedge_deadline_mono, max_hedge_submits
        self._first_used, self._hedge_used = False, 0

    def valid(self, now_mono: float | None = None) -> bool:
        """The FIRST leg may still be sent."""
        t = now_mono if now_mono is not None else time.monotonic()
        return not self._first_used and t <= self.expires_mono

    def consume(self, now_mono: float | None = None, *, hedge: bool = False) -> bool:
        """The first leg: exactly once, inside `expires_mono` (a few hundred ms -- a stale decision
        must not be acted on late). Hedge legs: only after the first, at most `max_hedge_submits`,
        inside `hedge_deadline_mono` (the risk limit on unhedged duration). Nothing else."""
        t = now_mono if now_mono is not None else time.monotonic()
        if not hedge:
            if not self.valid(t):
                return False
            self._first_used = True
            return True
        if not self._first_used or t > self.hedge_deadline_mono or self._hedge_used >= self.max_hedge_submits:
            return False
        self._hedge_used += 1
        return True

    @property
    def used(self) -> bool:
        return self._first_used


def clear(cand: Candidate, *, mode: Mode, limits: RiskLimits, ledger: ExposureLedger,
          kill: KillSwitches, breaker: LossBreaker, fills_today: Sequence[RealizedFill],
          clock_healthy: bool, fee_schedules_ok: bool, balances: Mapping[str, float] | None,
          venues_connected: Mapping[str, bool], now_mono: float | None = None,
          now: float | None = None) -> RiskClearance | Refused:
    """Every fail-closed condition, in order. The first failure is the answer."""
    t_mono = now_mono if now_mono is not None else time.monotonic()
    venues = tuple(sorted({v for v, _c, _p in cand.legs}))
    if not mode.executes:
        return Refused("MODE", f"{mode.value} does not execute; nothing to clear")
    hit = kill.active(event_id=cand.event_id, strategy=cand.strategy_version, live=mode.risks_capital, venues=venues)
    if hit:
        return Refused("KILL_SWITCH", f"active: {', '.join(hit)}")
    closed = breaker.evaluate(fills_today, max_daily_loss_usd=limits.max_daily_realized_loss_usd)
    if closed:
        return Refused("BREAKER", closed)
    if not clock_healthy:
        return Refused("CLOCK_UNHEALTHY", "local clock disagrees with a venue's by more than the bound")
    if not fee_schedules_ok:
        return Refused("FEE_SCHEDULE", "a venue's fee schedule is missing or unverified")
    for v in venues:
        if not venues_connected.get(v, False):
            return Refused("VENUE_DISCONNECTED", f"{v} is not connected and synced")
    if cand.max_book_age_s > limits.max_stale_book_age_s:
        return Refused("STALE_BOOK", f"priced from a {cand.max_book_age_s:.2f}s-old book; bound {limits.max_stale_book_age_s}s")
    if cand.net_profit_usd < limits.min_net_profit_usd:
        return Refused("MIN_PROFIT", f"{cand.net_profit_usd:.2f} < {limits.min_net_profit_usd:.2f}")
    if cand.locked_return < limits.min_locked_return:
        return Refused("MIN_RETURN", f"{cand.locked_return:.4f} < {limits.min_locked_return:.4f}")
    need = cand.per_venue_usd()
    if mode.sends_real_orders:
        if balances is None:
            return Refused("BALANCE_UNCONFIRMED", "venue balances could not be confirmed")
        for v, usd in need.items():
            if balances.get(v, 0.0) < usd:
                return Refused("BALANCE", f"{v}: need {usd:.2f}, have {balances.get(v, 0.0):.2f}")
    res = ledger.reserve(event_id=cand.event_id, league=cand.league, per_venue_usd=need, limits=limits,
                         opportunity_id=cand.opportunity_id, now=now)
    if isinstance(res, Refused):
        return res
    return RiskClearance(opportunity_id=cand.opportunity_id, event_id=cand.event_id, mode=mode,
                         reservation=res, limits_sha=limits.sha, issued_mono=t_mono,
                         expires_mono=t_mono + limits.clearance_ttl_ms / 1000.0,
                         hedge_deadline_mono=t_mono + limits.max_hedge_latency_ms / 1000.0, _mint=_MINT)
