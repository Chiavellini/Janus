#!/usr/bin/env python3
"""The exact join. No similarity score anywhere, and the slug is per league."""
from __future__ import annotations

from nodes.match_sports.sports_match import VenueMarket, _fullgame_slug, pair


def vm(venue, gid, ent, *, vid="e", oid="o", period="game", mtype="moneyline"):
    return VenueMarket(venue, vid, oid, gid, ent, mtype, period, 1_800_000_000, "label")


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
         vm("polymarket", "g2", "nyy", vid="slug2", oid="New York Yankees")]      # a different game
    out = pair(k, p)
    assert [(r["entity_id"], r["kalshi_outcome"], r["pm_outcome"]) for r in out] == [
        ("bos", "KX-1-BOS", "Boston Red Sox"), ("nyy", "KX-1-NYY", "New York Yankees")]
    assert all(r["game_id"] == "g1" for r in out)


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
