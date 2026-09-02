from __future__ import annotations

import json
from pathlib import Path

import pytest

from collectors.tuple_store import TupleStore
from lib.venues.cloudbet import CloudbetSelection, iter_event_markets
from lib.venues.cloudbet_trading import (
    AcceptanceConflict,
    AcceptanceState,
    CloudbetAcceptance,
    CloudbetBetRequest,
    CloudbetTradingClient,
    TradingDisabled,
    parse_acceptance,
)


FIXTURE = Path(__file__).parent / "fixtures" / "cloudbet" / "mlb_live.json"
REF = "00000000-0000-4000-8000-000000000001"


def selection() -> CloudbetSelection:
    payload = json.loads(FIXTURE.read_text())
    return next(iter(iter_event_markets(payload, fetched_utc=1000.0))).selections[0]


def request() -> CloudbetBetRequest:
    s = selection()
    return CloudbetBetRequest.from_selection(s, stake=10.0, currency="PLAY_EUR", reference_id=REF)


def response(req: CloudbetBetRequest, *, status="ACCEPTED", stake="10", price="2.1") -> dict:
    return {"referenceId": req.reference_id, "state": status, "stake": stake,
            "selection": {"eventId": req.event_id, "marketUrl": req.market_url,
                           "price": price}, "rejectionCode": ""}


def test_parse_acceptance_states_and_identity_guards():
    req = request()
    assert parse_acceptance(req, response(req)).state is AcceptanceState.ACCEPTED
    assert parse_acceptance(req, response(req, stake="4")).state is AcceptanceState.REDUCED
    assert parse_acceptance(req, response(req, status="PENDING_ACCEPTANCE")).state is AcceptanceState.PENDING
    assert parse_acceptance(req, response(req, status="STAKE_ABOVE_MAX")).state is AcceptanceState.REJECTED
    assert parse_acceptance(req, {**response(req), "referenceId": "wrong"}).state is AcceptanceState.UNKNOWN
    assert parse_acceptance(req, {**response(req), "stake": "11"}).state is AcceptanceState.UNKNOWN


class Journal:
    def __init__(self):
        self.rows = {}

    def get_cloudbet_acceptance(self, reference_id):
        return self.rows.get(reference_id)

    def put_cloudbet_acceptance(self, result):
        self.rows[result.reference_id] = result


class FakeTransport:
    def __init__(self, req, *, timeout=False):
        self.req = req
        self.timeout = timeout
        self.posts = 0
        self.gets = 0

    def post_json_once(self, url, payload, *, headers):
        self.posts += 1
        assert url.endswith("/bets/place")
        assert payload["referenceId"] == self.req.reference_id
        assert payload["selection"]["marketUrl"] == self.req.market_url
        assert payload["priceChange"]["value"] == self.req.accept_price_change
        assert headers["X-API-Key"] == "test-key"
        if self.timeout:
            raise TimeoutError("simulated")
        return response(self.req)

    def get_json(self, url, *, params, use_cache, headers):
        self.gets += 1
        assert url.endswith("/bets")
        assert params == {"referenceIds": self.req.reference_id}
        return {"bets": [response(self.req)]}


def test_place_is_opt_in_idempotent_and_uses_one_post():
    req = request()
    journal = Journal()
    transport = FakeTransport(req)
    client = CloudbetTradingClient("test-key", journal=journal, client=transport, submit_enabled=True)
    first = client.place(req)
    second = client.place(req)
    assert first.state is second.state is AcceptanceState.ACCEPTED
    assert transport.posts == 1


def test_timeout_is_not_retried_and_requires_explicit_reconciliation():
    req = request()
    journal = Journal()
    transport = FakeTransport(req, timeout=True)
    client = CloudbetTradingClient("test-key", journal=journal, client=transport, submit_enabled=True)
    result = client.place(req)
    assert result.state is AcceptanceState.TIMEOUT
    assert transport.posts == 1
    # A second place call cannot turn the ambiguous result into a duplicate POST.
    assert client.place(req).state is AcceptanceState.TIMEOUT
    assert transport.posts == 1


def test_reconcile_updates_timeout_from_provider_status():
    req = request()
    journal = Journal()
    timeout_transport = FakeTransport(req, timeout=True)
    client = CloudbetTradingClient("test-key", journal=journal, client=timeout_transport, submit_enabled=True)
    client.place(req)
    live_transport = FakeTransport(req)
    reconciled = CloudbetTradingClient("test-key", journal=journal, client=live_transport,
                                       submit_enabled=True).reconcile(req.reference_id)
    assert reconciled.state is AcceptanceState.ACCEPTED
    assert live_transport.gets == 1


def test_disabled_client_sends_nothing_and_reference_conflict_is_rejected():
    req = request()
    journal = Journal()
    client = CloudbetTradingClient("test-key", journal=journal, client=FakeTransport(req))
    with pytest.raises(TradingDisabled):
        client.place(req)
    assert not journal.rows

    other = CloudbetBetRequest(reference_id=REF, event_id=req.event_id,
                               market_url=req.market_url, price=req.price, stake=9,
                               currency=req.currency)
    journal.rows[REF] = CloudbetAcceptance(
        reference_id=REF, state=AcceptanceState.PENDING, event_id=req.event_id,
        market_url=req.market_url, requested_price=req.price, requested_stake=10,
        currency=req.currency,
    )
    enabled = CloudbetTradingClient("test-key", journal=journal, client=FakeTransport(req),
                                    submit_enabled=True)
    with pytest.raises(AcceptanceConflict):
        enabled.place(other)


def test_tuple_store_journals_acceptance_without_raw_payload(tmp_path):
    store = TupleStore(tmp_path / "tuples.sqlite", enforce_volume=False)
    result = CloudbetAcceptance(
        reference_id=REF, state=AcceptanceState.PENDING, event_id="7001001",
        market_url="baseball.moneyline/home", requested_price=2.1,
        requested_stake=10, currency="PLAY_EUR", observed_utc=1000,
    )
    store.put_cloudbet_acceptance(result)
    loaded = store.get_cloudbet_acceptance(REF)
    assert loaded == result
    cols = {row[1] for row in store.con.execute("PRAGMA table_info(cloudbet_acceptances)")}
    assert "raw_payload" not in cols
    store.close()
