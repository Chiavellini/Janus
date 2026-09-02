#!/usr/bin/env python3
"""Cloudbet Feed API adapter and sportsbook-to-payout normalization.

Cloudbet is a sportsbook, not a binary prediction-market CLOB. A back selection therefore
contributes one one-sided ask: decimal odds ``d`` become price ``1 / d`` and a displayed stake
limit ``S`` becomes ``S / price`` payout contracts. There is deliberately no synthetic NO side.

The feed is indicative. ``maxStake`` is a displayed limit, not an accepted fill, and in-play bets
can be delayed, rejected, reduced, or kept pending. A Cloudbet leg is consequently non-executable
until the trading API accepts the exact stake and (if applicable) odds. The cover screen enforces
that flag before it can emit an actionable opportunity.

This module has no credentials and performs no network I/O during normalization. The API key is
passed explicitly or read from ``JANUS_CLOUDBET_API_KEY`` by the optional ``from_env`` constructor;
it is never written to a cache or artifact.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlencode

from kernel.fetch import Client
from kernel.schema import (
    Book,
    NormMarket,
    Outcome,
    Quote,
    SettleRef,
    VoidPolicy,
    TiePolicy,
    decimal_odds_to_price,
    liquidity_source_for,
    stake_to_contracts,
)
from kernel.venue_protocol import BaseAdapter, VenueConfig
from kernel.venue_registry import register


CLOUDBET_BASE = "https://sports-api.cloudbet.com/pub/v2"
ENABLED_STATUSES = frozenset({"SELECTION_ENABLED", "ENABLED"})
DISABLED_STATUSES = frozenset({
    "SELECTION_DISABLED", "DISABLED", "SUSPENDED", "CLOSED", "SETTLED",
})
EVENT_TRADEABLE_STATUSES = frozenset({"TRADING", "TRADING_LIVE"})


def _items(value: Any) -> list[Mapping[str, Any]]:
    """Turn either a JSON list or a keyed JSON object into a list of objects."""
    if value is None:
        return []
    if isinstance(value, Mapping):
        if any(k in value for k in ("id", "key", "name", "price", "selectionId")):
            return [value]
        return [v for v in value.values() if isinstance(v, Mapping)]
    if isinstance(value, (list, tuple)):
        return [v for v in value if isinstance(v, Mapping)]
    return []


def _keyed_items(value: Any) -> list[tuple[str, Mapping[str, Any]]]:
    """Preserve keys from Cloudbet's proto-json maps."""
    if isinstance(value, Mapping):
        return [(str(key), item) for key, item in value.items() if isinstance(item, Mapping)]
    if isinstance(value, (list, tuple)):
        out: list[tuple[str, Mapping[str, Any]]] = []
        for item in value:
            if isinstance(item, Mapping):
                key = _text(item.get("key", item.get("marketKey", item.get("submarketKey", ""))))
                out.append((key, item))
        return out
    return []


def _text(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ("name", "label", "value", "key", "id"):
            if value.get(key) is not None:
                return str(value[key])
        return ""
    return "" if value is None else str(value)


def _number(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n and n not in (float("inf"), float("-inf")) else None


def _timestamp(value: Any) -> int | None:
    if value is None:
        return None
    n = _number(value)
    if n is not None:
        return int(n)
    text = str(value).replace("Z", "+00:00")
    try:
        return int(datetime.fromisoformat(text).timestamp())
    except ValueError:
        return None


def market_url(market_key: str, outcome: str, params: str = "") -> str:
    """Build the line ID required by Cloudbet's Trading API."""
    base = f"{market_key}/{outcome}"
    return f"{base}?{params}" if params else base


def event_status(event: Mapping[str, Any]) -> str:
    return _text(event.get("status")).upper()


def event_start_utc(event: Mapping[str, Any]) -> int | None:
    """Use Cloudbet's structured start time; a missing start is a join BLOCK."""
    return _timestamp(event.get("startTime", event.get("start_time")))


def event_team_name(event: Mapping[str, Any], side: str) -> str:
    """Resolve a Cloudbet home/away TeamIdentifier to its display name."""
    return _text((event.get(side) or {}).get("name")) if isinstance(event.get(side), Mapping) else ""


@dataclass(frozen=True)
class CloudbetSelection:
    event_id: str
    market_key: str
    submarket_key: str
    selection_id: str
    outcome: str
    params: str
    decimal_odds: float
    min_stake: float
    max_stake: float
    status: str
    fetched_utc: float
    accepted: bool = False
    accepted_stake: float | None = None

    @property
    def price(self) -> float:
        return decimal_odds_to_price(self.decimal_odds)

    @property
    def stake_limit(self) -> float:
        return self.accepted_stake if self.accepted_stake is not None else self.max_stake

    @property
    def contracts(self) -> float:
        return stake_to_contracts(self.stake_limit, self.price)

    def accepted_offer(self, stake: float, *, odds: float | None = None) -> "CloudbetSelection":
        """Return a locked selection after the trading API accepts ``stake``.

        A lower accepted stake is valid; an accepted stake above the displayed maximum is not
        silently trusted. Odds returned by the acceptance response replace the feed odds.
        """
        if stake <= 0 or stake > self.max_stake + 1e-9:
            raise ValueError(f"accepted stake {stake!r} exceeds displayed Cloudbet limit")
        accepted_odds = self.decimal_odds if odds is None else float(odds)
        if accepted_odds <= 1.0:
            raise ValueError(f"accepted decimal odds must be > 1.0, got {accepted_odds!r}")
        return CloudbetSelection(
            event_id=self.event_id, market_key=self.market_key, submarket_key=self.submarket_key,
            selection_id=self.selection_id, outcome=self.outcome, params=self.params,
            decimal_odds=accepted_odds,
            min_stake=self.min_stake, max_stake=self.max_stake, status=self.status,
            fetched_utc=self.fetched_utc, accepted=True, accepted_stake=float(stake),
        )

    @property
    def market_url(self) -> str:
        return market_url(self.market_key, self.outcome, self.params)


def parse_selection(raw: Mapping[str, Any], *, event_id: str, market_key: str,
                    submarket_key: str, fetched_utc: float) -> CloudbetSelection | None:
    """Parse one documented Cloudbet BACK selection; unknown/disabled offers are skipped."""
    side = _text(raw.get("side")).upper()
    status = _text(raw.get("status")).upper()
    # The documented enum is SELECTION_ENABLED/SELECTION_DISABLED. Missing or future statuses
    # are not assumed tradeable; a parser should lose coverage rather than manufacture a quote.
    if side != "BACK" or status not in ENABLED_STATUSES:
        return None
    odds = _number(raw.get("price", raw.get("odds")))
    min_stake = _number(raw.get("minStake", raw.get("min_stake")))
    max_stake = _number(raw.get("maxStake", raw.get("max_stake")))
    if odds is None or odds <= 1.0 or min_stake is None or max_stake is None or max_stake <= 0:
        return None
    outcome = _text(raw.get("outcome", raw.get("name", raw.get("label"))))
    params = _text(raw.get("params", raw.get("groupingParameters", "")))
    if not outcome:
        return None
    # Feed Selection has no ID. The market URL is the stable line identity and is also the exact
    # identifier required by the Trading API. Include event ID to make it unique across events.
    selection_id = f"{event_id}:{market_url(market_key, outcome, params)}"
    return CloudbetSelection(
        event_id=event_id, market_key=market_key, submarket_key=submarket_key,
        selection_id=selection_id, outcome=outcome, params=params, decimal_odds=odds,
        min_stake=max(0.0, min_stake), max_stake=max_stake, status=status,
        fetched_utc=float(fetched_utc),
    )


@dataclass(frozen=True)
class CloudbetEventMarket:
    event: Mapping[str, Any]
    market: Mapping[str, Any]
    submarket: Mapping[str, Any]
    market_key: str
    submarket_key: str
    selections: tuple[CloudbetSelection, ...]


def iter_event_markets(payload: Mapping[str, Any], *, fetched_utc: float) -> Iterable[CloudbetEventMarket]:
    """Yield each event/submarket from a competition or event response."""
    events = _items(payload.get("events"))
    if not events and isinstance(payload.get("event"), Mapping):
        events = [payload["event"]]
    if not events and (payload.get("id") or payload.get("eventId")):
        events = [payload]
    for event in events:
        event_id = _text(event.get("id", event.get("eventId", event.get("key"))))
        for market_key, market in _keyed_items(event.get("markets")):
            market_key = market_key or _text(market.get("marketKey", market.get("key")))
            submarkets = _keyed_items(market.get("submarkets"))
            if not submarkets and market.get("selections") is not None:
                submarkets = [("default", market)]
            for submarket_key, submarket in submarkets:
                submarket_key = submarket_key or _text(submarket.get("submarketKey", submarket.get("key", "default")))
                selections = tuple(
                    selection for raw in _items(submarket.get("selections"))
                    if (selection := parse_selection(
                        raw, event_id=event_id, market_key=market_key,
                        submarket_key=submarket_key, fetched_utc=fetched_utc)) is not None
                )
                if selections:
                    yield CloudbetEventMarket(event, market, submarket, market_key, submarket_key,
                                              selections)


def cloudbet_book(selection: CloudbetSelection) -> Book:
    """Convert one Cloudbet BACK selection to a one-sided payout-unit ask."""
    return Book(
        asks=(Quote(selection.price, selection.contracts),),
        fetched_utc=selection.fetched_utc,
        one_sided=True,
    )


def cloudbet_leg(selection: CloudbetSelection, *, market_id: str | None = None,
                outcome_id: str | None = None):
    """Build a cover leg; feed selections remain non-executable until accepted."""
    from nodes.cover.cover import Leg

    return Leg(
        venue="cloudbet", liquidity_source=liquidity_source_for("cloudbet"),
        outcome_id=outcome_id or selection.outcome, market_id=market_id or selection.event_id,
        book=cloudbet_book(selection), executable=selection.accepted,
    )


def normalize_event_market(item: CloudbetEventMarket, *, fetched_utc: float) -> NormMarket:
    """Purely normalize one Cloudbet event/submarket into Janus' common schema.

    The canonical sports key is intentionally left unset. It must be supplied by the external
    schedule matcher; Cloudbet titles are not a safe source of participant identity or start time.
    """
    event = item.event
    event_id = _text(event.get("id", event.get("eventId", event.get("key"))))
    market_key = item.market_key
    submarket_key = item.submarket_key
    outcomes = tuple(
        Outcome(
            outcome_id=s.selection_id, canonical_side=s.outcome, book=cloudbet_book(s),
            can_sell=False, can_short_direct=False,
        ) for s in item.selections
    )
    return NormMarket(
        venue="cloudbet", liquidity_source=liquidity_source_for("cloudbet"),
        venue_market_id=f"{event_id}:{market_key}:{submarket_key}", outcomes=outcomes,
        fee_model_id="embedded", settle_ref=SettleRef(
            oracle="official_league", void_policy=VoidPolicy.UNKNOWN,
            tie_policy=TiePolicy.UNKNOWN, provenance="assumed",
            terms_url="https://www.cloudbet.com/en/help/rules?section=settlement_and_cancellation_rules",
        ), raw_title=_text(event.get("name", event.get("key"))) or event_id,
        fetched_utc=float(fetched_utc), close_utc=_timestamp(event.get("cutoffTime")),
        exhaustive=False, rules_url="https://www.cloudbet.com/en/help/rules?section=settlement_and_cancellation_rules",
    )


class CloudbetFeedClient:
    """Credential-explicit client for the Cloudbet Feed API."""

    def __init__(self, api_key: str, *, client: Client | None = None,
                 base_url: str = CLOUDBET_BASE, feed_tier: str = "affiliate"):
        if not api_key or not api_key.strip():
            raise ValueError("Cloudbet API key is required")
        if feed_tier not in {"trading", "affiliate"}:
            raise ValueError("feed_tier must be 'trading' or 'affiliate'")
        self.api_key = api_key
        self.feed_tier = feed_tier
        self.data_quality = "live" if feed_tier == "trading" else "delayed"
        self.client = client or Client("cloudbet", rate=4, burst=8, cache_dir=None)
        self.base_url = base_url.rstrip("/")

    @classmethod
    def from_env(cls, variable: str = "JANUS_CLOUDBET_API_KEY", **kwargs) -> "CloudbetFeedClient":
        key = os.environ.get(variable, "")
        if not key:
            raise RuntimeError(f"missing {variable}; credentials are not stored in Janus")
        kwargs.setdefault("feed_tier", os.environ.get("JANUS_CLOUDBET_FEED_TIER", "affiliate"))
        return cls(key, **kwargs)

    def _get(self, path: str, params: Sequence[tuple[str, str]] = ()):
        url = f"{self.base_url}/{path.lstrip('/')}"
        if params:
            url += "?" + urlencode(list(params))
        return self.client.get_json(
            url, use_cache=False,
            headers={"X-API-Key": self.api_key, "Accept": "application/json",
                     "Content-Type": "application/json"},
        )

    def competition(self, key: str, *, markets: Sequence[str] = ()) -> Mapping[str, Any]:
        params = [("markets", market) for market in markets]
        return self._get(f"odds/competitions/{key}", params)

    def event(self, event_id: str) -> Mapping[str, Any]:
        return self._get(f"odds/events/{event_id}")

    def sports(self) -> Mapping[str, Any]:
        return self._get("odds/sports")


@register("cloudbet")
class CloudbetAdapter(BaseAdapter):
    venue = "cloudbet"
    liquidity_source = "cloudbet_sportsbook"
    fee_model_id = "embedded"
    supports = frozenset({"depth", "auth_required"})
    data_quality = "polled"
    config = VenueConfig(
        base_url=CLOUDBET_BASE, rate=4.0, burst=8.0, cache_ttl_s=None,
        auth_mode="api_key", timeout=10.0,
    )

    def __init__(self, api_key: str | None = None, *, feed: CloudbetFeedClient | None = None,
                 feed_tier: str = "affiliate"):
        self._api_key = api_key
        self._feed = feed
        self._feed_tier = feed_tier
        self.data_quality = feed.data_quality if feed is not None else "polled"

    def _client(self) -> CloudbetFeedClient:
        if self._feed is not None:
            return self._feed
        if self._api_key:
            self._feed = CloudbetFeedClient(self._api_key, feed_tier=self._feed_tier)
            self.data_quality = self._feed.data_quality
            return self._feed
        self._feed = CloudbetFeedClient.from_env()
        self.data_quality = self._feed.data_quality
        return self._feed

    def discover(self, *, leagues=None, start_window=None):
        """Discover by explicit Cloudbet competition keys supplied in ``leagues``."""
        if not leagues:
            return
        feed = self._client()
        for league in leagues:
            payload = feed.competition(league)
            competition = payload.get("competition") if isinstance(payload, Mapping) else None
            events = payload.get("events") if isinstance(payload, Mapping) else None
            if not events and isinstance(competition, Mapping):
                events = competition.get("events")
            yield from _items(events)

    def normalize(self, raw: Mapping[str, Any]) -> NormMarket | None:
        items = tuple(iter_event_markets(raw, fetched_utc=float(raw.get("_janus_fetched_utc", 0.0))))
        return normalize_event_market(items[0], fetched_utc=items[0].selections[0].fetched_utc) if items else None

    def quote(self, markets, *, depth: int = 10):
        feed = self._client()
        out = {}
        for market in markets:
            parts = market.venue_market_id.split(":", 2)
            if len(parts) != 3:
                continue
            payload = feed.event(parts[0])
            fetched_utc = time.time()
            for item in iter_event_markets(payload, fetched_utc=fetched_utc):
                if item.market_key != parts[1] or item.submarket_key != parts[2]:
                    continue
                out.update({selection.selection_id: cloudbet_book(selection)
                            for selection in item.selections})
        return out

    def health(self):
        return super().health()
