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


def test_the_ten_of_2026_09_03_and_their_shapes():
    from nodes.entities.leagues import SOCCER, espn_groups
    assert set(LEAGUES) == {"mlb", "nfl", "nba", "wnba", "nhl", "epl", "lal", "bun", "mls", "cfb"}
    assert espn_groups() == {"cfb": ("80", "81")}, "FBS and FCS; ESPN's default feed is FBS alone"
    assert set(SOCCER) == {"epl", "lal", "bun", "mls"}
    assert all(LEAGUES[c].outcomes == 3 for c in SOCCER) and all(LEAGUES[c].outcomes == 2 for c in LEAGUES if c not in SOCCER)
    assert all(lg.anchor == "espn" and lg.espn is not None for lg in LEAGUES.values())
    assert "ucl" not in LEAGUES, "a club is one entity across competitions before UCL can be registered"


def test_an_unregistered_league_still_blocks_at_the_rule():
    assert enablement("ufc") == ["UNREGISTERED"]
    assert prove("ufc", "moneyline", "game", ("a", "b")).code == "NO_RULE_FOR_LEAGUE"


def test_enablement_names_what_each_league_lacks():
    # MLB has a cited rule, both templates and measured rates; NFL lacks only the rates (ledger row
    # pending); NBA/WNBA/NHL have a rule but no templates;
    # Nothing here is a status: it is
    # computed from the rule and template registries at call time.
    assert enablement("mlb") == []
    assert enablement("nfl") == ["EVIDENCE_UNMEASURED:nfl.cancelled_rate", "EVIDENCE_UNMEASURED:nfl.postponed_gt48h_rate"]
    assert enablement("cfb") == ["EVIDENCE_UNMEASURED:cfb.cancelled_rate", "EVIDENCE_UNMEASURED:cfb.postponed_gt48h_rate"]
    for c in ("nba", "wnba", "nhl"):
        assert enablement(c) == ["NO_KALSHI_TEMPLATE", "NO_POLYMARKET_TEMPLATE"], c
    # soccer: rule cited, both templates reviewed 2026-09-03, rates unmeasured per competition
    for c in ("epl", "lal", "bun", "mls"):
        assert enablement(c) == [f"EVIDENCE_UNMEASURED:soccer.{c}.cancelled_rate", f"EVIDENCE_UNMEASURED:soccer.{c}.postponed_gt48h_rate"], c
    assert default_leagues() == ["mlb"]
