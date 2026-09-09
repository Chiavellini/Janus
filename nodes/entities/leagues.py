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
    #: Gamma `primaryTagId` from /sports, for competitions whose tag slug is not the sport code;
    #: when set, event pulls use `tag_id` instead of `tag_slug`.
    pm_tag_id: int | None = None
    #: Regexes removed from a venue's rules text before it is hashed into a template: the tournament
    #: and round a tennis text names change every match while the rules do not.
    template_scrub: tuple[str, ...] = ()
    #: Further Kalshi game-level series that belong to this league (tennis: the Challenger tour
    #: shares the tour's Polymarket prefix). Pulled beside `kalshi_series`.
    kalshi_series_extra: tuple[str, ...] = ()

    @property
    def kalshi_series_all(self) -> tuple[str, ...]:
        return (self.kalshi_series, *self.kalshi_series_extra)


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
    # Batch 2, 2026-09-03: the census's next soccer competitions both venues list (Gamma tag ids from /sports).
    "elc":  League("elc", "EFL Championship", "KXEFLCHAMPIONSHIPGAME", "elc", "elc", ("soccer", "eng.2"), outcomes=3, pm_tag_id=102643),
    "el1":  League("el1", "EFL League One", "KXEFLL1GAME", "el1", "el1", ("soccer", "eng.3"), outcomes=3, pm_tag_id=104319),
    # Serie A is the one league whose Gamma /sports `primaryTagId` (100618, "Serie A") is the
    # FUTURES tag -- champion, top scorer, relegation; every event under it has no teams. The game
    # events live under tag 101962 (slug `sea`, the same set `tag_slug=sea` returns). With 100618
    # the league produced zero Polymarket events for four days and no reason, because a futures
    # event is skipped before the matcher counts it (2026-09-07). Do not "correct" it back.
    "ita":  League("ita", "Serie A", "KXSERIEAGAME", "sea", "sea", ("soccer", "ita.1"), outcomes=3, pm_tag_id=101962),
    "fl1":  League("fl1", "Ligue 1", "KXLIGUE1GAME", "fl1", "fl1", ("soccer", "fra.1"), outcomes=3, pm_tag_id=102070),
    "ere":  League("ere", "Eredivisie", "KXEREDIVISIEGAME", "ere", "ere", ("soccer", "ned.1"), outcomes=3, pm_tag_id=101735),
    "por":  League("por", "Primeira Liga", "KXLIGAPORTUGALGAME", "por", "por", ("soccer", "por.1"), outcomes=3, pm_tag_id=101772),
    "scop":  League("scop", "Scottish Premiership", "KXSCOTTISHPREMGAME", "scop", "scop", ("soccer", "sco.1"), outcomes=3, pm_tag_id=102872),
    "bel1":  League("bel1", "Belgian Pro League", "KXBELGIANPLGAME", "bel1", "bel1", ("soccer", "bel.1"), outcomes=3, pm_tag_id=105725),
    # Tennis, 2026-09-03: no ESPN schedule anchors a match, so the schedule is Polymarket's own game
    # events (player names, ids and gameStartTime) and Kalshi is joined on the players' names and the
    # ticker date -- a `venue_structured` anchor with the weaker provenance grade. Both tours share
    # Polymarket's `tennis` tag; the slug prefix says which. Kalshi settles tennis on exchange shard 3.
    "atp":  League("atp", "ATP Tour", "KXATPMATCH", "tennis", "atp", None, anchor="venue_structured",
                   kalshi_series_extra=("KXATPCHALLENGERMATCH",),
                   template_scrub=(r"in the \d{4} .*? (?=after a ball has been played)",
                                   r"in the [A-Z][A-Za-z0-9 .'-]*?(?: (?:ATP|WTA))?,",
                                   r"official information from (?:the )?[A-Z][A-Za-z0-9 .'-]*?\.")),
    "wta":  League("wta", "WTA Tour", "KXWTAMATCH", "tennis", "wta", None, anchor="venue_structured",
                   kalshi_series_extra=("KXWTACHALLENGERMATCH",),
                   template_scrub=(r"in the \d{4} .*? (?=after a ball has been played)",
                                   r"in the [A-Z][A-Za-z0-9 .'-]*?(?: (?:ATP|WTA))?,",
                                   r"official information from (?:the )?[A-Z][A-Za-z0-9 .'-]*?\.")),
    # ITF (men's and women's), 2026-09-07 from the L28 census and the day's slate: Kalshi's two ITF
    # series carry 117 open events of which Polymarket lists 69 under the same `tennis` tag with
    # the `itf-` prefix. The same tennis rule and templates; certified only when the ITF rules
    # texts hash to the tennis templates (ops/harvest_templates.py --league itf).
    "itf":  League("itf", "ITF", "KXITFMATCH", "tennis", "itf", None, anchor="venue_structured",
                   kalshi_series_extra=("KXITFWMATCH",),
                   # ITF texts name the tournament by code ("M25 Rabat", "W15 Campulung", a
                   # "(moved from ...)" note) and the round by word ("Qualifying", "Round of 32");
                   # Kalshi's has no "Men's Singles" and Polymarket's names the ITF as the source.
                   template_scrub=(r"in the \d{4} .*? (?=after a ball has been played)",
                                   r"in the [MW]\d{2} [^,]*?, (?:Qualifying|Main Draw|Round of \d+|Quarterfinals?|Semifinals?|Finals?)[^,]*?,",
                                   r"official information from (?:the )?International Tennis Federation \(ITF\)\.")),
    # Not yet: UCL. Entities are keyed per league (lal:esp.real_madrid) and a club plays in its domestic
    # league AND the Champions League, so its one Kalshi team id would map to two entities and the
    # xref table refuses the collision. A club must become one entity across competitions first.
}

SOCCER = tuple(c for c, l in LEAGUES.items() if l.outcomes == 3)


def league_for_series(series_ticker: str) -> str | None:
    return next((c for c, l in LEAGUES.items() if series_ticker in l.kalshi_series_all), None)


def league_for_prefix(prefix: str) -> str | None:
    return next((c for c, l in LEAGUES.items() if l.pm_prefix == prefix), None)


def kalshi_series() -> dict[str, str]:
    return {c: l.kalshi_series for c, l in LEAGUES.items()}


def pm_tags() -> dict[str, str | int]:
    """league -> Gamma tag slug, or the numeric tag id when the registry carries one."""
    return {c: (l.pm_tag_id if l.pm_tag_id is not None else l.pm_tag) for c, l in LEAGUES.items()}


def venue_structured() -> list[str]:
    """Leagues whose schedule comes from the venues themselves (no ESPN anchor)."""
    return [c for c, l in LEAGUES.items() if l.anchor == "venue_structured"]


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
        verdicts = verdicts_for(by_venue["kalshi"], by_venue["polymarket"], league=code) or ()
        for key in sorted({v.evidence_key for v in verdicts if v.outcome == "BOUNDED" and v.evidence_key}):
            if key not in EVIDENCE:
                missing.append(f"EVIDENCE_UNMEASURED:{key}")
    return missing


def default_leagues() -> list[str]:
    """The grid's default: every registered league that lacks nothing. The rest still block
    downstream if named explicitly; this only decides what runs unasked."""
    return [c for c in LEAGUES if not enablement(c)]
