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


def test_seven_current_exact_variants_are_bound_by_both_venues_stable_ids():
    """Each pair was observed in one unique same-event listing on both venues on 2026-09-09."""
    r = Resolver()
    cases = (
        ("atp", "Kenta Miyoshi", "3281694", "miyoshi", "Kenta Miyoshi (b. 2004)",
         "6dbbd191-4ec7-4747-b092-ee632f87c06e", "atp:kenta-miyoshi"),
        ("atp", "Tai Sach", "3270406", "sach", "Tai Leonard Sach",
         "f8a58f4e-e8dc-4614-8323-a775822f888b", "atp:tai-sach"),
        ("atp", "Jay Dylan Friend", "3265229", "friend", "Jay Friend",
         "c5814da0-419c-44de-b791-26f2c50e44d4", "atp:jay-dylan-friend"),
        ("atp", "Yanis Durand", "3289713", "dur", "Yanis Ghazouani Durand",
         "3c20f904-f07e-4d78-a5b5-ff5fa2c59ac3", "atp:yanis-durand"),
        ("atp", "Joao Lucas Da Silva", "229608", "silv", "Joao Lucas Reis Da Silva",
         "dd7994f2-9995-4f47-bbe7-b430e85b354e", "atp:joao-lucas-da-silva"),
        ("wta", "Lucija Bagaric", "3267774", "bagaric", "Lucija Ciric-Bagaric",
         "93e92d4e-cb05-4168-9a0e-fe906bc6887c", "wta:lucija-bagaric"),
        ("wta", "Maria Lourdes Carle", "229684", "carle", "Maria Carle",
         "8da0dea9-d3f0-4597-9cc4-9fc972607d6c", "wta:maria-lourdes-carle"),
    )
    for league, pm_name, pm_id, abbreviation, kalshi_name, kalshi_id, expected in cases:
        assert r.add_player(league, name=pm_name, venue="polymarket", venue_id=pm_id,
                            abbreviation=abbreviation) == expected
        assert r.resolve(league, venue="polymarket", venue_team_id=pm_id).entity_id == expected
        assert r.resolve(league, venue="kalshi", venue_team_id=kalshi_id).entity_id == expected
        assert r.resolve(league, text=kalshi_name).entity_id == expected
