#!/usr/bin/env python3
"""Fail-closed Cloudbet Trading API acceptance and reconciliation.

This module intentionally has no order capability enabled by default. It is the boundary for a
future credentialed shadow/paper run: one POST, durable ``PENDING`` journal entry first, no client
retry after a timeout, then an explicit status reconciliation using the same provider reference.
Only provider-confirmed odds and stake may be passed to the cover screen.
"""

from __future__ import annotations

import socket
import time
import uuid
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Mapping, Protocol

from kernel.fetch import Client
from nodes.venue_cloudbet.feed import CloudbetSelection


TRADING_BASE = "https://sports-api.cloudbet.com/pub/v4"
_EPS = 1e-9


class AcceptanceState(str, Enum):
    PENDING = "PENDING"
    REJECTED = "REJECTED"
    REDUCED = "REDUCED"
    ACCEPTED = "ACCEPTED"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


TERMINAL_STATES = frozenset({
    AcceptanceState.REJECTED, AcceptanceState.REDUCED, AcceptanceState.ACCEPTED,
})


class TradingDisabled(RuntimeError):
    """Raised before any network call while the safety switch is off."""


class AcceptanceConflict(ValueError):
    """The same reference UUID was reused with a different request."""


class AcceptanceJournal(Protocol):
    def get_cloudbet_acceptance(self, reference_id: str) -> "CloudbetAcceptance | None": ...

    def put_cloudbet_acceptance(self, result: "CloudbetAcceptance") -> None: ...


@dataclass(frozen=True)
class CloudbetBetRequest:
    reference_id: str
    event_id: str
    market_url: str
    price: float
    stake: float
    currency: str
    side: str = "BACK"
    accept_price_change: str = "BETTER"
    accept_partial_stake: bool = True

    def __post_init__(self) -> None:
        try:
            uuid.UUID(self.reference_id)
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("reference_id must be a UUID") from exc
        if not self.event_id or not self.market_url or self.side != "BACK":
            raise ValueError("Cloudbet requests require event, market URL, and BACK side")
        if self.price <= 1.0 or self.stake <= 0 or not self.currency:
            raise ValueError("Cloudbet request has invalid price, stake, or currency")
        if self.accept_price_change not in {"NONE", "BETTER"}:
            raise ValueError("accept_price_change must be NONE or BETTER")

    @classmethod
    def from_selection(cls, selection: CloudbetSelection, *, stake: float, currency: str,
                       reference_id: str, accept_price_change: str = "BETTER",
                       accept_partial_stake: bool = True) -> "CloudbetBetRequest":
        if selection.accepted:
            raise ValueError("cannot submit an already accepted Cloudbet selection")
        if stake < selection.min_stake - _EPS or stake > selection.max_stake + _EPS:
            raise ValueError("requested stake is outside the displayed Cloudbet bounds")
        return cls(reference_id=reference_id, event_id=selection.event_id,
                   market_url=selection.market_url, price=selection.decimal_odds,
                   stake=float(stake), currency=currency, accept_price_change=accept_price_change,
                   accept_partial_stake=accept_partial_stake)

    def payload(self) -> dict[str, str]:
        # Strings match Cloudbet's proto-json examples and avoid binary floating-point formatting
        # changing the exact request fingerprint.
        return {
            "currency": self.currency,
            "referenceId": self.reference_id,
            "stake": format(self.stake, ".12g"),
            "acceptPartialStake": self.accept_partial_stake,
            "priceChange": {"value": self.accept_price_change},
            "selection": {
                "eventId": self.event_id, "marketUrl": self.market_url,
                "price": format(self.price, ".12g"),
            },
        }

    @property
    def fingerprint(self) -> tuple:
        return (self.event_id, self.market_url, round(self.price, 12), round(self.stake, 12),
                self.currency, self.side, self.accept_price_change, self.accept_partial_stake)


@dataclass(frozen=True)
class CloudbetAcceptance:
    reference_id: str
    state: AcceptanceState
    event_id: str
    market_url: str
    requested_price: float
    requested_stake: float
    currency: str
    accept_price_change: str = "BETTER"
    accept_partial_stake: bool = True
    accepted_price: float | None = None
    accepted_stake: float | None = None
    provider_status: str = ""
    error: str = ""
    observed_utc: float = 0.0

    @property
    def fingerprint(self) -> tuple:
        return (self.event_id, self.market_url, round(self.requested_price, 12),
                round(self.requested_stake, 12), self.currency, "BACK", self.accept_price_change,
                self.accept_partial_stake)

    @property
    def executable(self) -> bool:
        return self.state in TERMINAL_STATES and self.accepted_price is not None \
            and self.accepted_stake is not None and self.accepted_stake > 0


def pending_for(request: CloudbetBetRequest, *, now: float | None = None) -> CloudbetAcceptance:
    return CloudbetAcceptance(
        reference_id=request.reference_id, state=AcceptanceState.PENDING,
        event_id=request.event_id, market_url=request.market_url,
        requested_price=request.price, requested_stake=request.stake, currency=request.currency,
        accept_price_change=request.accept_price_change,
        accept_partial_stake=request.accept_partial_stake,
        observed_utc=time.time() if now is None else now,
    )


def _num(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n and n not in (float("inf"), float("-inf")) else None


def parse_acceptance(request: CloudbetBetRequest, payload: Mapping[str, Any], *, now: float | None = None) -> CloudbetAcceptance:
    """Parse one provider response, rejecting mismatched identity or missing economics."""
    observed = time.time() if now is None else now
    if not isinstance(payload, Mapping):
        return _unknown(request, "response_not_object", observed)
    reference = str(payload.get("referenceId", payload.get("reference_id", "")))
    if reference != request.reference_id:
        return _unknown(request, "reference_id_mismatch", observed)
    selection = payload.get("selection") if isinstance(payload.get("selection"), Mapping) else {}
    event_id = str(selection.get("eventId", payload.get("eventId", payload.get("event_id", ""))))
    market_url_value = str(selection.get("marketUrl", payload.get("marketUrl", payload.get("market_url", ""))))
    if event_id != request.event_id or market_url_value != request.market_url:
        return _unknown(request, "market_identity_mismatch", observed)
    status = str(payload.get("state", payload.get("status", ""))).upper()
    error = str(payload.get("rejectionCode", payload.get("error", "")) or "")
    if status == "PENDING_ACCEPTANCE":
        return CloudbetAcceptance(reference, AcceptanceState.PENDING, request.event_id,
                                  request.market_url, request.price, request.stake,
                                  request.currency, request.accept_price_change,
                                  provider_status=status, error=error,
                                  observed_utc=observed)
    if status not in {"ACCEPTED", "COMPLETED"}:
        if not status:
            return _unknown(request, "missing_provider_status", observed)
        return CloudbetAcceptance(reference, AcceptanceState.REJECTED, request.event_id,
                                  request.market_url, request.price, request.stake,
                                  request.currency, request.accept_price_change,
                                  provider_status=status, error=error,
                                  observed_utc=observed)
    accepted_price = _num(selection.get("price", payload.get("price")))
    accepted_stake = _num(payload.get("stake"))
    if accepted_price is None or accepted_price <= 1.0 or accepted_stake is None or accepted_stake <= 0:
        return _unknown(request, "accepted_response_missing_economics", observed)
    if accepted_stake > request.stake + _EPS:
        return _unknown(request, "accepted_stake_exceeds_requested", observed)
    state = AcceptanceState.ACCEPTED if abs(accepted_stake - request.stake) <= _EPS else AcceptanceState.REDUCED
    return CloudbetAcceptance(reference, state, request.event_id, request.market_url,
                              request.price, request.stake, request.currency,
                              request.accept_price_change,
                              accepted_price=accepted_price, accepted_stake=accepted_stake,
                              provider_status=status, error=error, observed_utc=observed)


def _unknown(request: CloudbetBetRequest, error: str, observed: float) -> CloudbetAcceptance:
    return CloudbetAcceptance(request.reference_id, AcceptanceState.UNKNOWN, request.event_id,
                              request.market_url, request.price, request.stake, request.currency,
                              request.accept_price_change,
                              error=error, observed_utc=observed)


class CloudbetTradingClient:
    """Credential-explicit Trading API client; submission is opt-in and non-retrying."""

    def __init__(self, api_key: str, *, journal: AcceptanceJournal, client: Client | None = None,
                 base_url: str = TRADING_BASE, submit_enabled: bool = False):
        if not api_key or not api_key.strip():
            raise ValueError("Cloudbet Trading API key is required")
        self.api_key = api_key
        self.journal = journal
        self.client = client or Client("cloudbet-trading", rate=4, burst=8, cache_dir=None, timeout=10)
        self.base_url = base_url.rstrip("/")
        self.submit_enabled = bool(submit_enabled)

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key, "Accept": "application/json",
                "Content-Type": "application/json"}

    @staticmethod
    def _check_existing(request: CloudbetBetRequest, prior: CloudbetAcceptance | None) -> CloudbetAcceptance | None:
        if prior is None:
            return None
        if prior.fingerprint != request.fingerprint:
            raise AcceptanceConflict("reference_id already belongs to a different Cloudbet request")
        # PENDING, TIMEOUT, and UNKNOWN are returned as-is. The caller must explicitly reconcile;
        # place() never turns an ambiguous provider result into a second POST.
        return prior

    def place(self, request: CloudbetBetRequest) -> CloudbetAcceptance:
        if not self.submit_enabled:
            raise TradingDisabled("Cloudbet submission disabled; no request was sent")
        prior = self._check_existing(request, self.journal.get_cloudbet_acceptance(request.reference_id))
        if prior is not None:
            return prior
        self.journal.put_cloudbet_acceptance(pending_for(request))
        try:
            payload = self.client.post_json_once(
                f"{self.base_url}/bets/place", request.payload(), headers=self._headers())
        except (TimeoutError, socket.timeout):
            result = _unknown(request, "transport_timeout", time.time())
            result = replace(result, state=AcceptanceState.TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            result = _unknown(request, f"transport_{type(exc).__name__}", time.time())
        else:
            result = parse_acceptance(request, payload)
        self.journal.put_cloudbet_acceptance(result)
        return result

    def reconcile(self, reference_id: str) -> CloudbetAcceptance:
        prior = self.journal.get_cloudbet_acceptance(reference_id)
        if prior is None:
            raise KeyError(f"unknown Cloudbet reference_id {reference_id!r}")
        if prior.state in TERMINAL_STATES:
            return prior
        request = CloudbetBetRequest(reference_id=prior.reference_id, event_id=prior.event_id,
                                     market_url=prior.market_url, price=prior.requested_price,
                                     stake=prior.requested_stake, currency=prior.currency,
                                     accept_price_change=prior.accept_price_change,
                                     accept_partial_stake=prior.accept_partial_stake)
        try:
            payload = self.client.get_json(
                f"{self.base_url}/bets", params={"referenceIds": reference_id}, use_cache=False,
                headers=self._headers())
        except (TimeoutError, socket.timeout):
            result = _unknown(request, "status_transport_timeout", time.time())
            result = replace(result, state=AcceptanceState.TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            result = _unknown(request, f"status_transport_{type(exc).__name__}", time.time())
        else:
            if isinstance(payload, Mapping) and isinstance(payload.get("bets"), list):
                rows = [row for row in payload["bets"] if isinstance(row, Mapping)]
                payload = next((row for row in rows
                                if str(row.get("referenceId", row.get("reference_id", ""))) == reference_id),
                               {})
            result = parse_acceptance(request, payload)
        self.journal.put_cloudbet_acceptance(result)
        return result
