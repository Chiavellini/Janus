"""Exact, venue-id-backed repairs from the 2026-09-09 current-slate audit."""
from nodes.entities.resolve import Resolver


def test_current_soccer_venue_ids_resolve_to_their_espn_entities():
    r = Resolver.load()
    cases = (("kalshi", "dca44d67-d382-4a24-b504-2839f6e59cb6", "por:por.benfica"),
             ("polymarket", "118503", "por:por.benfica"),
             ("kalshi", "ca5d00cc-f18d-4802-8337-32c0e7152d64", "por:estrela"),
             ("polymarket", "118515", "por:estrela"),
             ("kalshi", "cd4f6267-e0bf-4074-9c47-abb625ad14e1", "bel1:bel.kv-mechelen"),
             ("polymarket", "3282319", "bel1:bel.kv-mechelen"),
             ("polymarket", "3284406", "bel1:bel.anderlecht"),
             ("kalshi", "167b048f-0412-4626-9766-ec08603e62cc", "ere:ned.az"),
             ("polymarket", "115303", "ere:ned.willem_ii"))
    for venue, venue_id, entity_id in cases:
        assert r.by_xref(venue, venue_id).entity_id == entity_id


def test_cfb_collision_labels_use_venue_ids_and_leave_plain_troy_ambiguous():
    r = Resolver.load()
    assert r.by_xref("kalshi", "a3484578-3134-4a25-9c98-e1a05965f9aa").entity_id == "cfb:troy-trojans"
    assert r.by_xref("kalshi", "48514282-2c62-4c7a-a8c5-d66d90c4e7e3").entity_id == "cfb:ut-rio-grande-valley-vaqueros"
    assert r.resolve("cfb", text="UTRGV").entity_id == "cfb:ut-rio-grande-valley-vaqueros"
    assert not r.resolve("cfb", text="Troy").ok


def test_polymarket_portuguese_clubs_keep_estoril_and_estrela_distinct():
    r = Resolver.load()
    estoril = r.by_xref("polymarket", "118517").entity_id
    estrela = r.by_xref("polymarket", "118515").entity_id
    assert estoril == "por:por.estoril"
    assert estrela == "por:estrela"
    assert estoril != estrela


def test_pm_reseed_does_not_turn_estoril_praia_into_estrela_from_est_abbreviation():
    """118517's full structured name beats no guess: EST belongs to ESPN's Estrela entry."""
    from nodes.entities.seed import seed_pm_xrefs

    class PM:
        def get_json(self, _url, params=None, use_cache=True):
            if params["offset"]:
                return []
            return [{"slug": "por-est-foo-2026-09-13",
                     "teams": [{"id": "118517", "name": "Estoril Praia", "abbreviation": "est"}]}]

    rows, conflicts = seed_pm_xrefs(Resolver.load(), leagues=["por"], client=PM())
    assert not any(r["entity_id"] == "por:estrela" for r in rows)
    assert any(r["uuid"] == "118517" and r["reason"] == "disagree" for r in conflicts)
