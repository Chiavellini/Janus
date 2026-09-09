#!/usr/bin/env python3
"""The venue schedule for tennis: Polymarket's game events become the spine, players become entities."""
from __future__ import annotations

import pytest

from nodes.discovery.venue_schedule import pm_game_events, pm_players, schedule_from_events

NOW = 1_788_449_600.0   # 2026-09-03T15:33Z


def ev(slug, a, b, start, title="x", ids=(1, 2)):
    return {"id": slug, "slug": slug, "title": title,
            "teams": [{"name": a, "abbreviation": slug.split("-")[1], "id": ids[0]}, {"name": b, "abbreviation": slug.split("-")[2], "id": ids[1]}],
            "markets": [{"slug": slug, "sportsMarketType": "moneyline", "gameStartTime": start, "outcomes": '["A","B"]', "clobTokenIds": '["t1","t2"]'},
                        {"slug": slug + "-set-total", "sportsMarketType": "tennis_match_totals", "gameStartTime": start}]}


def test_schedule_from_events_keeps_singles_of_the_tour_and_infers_state():
    events = [ev("wta-bucsa-sakatsu-2026-09-03", "Cristina Bucsa", "Himeno Sakatsume", "2026-09-03 14:00:00+00", ids=(11, 12)),
              ev("atp-blockx-trungel-2026-09-03", "Alexander Blockx", "Marco Trungelliti", "2026-09-03 19:00:00+00", ids=(21, 22)),
              ev("atp-doubles-x-y-2026-09-03", "X", "Y", "2026-09-03 19:00:00+00"),
              ev("wta-old-match-2026-09-02", "Old", "Match", "2026-09-02 10:00:00+00", ids=(31, 32))]
    got = schedule_from_events("wta", "wta", events, NOW)
    assert [g.game_id for g in got] == ["pm:wta:wta-old-match-2026-09-02", "pm:wta:wta-bucsa-sakatsu-2026-09-03"]
    g = got[1]
    assert (g.away_espn, g.home_espn) == ("11", "12") and g.away_name == "Cristina Bucsa" and g.state == "in"
    assert g.participants_espn == ("11", "12") and g.short_name == "BUCSA V SAKATSU" and g.neutral_site
    assert got[0].state == "post" and got[0].completed
    atp = schedule_from_events("atp", "atp", events, NOW)
    assert [g.game_id for g in atp] == ["pm:atp:atp-blockx-trungel-2026-09-03"] and atp[0].state == "pre"


def test_pm_players_are_distinct_per_tour():
    events = [ev("wta-a-b-2026-09-03", "Ann A", "Bea B", "2026-09-03 14:00:00+00", ids=(1, 2)),
              ev("wta-a-c-2026-09-04", "Ann A", "Cat C", "2026-09-04 14:00:00+00", ids=(1, 3)),
              ev("atp-d-e-2026-09-03", "Dan D", "Ed E", "2026-09-03 14:00:00+00", ids=(4, 5))]
    got = pm_players("wta", "wta", events)
    assert [(p["id"], p["name"], p["abbreviation"]) for p in got] == [("1", "Ann A", "a"), ("2", "Bea B", "b"), ("3", "Cat C", "c")]


def test_schedule_deduplicates_the_same_pm_event_id_but_preserves_distinct_matches():
    one = ev("itf-nuudi1-kmieci1-2026-09-10", "Maileen Nuudi", "Anna Kmiecik",
             "2026-09-10 08:00:00+00", ids=(101, 102))
    one["id"] = 995780
    distinct = ev("itf-nuudi1-kmieci1-2026-09-11", "Maileen Nuudi", "Anna Kmiecik",
                  "2026-09-11 08:00:00+00", ids=(101, 102))
    distinct["id"] = 995781
    got = schedule_from_events("itf", "itf", [one, dict(one), distinct], NOW)
    assert [g.game_id for g in got] == ["pm:itf:995780", "pm:itf:995781"]


def test_schedule_merges_sparse_same_id_representations_and_rejects_conflicts():
    whole = ev("itf-a-b-2026-09-10", "Ann A", "Bea B", "2026-09-10 08:00:00+00", ids=(1, 2))
    whole["id"] = 77
    sparse_teams = {"id": 77, "slug": whole["slug"], "title": whole["title"], "teams": whole["teams"], "markets": []}
    sparse_market = {"id": 77, "slug": whole["slug"], "title": whole["title"], "teams": [], "markets": whole["markets"]}
    got = schedule_from_events("itf", "itf", [sparse_teams, sparse_market], NOW)
    assert [g.game_id for g in got] == ["pm:itf:77"]

    conflicting = {**whole, "teams": [dict(whole["teams"][0]), dict(whole["teams"][1])]}
    conflicting["teams"][0]["name"] = "Different Player"
    with pytest.raises(ValueError, match="conflicting duplicate PM schedule event"):
        schedule_from_events("itf", "itf", [whole, conflicting], NOW)

    different_participant = {**whole, "teams": [dict(whole["teams"][0]), dict(whole["teams"][1])]}
    different_participant["teams"][0]["id"] = 999
    with pytest.raises(ValueError, match="teams.ids"):
        schedule_from_events("itf", "itf", [whole, different_participant], NOW)

    same_slug_other_id = {**whole, "id": 78}
    with pytest.raises(ValueError, match="slug .* maps to multiple ids"):
        schedule_from_events("itf", "itf", [whole, same_slug_other_id], NOW)


class _Pages:
    def __init__(self, values):
        self.values = iter(values)

    def get_json(self, *args, **kwargs):
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return value


def test_pm_schedule_enumeration_requires_well_formed_terminal_short_page():
    full = [{"id": i} for i in range(100)]
    assert pm_game_events("tennis", _Pages([full, []]), pages=2) == full

    with pytest.raises(ValueError, match="expected list, got dict"):
        pm_game_events("tennis", _Pages([{"events": full}]))
    with pytest.raises(ValueError, match="event is not an identified object"):
        pm_game_events("tennis", _Pages([[{"id": 1}, "bad"]]))
    with pytest.raises(ValueError, match="event is not an identified object"):
        pm_game_events("tennis", _Pages([[{"teams": []}]]))
    with pytest.raises(RuntimeError, match="page 1 failed"):
        pm_game_events("tennis", _Pages([full, OSError("network")]), pages=2)
    with pytest.raises(RuntimeError, match="2 full pages without terminal short page"):
        pm_game_events("tennis", _Pages([full, full]), pages=2)
    with pytest.raises(ValueError, match="pages must be positive"):
        pm_game_events("tennis", _Pages([]), pages=0)
