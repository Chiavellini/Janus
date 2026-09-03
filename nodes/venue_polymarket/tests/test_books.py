#!/usr/bin/env python3
"""The reversed ladders, the fee schedule, and the fetch path that used to raise NameError."""
from __future__ import annotations

import nodes.venue_polymarket  # noqa: F401  -- registers the adapter
from kernel import venue_registry
from nodes.venue_polymarket.books import (fetch_pm_books, pm_book, pm_fee_params, pm_market_for_slug,
                                          pm_order_limits)

T = 1000.0
PAYLOAD = {"bids": [{"price": "0.01", "size": "5"}, {"price": "0.19", "size": "10"}],
           "asks": [{"price": "0.99", "size": "5"}, {"price": "0.20", "size": "8"}]}
#: Verbatim fee/limit fields of a Gamma MLB market on 2026-09-02.
MARKET = {"slug": "mlb-sea-bos-2026-09-02", "feeType": "sports_fees_v2", "feesEnabled": True,
          "feeSchedule": {"exponent": 1, "rate": 0.03, "takerOnly": True, "rebateRate": 0.25},
          "orderMinSize": 5, "orderPriceMinTickSize": 0.01}
EVENT = {"slug": "mlb-sea-bos-2026-09-02", "markets": [{"slug": "other"}, MARKET]}


def test_best_price_is_last_so_the_parser_sorts():
    b = pm_book(PAYLOAD, T)
    assert b.best_bid.price == 0.19 and b.best_ask.price == 0.20
    assert b.fetched_utc == T


class FakeClient:
    def __init__(self, books):
        self.books = books
    def get_json(self, url, *, params=None, use_cache=True, headers=None):
        tok = params["token_id"]
        if tok not in self.books:
            raise RuntimeError("HTTP 404")
        return self.books[tok]


def test_fetch_records_failures_by_outcome_instead_of_raising_nameerror():
    """`errors` and `slug` were out of scope: every call raised NameError, even the happy path."""
    out = fetch_pm_books({"home": "tok-h", "away": "tok-a"}, FakeClient({"tok-h": PAYLOAD}))
    assert out["home"].best_ask.price == 0.20
    assert "away" not in out
    assert out["__errors__"] == {"away": "RuntimeError: HTTP 404"}


def test_fee_schedule_comes_from_the_market_not_a_constant():
    assert pm_fee_params(MARKET) == {"fee_rate": 0.03, "fee_exponent": 1.0, "taker_only": True,
                                     "rebate_rate": 0.25}
    assert pm_fee_params({"slug": "x"}) is None
    assert pm_fee_params({"feeSchedule": {"exponent": 1}}) is None


def test_the_market_is_found_by_exact_slug_inside_the_event():
    assert pm_market_for_slug(EVENT, "mlb-sea-bos-2026-09-02") is MARKET
    assert pm_market_for_slug(EVENT, "mlb-sea-bos-2026-09-03") is None


def test_order_limits_use_schema_names():
    assert pm_order_limits(MARKET) == {"min_order_contracts": 5.0, "tick": 0.01}
    assert pm_order_limits({}) == {}


def test_polymarket_is_registered_and_live():
    a = venue_registry.get("polymarket")
    assert a.tradeable() and a.liquidity_source == "pm_clob"


def test_three_way_soccer_yields_three_yes_tokens_by_team_name_and_draw():
    from nodes.venue_polymarket.books import pm_outcome_tokens, pm_primary_market
    slug = "epl-lee-new-2026-09-14"
    ev = {"slug": slug, "teams": [{"name": "Leeds United FC", "abbreviation": "lee"}, {"name": "Newcastle United FC", "abbreviation": "new"}],
          "markets": [{"slug": f"{slug}-lee", "sportsMarketType": "moneyline", "clobTokenIds": '["t-lee-yes","t-lee-no"]', "feeSchedule": {"rate": 0.05}},
                      {"slug": f"{slug}-draw", "sportsMarketType": "moneyline", "clobTokenIds": '["t-draw-yes","t-draw-no"]'},
                      {"slug": f"{slug}-new", "sportsMarketType": "moneyline", "clobTokenIds": '["t-new-yes","t-new-no"]'},
                      {"slug": f"{slug}-total-2pt5", "sportsMarketType": "totals", "clobTokenIds": '["x","y"]'}]}
    assert pm_outcome_tokens(ev, slug) == {"Leeds United FC": "t-lee-yes", "Draw": "t-draw-yes", "Newcastle United FC": "t-new-yes"}
    assert pm_primary_market(ev, slug)["slug"] == f"{slug}-lee"
    # a two-outcome game is unchanged: one market carrying the slug, outcomes are the names
    two = {"slug": "mlb-sf-pit-2026-09-03", "markets": [{"slug": "mlb-sf-pit-2026-09-03", "outcomes": '["San Francisco Giants","Pittsburgh Pirates"]',
                                                          "clobTokenIds": '["a","b"]'}]}
    assert pm_outcome_tokens(two, "mlb-sf-pit-2026-09-03") == {"San Francisco Giants": "a", "Pittsburgh Pirates": "b"}
    assert pm_primary_market(two, "mlb-sf-pit-2026-09-03")["slug"] == "mlb-sf-pit-2026-09-03"
    # a three-way event missing its draw market yields nothing rather than two thirds of a cover
    del ev["markets"][1]
    assert pm_outcome_tokens(ev, slug) == {}
