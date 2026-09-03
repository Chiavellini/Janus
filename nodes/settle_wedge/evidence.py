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
_L30 = "research/sports/2026-09-03_nfl-settlement-wedge-rates-v2/spec.yaml"
_L33 = "research/sports/2026-09-03_soccer-settlement-wedge-rates/spec.yaml"
_L32 = "research/sports/2026-09-03_cfb-settlement-wedge-rates/spec.yaml"
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
    "nfl.postponed_gt48h_rate": Evidence(
        "nfl.postponed_gt48h_rate", 0.001515, 2640,
        "nflverse games.csv REG rows (denominator) + cited schedule-change table (numerator), seasons "
        "2015-2019 and 2021-2025; 2020 excluded by the operator's decision", "2026-09-03", _L30,
        "4 of 2640 games started more than 48 h after the original kickoff (2017 TB@MIA, 2021 LV@CLE at 48.5 h, "
        "SEA@LA, WAS@PHI); strict >48.0 h; completeness gate over Tue/Wed/Fri games passed. With 2020 the "
        "count would be far higher: the exclusion is stated, not hidden."),
    "nfl.cancelled_rate": Evidence(
        "nfl.cancelled_rate", 0.000379, 2640,
        "nflverse games.csv REG rows (denominator) + cited schedule-change table (numerator), seasons "
        "2015-2019 and 2021-2025", "2026-09-03", _L30,
        "1 of 2640: 2022 week 17 BUF@CIN, suspended in the first quarter and declared cancelled; the game is "
        "absent from nflverse and added to the denominator."),
    "soccer.bun.postponed_gt48h_rate": Evidence(
        "soccer.bun.postponed_gt48h_rate", 0.003268, 1224,
        "openfootball Bundesliga season files 2021-22..2024-25 (frozen under the row), round-window proxy", "2026-09-03", _L33,
        "PROXY: 4 of 1224 matches were played more than 48 h after their round's core window. "
        "It counts every such move, including cup-related moves announced weeks ahead (not postponements at the "
        "venue's listing time), and misses every move inside the window; a FLOOR on the second count, an over-count "
        "on the first. Replace with a forward measurement of true original dates (DESIGN.md)."),
    "soccer.bun.cancelled_rate": Evidence(
        "soccer.bun.cancelled_rate", 0.000000, 1224,
        "openfootball Bundesliga season files 2021-22..2024-25: scheduled N(N-1) minus played", "2026-09-03", _L33,
        "0 of 1224: every season parsed to exactly N(N-1) matches. Registered verbatim; the rule-of-three bound at "
        "this n is ~0.002 and a re-measurement over more seasons is the honest way to raise it."),
    "soccer.epl.postponed_gt48h_rate": Evidence(
        "soccer.epl.postponed_gt48h_rate", 0.038158, 1520,
        "openfootball Premier League season files 2021-22..2024-25 (frozen under the row), round-window proxy", "2026-09-03", _L33,
        "PROXY: 58 of 1520 matches were played more than 48 h after their round's core window. "
        "It counts every such move, including cup-related moves announced weeks ahead (not postponements at the "
        "venue's listing time), and misses every move inside the window; a FLOOR on the second count, an over-count "
        "on the first. Replace with a forward measurement of true original dates (DESIGN.md)."),
    "soccer.epl.cancelled_rate": Evidence(
        "soccer.epl.cancelled_rate", 0.000000, 1520,
        "openfootball Premier League season files 2021-22..2024-25: scheduled N(N-1) minus played", "2026-09-03", _L33,
        "0 of 1520: every season parsed to exactly N(N-1) matches. Registered verbatim; the rule-of-three bound at "
        "this n is ~0.002 and a re-measurement over more seasons is the honest way to raise it."),
    "soccer.lal.postponed_gt48h_rate": Evidence(
        "soccer.lal.postponed_gt48h_rate", 0.013816, 1520,
        "openfootball La Liga season files 2021-22..2024-25 (frozen under the row), round-window proxy", "2026-09-03", _L33,
        "PROXY: 21 of 1520 matches were played more than 48 h after their round's core window. "
        "It counts every such move, including cup-related moves announced weeks ahead (not postponements at the "
        "venue's listing time), and misses every move inside the window; a FLOOR on the second count, an over-count "
        "on the first. Replace with a forward measurement of true original dates (DESIGN.md)."),
    "soccer.lal.cancelled_rate": Evidence(
        "soccer.lal.cancelled_rate", 0.000000, 1520,
        "openfootball La Liga season files 2021-22..2024-25: scheduled N(N-1) minus played", "2026-09-03", _L33,
        "0 of 1520: every season parsed to exactly N(N-1) matches. Registered verbatim; the rule-of-three bound at "
        "this n is ~0.002 and a re-measurement over more seasons is the honest way to raise it."),
    "cfb.postponed_gt48h_rate": Evidence(
        "cfb.postponed_gt48h_rate", 0.000630, 9529,
        "ESPN college-football scoreboard, FBS + FCS, seasons 2019 and 2021-2025 (denominator) + cited "
        "schedule-change table (numerator); 2020 excluded by the same decision as the NFL row", "2026-09-03", _L32,
        "6 of 9529 games started more than 48 h late (FBS 3, FCS 3: hurricanes Ida, Ian, Helene, a snowstorm, "
        "two deaths in a program). FLOOR for FCS: the table rests on press coverage and FCS moves are poorly indexed; "
        "FBS is near-complete (FBS-only rate 0.000552)."),
    "cfb.cancelled_rate": Evidence(
        "cfb.cancelled_rate", 0.001784, 9529,
        "ESPN college-football scoreboard, FBS + FCS, seasons 2019 and 2021-2025 + cited schedule-change table", "2026-09-03", _L32,
        "17 of 9529: 13 FCS and 4 FBS games cancelled, forfeited or ruled no contest (hurricanes, two campus "
        "shootings, a player's death, a lightning no-contest). FLOOR for FCS for the same reason as above."),
}


def rates(overrides: Mapping[str, float] | None = None) -> dict[str, float]:
    out = {k: e.value for k, e in EVIDENCE.items()}
    if overrides:
        out.update(overrides)
    return out
