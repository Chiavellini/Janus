#!/usr/bin/env python3
"""Capital reservation and cross-venue exposure, accounted in ONE place.

GATE_TO_LIVE cross-venue additions #3: net exposure is accounted once, not per venue. A
reservation is taken BEFORE any leg is submitted and released only when both venues have
reconciled (spec §10, §11). Until then it is UNRESOLVED exposure, capped separately, because an
unhedged leg is a directional position that was never authorised.

Reservations are journaled to the store when one is attached, and open ones are reloaded at
start: single-flight per event survives a restart.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Mapping

from nodes.risk.limits import RiskLimits

LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS capital_reservations(
  reservation_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, league TEXT NOT NULL,
  per_venue_json TEXT NOT NULL, opportunity_id TEXT, created_utc REAL NOT NULL,
  released_utc REAL, release_reason TEXT);
CREATE INDEX IF NOT EXISTS capital_reservations_open ON capital_reservations(released_utc);
"""


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    event_id: str
    league: str
    per_venue_usd: Mapping[str, float]
    opportunity_id: str | None
    created_utc: float

    @property
    def total_usd(self) -> float:
        return float(sum(self.per_venue_usd.values()))


@dataclass(frozen=True)
class Refused:
    code: str
    detail: str


@dataclass
class ExposureLedger:
    store: object | None = None
    open: dict[str, Reservation] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.store is not None:
            self.store.ensure_ddl(LEDGER_DDL)
            for row in self.store.con.execute(
                    "SELECT reservation_id, event_id, league, per_venue_json, opportunity_id, created_utc "
                    "FROM capital_reservations WHERE released_utc IS NULL").fetchall():
                r = Reservation(row[0], row[1], row[2], json.loads(row[3]), row[4], row[5])
                self.open[r.reservation_id] = r

    # ── the picture ──────────────────────────────────────────────────────
    def total_usd(self) -> float:
        return sum(r.total_usd for r in self.open.values())

    def venue_usd(self, venue: str) -> float:
        return sum(float(r.per_venue_usd.get(venue, 0.0)) for r in self.open.values())

    def league_usd(self, league: str) -> float:
        return sum(r.total_usd for r in self.open.values() if r.league == league)

    def event_usd(self, event_id: str) -> float:
        return sum(r.total_usd for r in self.open.values() if r.event_id == event_id)

    def events(self) -> set[str]:
        return {r.event_id for r in self.open.values()}

    def has_event(self, event_id: str) -> bool:
        return any(r.event_id == event_id for r in self.open.values())

    # ── reserve / release ────────────────────────────────────────────────
    def reserve(self, *, event_id: str, league: str, per_venue_usd: Mapping[str, float],
                limits: RiskLimits, opportunity_id: str | None = None,
                now: float | None = None) -> Reservation | Refused:
        """Every limit is checked against the picture INCLUDING this request. Any breach refuses;
        nothing is partially reserved."""
        add = {k: float(v) for k, v in per_venue_usd.items() if float(v) > 0}
        if not add:
            return Refused("EMPTY_RESERVATION", "nothing to reserve")
        total = sum(add.values())
        if self.has_event(event_id):
            return Refused("EVENT_IN_FLIGHT", f"{event_id} already has an open reservation (single-flight)")
        if len(self.events()) + 1 > limits.max_simultaneous_events:
            return Refused("MAX_EVENTS", f"{len(self.events())} events open; limit {limits.max_simultaneous_events}")
        if total > limits.max_event_notional_usd:
            return Refused("EVENT_NOTIONAL", f"{total:.2f} > per-event {limits.max_event_notional_usd:.2f}")
        if self.league_usd(league) + total > limits.league_cap(league):
            return Refused("LEAGUE_EXPOSURE", f"{league}: {self.league_usd(league):.2f} + {total:.2f} > {limits.league_cap(league):.2f}")
        for v, usd in add.items():
            if self.venue_usd(v) + usd > limits.venue_cap(v):
                return Refused("VENUE_CAPITAL", f"{v}: {self.venue_usd(v):.2f} + {usd:.2f} > {limits.venue_cap(v):.2f}")
        if self.total_usd() + total > limits.max_total_usd:
            return Refused("TOTAL_CAPITAL", f"{self.total_usd():.2f} + {total:.2f} > {limits.max_total_usd:.2f}")
        if self.total_usd() + total > limits.max_unresolved_usd:
            return Refused("UNRESOLVED_EXPOSURE", f"{self.total_usd():.2f} + {total:.2f} > {limits.max_unresolved_usd:.2f}")
        r = Reservation(uuid.uuid4().hex, event_id, league, add, opportunity_id, now or time.time())
        self.open[r.reservation_id] = r
        if self.store is not None:
            self.store.con.execute(
                "INSERT INTO capital_reservations(reservation_id, event_id, league, per_venue_json, "
                "opportunity_id, created_utc) VALUES(?,?,?,?,?,?)",
                (r.reservation_id, event_id, league, json.dumps(add, sort_keys=True), opportunity_id, r.created_utc))
        return r

    def release(self, reservation_id: str, *, reason: str, now: float | None = None) -> bool:
        """Only after BOTH venues have reconciled. The caller says why; the row keeps it."""
        r = self.open.pop(reservation_id, None)
        if r is None:
            return False
        if self.store is not None:
            self.store.con.execute("UPDATE capital_reservations SET released_utc=?, release_reason=? "
                                   "WHERE reservation_id=?", (now or time.time(), reason, reservation_id))
        return True

    def oldest_open_age_s(self, now: float | None = None) -> float | None:
        if not self.open:
            return None
        t = now or time.time()
        return max(t - r.created_utc for r in self.open.values())
