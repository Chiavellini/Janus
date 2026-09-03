#!/usr/bin/env python3
"""The gate that stands between a 3-way market and a two-leg 'cover'.

Every test here exists because the untested version of this logic priced an EPL match at +31%.
"""
from __future__ import annotations

import pytest

from nodes.cover.cover import REJECT_NO_PROOF, Leg, best_cover
from nodes.settle_wedge.fixtures import mlb_cover_proof
from nodes.rules_exhaustive.rules import (RULES, ExhaustiveOutcomeSet, NotExhaustive, prove)
from kernel.schema import Book, Quote


def _bk(px: float, size: float = 5000.0) -> Book:
    return Book(asks=(Quote(px, size),), fetched_utc=1000.0)


def test_the_proof_cannot_be_forged():
    """The whole design rests on this. If a caller can construct the token, the gate is decorative."""
    with pytest.raises(TypeError):
        ExhaustiveOutcomeSet("mlb", "moneyline", "game", ("a", "b"), "mlb_no_draw", "cite")


def test_two_way_leagues_with_a_citation_mint_a_proof():
    for league in ("mlb", "nba", "wnba", "nhl"):
        got = prove(league, "moneyline", "game", ["home", "away"])
        assert isinstance(got, ExhaustiveOutcomeSet), f"{league} should prove"
        assert got.citation, "a proof without a citation is an assertion"


def test_soccer_is_three_way_so_two_outcomes_never_prove_and_three_do():
    """Cited 2026-09-03 (IFAB Law 10.1, both venues settle at full time). The +31% ghost was a
    two-leg EPL cover; the type still refuses it, now by count rather than by a missing citation."""
    for league in ("epl", "lal", "bun", "mls"):
        got = prove(league, "moneyline", "game", ["home", "away"])
        assert isinstance(got, NotExhaustive) and got.code == "OUTCOME_COUNT_MISMATCH", league
        three = prove(league, "moneyline", "game", ["home", "draw", "away"])
        assert isinstance(three, ExhaustiveOutcomeSet) and "Law 10.1" in three.citation, league


def _old_nfl_blocks_because_regular_season_games_can_tie():
    got = prove("nfl", "moneyline", "game", ["home", "away"])
    assert isinstance(got, NotExhaustive)
    assert got.code == "RULE_UNCITED"


def test_unregistered_league_blocks_rather_than_defaulting_open():
    got = prove("ufc", "moneyline", "game", ["a", "b"])   # tennis got its rule on 2026-09-03; UFC has none
    assert isinstance(got, NotExhaustive)
    assert got.code == "NO_RULE_FOR_LEAGUE"


def test_wrong_outcome_count_blocks_even_for_a_cited_league():
    got = prove("mlb", "moneyline", "game", ["home", "away", "draw"])
    assert isinstance(got, NotExhaustive)
    assert got.code == "OUTCOME_COUNT_MISMATCH"


def test_duplicate_outcomes_block():
    got = prove("mlb", "moneyline", "game", ["home", "home"])
    assert isinstance(got, NotExhaustive)
    assert got.code == "DUPLICATE_OUTCOME"


def test_every_cited_rule_names_a_real_source():
    """A citation of '' or 'TODO' would pass isinstance and defeat the point."""
    for key, (_n, rule_id, cite) in RULES.items():
        if cite is None:
            continue
        assert len(cite) > 40, f"{key} citation for {rule_id} is too thin to be a source"
        assert "TODO" not in cite.upper()


def test_cover_refuses_a_bool_where_a_proof_is_required():
    """The original bug in one line: proof=True must no longer buy you a price."""
    offers = {"home": [Leg("kalshi", "kalshi_clob", "home", "m", _bk(0.46))],
              "away": [Leg("polymarket", "pm_clob", "away", "m2", _bk(0.30))]}
    cov = best_cover(offers, 100, now_utc=1000.0, proof=True)
    assert not cov.ok
    assert cov.reject_reason == REJECT_NO_PROOF


def test_the_epl_bug_end_to_end():
    """home .46 / away .30 with an invisible .24 draw. Priced, this is a +31% 'arbitrage'."""
    offers = {"home": [Leg("kalshi", "kalshi_clob", "home", "m", _bk(0.46))],
              "away": [Leg("polymarket", "pm_clob", "away", "m2", _bk(0.30))]}
    assert isinstance(prove("epl", "moneyline", "game", sorted(offers)), NotExhaustive)
    # and the same books under a league that IS two-way do price, so the block is the rule
    # doing its job rather than the cover engine being broken.
    mlb = mlb_cover_proof(sorted(offers))
    assert best_cover(offers, 100, now_utc=1000.0, proof=mlb).ok


def test_nfl_is_cited_through_both_venues_tie_clauses():
    got = prove("nfl", "moneyline", "game", ["home", "away"])
    assert isinstance(got, ExhaustiveOutcomeSet) and "0.50" in got.citation and "settle_wedge" in got.citation
