#!/usr/bin/env python3
"""Venue adapter registry. Dispatch by NormMarket.venue; iterate for symmetric matching.

the candidate-generation stage built its inverted index over Polymarket only and looped over Kalshi, so the
matcher had a PRIVILEGED DIRECTION baked in. Iterating this registry is what removes that: every
venue is indexed the same way, and adding a third does not change the loop.
"""

from __future__ import annotations

from typing import Callable, Iterator

from kernel.venue_protocol import VenueAdapter

_REGISTRY: dict[str, VenueAdapter] = {}


def register(name: str) -> Callable:
    """Class decorator: @register("kalshi") on the adapter class."""
    def deco(cls):
        inst = cls() if isinstance(cls, type) else cls
        if name in _REGISTRY:
            raise KeyError(f"venue {name!r} already registered")
        _REGISTRY[name] = inst
        return cls
    return deco


def get(name: str) -> VenueAdapter:
    if name not in _REGISTRY:
        raise KeyError(f"no adapter for venue {name!r}; registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def all_adapters() -> Iterator[VenueAdapter]:
    return iter(_REGISTRY.values())


def names() -> list[str]:
    return sorted(_REGISTRY)


def tradeable_names() -> list[str]:
    """Venues whose prices may back a tradeability claim (data_quality == 'live')."""
    return sorted(n for n, a in _REGISTRY.items() if getattr(a, "data_quality", "") == "live")


def independent(venues: list[str]) -> bool:
    """False if any two venues share a liquidity source — i.e. it is not a real cross-venue trade.

    Robinhood/Webull/IBKR all route to Kalshi's book. This guard is what stops the cover
    enumerator reporting an arbitrage between a book and itself.
    """
    sources = [get(v).liquidity_source for v in venues]
    return len(set(sources)) == len(sources)
