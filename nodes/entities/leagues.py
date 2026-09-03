#!/usr/bin/env python3
"""The league registry: ONE table for what a competition is called on each venue and how it is anchored.

Until 2026-09-03 the six leagues were spelled out in three places (`entities/seed.py`,
`schedule_espn/espn.py`, `grids/live_stream/grid.py`) and adding a competition meant editing all
three and forgetting one. Every consumer reads this table now. Adding a competition is one row
here -- and that row buys NOTHING on its own: a league trades only when `nodes/rules_exhaustive`
carries a cited rule for it and `nodes/settle_wedge` carries reviewed templates for both venues.
`enablement()` says which of those each row still lacks; the grid's default league list is the
rows that lack none.

`anchor` is how the canonical key is built: `espn` (the ESPN schedule is the external anchor,
`nodes/schedule_espn`) or `venue_structured` (no third-party schedule; participants and start from
both venues' own structured fields, a weaker provenance grade). `outcomes` is the cardinality of
the game market (2, or 3 for soccer's home/draw/away). Nothing here is a status; status is
`enablement()`, computed from the rule and template registries at call time.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class League:
    code: str
    name: str
    kalshi_series: str            # the game-level series, e.g. KXMLBGAME
    pm_tag: str                   # Gamma tag slug
    pm_prefix: str                # the full-game slug prefix: {prefix}-{away}-{home}-{date}
    espn: tuple[str, str] | None  # ESPN (sport, league) path pair; None for venue_structured
    outcomes: int = 2
    anchor: str = "espn"
    pm_sport: str | None = None   # Gamma /sports `sport` code when it differs from pm_prefix
    #: ESPN scoreboard `groups` to query (college football: 80 = FBS, 81 = FCS); () = the default feed.
    espn_groups: tuple[str, ...] = ()


LEAGUES: dict[str, League] = {
    "mlb":  League("mlb", "MLB", "KXMLBGAME", "mlb", "mlb", ("baseball", "mlb")),
    "nfl":  League("nfl", "NFL", "KXNFLGAME", "nfl", "nfl", ("football", "nfl")),
    "nba":  League("nba", "NBA", "KXNBAGAME", "nba", "nba", ("basketball", "nba")),
    "wnba": League("wnba", "WNBA", "KXWNBAGAME", "wnba", "wnba", ("basketball", "wnba")),
    "nhl":  League("nhl", "NHL", "KXNHLGAME", "nhl", "nhl", ("hockey", "nhl")),
    "epl":  League("epl", "Premier League", "KXEPLGAME", "epl", "epl", ("soccer", "eng.1"), outcomes=3),
    # Three-way soccer, added 2026-09-03 from the L28 census (La Liga ranked first in the window).
    "lal":  League("lal", "La Liga", "KXLALIGAGAME", "la-liga", "lal", ("soccer", "esp.1"), outcomes=3),
    "bun":  League("bun", "Bundesliga", "KXBUNDESLIGAGAME", "bundesliga", "bun", ("soccer", "ger.1"), outcomes=3),
    "mls":  League("mls", "MLS", "KXMLSGAME", "mls", "mls", ("soccer", "usa.1"), outcomes=3),
    # College football, added 2026-09-03 from the L28 census (39 co-listed games in the first window).
    # Kalshi lists FBS, FCS and Division II games; ESPN's default scoreboard is FBS, so FCS is asked
    # for explicitly and Division II stays unmatched (blocked, by name) until it is worth a group.
    "cfb":  League("cfb", "College Football", "KXNCAAFGAME", "cfb", "cfb", ("football", "college-football"),
                   espn_groups=("80", "81")),
    # Not yet: UCL. Entities are keyed per league (lal:esp.real_madrid) and a club plays in its domestic
    # league AND the Champions League, so its one Kalshi team id would map to two entities and the
    # xref table refuses the collision. A club must become one entity across competitions first.
}

SOCCER = tuple(c for c, l in LEAGUES.items() if l.outcomes == 3)


def league_for_series(series_ticker: str) -> str | None:
    return next((c for c, l in LEAGUES.items() if l.kalshi_series == series_ticker), None)


def league_for_prefix(prefix: str) -> str | None:
    return next((c for c, l in LEAGUES.items() if l.pm_prefix == prefix), None)


def kalshi_series() -> dict[str, str]:
    return {c: l.kalshi_series for c, l in LEAGUES.items()}


def pm_tags() -> dict[str, str]:
    return {c: l.pm_tag for c, l in LEAGUES.items()}


def espn_paths() -> dict[str, tuple[str, str]]:
    return {c: l.espn for c, l in LEAGUES.items() if l.espn is not None}


def espn_groups() -> dict[str, tuple[str, ...]]:
    return {c: l.espn_groups for c, l in LEAGUES.items() if l.espn_groups}


def enablement(code: str) -> list[str]:
    """What this league still lacks before it may trade: [] means nothing. Computed, never stored.
    Imports are local: the rule and template registries sit downstream of entities in the grid."""
    from nodes.rules_exhaustive.rules import RULES
    from nodes.settle_wedge.policy import TEMPLATES
    lg = LEAGUES.get(code)
    if lg is None:
        return ["UNREGISTERED"]
    missing = []
    spec = RULES.get((code, "moneyline", "game"))
    if spec is None:
        missing.append("NO_RULE_FOR_LEAGUE")
    elif spec[2] is None:
        missing.append("RULE_UNCITED")
    elif spec[0] != lg.outcomes:
        missing.append(f"RULE_OUTCOMES_{spec[0]}_VS_REGISTRY_{lg.outcomes}")
    by_venue = {t.venue: t.template_id for t in TEMPLATES.values() if code in t.leagues}
    for v in ("kalshi", "polymarket"):
        if v not in by_venue:
            missing.append(f"NO_{v.upper()}_TEMPLATE")
    if "kalshi" in by_venue and "polymarket" in by_venue:
        # A BOUNDED dimension prices from a registered measurement; without one the league blocks
        # at EVIDENCE_UNMEASURED (nodes/settle_wedge/equivalence.py), which is what NFL does today.
        from nodes.settle_wedge.evidence import EVIDENCE
        from nodes.settle_wedge.policy import verdicts_for
        verdicts = verdicts_for(by_venue["kalshi"], by_venue["polymarket"]) or ()
        for key in sorted({v.evidence_key for v in verdicts if v.outcome == "BOUNDED" and v.evidence_key}):
            if key not in EVIDENCE:
                missing.append(f"EVIDENCE_UNMEASURED:{key}")
    return missing


def default_leagues() -> list[str]:
    """The grid's default: every registered league that lacks nothing. The rest still block
    downstream if named explicitly; this only decides what runs unasked."""
    return [c for c in LEAGUES if not enablement(c)]
