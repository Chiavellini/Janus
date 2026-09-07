from nodes.entities.resolve import Resolver


def test_a_player_a_venue_lists_today_becomes_an_entity_for_this_pass():
    """2026-09-07: Swiatek had no entity row; the venues' own listings are the roster."""
    r = Resolver(teams={}, alias_index={}, xrefs={})
    eid = r.add_player("wta", name="Iga Swiatek", venue="polymarket", venue_id="183136", abbreviation="swi")
    assert eid == "wta:iga-swiatek" and r.teams[eid].espn_id == "183136"
    assert r.resolve("wta", text="Iga Swiatek").entity_id == eid, "the other venue's full-name label resolves"
    assert r.resolve("wta", text="I. Swiatek").entity_id == eid and r.by_text("wta", "SWI").entity_id == eid
    assert r.by_xref("polymarket", "183136").entity_id == eid
    # the same player again from the other venue: no second entity, the id is learned
    assert r.add_player("wta", name="Iga Swiatek", venue="kalshi", venue_id="3887631b-0004") == eid
    assert r.by_xref("kalshi", "3887631b-0004").entity_id == eid and len(r.teams) == 1
    assert r.add_player("wta", name="", venue="polymarket", venue_id="1") is None
