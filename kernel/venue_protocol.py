#!/usr/bin/env python3
"""The venue adapter contract. Adding a venue must mean writing ONE file, not touching five.

Phase 1 had no abstraction at all — zero dataclasses, zero Protocols, zero registries. A third
venue required edits to a new enumerator, `nodes/fees/venue_costs.py`, the candidate-generation stage (a new text
extractor), an earlier screen (a new fee function), plus a rewrite of the two-direction trade
algebra and the pair-key tuple. That is why the corpus stayed at two venues.

────────────────────────────────────────────────────────────────────────────
THREE RULES THAT ARE NOT STYLE PREFERENCES
────────────────────────────────────────────────────────────────────────────
1. `normalize()` MUST BE PURE. Raw dict in, NormMarket out, no network, no clock, no randomness.
   This buys frozen-fixture golden tests, byte-identical reruns (the existing determinism gate),
   and the ability to re-parse an archived payload after a schema change without re-fetching.

2. `data_quality` IS LOAD-BEARING, not documentation. A "delayed" adapter — e.g. Betfair on its
   free development key — may contribute to a MEASUREMENT of divergence but must be structurally
   barred from any tradeability claim. The screen enforces this; convention would not.

3. `liquidity_source` DEDUPLICATES. Robinhood, Webull and IBKR all report "kalshi_clob". The cover
   enumerator refuses to treat two legs sharing a liquidity source as independent. Without this,
   the scanner eventually reports a beautiful arbitrage between a book and itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol, Sequence, runtime_checkable

from kernel.schema import Book, NormMarket, Outcome, SettleRef


@dataclass(frozen=True)
class VenueConfig:
    """Per-host settings. Rate limits were hardcoded at call sites in phase 1; they live here now."""
    base_url: str
    rate: float = 4.0                 # requests/sec sustained
    burst: float = 8.0
    cache_ttl_s: float | None = 3600.0
    auth_mode: str = "none"           # "none" | "bearer" | "rsa_pss" | "api_key" | "session"
    timeout: float = 40.0


@dataclass(frozen=True)
class Capacity:
    """How much you could actually do, and what stopped you.

    Phase 1's mentions track found capacity ($4 median at touch) binding BEFORE edge did, so this
    is a first-pass screen rather than a late portfolio step.
    """
    contracts: float
    usd: float
    limited_by: str                   # "depth" | "venue_max" | "min_order" | "account_limit"


@dataclass(frozen=True)
class AdapterHealth:
    ok: bool
    checked_utc: float
    detail: str = ""
    quote_age_p50_s: float | None = None


@runtime_checkable
class VenueAdapter(Protocol):
    """What every venue must provide. Return 0/empty rather than raising for unsupported ops."""

    venue: str
    liquidity_source: str
    fee_model_id: str
    supports: frozenset          # {"sell","short","maker","depth","ws","auth_required"}
    data_quality: str            # "live" | "delayed" | "polled"
    config: VenueConfig

    def discover(self, *, leagues: Sequence[str] | None = None,
                 start_window: tuple[int, int] | None = None) -> Iterable[Mapping[str, Any]]:
        """Raw market payloads. Network lives here and ONLY here (plus `quote`)."""
        ...

    def normalize(self, raw: Mapping[str, Any]) -> NormMarket | None:
        """Raw payload -> NormMarket. PURE. Returns None for markets this adapter skips."""
        ...

    def quote(self, markets: Sequence[NormMarket], *, depth: int = 10) -> Mapping[str, Book]:
        """Fresh books keyed by outcome_id. Every Book MUST carry a real `fetched_utc`."""
        ...

    def settle_ref(self, m: NormMarket) -> SettleRef: ...

    def capacity(self, m: NormMarket, outcome: Outcome, price: float) -> Capacity: ...

    def health(self) -> AdapterHealth: ...


class BaseAdapter:
    """Optional convenience base. Implements the boring parts; override what matters."""

    venue: str = "unset"
    liquidity_source: str = "unset"
    fee_model_id: str = "embedded"
    supports: frozenset = frozenset()
    data_quality: str = "polled"
    config: VenueConfig = VenueConfig(base_url="")

    def settle_ref(self, m: NormMarket) -> SettleRef:
        return m.settle_ref

    def capacity(self, m: NormMarket, outcome: Outcome, price: float) -> Capacity:
        contracts = outcome.book.depth_to(price)
        if contracts < m.min_order_contracts:
            return Capacity(0.0, 0.0, "min_order")
        return Capacity(contracts, contracts * price, "depth")

    def health(self) -> AdapterHealth:
        import time
        return AdapterHealth(ok=True, checked_utc=time.time(), detail="no health check implemented")

    def tradeable(self) -> bool:
        """Whether this adapter's prices may back a TRADEABILITY claim, as opposed to a measurement.

        Delayed data bounds divergence; it never evidences that a trade was available.
        """
        return self.data_quality == "live"
