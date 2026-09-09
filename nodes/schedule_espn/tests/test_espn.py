#!/usr/bin/env python3
"""The scoreboard fetch: one call per registered ESPN group, de-duplicated; the default feed otherwise."""
from __future__ import annotations

from datetime import datetime, timezone

from nodes.schedule_espn import espn


def event(eid, date, home, away):
    return {"id": eid, "date": date, "shortName": f"{away} @ {home}", "name": "x", "season": {"slug": "regular-season"},
            "status": {"type": {"state": "pre", "completed": False}},
            "competitions": [{"competitors": [{"homeAway": "home", "team": {"id": home, "displayName": home}},
                                              {"homeAway": "away", "team": {"id": away, "displayName": away}}]}]}


class FakeClient:
    def __init__(self):
        self.calls = []

    def get_json(self, url, params=None, use_cache=True):
        self.calls.append((url, dict(params or {})))
        g = (params or {}).get("groups")
        if g == "80":
            return {"events": [event("1", "2026-09-05T16:00Z", "IU", "UNT"), event("2", "2026-09-05T19:30Z", "ALA", "ECU")]}
        if g == "81":
            return {"events": [event("3", "2026-09-05T17:00Z", "ARMY", "BRY"), event("1", "2026-09-05T16:00Z", "IU", "UNT")]}
        return {"events": [event("9", "2026-09-05T20:10Z", "NYY", "BOS")]}


def test_college_football_asks_for_fbs_and_fcs_and_dedups_on_the_game_id():
    cl = FakeClient()
    lo, hi = datetime(2026, 9, 5, tzinfo=timezone.utc), datetime(2026, 9, 6, tzinfo=timezone.utc)
    games = espn.fetch_range("cfb", lo, hi, client=cl)
    assert [c[1].get("groups") for c in cl.calls] == ["80", "81"]
    assert [g.game_id for g in games] == ["espn:cfb:1", "espn:cfb:3", "espn:cfb:2"]
    assert all("college-football/scoreboard" in c[0] for c in cl.calls)


def test_other_leagues_use_the_default_feed_once():
    cl = FakeClient()
    lo, hi = datetime(2026, 9, 5, tzinfo=timezone.utc), datetime(2026, 9, 6, tzinfo=timezone.utc)
    games = espn.fetch_range("mlb", lo, hi, client=cl)
    assert len(cl.calls) == 1 and "groups" not in cl.calls[0][1]
    assert [g.game_id for g in games] == ["espn:mlb:9"]


def test_ucl_uses_its_external_competition_path_and_game_namespace():
    cl = FakeClient()
    lo, hi = datetime(2026, 9, 5, tzinfo=timezone.utc), datetime(2026, 9, 6, tzinfo=timezone.utc)
    games = espn.fetch_range("ucl", lo, hi, client=cl)
    assert len(cl.calls) == 1
    assert cl.calls[0][0].endswith("/soccer/uefa.champions/scoreboard")
    assert games[0].league == "ucl" and games[0].game_id == "espn:ucl:9"
