#!/usr/bin/env python3
"""The census over frozen payloads: ticker parsing, both venues' event shapes as captured 2026-09-03,
the join on date + participants, and the ranking. No network."""
from __future__ import annotations

import json

from nodes.discovery.census import (GameEvent, events_match, is_game_series, join, kalshi_events, parse_kalshi_event,
                                    pm_events, pm_events_for_sport, summarize)

NOW = 1788460000.0   # 2026-09-03T04:26:40Z


class FrozenGamma:
    def __init__(self, pages, failures=()):
        self.pages = pages
        self.failures = set(failures)
        self.calls = []

    def get_json(self, _url, *, params, use_cache):
        key = "tag_id" if "tag_id" in params else "tag_slug"
        selector = (key, str(params[key]))
        self.calls.append((selector, params["offset"]))
        if selector in self.failures:
            raise RuntimeError(f"frozen {key} failure")
        return self.pages.get(selector, {}).get(params["offset"], [])


def gamma_game(slug, *, event_id=None):
    return {"id": event_id or f"id-{slug}", "slug": slug,
            "markets": [{"sportsMarketType": "moneyline", "gameStartTime": "2026-09-10T19:00:00Z"}]}


def gamma_future(slug):
    return {"id": f"id-{slug}", "slug": slug, "markets": [{"sportsMarketType": "winner"}]}


def kmarket(ticker, sub, bid="0.4000", ask="0.4200", bs="150", as_="200", ev=None,
            open_time="2026-09-01T00:00:00Z", exp="2026-09-04T03:00:00Z"):
    return {"ticker": ticker, "event_ticker": ev or ticker.rsplit("-", 1)[0], "yes_sub_title": sub,
            "yes_bid_dollars": bid, "yes_ask_dollars": ask, "yes_bid_size_fp": bs, "yes_ask_size_fp": as_,
            "open_time": open_time, "expected_expiration_time": exp, "status": "active"}


def pm_event(slug, title, start="2026-09-03 19:00:00+00", created="2026-08-21T06:00:01Z", outcomes=("Yes", "No"),
             per_team=True, bid=0.53, ask=0.54):
    mk = []
    suffixes = [p for p in slug.split("-")[1:3]] + ["draw"] if per_team else [""]
    for i, suf in enumerate(suffixes):
        mk.append({"slug": f"{slug}-{suf}" if suf else slug, "outcomes": json.dumps(list(outcomes)),
                   "gameStartTime": start, "createdAt": created, "sportsMarketType": "moneyline",
                   "bestBid": bid, "bestAsk": ask, "clobTokenIds": json.dumps([f"tok{i}a", f"tok{i}b"])})
    return {"slug": slug, "title": title, "markets": mk}


def test_series_classification_and_event_ticker_parsing():
    assert is_game_series("KXMLBGAME") and is_game_series("KXUFCFIGHT") and is_game_series("KXATPMATCH")
    assert not is_game_series("KXCS2GAMES") and not is_game_series("KXCOLLEGEGAMEDAY") and not is_game_series("KXMLBSPREAD")
    p = parse_kalshi_event("KXLALIGAGAME-26SEP17MCFVIL")
    assert p == {"series": "KXLALIGAGAME", "date": "2026-09-17", "time": None, "abbrevs": "MCFVIL"}
    p = parse_kalshi_event("KXMLBGAME-26SEP031235SFPIT")
    assert p["date"] == "2026-09-03" and p["time"] == "1235" and p["abbrevs"] == "SFPIT"
    assert parse_kalshi_event("KXWTIW-26SEP17") is None and parse_kalshi_event("NOPE") is None


def test_kalshi_events_drop_the_draw_and_measure_the_touch_and_the_life():
    ms = [kmarket("KXEPLGAME-26SEP14LEENEW-LEE", "Leeds United", ev="KXEPLGAME-26SEP14LEENEW", open_time="2026-09-10T00:00:00Z",
                  exp="2026-09-14T22:00:00Z"),
          kmarket("KXEPLGAME-26SEP14LEENEW-NEW", "Newcastle", ev="KXEPLGAME-26SEP14LEENEW", bid="0.3000", ask="0.3100", bs="10", as_="1000",
                  open_time="2026-09-10T00:00:00Z", exp="2026-09-14T22:00:00Z"),
          kmarket("KXEPLGAME-26SEP14LEENEW-TIE", "Tie", ev="KXEPLGAME-26SEP14LEENEW", open_time="2026-09-10T00:00:00Z",
                  exp="2026-09-14T22:00:00Z"),
          kmarket("KXEPLGAME-26SEP15AAABBB-AAA", "Aaa", bid=None, ev="KXEPLGAME-26SEP15AAABBB")]
    evs = {e.event_id: e for e in kalshi_events("KXEPLGAME", ms)}
    e = evs["KXEPLGAME-26SEP14LEENEW"]
    assert e.participants == ["Leeds United", "Newcastle"] and e.abbrevs == ["lee", "new"] and e.n_markets == 3
    assert e.two_sided and e.touch_bid_usd == 3.0 and e.touch_ask_usd == 84.0    # the binding side per market, min across
    assert e.life_h == 118.0
    assert not evs["KXEPLGAME-26SEP15AAABBB"].two_sided


def test_pm_events_take_names_from_outcomes_or_the_title_and_the_life_from_creation():
    three = pm_event("epl-lee-new-2026-09-14", "Leeds United FC vs. Newcastle United FC", start="2026-09-14 19:00:00+00",
                     created="2026-09-01T04:00:14Z")
    two = pm_event("ufc-nat-pavand-2026-09-05", "UFC Fight Night: Nathaniel Wood vs. Pavel Andrusca (Featherweight, Prelims)",
                   outcomes=("Nathaniel Wood", "Pavel Andrusca"), per_team=False, start="2026-09-05 16:00:00+00",
                   created="2026-09-02T22:00:15Z")
    futures = {"slug": "will-faze-win", "title": "Will FaZe win?", "markets": [{"outcomes": '["Yes","No"]'}]}
    out = {e.event_id: e for e in pm_events("epl", [three, futures]) + pm_events("ufc", [two])}
    assert "will-faze-win" not in out
    e = out["epl-lee-new-2026-09-14"]
    assert e.participants == ["Leeds United FC", "Newcastle United FC"] and e.abbrevs == ["lee", "new"]
    assert e.n_markets == 3 and e.date == "2026-09-14" and len(e.tokens) == 3 and e.two_sided
    assert abs(e.life_h - (13 * 24 + 15 - 0.004)) < 0.01     # 2026-09-01T04:00:14Z -> 2026-09-14T19:00Z
    u = out["ufc-nat-pavand-2026-09-05"]
    assert u.participants == ["Nathaniel Wood", "Pavel Andrusca"] and u.abbrevs == ["nat", "pavand"]


def test_join_matches_on_date_and_participants_and_reports_the_rest():
    k = kalshi_events("KXEPLGAME", [
        kmarket("KXEPLGAME-26SEP14LEENEW-LEE", "Leeds United", ev="KXEPLGAME-26SEP14LEENEW", exp="2026-09-14T22:00:00Z"),
        kmarket("KXEPLGAME-26SEP14LEENEW-NEW", "Newcastle", ev="KXEPLGAME-26SEP14LEENEW", exp="2026-09-14T22:00:00Z"),
        kmarket("KXEPLGAME-26SEP14ARSCHE-ARS", "Arsenal", ev="KXEPLGAME-26SEP14ARSCHE", exp="2026-09-14T17:00:00Z"),
        kmarket("KXEPLGAME-26SEP14ARSCHE-CHE", "Chelsea", ev="KXEPLGAME-26SEP14ARSCHE", exp="2026-09-14T17:00:00Z")])
    k += kalshi_events("KXMLBGAME", [
        kmarket("KXMLBGAME-26SEP031235SFPIT-SF", "San Francisco", ev="KXMLBGAME-26SEP031235SFPIT"),
        kmarket("KXMLBGAME-26SEP031235SFPIT-PIT", "Pittsburgh", ev="KXMLBGAME-26SEP031235SFPIT")])
    p = pm_events("epl", [pm_event("epl-lee-new-2026-09-14", "Leeds United FC vs. Newcastle United FC", start="2026-09-14 19:00:00+00"),
                          pm_event("epl-liv-mci-2026-09-14", "Liverpool FC vs. Manchester City", start="2026-09-14 15:00:00+00")])
    # MLB on Polymarket: abbreviations differ (sf vs "san francisco"); the name token carries it
    p += pm_events("mlb", [pm_event("mlb-sf-pit-2026-09-03", "San Francisco Giants vs. Pittsburgh Pirates", per_team=False,
                                    outcomes=("San Francisco Giants", "Pittsburgh Pirates"), start="2026-09-03 16:35:00+00")])
    pairs = join(k, p)
    got = {(a.event_id, b.event_id) for a, b in pairs}
    assert got == {("KXEPLGAME-26SEP14LEENEW", "epl-lee-new-2026-09-14"), ("KXMLBGAME-26SEP031235SFPIT", "mlb-sf-pit-2026-09-03")}
    # a shared stop-word ("United", "City") is not a match
    assert not events_match(k[1], p[1])
    now = 1788780000.0   # 2026-09-06T21:20Z: the EPL games are 8 days out (outside 48 h), MLB is in the past
    s = summarize(k, p, pairs, {}, now)
    assert s["competitions"] == [] and sorted(m[:2] for m in s["mapping"]) == [["KXEPLGAME", "epl"], ["KXMLBGAME", "mlb"]]
    now = 1789408800.0   # 2026-09-14T04:00Z
    s = summarize(k, p, pairs, {"epl-lee-new-2026-09-14": (60.0, 90.0)}, now)
    row = s["competitions"][0]
    assert row["kalshi_series"] == "KXEPLGAME" and row["pm_sport"] == "epl" and row["co_listed_48h"] == 1
    assert row["two_sided_both"] == 1 and row["pm_touch_usd_median"] == 60.0 and row["kalshi_touch_usd_median"] == 60.0
    assert row["capacity_usd"] == 60.0 and row["score"] > 0
    assert s["unmatched_kalshi_48h"] == {"KXEPLGAME": 1} and s["unmatched_pm_48h"] == {"epl": 1}
    # the events behind the counts, for ops/coverage_report.py (2026-09-07)
    assert [p["kalshi_event"] for p in s["co_listed_pairs_48h"]] == ["KXEPLGAME-26SEP14LEENEW"]
    assert s["co_listed_pairs_48h"][0]["pm_event"] == "epl-lee-new-2026-09-14" and s["co_listed_pairs_48h"][0]["participants"]
    assert [e["event_id"] for e in s["unmatched_kalshi_events_48h"]] == ["KXEPLGAME-26SEP14ARSCHE"]
    assert [e["event_id"] for e in s["unmatched_pm_events_48h"]] == ["epl-liv-mci-2026-09-14"]


def test_a_competition_with_no_book_sample_still_ranks_from_the_kalshi_touch():
    k = GameEvent("kalshi", "KXNCAAFGAME", "KXNCAAFGAME-26SEP05CWUCP", "2026-09-05", NOW + 3600, ["Central Washington", "Cal Poly"],
                  ["cwu", "cp"], 2, True, 40.0, 55.0, 70.0)
    p = GameEvent("polymarket", "cfb", "cfb-cwu-cp-2026-09-05", "2026-09-05", NOW + 3600, ["Central Washington Wildcats", "Cal Poly Mustangs"],
                  ["cwu", "cp"], 1, True, None, None, 100.0, ["t"])
    s = summarize([k], [p], [(k, p)], {}, NOW)
    row = s["competitions"][0]
    assert row["co_listed_48h"] == 1 and row["two_sided_both"] == 1 and row["pm_touch_n"] == 0
    assert row["capacity_usd"] == 40.0 and row["life_h_median"] == 85.0


def test_pm_sport_falls_back_to_slug_and_merges_pages_without_duplicates():
    duplicate = gamma_future("ucl-old")
    cl = FrozenGamma({
        ("tag_id", "1234"): {0: [duplicate], 2: []},
        ("tag_slug", "ucl"): {0: [duplicate, gamma_game("ucl-ars-psg")],
                                  2: [gamma_game("ucl-real-bayern")], 4: []},
    })
    events, meta = pm_events_for_sport(1234, "ucl", cl, page=2, max_pages=10)
    assert [e["slug"] for e in events] == ["ucl-old", "ucl-ars-psg", "ucl-real-bayern"]
    assert meta["fallback_used"] is True and meta["game_events"] == 2
    assert meta["primary"]["game_events"] == 0 and meta["fallback"]["game_events"] == 2
    assert (('tag_id', '1234'), 0) in cl.calls and (('tag_slug', 'ucl'), 2) in cl.calls


def test_pm_sport_keeps_primary_error_visible_when_slug_succeeds():
    cl = FrozenGamma({
        ("tag_slug", "ucl"): {0: [gamma_game("ucl-ars-psg")], 100: []},
    }, failures={("tag_id", "1234")})
    events, meta = pm_events_for_sport(1234, "ucl", cl)
    assert [e["slug"] for e in events] == ["ucl-ars-psg"]
    assert meta["fallback_used"] is True
    assert "tag_id" in meta["errors"] and "frozen tag_id failure" in meta["errors"]["tag_id"]


def test_pm_sport_reports_partial_primary_disagreement_deterministically():
    cl = FrozenGamma({
        ("tag_id", "1234"): {0: [gamma_game("ucl-shared"), gamma_game("ucl-only-id")]},
        ("tag_slug", "ucl"): {0: [gamma_game("ucl-shared"), gamma_game("ucl-only-slug")]},
    })
    events, meta = pm_events_for_sport(1234, "ucl", cl)
    assert [e["slug"] for e in events] == ["ucl-shared", "ucl-only-id", "ucl-only-slug"]
    assert meta["only_primary"] == ["id:id-ucl-only-id"]
    assert meta["only_fallback"] == ["id:id-ucl-only-slug"]


def test_pm_sport_deduplicates_when_one_selector_has_only_id_and_other_only_slug():
    left = gamma_game("ucl-same", event_id="event-42")
    right = gamma_game("", event_id="event-42")
    cl = FrozenGamma({
        ("tag_id", "1234"): {0: [left]},
        ("tag_slug", "ucl"): {0: [right]},
    })
    events, meta = pm_events_for_sport(1234, "ucl", cl)
    assert len(events) == 1 and meta["only_primary"] == [] and meta["only_fallback"] == []


def test_pm_sport_collapses_a_complete_record_bridging_sparse_id_and_slug_records():
    m1 = {"id": "m1", "sportsMarketType": "moneyline", "gameStartTime": "2026-09-10T19:00:00Z"}
    m2 = {"id": "m2", "sportsMarketType": "moneyline", "gameStartTime": "2026-09-10T19:00:00Z"}
    sparse = [{"id": "42", "markets": [m1]}, {"slug": "ucl-test", "markets": [m2]}]
    bridge = {"id": "42", "slug": "ucl-test", "markets": []}
    for primary, fallback in ((sparse, [bridge]), ([bridge], sparse)):
        cl = FrozenGamma({("tag_id", "1234"): {0: primary}, ("tag_slug", "ucl"): {0: fallback}})
        events, meta = pm_events_for_sport(1234, "ucl", cl)
        assert len(events) == 1
        assert events[0]["id"] == "42" and events[0]["slug"] == "ucl-test"
        assert {m["id"] for m in events[0]["markets"]} == {"m1", "m2"}
        assert meta["game_events"] == 1 and meta["representation_conflicts"] == []


def test_pm_sport_marks_full_last_page_as_incomplete():
    cl = FrozenGamma({
        ("tag_id", "1234"): {0: [gamma_game("ucl-a"), gamma_game("ucl-b")]},
        ("tag_slug", "ucl"): {0: [gamma_game("ucl-a"), gamma_game("ucl-b")]},
    })
    _, meta = pm_events_for_sport(1234, "ucl", cl, page=2, max_pages=1)
    assert meta["pagination_exhausted"] == ["tag_id", "tag_slug"]


def test_pm_sport_full_page_followed_by_short_page_is_complete():
    cl = FrozenGamma({
        ("tag_id", "1234"): {0: [gamma_game("ucl-a"), gamma_game("ucl-b")], 2: [gamma_game("ucl-c")]},
        ("tag_slug", "ucl"): {0: [gamma_game("ucl-a"), gamma_game("ucl-b")], 2: [gamma_game("ucl-c")]},
    })
    _, meta = pm_events_for_sport(1234, "ucl", cl, page=2, max_pages=3)
    assert meta["pagination_exhausted"] == []


def test_pm_sport_merges_sparse_primary_with_richer_fallback_in_either_order():
    sparse = {"id": "event-42", "slug": "ucl-test", "markets": [], "teams": []}
    rich = {"id": "event-42", "slug": "ucl-test",
            "markets": [{"id": "m1", "sportsMarketType": "moneyline", "gameStartTime": "2026-09-10T19:00:00Z"}],
            "teams": [{"id": "a", "name": "Arsenal"}, {"id": "p", "name": "PSG"}]}
    for primary, fallback in (([sparse], [rich]), ([rich], [sparse])):
        cl = FrozenGamma({("tag_id", "1234"): {0: primary}, ("tag_slug", "ucl"): {0: fallback}})
        events, meta = pm_events_for_sport(1234, "ucl", cl)
        assert len(events) == 1 and meta["game_events"] == 1
        assert events[0]["markets"] and events[0]["teams"]


def test_pm_sport_surfaces_inconsistent_identity_representation():
    cl = FrozenGamma({
        ("tag_id", "1234"): {0: [gamma_game("ucl-one", event_id="event-42")]},
        ("tag_slug", "ucl"): {0: [gamma_game("ucl-two", event_id="event-42")]},
    })
    events, meta = pm_events_for_sport(1234, "ucl", cl)
    assert len(events) == 1
    assert meta["representation_conflicts"] == ["id:event-42->ucl-one,ucl-two"]
    assert "representation" in meta["errors"]


def test_pm_sport_surfaces_malformed_primary_payload_and_keeps_slug_events():
    cl = FrozenGamma({("tag_id", "1234"): {0: None},
                      ("tag_slug", "ucl"): {0: [gamma_game("ucl-good")]}})
    events, meta = pm_events_for_sport(1234, "ucl", cl)
    assert [e["slug"] for e in events] == ["ucl-good"]
    assert "tag_id" in meta["errors"] and "not a list" in meta["errors"]["tag_id"]


def test_pm_sport_surfaces_malformed_payloads_from_both_selectors():
    cl = FrozenGamma({("tag_id", "1234"): {0: {}}, ("tag_slug", "ucl"): {0: "bad"}})
    events, meta = pm_events_for_sport(1234, "ucl", cl)
    assert events == []
    assert set(meta["errors"]) == {"tag_id", "tag_slug"}
