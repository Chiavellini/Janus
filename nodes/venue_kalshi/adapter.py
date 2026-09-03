#!/usr/bin/env python3
"""Kalshi in the venue registry.

Registration is what makes `kernel.venue_registry.independent()` and `tradeable_names()` mean
something for the two venues actually scanned; until now only the parked Cloudbet adapter was
registered, so the dedup guard the registry documents fired only inside `nodes/cover`.

Discovery lives in `nodes/discovery` (schedule-anchored, not venue-driven), so `discover()` and
`normalize()` deliberately return nothing here rather than pretending. `quote()` is the REST book.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from kernel.fetch import Client
from kernel.schema import Book, NormMarket, liquidity_source_for
from kernel.venue_protocol import BaseAdapter, VenueConfig
from kernel.venue_registry import register
from nodes.venue_kalshi.books import KALSHI_BASE, fetch_kalshi_books


@register("kalshi")
class KalshiAdapter(BaseAdapter):
    venue = "kalshi"
    liquidity_source = liquidity_source_for("kalshi")
    fee_model_id = "kalshi_quadratic"
    supports = frozenset({"depth", "ws", "auth_required", "maker", "sell"})
    data_quality = "live"
    config = VenueConfig(base_url=KALSHI_BASE, rate=8.0, burst=8.0, cache_ttl_s=None,
                         auth_mode="rsa_pss", timeout=20.0)

    def discover(self, *, leagues: Sequence[str] | None = None,
                 start_window: tuple[int, int] | None = None) -> Iterable[Mapping[str, Any]]:
        return ()                      # schedule-anchored discovery lives in nodes/discovery

    def normalize(self, raw: Mapping[str, Any]) -> NormMarket | None:
        return None

    def quote(self, markets: Sequence[NormMarket], *, depth: int = 10) -> Mapping[str, Book]:
        cl = Client("kalshi", rate=self.config.rate, burst=self.config.burst, cache_dir=None)
        return fetch_kalshi_books([m.venue_market_id for m in markets], cl)
