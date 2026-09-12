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
    """Registrations are a LIST per market, as the real sockets keep them: the capture watchlist and
    a game poller both subscribe the same tennis ticker."""

    def __init__(self):
        self.regs, self.unregistered = {}, []

    def register(self, market_id, replica, *a, **kw):
        self.regs.setdefault(market_id, []).append(replica)

    def unregister(self, market_id, replica=None):
        self.unregistered.append(market_id)
        if replica is not None:
            rest = [r for r in self.regs.get(market_id, []) if r is not replica]
            if rest:
                self.regs[market_id] = rest
                return
        self.regs.pop(market_id, None)

    @property
    def registered(self):
        return {m: rs[0] for m, rs in self.regs.items()}


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


def test_capture_leaving_its_window_never_unregisters_a_poller_sharing_the_ticker():
    """L89: these sockets are shared. Tennis is capture-registered hours before first serve and a
    game poller registers the same ticker when the match goes live. Dropping the capture ticker by
    NAME took the poller's registration with it, and the orphaned replica -- still holding the
    socket's shared pulse -- then reported age 0 and state SYNCED over a frozen ladder forever,
    unreachable by the reconnect and seq-gap sweeps because both iterate the registration map."""
    ks, ps, w = FakeSocket(), FakeSocket(), Watchlist()
    w.sync(ks, ps, [("K1", "KXATPMATCH")], [])
    poller_replica = object()                       # the match went live; the poller joined
    ks.register("K1", poller_replica)
    assert len(ks.regs["K1"]) == 2, "both owners are subscribed to the one ticker"

    w.sync(ks, ps, [], [])                          # the capture window moved on
    assert ks.regs.get("K1") == [poller_replica], "the poller still prices K1"
    assert w.stats()["kalshi"] == 0, "capture let go of its own"


def test_the_last_owner_leaving_really_does_drop_the_ticker():
    ks, ps, w = FakeSocket(), FakeSocket(), Watchlist()
    w.sync(ks, ps, [("K1", "KXATPMATCH")], [("T1", "s1")])
    w.sync(ks, ps, [], [])
    assert "K1" not in ks.regs and "T1" not in ps.regs


def test_pm_watch_events_keep_the_start_and_participants_behind_the_tokens():
    ev = {"slug": "wta-a-b-2026-09-03", "teams": [], "markets": [
        {"slug": "wta-a-b-2026-09-03", "sportsMarketType": "moneyline", "gameStartTime": "2026-09-03 17:00:00+00",
         "outcomes": '["A", "B"]', "clobTokenIds": '["tokA", "tokB"]', "createdAt": "2026-09-01T00:00:00Z", "bestBid": 0.4, "bestAsk": 0.6}]}
    got = pm_watch_events(["tennis"], FakeClient(pm={"tennis": [ev]}), now=NOW, ahead_h=24.0)
    assert len(got) == 1 and got[0].event_id == "wta-a-b-2026-09-03" and got[0].participants == ["A", "B"]
    assert got[0].start_utc and got[0].tokens == ["tokA"]


def test_pm_watch_keeps_only_the_tours_the_registry_knows():
    def ev(slug):
        return {"slug": slug, "teams": [], "markets": [{"slug": slug, "sportsMarketType": "moneyline", "gameStartTime": "2026-09-03 17:00:00+00",
                "outcomes": '["A","B"]', "clobTokenIds": '["t-' + slug + '","u"]', "createdAt": "2026-09-01T00:00:00Z"}]}
    cl = FakeClient(pm={"tennis": [ev("atp-a-b-2026-09-03"), ev("wta-c-d-2026-09-03"), ev("itf-e-f-2026-09-03"), ev("atp-doubles-g-h-2026-09-03")]})
    got = [e.event_id for e in pm_watch_events(["tennis"], cl, now=NOW, ahead_h=24.0)]
    assert got == ["atp-a-b-2026-09-03", "wta-c-d-2026-09-03", "atp-doubles-g-h-2026-09-03"], "ITF is out; the prefix is the filter"
    assert [e.event_id for e in pm_watch_events(["tennis"], cl, now=NOW, ahead_h=24.0, prefixes=())] == \
        ["atp-a-b-2026-09-03", "wta-c-d-2026-09-03", "itf-e-f-2026-09-03", "atp-doubles-g-h-2026-09-03"]
