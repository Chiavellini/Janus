#!/usr/bin/env python3
"""Kalshi's two-sided book, and the liquidity that reading only YES throws away."""
from __future__ import annotations

import pytest

from kernel.schema import liquidity_source_for
from nodes.cover.capacity import frontier
from nodes.cover.cover import Leg, best_cover
from nodes.settle_wedge.fixtures import mlb_cover_proof
from nodes.venue_kalshi.books import kalshi_book

T = 1000.0
PROOF = mlb_cover_proof(["ath", "tex"])

#: One market's payload. BOTH arrays are bid ladders -- there are no asks on the wire.
PAYLOAD = {"orderbook_fp": {"yes_dollars": [[0.40, 100], [0.39, 200]],
                            "no_dollars": [[0.55, 300], [0.54, 400]]}}


def test_both_arrays_are_bids_and_each_side_folds_the_other():
    yes = kalshi_book(PAYLOAD, "yes", T)
    no = kalshi_book(PAYLOAD, "no", T)
    assert yes.best_bid.price == 0.40
    assert yes.best_ask.price == pytest.approx(0.45), "a NO bid at 0.55 is a YES ask at 0.45"
    assert no.best_bid.price == 0.55
    assert no.best_ask.price == pytest.approx(0.60), "a YES bid at 0.40 is a NO ask at 0.60"


def test_the_two_sides_come_from_one_payload_so_cost_no_extra_request():
    """The reason there is no excuse for ignoring the NO ladder."""
    assert kalshi_book(PAYLOAD, "yes", T).asks and kalshi_book(PAYLOAD, "no", T).asks


def test_buying_no_on_the_other_market_is_the_same_exposure():
    """A Kalshi event has one market per participant. NO on TEX is YES on ATH."""
    ath = {"orderbook_fp": {"yes_dollars": [[0.40, 10]], "no_dollars": [[0.58, 10]]}}
    tex = {"orderbook_fp": {"yes_dollars": [[0.58, 500]], "no_dollars": [[0.41, 20]]}}
    via_yes = kalshi_book(ath, "yes", T).best_ask       # fold ATH's NO bid: 1 - 0.58 = 0.42
    via_no = kalshi_book(tex, "no", T).best_ask         # fold TEX's YES bid: 1 - 0.58 = 0.42
    assert via_yes.price == pytest.approx(via_no.price), "same exposure prices the same"
    assert via_no.size == 500 and via_yes.size == 10, "but the depth behind it is independent"


def test_the_complementary_no_ladder_deepens_capacity():
    """Measured live on 2026-09-02: +67% and +563% of takeable depth on two MLB games."""
    ath = {"orderbook_fp": {"yes_dollars": [[0.40, 10]], "no_dollars": [[0.58, 50]]}}
    tex = {"orderbook_fp": {"yes_dollars": [[0.56, 5000]], "no_dollars": [[0.58, 5000]]}}
    pm_tex = Leg("polymarket", liquidity_source_for("polymarket"), "pm", "m",
                 kalshi_book({"orderbook_fp": {"yes_dollars": [[0.40, 5000]],
                                               "no_dollars": [[0.55, 5000]]}}, "yes", T),
                 {"fee_rate": 0.0})

    yes_only = {"ath": [Leg("kalshi", liquidity_source_for("kalshi"), "ATH", "e",
                            kalshi_book(ath, "yes", T), {"fee_multiplier": 0.0})],
                "tex": [pm_tex]}
    with_no = {"ath": [Leg("kalshi", liquidity_source_for("kalshi"), "ATH", "e",
                           kalshi_book(ath, "yes", T), {"fee_multiplier": 0.0}),
                       Leg("kalshi", liquidity_source_for("kalshi"), "TEX:NO", "e",
                           kalshi_book(tex, "no", T), {"fee_multiplier": 0.0})],
               "tex": [pm_tex]}

    a = frontier(yes_only, now_utc=T, proof=PROOF, cross_venue_only=False)
    b = frontier(with_no, now_utc=T, proof=PROOF, cross_venue_only=False)
    assert b.n_max > a.n_max, "the extra book must raise capacity, not just prices"


def test_a_no_leg_keeps_its_own_ticker_so_double_counting_is_still_caught():
    """The liquidity_source guard must still fire on two renderings of ONE book."""
    same = kalshi_book(PAYLOAD, "yes", T)
    offers = {"ath": [Leg("kalshi", "kalshi_clob", "ATH", "e", same)],
              "tex": [Leg("kalshi", "kalshi_clob", "ATH", "e", same)]}
    got = best_cover(offers, 10, now_utc=T, proof=PROOF)
    assert got.reject_reason == "shared_liquidity_source"


def test_an_empty_side_is_absent_rather_than_a_zero_priced_leg():
    one_sided = {"orderbook_fp": {"yes_dollars": [[0.40, 100]], "no_dollars": []}}
    assert kalshi_book(one_sided, "yes", T).asks == ()


def test_a_ladder_as_long_as_the_request_is_flagged_truncated_and_rest_labelled():
    full = {"orderbook_fp": {"yes_dollars": [[0.40 - i * 0.01, 10] for i in range(20)],
                             "no_dollars": [[0.55, 300]]}}
    b = kalshi_book(full, "yes", T, depth_requested=20)
    assert b.depth_truncated and b.source == "rest"
    assert not kalshi_book(PAYLOAD, "yes", T, depth_requested=20).depth_truncated
    assert not kalshi_book(full, "yes", T).depth_truncated, "no request depth known: no claim"
