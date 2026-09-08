#!/usr/bin/env python3
"""The exact join. No similarity score anywhere, and the slug is per league."""
from __future__ import annotations

from kernel.schema import CanonicalKey, KeyProvenance
from nodes.match_sports.sports_match import VenueMarket, _fullgame_slug, pair, venue_structured_game


def vm(venue, gid, ent, *, vid="e", oid="o", period="game", mtype="moneyline", start=1_800_000_000,
       teams=("10", "12"), key=True):
    k = CanonicalKey("mlb", tuple(sorted(teams)), start, mtype, period) if key else None
    return VenueMarket(venue, vid, oid, gid, ent, mtype, period, start, "label", key=k,
                       key_provenance=KeyProvenance.API_STRUCTURED if venue == "polymarket" else KeyProvenance.TICKER_PARSE)


def test_the_full_game_slug_is_per_league_not_mlb_only():
    """`^mlb-` applied to every league starved five of six of all Polymarket pairs."""
    for league, slug in (("mlb", "mlb-tb-nyy-2026-09-02"), ("nfl", "nfl-ne-sea-2026-09-07"),
                         ("nhl", "nhl-tor-mon-2026-10-08"), ("epl", "epl-ips-liv-2026-08-17")):
        assert _fullgame_slug(league).match(slug), (league, slug)
        assert not _fullgame_slug("mlb").match(slug) or league == "mlb"


def test_derivative_events_are_not_full_game_moneylines():
    for slug in ("mlb-tb-nyy-2026-09-02-first-five-winner", "mlb-tb-nyy-2026-09-02-total-9pt5",
                 "mlb-tb-nyy-2026-09-02-spread-away-1pt5", "mlb-tb-nyy-2026-09-02-player-props"):
        assert not _fullgame_slug("mlb").match(slug), slug


def test_pair_joins_on_game_type_period_and_entity_exactly():
    k = [vm("kalshi", "g1", "nyy", vid="KX-1", oid="KX-1-NYY"), vm("kalshi", "g1", "bos", vid="KX-1", oid="KX-1-BOS")]
    p = [vm("polymarket", "g1", "nyy", vid="slug", oid="New York Yankees"),
         vm("polymarket", "g1", "bos", vid="slug", oid="Boston Red Sox"),
         vm("polymarket", "g2", "nyy", vid="slug2", oid="New York Yankees", start=1_800_000_000 + 86400)]  # same teams, different day
    out = pair(k, p)
    assert [(r["entity_id"], r["kalshi_outcome"], r["pm_outcome"]) for r in out] == [
        ("bos", "KX-1-BOS", "Boston Red Sox"), ("nyy", "KX-1-NYY", "New York Yankees")]
    assert all(r["game_id"] == "g1" for r in out)
    assert out[0]["canonical_key"]["participants"] == ["10", "12"] and out[0]["canonical_key"]["period"] == "game"
    assert out[0]["key_provenance"] == {"kalshi": "ticker_parse", "polymarket": "api_structured"}


def test_a_different_period_or_market_type_never_pairs():
    k = [vm("kalshi", "g1", "nyy")]
    assert pair(k, [vm("polymarket", "g1", "nyy", period="h1")]) == []
    assert pair(k, [vm("polymarket", "g1", "nyy", mtype="spread")]) == []


def test_pair_output_is_deterministic_and_price_free():
    k = [vm("kalshi", "g1", "b"), vm("kalshi", "g1", "a")]
    p = [vm("polymarket", "g1", "a"), vm("polymarket", "g1", "b")]
    rows = pair(k, p)
    assert rows == pair(list(reversed(k)), list(reversed(p)))
    assert not any("price" in key for row in rows for key in row)


def test_a_market_that_resolved_onto_no_schedule_game_pairs_with_nothing():
    assert pair([vm("kalshi", "g1", "a", key=False)], [vm("polymarket", "g1", "a")]) == []


def test_the_lakers_celtics_trap_never_pairs_across_dates():
    """Same league, same participants, different external start: two different games."""
    k = [vm("kalshi", "g1", "a", start=1_800_000_000)]
    p = [vm("polymarket", "g1", "a", start=1_800_000_000 + 14 * 86400)]
    assert pair(k, p) == []


def test_the_draw_of_a_three_way_game_pairs_like_any_other_side():
    from nodes.match_sports.sports_match import DRAW_ENTITY
    k = [vm("kalshi", "g1", "lee", vid="KX-1", oid="KX-1-LEE"), vm("kalshi", "g1", "new", vid="KX-1", oid="KX-1-NEW"),
         vm("kalshi", "g1", DRAW_ENTITY, vid="KX-1", oid="KX-1-TIE")]
    p = [vm("polymarket", "g1", "lee", vid="slug", oid="slug:lee"), vm("polymarket", "g1", "new", vid="slug", oid="slug:new"),
         vm("polymarket", "g1", DRAW_ENTITY, vid="slug", oid="slug:draw")]
    out = pair(k, p)
    assert [(r["entity_id"], r["kalshi_outcome"], r["pm_outcome"]) for r in out] == [
        (DRAW_ENTITY, "KX-1-TIE", "slug:draw"), ("lee", "KX-1-LEE", "slug:lee"), ("new", "KX-1-NEW", "slug:new")]


def test_polymarket_outcome_labels_are_the_fallback_for_nickname_only_team_names():
    from nodes.match_sports.sports_match import _pm_outcome_labels
    ev = {"markets": [{"slug": "cfb-lcdbfc25-nwst-2026-08-27", "outcomes": '["Louisiana Christian", "Northwestern State"]'},
                      {"slug": "cfb-lcdbfc25-nwst-2026-08-27-spread", "outcomes": '["Yes", "No"]'}]}
    assert _pm_outcome_labels(ev, "cfb-lcdbfc25-nwst-2026-08-27") == ["Louisiana Christian", "Northwestern State"]
    assert _pm_outcome_labels(ev, "cfb-x") == [] and _pm_outcome_labels({"markets": [{"slug": "s", "outcomes": "nope"}]}, "s") == []


def test_the_full_match_slug_admits_player_pieces_up_to_eight_characters():
    assert _fullgame_slug("cfb").match("cfb-mhud34ce7-nmxst-2026-09-05"), "a hash-broken college piece (nine characters) is admitted (2026-09-08)"
    assert not _fullgame_slug("cfb").match("cfb-tenletters-nmxst-2026-09-05")
    assert _fullgame_slug("wta").match("wta-siegemu-samsono-2026-01-18")
    assert _fullgame_slug("atp").match("atp-blockx-trungel-2026-09-02")
    assert not _fullgame_slug("atp").match("atp-doubles-marclop-kolapol-2026-09-04")


def test_a_tennis_ticker_dated_the_day_before_its_lone_candidate_is_the_same_match():
    """Swiatek v Zheng, 2026-09-07: Kalshi ticker 26SEP06, played Sep 7 (moved a day); unpaired."""
    from datetime import datetime, timezone
    from nodes.schedule_espn.espn import ScheduledGame

    def game(gid, when_utc):
        return ScheduledGame(gid, "wta", int(datetime.fromisoformat(when_utc).replace(tzinfo=timezone.utc).timestamp()),
                             "1", "2", "Swiatek", "Zheng", "in", False, True, False, "us-open", "SWIATEK V ZHEN", "Swiatek v Zheng")
    sep7 = game("pm:wta:1", "2026-09-07T15:30:00")
    assert venue_structured_game([sep7], (2026, 9, 7)) == (sep7, False)
    assert venue_structured_game([sep7], (2026, 9, 6)) == (sep7, True), "one day off, lone candidate: the same match"
    assert venue_structured_game([sep7], (2026, 9, 5)) == (None, False), "two days off is not this match"
    sep6 = game("pm:wta:0", "2026-09-06T15:30:00")
    assert venue_structured_game([sep6, sep7], (2026, 9, 8)) == (None, False), "two candidates: never a guess"
    assert venue_structured_game([sep7], None) == (None, False)


def test_pull_kalshi_follows_the_cursor_and_every_series_of_the_league():
    """One page of 200 cut college football's tail with no signal until 2026-09-07."""
    from nodes.match_sports.stage1_checkpoint import pull_kalshi

    class Fake:
        def __init__(self): self.calls = []
        def get_json(self, url, params=None, use_cache=False):
            self.calls.append(dict(params))
            if params["status"] == "unopened":
                return {"events": []}
            if params["series_ticker"] == "KXATPMATCH":
                if params.get("cursor") is None:
                    return {"events": [{"event_ticker": "A1"}], "cursor": "c2"}
                return {"events": [{"event_ticker": "A2"}], "cursor": ""}
            return {"events": [{"event_ticker": "CH1"}]}
    f = Fake()
    got = [e["event_ticker"] for e in pull_kalshi("atp", f)]
    assert got == ["A1", "A2", "CH1"]
    assert {c["series_ticker"] for c in f.calls} == {"KXATPMATCH", "KXATPCHALLENGERMATCH"}


def test_live_players_seed_the_resolver_and_the_counters_name_every_drop():
    from collections import Counter
    from nodes.entities.resolve import Resolver
    from nodes.match_sports.sports_match import pm_markets, seed_live_players
    r = Resolver(teams={}, alias_index={}, xrefs={})
    events = [
        {"slug": "wta-swiatek-zheng-2026-09-07", "teams": [{"id": 1, "name": "Iga Swiatek", "abbreviation": "swi"},
                                                            {"id": 2, "name": "Qinwen Zheng", "abbreviation": "zhe"}], "markets": []},
        {"slug": "wta-doubles-a-b-2026-09-07", "teams": [{"id": 3, "name": "A / B", "abbreviation": "ab"}, {"id": 4, "name": "C / D", "abbreviation": "cd"}]},
        {"slug": "atp-x-y-2026-09-07", "teams": [{"id": 5, "name": "X", "abbreviation": "x"}, {"id": 6, "name": "Y", "abbreviation": "y"}]},
        {"slug": "wta-swiatek-zheng-2026-09-07-exact-score", "teams": [{"id": 1, "name": "Iga Swiatek"}, {"id": 2, "name": "Qinwen Zheng"}]},
        {"slug": "wta-verylongname-zheng-2026-09-07", "teams": [{"id": 7, "name": "Very Longname"}, {"id": 2, "name": "Qinwen Zheng"}]},
        {"slug": "wta-lonely-2026-09-07", "teams": [{"id": 8, "name": "Lonely"}]},
    ]
    assert seed_live_players("wta", r, events) == 4, "two singles players, twice each; no doubles pair, no ATP"
    assert r.resolve("wta", text="Iga Swiatek").ok and not r.resolve("wta", text="A / B").ok
    stats = Counter(); stats["k_reason"] = Counter(); stats["p_reason"] = Counter()
    near = []
    out = pm_markets("wta", r, {}, (0, 4_000_000_000), stats, near, events=events)
    assert out == []          # the one full-game event carries no market start: no_start_time
    assert stats["p_reason"] == {"doubles": 1, "other_league_under_shared_tag": 1,
                                 "derivative_event_not_full_game_moneyline": 1, "slug_piece_too_long": 1,
                                 "teams_not_two": 1, "no_start_time": 1}
    assert [n["reason"] for n in near] == ["slug_piece_too_long"]
