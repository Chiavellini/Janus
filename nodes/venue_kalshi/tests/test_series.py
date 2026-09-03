#!/usr/bin/env python3
"""The series fee schedule, and the registry entry."""
from __future__ import annotations

import nodes.venue_kalshi  # noqa: F401  -- registers the adapter
from kernel import venue_registry
from kernel.schema import liquidity_source_for
from nodes.venue_kalshi.books import kalshi_fee_params

#: Verbatim shape of GET /series/KXMLBGAME on 2026-09-02.
SERIES = {"series": {"ticker": "KXMLBGAME", "fee_type": "quadratic_with_maker_fees",
                     "fee_multiplier": 0.5, "category": "Sports"}}


def test_sports_is_not_the_crypto_tier():
    fp = kalshi_fee_params(SERIES)
    assert fp == {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 0.5}


def test_the_unwrapped_record_is_accepted_too():
    assert kalshi_fee_params(SERIES["series"]) == kalshi_fee_params(SERIES)


def test_a_missing_multiplier_is_none_not_one():
    assert kalshi_fee_params({"series": {"fee_type": "quadratic"}}) is None
    assert kalshi_fee_params({"series": {"fee_multiplier": 1.0}}) is None
    assert kalshi_fee_params({}) is None


def test_kalshi_is_registered_live_and_independent_of_polymarket():
    import nodes.venue_polymarket  # noqa: F401
    a = venue_registry.get("kalshi")
    assert a.tradeable() and a.liquidity_source == liquidity_source_for("kalshi")
    assert venue_registry.independent(["kalshi", "polymarket"])
    assert not venue_registry.independent(["kalshi", "kalshi"])
