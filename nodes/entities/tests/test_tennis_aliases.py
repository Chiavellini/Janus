"""Audited tennis aliases observed in the live cross-venue matcher."""
from nodes.entities.resolve import Resolver, load_teams


def test_checked_tennis_aliases_have_static_entities_with_the_verified_pm_ids():
    teams = load_teams()
    assert teams["atp:gabi-boitan"].espn_id == "3269868"
    assert teams["wta:tessa-brockmann"].espn_id == "3270416"
    assert teams["wta:miriam-bulgaru"].espn_id == "229717"


def test_checked_aliases_join_kalshi_extended_names_to_polymarket_live_players():
    """The dynamic player entity exists only after the current PM slate is seeded.

    Each Kalshi full name below was checked against the same game's PM player id on
    2026-09-09.  This is deliberately a three-row alias table, not a fuzzy
    middle-name heuristic.
    """
    r = Resolver()
    cases = (
        ("atp", "Gabi Boitan", "3269868", "boitan", "Gabi Adrian Boitan", "atp:gabi-boitan"),
        ("wta", "Tessa Brockmann", "3270416", "brockma", "Tessa Johanna Brockmann", "wta:tessa-brockmann"),
        ("wta", "Miriam Bulgaru", "229717", "bulgaru", "Miriam Bianca Bulgaru", "wta:miriam-bulgaru"),
    )
    for league, pm_name, pm_id, abbreviation, kalshi_name, expected in cases:
        assert r.add_player(league, name=pm_name, venue="polymarket", venue_id=pm_id,
                            abbreviation=abbreviation) == expected
        assert r.resolve(league, text=kalshi_name).entity_id == expected
