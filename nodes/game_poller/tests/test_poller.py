#!/usr/bin/env python3
"""One game, four books, priced on every event."""
from __future__ import annotations

import pytest

from nodes.game_poller.poller import Evaluation, GamePoller, PollerState

T = 1000.0
OUT = {"home": {"kalshi": "K_H", "polymarket": "P_H"},
       "away": {"kalshi": "K_A", "polymarket": "P_A"}}


def mlb(**kw) -> GamePoller:
    return GamePoller("g1", "mlb", OUT, quantities=(100.0,), **kw)


def sync_all(p: GamePoller, *, kh=0.50, ka=0.50, ph=0.50, pa=0.50, now=T, size=5000.0):
    prices = {("kalshi", "home"): kh, ("kalshi", "away"): ka,
              ("polymarket", "home"): ph, ("polymarket", "away"): pa}
    for key, rep in p.replicas.items():
        rep.subscribed(now)
        rep.snapshot_in([(0.01, size)], [(prices[key], size)],
                        seq=1 if rep.has_sequence else None, now=now)


def test_a_three_way_league_never_gets_a_poller():
    """No subscription should be spent on a game whose outcome set cannot be proven complete."""
    p = GamePoller("g", "epl", OUT)
    assert p.state is PollerState.BLOCKED
    assert p.block_reason == "RULE_UNCITED"
    assert p.replicas == {}
    assert p.on_event("kalshi", "K_H", now=T) == []


def test_it_warms_before_it_watches():
    p = mlb()
    assert p.state is PollerState.WARMING
    evs = p.on_event("kalshi", "K_H", now=T)
    assert all(e.cover is None for e in evs)
    assert evs[0].blocked_by is not None


def test_a_blocked_evaluation_still_reports_why():
    """'We could not price this, and here is why' is what separates no-edge from no-data."""
    p = mlb()
    e = p.on_event("kalshi", "K_H", now=T)[0]
    assert "NOT_SYNCED" in e.blocked_by or "HEARTBEAT" in e.blocked_by


def test_all_four_synced_lets_it_price():
    p = mlb()
    sync_all(p, kh=0.48, pa=0.48)
    e = p.on_event("kalshi", "K_H", now=T)[0]
    assert p.state is PollerState.WATCHING
    assert e.cover is not None and e.cover.ok
    assert e.blocked_by is None


def test_a_real_gap_is_flagged_actionable():
    """0.44 + 0.44 = 0.88 gross; fees at the money are ~3c, so this clears 1% comfortably."""
    p = mlb()
    sync_all(p, kh=0.44, ka=0.99, ph=0.99, pa=0.44)
    e = p.on_event("polymarket", "P_A", now=T)[0]
    assert e.actionable_return is not None and e.actionable_return > 0.01
    assert p.opportunities == 1


def test_one_desynced_replica_blocks_the_whole_cover():
    """A drifted book invents gaps. Three good replicas do not make a fourth trustworthy."""
    p = mlb()
    sync_all(p, kh=0.44, pa=0.44)
    p.replicas[("kalshi", "home")].delta_in([], seq=99, now=T)      # force a seq gap
    e = p.on_event("kalshi", "K_H", now=T)[0]
    assert e.cover is None
    assert "SEQ_GAP" in e.blocked_by
    assert p.opportunities == 0


def test_a_stale_replica_blocks_even_with_a_live_socket():
    p = mlb(max_book_age_s=2.0)
    sync_all(p, kh=0.44, pa=0.44)
    for r in p.replicas.values():
        r.heartbeat(T + 10)
    e = p.on_event("kalshi", "K_H", now=T + 10)[0]
    assert e.cover is None and "STALE" in e.blocked_by


def test_evaluation_happens_per_event_not_per_tick_of_a_clock():
    p = mlb()
    sync_all(p, kh=0.48, pa=0.48)
    before = p.evaluations
    for _ in range(25):
        p.on_event("kalshi", "K_H", now=T)
    assert p.evaluations == before + 25
    assert p.events >= 25


def test_it_reports_its_subscriptions_per_venue():
    p = mlb()
    assert sorted(p.market_ids("kalshi")) == ["K_A", "K_H"]
    assert sorted(p.market_ids("polymarket")) == ["P_A", "P_H"]


def test_kalshi_replicas_use_sequence_and_polymarket_ones_do_not():
    """Kalshi has a monotonic seq; Polymarket has no sequence number at all."""
    p = mlb()
    assert p.replicas[("kalshi", "home")].has_sequence
    assert not p.replicas[("polymarket", "home")].has_sequence


def test_draining_stops_evaluation():
    p = mlb()
    sync_all(p)
    p.drain()
    assert p.on_event("kalshi", "K_H", now=T) == []


def test_a_single_venue_cover_is_not_counted_as_an_opportunity():
    """Both legs on one book is the intra-venue control, not an arbitrage."""
    p = mlb()
    sync_all(p, kh=0.44, ka=0.44, ph=0.99, pa=0.99)
    e = p.on_event("kalshi", "K_H", now=T)[0]
    assert e.cover.ok and e.cover.single_venue
    assert p.opportunities == 0
