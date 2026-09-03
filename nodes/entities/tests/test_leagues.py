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
    assert league_for_prefix("epl") == "epl" and league_for_prefix("lal") is None


def test_the_six_of_2026_09_03_and_their_shapes():
    assert set(LEAGUES) == {"mlb", "nfl", "nba", "wnba", "nhl", "epl"}
    assert LEAGUES["epl"].outcomes == 3 and all(LEAGUES[c].outcomes == 2 for c in LEAGUES if c != "epl")
    assert all(lg.anchor == "espn" and lg.espn is not None for lg in LEAGUES.values())


def test_an_unregistered_league_still_blocks_at_the_rule():
    assert enablement("cfb") == ["UNREGISTERED"]
    assert prove("cfb", "moneyline", "game", ("a", "b")).code == "NO_RULE_FOR_LEAGUE"


def test_enablement_names_what_each_league_lacks():
    # MLB has a cited rule, both templates and measured rates; NFL lacks only the rates (ledger row
    # pending); NBA/WNBA/NHL have a rule but no templates;
    # EPL's three-way rule is uncited and no template exists. Nothing here is a status: it is
    # computed from the rule and template registries at call time.
    assert enablement("mlb") == []
    assert enablement("nfl") == ["EVIDENCE_UNMEASURED:nfl.cancelled_rate", "EVIDENCE_UNMEASURED:nfl.postponed_gt48h_rate"]
    for c in ("nba", "wnba", "nhl"):
        assert enablement(c) == ["NO_KALSHI_TEMPLATE", "NO_POLYMARKET_TEMPLATE"], c
    assert enablement("epl") == ["RULE_UNCITED", "NO_KALSHI_TEMPLATE", "NO_POLYMARKET_TEMPLATE"]
    assert default_leagues() == ["mlb"]
