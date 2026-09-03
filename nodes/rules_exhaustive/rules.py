#!/usr/bin/env python3
"""Proof that an outcome set partitions the sample space. The gate on every cover claim.

A cover is only a cover if the outcome set is PROVEN exhaustive. `nodes/cover/cover.py` says so in
its module docstring and then accepts a caller-supplied `bool`, and `grids/live_sports` passes
`True` for every league it is handed -- including 3-way EPL and tie-capable NFL. An EPL match at
home 0.46 / away 0.30 / draw 0.24 prices as a 0.76 "cover" returning +31%, which is not arbitrage
but a bet the match is not drawn.

The fix is a TYPE, not a check. `ExhaustiveOutcomeSet` can only be minted by `prove()`, and `prove()`
requires a rule carrying a CITATION. A league with no citation cannot produce the token, so it
cannot reach the pricer at all. Adding a league is deliberately annoying: you must name the rule
that makes its outcome set complete.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

_MINT = object()


@dataclass(frozen=True)
class ExhaustiveOutcomeSet:
    """PROOF, not an assertion. Only `prove()` can construct one."""
    league: str
    market_type: str
    period: str
    outcome_ids: tuple[str, ...]
    rule_id: str
    citation: str
    _mint: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._mint is not _MINT:
            raise TypeError(
                "ExhaustiveOutcomeSet cannot be constructed directly; call rules.prove(). "
                "A cover priced against a forged proof is the +31% EPL bug.")


@dataclass(frozen=True)
class NotExhaustive:
    """Why the outcome set is not proven complete. A BLOCK, never a zero-risk shrug."""
    code: str
    league: str
    market_type: str
    period: str
    detail: str
    context: Mapping[str, object] = field(default_factory=dict)


#: (league, market_type, period) -> (n_outcomes, rule_id, citation | None)
#: A None citation means the rule is ASSERTED, not proven -- `prove()` then BLOCKS. That is the
#: honest state for a league nobody has actually checked, and it is how nfl/wnba sit today.
RULES: dict[tuple[str, str, str], tuple[int, str, str | None]] = {
    ("mlb", "moneyline", "game"): (
        2, "mlb_no_draw",
        "MLB Official Baseball Rules 7.01: a regulation game continues in extra innings until one "
        "side leads after a completed inning. No regulation tie exists, so {home, away} is complete."),
    ("nba", "moneyline", "game"): (
        2, "nba_no_draw",
        "NBA Rule 5 Section I(b): overtime periods are played until a winner emerges. "
        "{home, away} is complete."),
    ("wnba", "moneyline", "game"): (
        2, "wnba_no_draw",
        "WNBA Rule 5: overtime periods until a winner. {home, away} is complete."),
    ("nhl", "moneyline", "game"): (
        2, "nhl_ot_shootout_no_draw",
        "NHL Rules 84-85: regular-season games tied after regulation go to 3-on-3 overtime and "
        "then a shootout, so a winner is always produced. NOTE: this citation covers the FULL-GAME "
        "period only. NHL 'regulation time' 3-way markets are a different period key and are NOT "
        "covered by this rule."),

    # ---- HONEST GAPS: rule stated, citation absent, therefore BLOCKED ----
    ("nfl", "moneyline", "game"): (
        2, "nfl_tie_pays_half_each_side",
        "NFL Rule 16 Section 1: a regular-season game tied after one 10-minute overtime period ends in a "
        "tie. {home, away} is therefore NOT a partition of the game's outcomes; it is complete as a COVER "
        "because both venues pay each side $0.50 on a tie (Kalshi KXNFLGAME rules_secondary: 'resolve to "
        "$0.50 for each team'; Polymarket NFL game description: 'ends in a tie ... resolve 50-50', both "
        "harvested 2026-09-03 and pinned as templates in nodes/settle_wedge/policy.py), so one contract of "
        "each side receives exactly $1.00 in every terminal state. Valid ONLY paired with a venue pair whose "
        "settle_wedge verdict on 'tie' is SAME."),
}

#: Three-way soccer. IFAB Laws of the Game 2025/26, Law 10.1 (Determining the outcome of a match):
#: "The team scoring the greater number of goals is the winner. If both teams score no goals or an
#: equal number of goals the match is drawn." {home, draw, away} therefore partitions the result at
#: full time. Both venues' game markets settle on exactly that period and no other -- Kalshi
#: KX*GAME rules: "after 90 minutes plus stoppage time (does not include extra time or penalties)";
#: Polymarket: "refers only to the outcome within the first 90 minutes of regular play plus
#: stoppage time" -- harvested 2026-09-03 and pinned as templates in nodes/settle_wedge/policy.py.
#: A two-leg cover pays nothing on a draw; only the three-leg cover is complete. Valid ONLY paired
#: with a settle_wedge verdict of SAME on 'overtime' (the period) for the pair.
_SOCCER_3WAY = (
    3, "soccer_3way_full_time",
    "IFAB Laws of the Game 2025/26, Law 10.1: the team scoring more goals wins; equal goals is a draw. "
    "{home, draw, away} partitions the full-time result. Both venues settle their game markets on 90 minutes "
    "plus stoppage time, extra time and penalties excluded (Kalshi KX*GAME rules_primary; Polymarket market "
    "description), harvested 2026-09-03 and pinned in nodes/settle_wedge/policy.py. A cover must hold all three.")
for _lg in ("epl", "lal", "bun", "mls", "ucl"):   # ucl: rule ready, league not yet registered (entities)
    RULES[(_lg, "moneyline", "game")] = _SOCCER_3WAY


def prove(league: str, market_type: str, period: str,
          outcome_ids) -> ExhaustiveOutcomeSet | NotExhaustive:
    """The ONLY way to obtain an ExhaustiveOutcomeSet."""
    key = (league, market_type, period)
    spec = RULES.get(key)
    if spec is None:
        return NotExhaustive("NO_RULE_FOR_LEAGUE", league, market_type, period,
                             f"no exhaustiveness rule registered for {league}/{market_type}/{period}")
    n, rule_id, citation = spec
    if citation is None:
        return NotExhaustive("RULE_UNCITED", league, market_type, period,
                             f"rule {rule_id!r} is asserted but carries no citation; "
                             "exhaustiveness is unproven", {"rule_id": rule_id})
    ids = tuple(sorted(outcome_ids))
    if len(set(ids)) != len(ids):
        return NotExhaustive("DUPLICATE_OUTCOME", league, market_type, period,
                             f"duplicate outcome ids: {ids}", {"outcome_ids": list(ids)})
    if len(ids) != n:
        return NotExhaustive("OUTCOME_COUNT_MISMATCH", league, market_type, period,
                             f"{league}/{market_type}/{period} requires {n} outcomes under "
                             f"{rule_id!r}, got {len(ids)}",
                             {"outcome_ids": list(ids), "required": n, "rule_id": rule_id})
    return ExhaustiveOutcomeSet(league, market_type, period, ids, rule_id, citation, _mint=_MINT)
