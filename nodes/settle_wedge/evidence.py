#!/usr/bin/env python3
"""Measured probabilities the bounded settlement dimensions price with. Nothing here is a guess.

A BOUNDED dimension (the venues differ, but the difference has a bounded cost) is priced as
probability x worst-case loss. The probability must come from a registered measurement: a
`research/` row with a spec, a results file and a verdict. A key that is absent here makes the
dimension UNKNOWN, and UNKNOWN blocks (spec §5: unknown rules are a hard BLOCKED_RULES state,
never zero risk). Filling a key without a research reference is the one thing this file forbids.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Evidence:
    key: str
    value: float
    n: int
    source: str
    retrieved_at: str
    research_ref: str
    note: str = ""

    def __post_init__(self) -> None:
        if not self.research_ref.startswith("research/"):
            raise ValueError(f"evidence {self.key!r} must cite a research/ row, got {self.research_ref!r}")
        if not (0.0 <= self.value <= 1.0):
            raise ValueError(f"evidence {self.key!r} is a probability; got {self.value}")


#: key -> Evidence. Filled ONLY from a registered measurement. See research/sports/.
_L26 = "research/sports/2026-09-02_mlb-settlement-wedge-rates/spec.yaml"
EVIDENCE: dict[str, Evidence] = {
    "mlb.postponed_gt2d_rate": Evidence(
        "mlb.postponed_gt2d_rate", 0.004762, 2100,
        "MLB Stats API schedule, 2026 regular season 2026-03-25..2026-09-02", "2026-09-03", _L26,
        "10 of 2100 games postponed and made up more than two days later; exact "
        "(every postponement carried a reschedule date). All-cause postponement rate 0.0129."),
    "mlb.cancelled_rate": Evidence(
        "mlb.cancelled_rate", 0.000000, 2100,
        "MLB Stats API schedule, 2026 regular season 2026-03-25..2026-09-02", "2026-09-03", _L26,
        "0 cancellations in 2100 games. Registered verbatim per the spec; the rule-of-three "
        "upper bound at this n is ~0.0014, and a re-measurement over more seasons is the honest way to "
        "raise it, not an edit here."),
}


def rates(overrides: Mapping[str, float] | None = None) -> dict[str, float]:
    out = {k: e.value for k, e in EVIDENCE.items()}
    if overrides:
        out.update(overrides)
    return out
