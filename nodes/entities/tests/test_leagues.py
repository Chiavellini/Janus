#!/usr/bin/env python3
"""One league table, read everywhere; a row buys nothing until the rule and the templates exist."""
from __future__ import annotations

from nodes.entities import seed
from nodes.entities.leagues import (LEAGUES, default_leagues, enablement, espn_paths, kalshi_series, league_for_prefix,
                                    league_for_series, pm_tags)
from nodes.rules_exhaustive.rules import prove
from nodes.schedule_espn import espn


def test_every_consumer_reads_the_registry():
    assert seed.SEED_LEAGUES == list(LEAGUES)
    assert seed.KALSHI_GAME_SERIES == kalshi_series() and seed.PM_TAG == pm_tags()
    assert espn.LEAGUE_PATHS == espn_paths()
    assert league_for_series("KXMLBGAME") == "mlb" and league_for_series("KXWTIW") is None
    assert league_for_prefix("epl") == "epl" and league_for_prefix("lal") == "lal" and league_for_prefix("ucl") is None


BATCH2 = {"elc", "el1", "ita", "fl1", "ere", "por", "scop", "bel1"}


def test_the_eighteen_of_2026_09_03_and_their_shapes():
    from nodes.entities.leagues import SOCCER, espn_groups
    assert set(LEAGUES) == {"mlb", "nfl", "nba", "wnba", "nhl", "epl", "lal", "bun", "mls", "cfb", "atp", "wta"} | BATCH2
    assert espn_groups() == {"cfb": ("80", "81")}, "FBS and FCS; ESPN's default feed is FBS alone"
    assert set(SOCCER) == {"epl", "lal", "bun", "mls"} | BATCH2
    assert all(LEAGUES[c].pm_tag_id for c in BATCH2), "batch 2 pulls Gamma events by tag id"
    assert pm_tags()["elc"] == 102643 and pm_tags()["mlb"] == "mlb"
    assert all(LEAGUES[c].outcomes == 3 for c in SOCCER) and all(LEAGUES[c].outcomes == 2 for c in LEAGUES if c not in SOCCER)
    assert all(lg.anchor == "espn" and lg.espn is not None for c, lg in LEAGUES.items() if c not in ("atp", "wta"))
    assert all(LEAGUES[c].anchor == "venue_structured" and LEAGUES[c].espn is None and LEAGUES[c].template_scrub for c in ("atp", "wta"))
    assert "atp" not in espn_paths()
    assert "ucl" not in LEAGUES, "a club is one entity across competitions before UCL can be registered"


def test_an_unregistered_league_still_blocks_at_the_rule():
    assert enablement("ufc") == ["UNREGISTERED"]
    assert prove("ufc", "moneyline", "game", ("a", "b")).code == "NO_RULE_FOR_LEAGUE"


def test_enablement_names_what_each_league_lacks():
    # MLB and NFL lack nothing; soccer and college football wait on their rates. Nothing here is a status: it is
    # computed from the rule and template registries at call time.
    assert enablement("mlb") == []
    assert enablement("nfl") == []                 # L30 registered both rates on 2026-09-03
    assert enablement("cfb") == []                 # L32 (a FLOOR for FCS, said so in the evidence note)
    for c in ("nba", "wnba", "nhl"):
        assert enablement(c) == ["NO_KALSHI_TEMPLATE", "NO_POLYMARKET_TEMPLATE"], c
    # soccer: rule cited, both templates reviewed 2026-09-03, rates unmeasured per competition
    for c in ("epl", "lal", "bun"):
        assert enablement(c) == [], c                # L33 (a proxy, labelled FLOOR in the evidence note)
    assert enablement("mls") == ["EVIDENCE_UNMEASURED:soccer.mls.cancelled_rate", "EVIDENCE_UNMEASURED:soccer.mls.postponed_gt48h_rate"]
    for c in ("elc", "el1", "ita"):
        assert enablement(c) == [], c                # L35, the same proxy
    for c in ("fl1", "ere", "por", "scop", "bel1"):  # registered and reviewed; no archive to measure from
        assert enablement(c) == [f"EVIDENCE_UNMEASURED:soccer.{c}.cancelled_rate", f"EVIDENCE_UNMEASURED:soccer.{c}.postponed_gt48h_rate"], c
    for c in ("atp", "wta"):
        assert enablement(c) == ["EVIDENCE_UNMEASURED:tennis.delayed_gt7d_rate", "EVIDENCE_UNMEASURED:tennis.walkover_rate"], c   # one rate pair for both tours
    assert default_leagues() == ["mlb", "nfl", "epl", "lal", "bun", "cfb", "elc", "el1", "ita"]
