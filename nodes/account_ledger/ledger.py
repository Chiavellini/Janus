#!/usr/bin/env python3
"""Cent-exact, source-line accounting for venue statements.

This node deliberately does not infer funding, fees, or missing trades from balances. Every row
must be a venue statement line (or an explicitly named independent control), amounts are parsed
from decimal strings into integer cents, and duplicate source ids are refused.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping


class Classification(str, Enum):
    REALIZED = "REALIZED"
    OPEN_POSITION = "OPEN_POSITION"
    FUNDING = "FUNDING"


def cents(value: object) -> int:
    """Parse a dollar decimal with no sub-cent component. Binary floats are never accepted."""
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("amount_usd must be a decimal string, never a binary float")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid amount_usd {value!r}") from exc
    if not amount.is_finite() or amount != amount.quantize(Decimal("0.01")):
        raise ValueError(f"amount_usd must resolve to an exact cent: {value!r}")
    return int(amount * 100)


def dollars(value_cents: int) -> str:
    sign = "-" if value_cents < 0 else ""
    whole, part = divmod(abs(value_cents), 100)
    return f"{sign}{whole}.{part:02d}"


@dataclass(frozen=True)
class Activity:
    source_id: str
    venue: str
    description: str
    classification: Classification
    amount_cents: int
    status: str = ""

    @classmethod
    def from_mapping(cls, row: Mapping[str, object]) -> "Activity":
        required = ("source_id", "venue", "description", "classification", "amount_usd")
        missing = [key for key in required if row.get(key) in (None, "")]
        if missing:
            raise ValueError(f"activity missing required fields: {', '.join(missing)}")
        return cls(str(row["source_id"]), str(row["venue"]), str(row["description"]),
                   Classification(str(row["classification"])), cents(row["amount_usd"]),
                   str(row.get("status") or ""))


@dataclass(frozen=True)
class Summary:
    realized_cents: int
    open_position_cents: int
    funding_cents: int
    realized_by_venue: dict[str, int]

    @property
    def trading_cash_flow_cents(self) -> int:
        return self.realized_cents + self.open_position_cents

    def as_dict(self) -> dict:
        return {
            "realized_pnl_usd": dollars(self.realized_cents),
            "open_position_cash_flow_usd": dollars(self.open_position_cents),
            "trading_cash_flow_usd": dollars(self.trading_cash_flow_cents),
            "external_funding_usd": dollars(self.funding_cents),
            "realized_by_venue_usd": {venue: dollars(amount)
                                       for venue, amount in sorted(self.realized_by_venue.items())},
        }


def summarize(rows: Iterable[Activity]) -> Summary:
    seen: set[str] = set()
    realized = open_position = funding = 0
    by_venue: dict[str, int] = {}
    for row in rows:
        if row.source_id in seen:
            raise ValueError(f"duplicate source_id: {row.source_id}")
        seen.add(row.source_id)
        if row.classification is Classification.REALIZED:
            realized += row.amount_cents
            by_venue[row.venue] = by_venue.get(row.venue, 0) + row.amount_cents
        elif row.classification is Classification.OPEN_POSITION:
            open_position += row.amount_cents
        elif row.classification is Classification.FUNDING:
            funding += row.amount_cents
    return Summary(realized, open_position, funding, by_venue)


def load_activities(path: Path) -> tuple[list[Activity], dict]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict) or not isinstance(payload.get("activities"), list):
        raise ValueError("source must be an object with an activities list")
    rows = [Activity.from_mapping(row) for row in payload["activities"]]
    summarize(rows)  # duplicate-id and classification validation at the boundary
    return rows, payload
