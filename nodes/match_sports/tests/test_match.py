#!/usr/bin/env python3
"""The exact join. No similarity score anywhere, and the slug is per league."""
from __future__ import annotations

import pytest

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


def test_pm_market_preserves_the_token_outcome_label_after_team_id_resolution():
    """A known PM team id resolves ``Hurricanes``, while its tradable outcome/token is labeled
    ``Miami (FL)``.  The exact correspondence must survive the matcher."""
    from collections import Counter
    from nodes.entities.resolve import Resolver
    from nodes.match_sports.sports_match import pm_markets
    from nodes.schedule_espn.espn import ScheduledGame, index_by_participants

    r = Resolver.load()
    famu = r.resolve("cfb", venue="polymarket", venue_team_id="118359").entity_id
    miami = r.resolve("cfb", venue="polymarket", venue_team_id="118247").entity_id
    assert famu and miami
    start = 1_800_000_000
    g = ScheduledGame("espn:cfb:1", "cfb", start, r.teams[miami].espn_id, r.teams[famu].espn_id,
                      "Miami", "Florida A&M", "pre", False, False, False, "regular-season", "FAMU @ MIA", "x")
    slug = "cfb-flam-mia-2026-09-10"
    teams = [{"id": 118359, "name": "Rattlers", "abbreviation": "flam"},
             {"id": 118247, "name": "Hurricanes", "abbreviation": "mia"}]
    event = {"slug": slug, "teams": teams,
             "markets": [{"slug": slug, "sportsMarketType": "moneyline", "gameStartTime": "2027-01-15 08:00:00+00",
                           "outcomes": '["Florida A&M", "Miami (FL)"]'}]}
    # Use the fixture's exact timestamp in the structured field.
    from datetime import datetime, timezone
    event["markets"][0]["gameStartTime"] = datetime.fromtimestamp(start, timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00")
    by_pair = index_by_participants([g])
    for rendered_teams in (teams, list(reversed(teams))):
        event["teams"] = rendered_teams
        stats = Counter(); stats["p_reason"] = Counter(); stats["k_reason"] = Counter()
        got = pm_markets("cfb", r, by_pair, (start - 1, start + 1), stats, [], events=[event])
        assert {m.entity_id: m.label for m in got} == {
            famu: "Rattlers", miami: "Hurricanes"}
        assert {m.entity_id: m.token_label for m in got} == {
            famu: "Florida A&M", miami: "Miami (FL)"}


def test_pm_outcome_label_that_does_not_resolve_to_its_participant_is_unbound():
    from collections import Counter
    from nodes.entities.resolve import Resolver, Team, build_alias_index
    from nodes.match_sports.sports_match import pm_markets
    from nodes.schedule_espn.espn import ScheduledGame, index_by_participants

    teams = {
        "x:a": Team("x:a", "x", "1", "AAA", "Alpha", "A", "Alpha A"),
        "x:b": Team("x:b", "x", "2", "BBB", "Beta", "B", "Beta B"),
    }
    aliases = build_alias_index([
        {"league": "x", "alias": "Alpha A", "entity_id": "x:a"},
        {"league": "x", "alias": "Beta B", "entity_id": "x:b"},
    ])
    r = Resolver(teams, aliases, {("polymarket", "pa"): "x:a", ("polymarket", "pb"): "x:b"})
    start = 1_800_000_000
    game = ScheduledGame("g", "x", start, "1", "2", "Alpha A", "Beta B", "pre",
                         False, False, False, "regular", "A v B", "A v B")
    slug = "x-a-b-2026-09-10"
    event = {"slug": slug,
             "teams": [{"id": "pa", "name": "Alpha A", "abbreviation": "aaa"},
                       {"id": "pb", "name": "Beta B", "abbreviation": "bbb"}],
             "markets": [{"slug": slug, "gameStartTime": "2027-01-15 08:00:00+00",
                           "outcomes": '["Unknown A", "Beta B"]'}]}
    from datetime import datetime, timezone
    event["markets"][0]["gameStartTime"] = datetime.fromtimestamp(
        start, timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00")
    stats = Counter(); stats["p_reason"] = Counter(); stats["k_reason"] = Counter()
    got = pm_markets("x", r, index_by_participants([game]), (start - 1, start + 1),
                     stats, [], events=[event])
    assert {m.entity_id: m.label for m in got} == {"x:a": "Alpha A", "x:b": "Beta B"}
    assert {m.entity_id: m.token_label for m in got} == {"x:a": "", "x:b": "Beta B"}


def test_the_full_match_slug_uses_exact_segments_not_arbitrary_side_lengths():
    assert _fullgame_slug("cfb").match("cfb-mhud34ce7-nmxst-2026-09-05"), "a hash-broken college piece (nine characters) is admitted (2026-09-08)"
    assert _fullgame_slug("cfb").match("cfb-tenlettersplus-nmxst-2026-09-05")
    assert _fullgame_slug("cfb").match("cfb-x-y-2026-09-05")
    assert _fullgame_slug("wta").match("wta-siegemu-samsono-2026-01-18")
    assert _fullgame_slug("atp").match("atp-blockx-trungel-2026-09-02")
    assert not _fullgame_slug("atp").match("atp-doubles-marclop-kolapol-2026-09-04")
    assert not _fullgame_slug("atp").match("atp-x-y-2026-09-04-exact-score")


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
                    return {"events": [{"event_ticker": "A1", "markets": []}], "cursor": "c2"}
                return {"events": [{"event_ticker": "A2", "markets": []}], "cursor": ""}
            return {"events": [{"event_ticker": "CH1", "markets": []}]}
    f = Fake()
    got = [e["event_ticker"] for e in pull_kalshi("atp", f)]
    assert got == ["A1", "A2", "CH1"]
    assert {c["series_ticker"] for c in f.calls} == {"KXATPMATCH", "KXATPCHALLENGERMATCH"}


def test_kalshi_pull_never_returns_a_partial_or_malformed_enumeration():
    from nodes.match_sports.stage1_checkpoint import VenuePullError, pull_kalshi

    class BrokenSecondPage:
        def get_json(self, _url, params=None, use_cache=False):
            if params["status"] == "open" and params.get("cursor") is None:
                return {"events": [{"event_ticker": "A1", "markets": []}], "cursor": "again"}
            raise OSError("page two unavailable")

    with pytest.raises(VenuePullError, match="incomplete Kalshi pull") as stopped:
        pull_kalshi("atp", BrokenSecondPage())
    assert stopped.value.diagnostics["errors"]["KXATPMATCH:open"].startswith("OSError:")

    class Malformed:
        def get_json(self, _url, params=None, use_cache=False):
            return {"events": None}

    with pytest.raises(VenuePullError, match="malformed"):
        pull_kalshi("atp", Malformed())

    class MalformedNestedMarket:
        def get_json(self, _url, params=None, use_cache=False):
            return {"events": [{"event_ticker": "A1", "markets": [{"yes_sub_title": "Alpha"}]}]}

    with pytest.raises(VenuePullError, match="market is malformed"):
        pull_kalshi("atp", MalformedNestedMarket())

    class ConflictingDuplicate:
        def get_json(self, _url, params=None, use_cache=False):
            rules = "first rules" if params["status"] == "open" else "changed rules"
            return {"events": [{"event_ticker": "SAME", "series_ticker": params["series_ticker"],
                                 "markets": [{"ticker": "SAME-A", "rules_primary": rules}]}]}

    with pytest.raises(VenuePullError, match="conflicting Kalshi representations"):
        pull_kalshi("atp", ConflictingDuplicate())

    class RepeatedCursor:
        def get_json(self, _url, params=None, use_cache=False):
            return {"events": [], "cursor": "same"}

    with pytest.raises(VenuePullError, match="repeated"):
        pull_kalshi("atp", RepeatedCursor())

    class NeverTerminal:
        def get_json(self, _url, params=None, use_cache=False):
            return {"events": [], "cursor": f"page-{params.get('cursor', 'first')}"}

    with pytest.raises(VenuePullError, match="exceeded 2 pages"):
        pull_kalshi("atp", NeverTerminal(), max_pages=2)

    class DuplicateMarketIdentity:
        def get_json(self, _url, params=None, use_cache=False):
            if params["status"] == "unopened":
                return {"events": []}
            return {"events": [{"event_ticker": "EVENT", "markets": [
                {"ticker": "EVENT-A", "yes_sub_title": "Alpha"},
                {"ticker": "EVENT-A", "yes_sub_title": "Beta"}]}]}

    with pytest.raises(VenuePullError, match="conflicting Kalshi representations"):
        pull_kalshi("atp", DuplicateMarketIdentity())

    class MarketOwnedByTwoEvents:
        def get_json(self, _url, params=None, use_cache=False):
            if params["status"] == "unopened":
                return {"events": []}
            return {"events": [
                {"event_ticker": "EVENT-1", "markets": [{"ticker": "MARKET-A"}]},
                {"event_ticker": "EVENT-2", "markets": [{"ticker": "MARKET-A"}]}]}

    with pytest.raises(VenuePullError, match="owners:EVENT-1,EVENT-2"):
        pull_kalshi("atp", MarketOwnedByTwoEvents())

    class ProgrammerBug:
        def get_json(self, _url, params=None, use_cache=False):
            raise AssertionError("not a transport failure")

    with pytest.raises(AssertionError, match="not a transport failure"):
        pull_kalshi("atp", ProgrammerBug())


def test_polymarket_pull_queries_numeric_and_slug_independently_and_merges_sparse_records():
    from nodes.match_sports.stage1_checkpoint import pull_pm

    class Both:
        def __init__(self): self.calls = []
        def get_json(self, _url, params=None, use_cache=False):
            self.calls.append(dict(params))
            if "tag_id" in params:
                return [{"id": "7", "slug": "ere-a-b-2026-09-10", "teams": []}]
            return [{"id": "7", "slug": "ere-a-b-2026-09-10",
                     "teams": [{"id": 1}, {"id": 2}],
                     "markets": [{"id": "m", "sportsMarketType": "moneyline",
                                   "gameStartTime": "2026-09-10 12:00:00+00"}]}]

    f = Both()
    got = pull_pm("ere", f)
    assert len(got) == 1 and [t["id"] for t in got[0]["teams"]] == [1, 2]
    assert {"tag_id", "tag_slug"} == {next(k for k in c if k.startswith("tag_")) for c in f.calls}
    assert got.diagnostics["complete"] is True and got.diagnostics["degraded"] is False
    assert got.diagnostics["selector_disagreement"] == {
        "selectors": ["tag_id:101735", "tag_slug:ere"], "only_first": [], "only_second": []}


def test_polymarket_pull_dedupes_complementary_markets_inside_the_first_event():
    from nodes.match_sports.stage1_checkpoint import pull_pm

    class DuplicateInsideFirst:
        def get_json(self, _url, params=None, use_cache=False):
            if "tag_slug" in params:
                return []
            return [{"id": "event", "slug": "ere-a-b-2026-09-10", "markets": [
                {"id": "market", "slug": "ere-a-b-2026-09-10", "outcomes": '["A","B"]'},
                {"id": "market", "slug": "ere-a-b-2026-09-10", "clobTokenIds": '["ta","tb"]'}]}]

    got = pull_pm("ere", DuplicateInsideFirst())
    assert len(got) == 1 and len(got[0]["markets"]) == 1
    assert got[0]["markets"][0]["outcomes"] == '["A","B"]'
    assert got[0]["markets"][0]["clobTokenIds"] == '["ta","tb"]'


def test_matcher_stats_preserve_venue_pull_diagnostics(monkeypatch):
    from collections import Counter
    from nodes.entities.resolve import Resolver
    from nodes.match_sports import sports_match
    from nodes.match_sports.stage1_checkpoint import PulledEvents

    stats = Counter(); stats["k_reason"] = Counter(); stats["p_reason"] = Counter()
    r = Resolver(teams={}, alias_index={}, xrefs={})
    monkeypatch.setattr(sports_match, "pull_kalshi",
                        lambda *_a, **_k: PulledEvents([], diagnostics={"complete": True, "events": 0}))
    assert sports_match.kalshi_markets("mlb", r, {}, (0, 1), stats, []) == []
    pm = PulledEvents([], diagnostics={"complete": False, "degraded": True,
                                      "errors": {"tag_id:1": "page two failed"}})
    assert sports_match.pm_markets("mlb", r, {}, (0, 1), stats, [], events=pm) == []
    assert stats["enumeration"] == {
        "kalshi": {"complete": True, "events": 0},
        "polymarket": {"complete": False, "degraded": True,
                        "errors": {"tag_id:1": "page two failed"}},
    }


def test_live_match_result_does_not_drop_venue_pull_diagnostics(monkeypatch):
    from datetime import datetime, timezone
    from nodes.discovery import discovery

    marker = object()
    monkeypatch.setattr(discovery.Resolver, "load", lambda: marker)
    monkeypatch.setattr(discovery.espn, "index_by_participants", lambda _games: {})

    def fake_kalshi(_league, _resolver, _by_pair, _window, stats, _near_miss):
        stats.setdefault("enumeration", {})["kalshi"] = {"complete": True}
        return []

    def fake_pm(_league, _resolver, _by_pair, _window, stats, _near_miss, *, events=None):
        stats.setdefault("enumeration", {})["polymarket"] = {
            "complete": False, "degraded": True, "errors": {"tag_id:1": "failed"}}
        return []

    monkeypatch.setattr(discovery, "kalshi_markets", fake_kalshi)
    monkeypatch.setattr(discovery, "pm_markets", fake_pm)
    matches, stats, resolver = discovery.match_live("mlb", [], datetime.now(timezone.utc))
    assert matches == [] and resolver is marker
    assert stats["enumeration"] == {
        "kalshi": {"complete": True},
        "polymarket": {"complete": False, "degraded": True,
                        "errors": {"tag_id:1": "failed"}},
    }


def test_polymarket_pull_discards_a_failed_selectors_partial_pages_but_keeps_complete_fallback():
    from nodes.match_sports.stage1_checkpoint import pull_pm

    partial = [{"id": str(i), "slug": f"ere-a{i}-b{i}-2026-09-10"} for i in range(100)]

    class PrimaryBreaks:
        def get_json(self, _url, params=None, use_cache=False):
            if "tag_id" in params:
                if params["offset"] == 0:
                    return partial
                raise OSError("primary page two failed")
            return [{"id": "fallback", "slug": "ere-c-d-2026-09-10"}]

    got = pull_pm("ere", PrimaryBreaks())
    assert [e["id"] for e in got] == ["fallback"]
    assert got.diagnostics["degraded"] is True
    assert "tag_id:101735" in got.diagnostics["errors"]


def test_polymarket_successful_but_different_selector_populations_are_visible():
    from nodes.match_sports.stage1_checkpoint import pull_pm

    class Different:
        def get_json(self, _url, params=None, use_cache=False):
            return [{"id": "primary", "slug": "ere-a-b-2026-09-10"}] if "tag_id" in params else [
                {"id": "fallback", "slug": "ere-c-d-2026-09-10"}]

    got = pull_pm("ere", Different())
    assert {event["id"] for event in got} == {"primary", "fallback"}
    assert got.diagnostics["selector_disagreement"]["only_first"] == ["id:primary"]
    assert got.diagnostics["selector_disagreement"]["only_second"] == ["id:fallback"]


def test_polymarket_pull_rejects_all_failed_malformed_truncated_or_conflicting_sources():
    from nodes.match_sports.stage1_checkpoint import VenuePullError, pull_pm

    class AllMalformed:
        def get_json(self, _url, params=None, use_cache=False):
            return None if "tag_id" in params else {"events": []}

    with pytest.raises(VenuePullError, match="no complete Polymarket selector") as stopped:
        pull_pm("ere", AllMalformed())
    assert set(stopped.value.diagnostics["errors"]) == {"tag_id:101735", "tag_slug:ere"}

    full = [{"id": str(i), "slug": f"ere-a{i}-b{i}-2026-09-10"} for i in range(100)]

    class NeverExhausts:
        def get_json(self, _url, params=None, use_cache=False): return full

    with pytest.raises(VenuePullError, match="no complete Polymarket selector"):
        pull_pm("ere", NeverExhausts(), max_pages=1)

    class Conflict:
        def get_json(self, _url, params=None, use_cache=False):
            return [{"id": "same", "slug": "ere-a-b-2026-09-10"}] if "tag_id" in params else [
                {"id": "same", "slug": "ere-c-d-2026-09-10"}]

    with pytest.raises(VenuePullError, match="conflicting Polymarket representations"):
        pull_pm("ere", Conflict())

    class CriticalConflict:
        def get_json(self, _url, params=None, use_cache=False):
            start = "2026-09-10 12:00:00+00" if "tag_id" in params else "2026-09-10 13:00:00+00"
            return [{"id": "same", "slug": "ere-a-b-2026-09-10", "teams": [{"id": 1}, {"id": 2}],
                     "markets": [{"id": "m", "slug": "ere-a-b-2026-09-10",
                                  "sportsMarketType": "moneyline", "gameStartTime": start}]}]

    with pytest.raises(VenuePullError, match="start_times_disagree"):
        pull_pm("ere", CriticalConflict())

    class NestedIdentityConflict:
        def get_json(self, _url, params=None, use_cache=False):
            market_id = "m-primary" if "tag_id" in params else "m-fallback"
            return [{"id": "same", "slug": "ere-a-b-2026-09-10",
                     "markets": [{"id": market_id, "slug": "ere-a-b-2026-09-10",
                                  "sportsMarketType": "moneyline"}]}]

    with pytest.raises(VenuePullError, match="market.slug:ere-a-b-2026-09-10"):
        pull_pm("ere", NestedIdentityConflict())

    class ContradictionInsideFirstEvent:
        def get_json(self, _url, params=None, use_cache=False):
            return [{"id": "same", "slug": "ere-a-b-2026-09-10", "markets": [
                {"id": "m", "slug": "ere-a-b-2026-09-10", "clobTokenIds": '["a","b"]'},
                {"id": "m", "slug": "ere-a-b-2026-09-10", "clobTokenIds": '["b","a"]'}]}]

    with pytest.raises(VenuePullError, match="clobTokenIds"):
        pull_pm("ere", ContradictionInsideFirstEvent())

    class SparseIdContradictionInsideFirstEvent:
        def get_json(self, _url, params=None, use_cache=False):
            return [{"id": "same", "slug": "ere-a-b-2026-09-10", "markets": [
                {"id": "m", "slug": "ere-a-b-2026-09-10", "clobTokenIds": '["a","b"]'},
                {"slug": "ere-a-b-2026-09-10", "clobTokenIds": '["b","a"]'}]}]

    with pytest.raises(VenuePullError, match="clobTokenIds"):
        pull_pm("ere", SparseIdContradictionInsideFirstEvent())

    class SparseIdContradictionAcrossSelectors:
        def get_json(self, _url, params=None, use_cache=False):
            market = ({"id": "m", "slug": "ere-a-b-2026-09-10",
                       "clobTokenIds": '["a","b"]'} if "tag_id" in params else
                      {"slug": "ere-a-b-2026-09-10", "clobTokenIds": '["b","a"]'})
            return [{"id": "same", "slug": "ere-a-b-2026-09-10", "markets": [market]}]

    with pytest.raises(VenuePullError, match="clobTokenIds"):
        pull_pm("ere", SparseIdContradictionAcrossSelectors())

    class ProgrammerBug:
        def get_json(self, _url, params=None, use_cache=False):
            raise AssertionError("not a selector failure")

    with pytest.raises(AssertionError, match="not a selector failure"):
        pull_pm("ere", ProgrammerBug())


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
        {"slug": "wta-verylongname-zheng-2026-09-07-exact-score", "teams": [{"id": 7, "name": "Very Longname"}, {"id": 2, "name": "Qinwen Zheng"}]},
        {"slug": "wta-lonely-2026-09-07", "teams": [{"id": 8, "name": "Lonely"}]},
    ]
    assert seed_live_players("wta", r, events) == 4, "two singles players, twice each; no doubles pair, no ATP"
    assert r.resolve("wta", text="Iga Swiatek").ok and not r.resolve("wta", text="A / B").ok
    stats = Counter(); stats["k_reason"] = Counter(); stats["p_reason"] = Counter()
    near = []
    out = pm_markets("wta", r, {}, (0, 4_000_000_000), stats, near, events=events)
    assert out == []          # the one full-game event carries no market start: no_start_time
    assert stats["p_reason"] == {"doubles": 1, "other_league_under_shared_tag": 1,
                                 "derivative_event_not_full_game_moneyline": 2,
                                 "teams_not_two": 1, "no_start_time": 1}
    assert near == []
