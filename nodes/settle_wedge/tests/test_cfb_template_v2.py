"""L59: the Polymarket CFB wording first observed on the 2026-09-10/11 slate."""
from __future__ import annotations

import pytest

from nodes.settle_wedge.equivalence import NotEquivalent, SettlementEquivalence, certify
from nodes.settle_wedge.harvest import harvest_kalshi, harvest_polymarket
from nodes.settle_wedge.pair import certify_from_spec
from nodes.settle_wedge.policy import (
    DIMENSIONS,
    KALSHI_CFB_GAME_V1,
    POLYMARKET_CFB_GAME_V1,
    POLYMARKET_CFB_GAME_V2,
)

T = 1_789_000_000.0
GAME_ID = "espn:cfb:401858213"
POPULATION = {"source": "espn", "league": "cfb", "season_slug": "regular-season",
              "game_id": GAME_ID}
# Test-only values prove policy plumbing; L60 deliberately withholds both production keys.
RATES = {"cfb.postponed_gt48h_rate": 0.02, "cfb.cancelled_rate": 0.01}


def _records(pm_text: str = POLYMARKET_CFB_GAME_V2.sample_text):
    k = harvest_kalshi(
        {"ticker": "KXNCAAFGAME-26SEP10FAMUMIA-FAMU",
         "rules_primary": KALSHI_CFB_GAME_V1.sample_text.split("\n", 1)[0],
         "rules_secondary": KALSHI_CFB_GAME_V1.sample_text.split("\n", 1)[1]},
        participants=KALSHI_CFB_GAME_V1.sample_participants, retrieved_at=T)
    p = harvest_polymarket(
        {"slug": "cfb-flam-mia-2026-09-10", "description": pm_text,
         "resolutionSource": "https://www.ncaa.com/"},
        participants=POLYMARKET_CFB_GAME_V2.sample_participants, retrieved_at=T)
    return k, p


def test_current_polymarket_cfb_text_is_an_exact_reviewed_template():
    _k, p = _records()
    assert p.template_hash == POLYMARKET_CFB_GAME_V2.template_hash == "a85d52e70c02f6cd"
    assert p.settlement_sources == ("https://www.ncaa.com/",)

    # The other three current games differ only in participant/date metadata.
    variants = [
        ("Villanova", "Louisville", "September 11 at 7:00PM ET"),
        ("Norfolk State", "Virginia", "September 11 at 7:00PM ET"),
        ("Richmond", "NC State", "September 11 at 7:00PM ET"),
    ]
    for away, home, when in variants:
        text = (POLYMARKET_CFB_GAME_V2.sample_text
                .replace("Florida A&M", away).replace("Miami (FL)", home)
                .replace("September 10 at 8:00PM ET", when))
        got = harvest_polymarket({"slug": "s", "description": text},
                                 participants=(away, home), retrieved_at=T)
        assert got.template_hash == "a85d52e70c02f6cd"


def test_v2_has_a_verdict_on_all_dimensions_when_valid_rates_are_injected():
    k, p = _records()
    got = certify(k, p, league="cfb", population=POPULATION, rates=RATES)
    assert isinstance(got, SettlementEquivalence)
    assert {v.dimension for v in got.verdicts} == set(DIMENSIONS)
    assert {v.dimension: v.outcome for v in got.verdicts} == {
        "official_source": "SAME", "winner_determination": "SAME", "overtime": "SAME",
        "tie": "NA", "postponement": "BOUNDED", "cancellation": "BOUNDED",
        "suspended": "BOUNDED", "abandoned": "SAME", "player_non_participation": "NA",
        "retirement": "NA", "dispute_revision": "SAME", "settlement_timing": "SAME"}
    assert got.rates == RATES
    assert got.evidence_population == "regular-season"
    assert got.schedule_game_id == GAME_ID


def test_v2_is_reviewed_but_cannot_mint_without_corrected_l60_evidence():
    from nodes.entities.leagues import default_leagues, enablement
    from nodes.settle_wedge.evidence import EVIDENCE

    assert "cfb.postponed_gt48h_rate" not in EVIDENCE
    assert "cfb.cancelled_rate" not in EVIDENCE
    assert enablement("cfb") == ["EVIDENCE_UNMEASURED:cfb.cancelled_rate",
                                  "EVIDENCE_UNMEASURED:cfb.postponed_gt48h_rate"]
    assert "cfb" not in default_leagues()
    got = certify(*_records(), league="cfb", population=POPULATION)
    assert isinstance(got, NotEquivalent) and got.code == "EVIDENCE_UNMEASURED"


@pytest.mark.parametrize("population", [
    None,
    {"source": "venue_structured", "league": "cfb", "season_slug": "regular-season",
     "game_id": GAME_ID},
    {"source": "espn", "league": "cfb", "season_slug": "post-season", "game_id": GAME_ID},
    {"source": "espn", "league": "cfb", "season_slug": "regular-season",
     "game_id": "espn:cfb-playoff:1"},
    {"source": "espn", "league": "nfl", "season_slug": "regular-season", "game_id": GAME_ID},
])
def test_l32_evidence_cannot_escape_its_cfb_regular_season_population(population):
    got = certify(*_records(), league="cfb", population=population)
    assert isinstance(got, NotEquivalent)
    assert got.code == "EVIDENCE_POPULATION_MISMATCH"


def test_spec_population_must_name_the_exact_same_cfb_game():
    k, p = _records()
    spec = {
        "game_id": GAME_ID, "league": "cfb", "schedule_population": {**POPULATION, "game_id": "espn:cfb:other"},
        "rules": {
            "retrieved_at": T,
            "kalshi": {"market": {"ticker": k.market_id,
                                     "rules_primary": KALSHI_CFB_GAME_V1.sample_text.split("\n", 1)[0],
                                     "rules_secondary": KALSHI_CFB_GAME_V1.sample_text.split("\n", 1)[1]},
                       "participants": list(KALSHI_CFB_GAME_V1.sample_participants)},
            "polymarket": {"market": {"slug": p.market_id,
                                        "description": POLYMARKET_CFB_GAME_V2.sample_text,
                                        "resolutionSource": "https://www.ncaa.com/"},
                            "participants": list(POLYMARKET_CFB_GAME_V2.sample_participants)}}}
    got = certify_from_spec(spec, "cfb")
    assert isinstance(got, NotEquivalent) and got.code == "EVIDENCE_POPULATION_MISMATCH"
    spec["schedule_population"] = POPULATION
    assert isinstance(certify_from_spec(spec, "cfb"), NotEquivalent)
    assert isinstance(certify_from_spec(spec, "cfb", rates=RATES), SettlementEquivalence)


@pytest.mark.parametrize("old,new", [
    ("this market will resolve 50-50.", "this market will resolve at the last traded price."),
    ("Overtime is included if played.", "Overtime is excluded."),
    ("remain open until the game has been completed", "resolve 50-50 after 24 hours"),
])
def test_semantic_changes_do_not_inherit_the_reviewed_v2_policy(old: str, new: str):
    assert old in POLYMARKET_CFB_GAME_V2.sample_text
    text = POLYMARKET_CFB_GAME_V2.sample_text.replace(old, new, 1)
    got = certify(*_records(text), league="cfb", population=POPULATION, rates=RATES)
    assert isinstance(got, NotEquivalent)
    assert got.code == "TEMPLATE_UNKNOWN"


def test_original_cfb_template_remains_valid_inside_the_same_population():
    k, _p = _records()
    old = harvest_polymarket({"slug": "s", "description": POLYMARKET_CFB_GAME_V1.sample_text,
                              "resolutionSource": "https://www.ncaa.com/"},
                             participants=POLYMARKET_CFB_GAME_V1.sample_participants, retrieved_at=T)
    got = certify(k, old, league="cfb", population=POPULATION)
    assert isinstance(got, NotEquivalent) and got.code == "EVIDENCE_UNMEASURED"
    assert isinstance(certify(k, old, league="cfb", population=POPULATION, rates=RATES),
                      SettlementEquivalence)
