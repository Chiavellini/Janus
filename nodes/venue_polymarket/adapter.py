#!/usr/bin/env python3
"""Polymarket in the venue registry. See nodes/venue_kalshi/adapter.py for why this exists."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from kernel.fetch import Client
from kernel.schema import Book, NormMarket, liquidity_source_for
from kernel.venue_protocol import BaseAdapter, VenueConfig
from kernel.venue_registry import register
from nodes.venue_polymarket.books import PM_CLOB, fetch_pm_books


@register("polymarket")
class PolymarketAdapter(BaseAdapter):
    venue = "polymarket"
    liquidity_source = liquidity_source_for("polymarket")
    fee_model_id = "pm_quadratic"
    supports = frozenset({"depth", "ws", "maker", "sell"})
    data_quality = "live"
    config = VenueConfig(base_url=PM_CLOB, rate=8.0, burst=8.0, cache_ttl_s=None,
                         auth_mode="none", timeout=20.0)

    def discover(self, *, leagues: Sequence[str] | None = None,
                 start_window: tuple[int, int] | None = None) -> Iterable[Mapping[str, Any]]:
        return ()                      # schedule-anchored discovery lives in nodes/discovery

    def normalize(self, raw: Mapping[str, Any]) -> NormMarket | None:
        return None

    def quote(self, markets: Sequence[NormMarket], *, depth: int = 10) -> Mapping[str, Book]:
        cl = Client("polymarket", rate=self.config.rate, burst=self.config.burst, cache_dir=None)
        # venue_market_id is the CLOB token id for a Polymarket outcome.
        return fetch_pm_books({m.venue_market_id: m.venue_market_id for m in markets}, cl)
