#!/usr/bin/env python3
from __future__ import annotations

from nodes.reconcile.results import kalshi_result, polymarket_result, winners_for_pair


def test_kalshi_result_is_only_read_once_settled():
    assert kalshi_result({"status": "active", "result": ""}) is None
    assert kalshi_result({"market": {"status": "settled", "result": "yes"}}) == "yes"
    assert kalshi_result({"status": "settled", "result": "no"}) == "no"


def test_polymarket_result_needs_a_closed_market_with_one_winner():
    m = {"closed": False, "outcomes": '["A","B"]', "outcomePrices": '["1","0"]'}
    assert polymarket_result(m) is None
    assert polymarket_result({**m, "closed": True}) == "A"
    assert polymarket_result({**m, "closed": True, "outcomePrices": '["0.5","0.5"]'}) is None, "50-50 is not a winner"


def test_winners_are_per_venue_and_partial_when_one_has_not_settled():
    km = {"K_H": {"status": "settled", "result": "yes"}, "K_A": {"status": "settled", "result": "no"}}
    w = winners_for_pair(kalshi_markets=km, pm_market={"closed": False},
                         kalshi_outcomes={"K_H": "home", "K_A": "away"}, pm_outcomes={"Home": "tok-h", "Away": "tok-a"})
    assert w == {"kalshi": "home"}
    w2 = winners_for_pair(kalshi_markets=km, pm_market={"closed": True, "outcomes": '["Home","Away"]', "outcomePrices": '["1","0"]'},
                          kalshi_outcomes={"K_H": "home", "K_A": "away"}, pm_outcomes={"Home": "tok-h", "Away": "tok-a"})
    assert w2 == {"kalshi": "home", "polymarket": "tok-h"}
    half = {"K_H": {"status": "settled", "result": "yes"}, "K_A": {"status": "active", "result": ""}}
    assert "kalshi" not in winners_for_pair(kalshi_markets=half, pm_market=None, kalshi_outcomes={}, pm_outcomes={})
