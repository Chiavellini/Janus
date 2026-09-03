#!/usr/bin/env python3
"""The venue schedule for tennis: Polymarket's game events become the spine, players become entities."""
from __future__ import annotations

from nodes.discovery.venue_schedule import pm_players, schedule_from_events

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
