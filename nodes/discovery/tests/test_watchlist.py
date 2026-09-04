#!/usr/bin/env python3
"""Capture-only subscriptions: selected by window, registered once, unregistered when gone, never priced."""
from __future__ import annotations

from nodes.discovery.watchlist import Watchlist, kalshi_watch, pm_watch, pm_watch_events

NOW = 1_788_449_600.0   # 2026-09-03T15:33Z


class FakeClient:
    def __init__(self, kalshi=None, pm=None):
        self.kalshi, self.pm = kalshi or {}, pm or {}

    def get_json(self, url, params=None, use_cache=True):
        if "/markets" in url:
            return {"markets": self.kalshi.get(params["series_ticker"], [])}
        if "/events" in url:
            return self.pm.get(params.get("tag_slug") or params.get("tag_id"), []) if params.get("offset", 0) == 0 else []
        raise AssertionError(url)


class FakeSocket:
    def __init__(self):
        self.registered, self.unregistered = {}, []

    def register(self, market_id, replica, *a, **kw):
        self.registered[market_id] = replica

    def unregister(self, market_id):
        self.unregistered.append(market_id); self.registered.pop(market_id, None)


def test_kalshi_watch_keeps_markets_expiring_inside_the_window():
    def m(t, exp): return {"ticker": t, "expected_expiration_time": exp}
    cl = FakeClient(kalshi={"KXATPMATCH": [m("KXATPMATCH-A", "2026-09-03T20:00:00Z"), m("KXATPMATCH-B", "2026-09-06T12:00:00Z"),
                                           m("KXATPMATCH-C", "2026-09-03T10:00:00Z")]})
    got = kalshi_watch(["KXATPMATCH"], cl, now=NOW, ahead_h=24.0)
    assert [t for t, _ in got] == ["KXATPMATCH-A"]           # B is 3 days out; C expired 5 h ago


def test_pm_watch_takes_the_yes_token_of_game_markets_in_the_window():
    ev = {"slug": "wta-a-b-2026-09-03", "teams": [], "markets": [
        {"slug": "wta-a-b-2026-09-03", "sportsMarketType": "moneyline", "gameStartTime": "2026-09-03 17:00:00+00",
         "outcomes": '["A", "B"]', "clobTokenIds": '["tokA", "tokB"]', "createdAt": "2026-09-01T00:00:00Z", "bestBid": 0.4, "bestAsk": 0.6},
        {"slug": "wta-a-b-2026-09-03-set-total", "sportsMarketType": "tennis_match_totals", "gameStartTime": "2026-09-03 17:00:00+00", "clobTokenIds": '["x","y"]'}]}
    far = {"slug": "atp-c-d-2026-09-09", "teams": [], "markets": [{"slug": "atp-c-d-2026-09-09", "sportsMarketType": "moneyline",
           "gameStartTime": "2026-09-09 17:00:00+00", "outcomes": '["C","D"]', "clobTokenIds": '["tokC","tokD"]', "createdAt": "2026-09-01T00:00:00Z"}]}
    got = pm_watch(["tennis"], FakeClient(pm={"tennis": [ev, far]}), now=NOW, ahead_h=24.0)
    assert got == [("tokA", "wta-a-b-2026-09-03")]


def test_sync_registers_new_unregisters_gone_and_never_prices():
    ks, ps, w = FakeSocket(), FakeSocket(), Watchlist()
    assert w.sync(ks, ps, [("K1", "KXATPMATCH"), ("K2", "KXWTAMATCH")], [("T1", "s1")]) == (3, 0)
    assert set(ks.registered) == {"K1", "K2"} and set(ps.registered) == {"T1"}
    assert ks.registered["K1"].verification == "stream" and ps.registered["T1"].verification == "external"
    assert w.sync(ks, ps, [("K2", "KXWTAMATCH")], [("T1", "s1"), ("T2", "s2")]) == (1, 1)
    assert ks.unregistered == ["K1"] and set(ps.registered) == {"T1", "T2"}
    assert w.stats() == {"kalshi": 1, "polymarket": 2, "registered": 4, "unregistered": 1}


def test_pm_watch_events_keep_the_start_and_participants_behind_the_tokens():
    ev = {"slug": "wta-a-b-2026-09-03", "teams": [], "markets": [
        {"slug": "wta-a-b-2026-09-03", "sportsMarketType": "moneyline", "gameStartTime": "2026-09-03 17:00:00+00",
         "outcomes": '["A", "B"]', "clobTokenIds": '["tokA", "tokB"]', "createdAt": "2026-09-01T00:00:00Z", "bestBid": 0.4, "bestAsk": 0.6}]}
    got = pm_watch_events(["tennis"], FakeClient(pm={"tennis": [ev]}), now=NOW, ahead_h=24.0)
    assert len(got) == 1 and got[0].event_id == "wta-a-b-2026-09-03" and got[0].participants == ["A", "B"]
    assert got[0].start_utc and got[0].tokens == ["tokA"]
