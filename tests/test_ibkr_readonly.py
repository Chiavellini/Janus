#!/usr/bin/env python3
"""Hermetic safety tests for the live-account IBKR boundary."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.ibkr_readonly import (  # noqa: E402
    IBKRReadOnlyClient,
    IBKRSafetyError,
    READ_ONLY_HTTP_RULES,
    authorize_http,
    authorize_ws_message,
    validate_base_url,
)
from collectors.probe_ibkr import (  # noqa: E402
    _availability,
    _family_status,
    _nearest_strike,
    _option_month,
    _quote_summary,
    _select_future,
)


def test_base_url_is_https_loopback_only():
    assert validate_base_url("https://localhost:5055/v1/api").endswith("/v1/api")
    assert validate_base_url("https://127.0.0.1:5055/v1/api")
    for unsafe in (
        "http://localhost:5055/v1/api",
        "https://api.ibkr.com/v1/api",
        "https://localhost:5055/v1/api?next=https://evil.invalid",
        "https://user:pass@localhost:5055/v1/api",
    ):
        with pytest.raises(IBKRSafetyError):
            validate_base_url(unsafe)


def test_allowlist_has_no_dynamic_or_trading_paths():
    assert READ_ONLY_HTTP_RULES
    for path in READ_ONLY_HTTP_RULES:
        assert "{" not in path
        assert not any(word in path.lower() for word in ("order", "trade", "reply", "withdraw"))


def test_only_pinned_auth_post_is_allowed():
    authorize_http("POST", "/iserver/auth/status", json_body={})
    with pytest.raises(IBKRSafetyError):
        authorize_http("POST", "/iserver/auth/status", json_body={"publish": True})
    with pytest.raises(IBKRSafetyError):
        authorize_http("GET", "/iserver/auth/status")


def test_orders_and_unknown_endpoints_fail_closed():
    blocked = (
        ("POST", "/iserver/account/U123/orders"),
        ("DELETE", "/iserver/account/U123/order/1"),
        ("POST", "/iserver/reply/abc"),
        ("GET", "/iserver/account/orders"),
        ("GET", "/portfolio/U123/positions/0"),
        ("GET", "/iserver/marketdata/history"),
    )
    for method, path in blocked:
        with pytest.raises(IBKRSafetyError):
            authorize_http(method, path)


def test_url_and_path_injection_fail_closed():
    for path in (
        "https://localhost:5055/v1/api/tickle",
        "/tickle?next=/orders",
        "/iserver/../account/orders",
        "//tickle",
    ):
        with pytest.raises(IBKRSafetyError):
            authorize_http("GET", path)


def test_market_snapshot_is_bounded_to_quote_fields():
    authorize_http(
        "GET",
        "/iserver/marketdata/snapshot",
        params={"conids": "123,456", "fields": "31,84,85,86,88,6509"},
    )
    with pytest.raises(IBKRSafetyError):
        authorize_http(
            "GET",
            "/iserver/marketdata/snapshot",
            params={"conids": "123", "fields": "73"},  # position market value
        )
    with pytest.raises(IBKRSafetyError):
        authorize_http(
            "GET",
            "/iserver/marketdata/snapshot",
            params={"conids": "123,U456", "fields": "31"},
        )


def test_contract_search_is_read_only_and_validated():
    authorize_http("GET", "/iserver/secdef/search", params={"symbol": "SPX", "secType": "IND"})
    authorize_http("GET", "/trsrv/futures", params={"symbols": "ES,BTC,ZQ"})
    with pytest.raises(IBKRSafetyError):
        authorize_http("GET", "/iserver/secdef/search", params={"symbol": "SPX", "evil": "1"})


def test_option_chain_endpoints_are_exact_and_bounded():
    authorize_http(
        "GET", "/iserver/secdef/strikes",
        params={"conid": "416904", "sectype": "OPT", "month": "AUG26"},
    )
    authorize_http(
        "GET", "/iserver/secdef/info",
        params={"conid": "416904", "sectype": "OPT", "month": "AUG26",
                "strike": "6400", "right": "C"},
    )
    with pytest.raises(IBKRSafetyError):
        authorize_http(
            "GET", "/iserver/secdef/info",
            params={"conid": "416904", "sectype": "OPT", "month": "AUG26",
                    "strike": "6400", "right": "BUY"},
        )


def test_websocket_allows_quotes_only():
    assert authorize_ws_message('smd+265598+{"fields":["31","84","85","86","88","6509"]}') == (
        "smd",
        265598,
    )
    assert authorize_ws_message("umd+265598+{}") == ("umd", 265598)
    for message in (
        "sor+{}",                       # order updates
        "str+{}",                       # trades/account activity
        "ssd+U123+{}",                  # account summary
        "sbd+265598+{}",                # depth not yet protocol-pinned
        'smd+265598+{"fields":["73"]}', # position-derived field
    ):
        with pytest.raises(IBKRSafetyError):
            authorize_ws_message(message)


def test_public_client_surface_has_no_generic_post_or_order_method():
    public = {name for name in dir(IBKRReadOnlyClient) if not name.startswith("_")}
    assert "post" not in public
    assert not any("order" in name or "trade" in name for name in public)


def test_probe_selects_earliest_unexpired_future_deterministically():
    raw = {"BTC": [
        {"conid": 3, "symbol": "BTC", "expirationDate": "20260925"},
        {"conid": 2, "symbol": "BTC", "expirationDate": "20260828"},
        {"conid": 1, "symbol": "BTC", "expirationDate": "20260731"},
    ]}
    selected = _select_future(raw, "BTC", __import__("datetime").date(2026, 8, 18))
    assert selected == {
        "root": "BTC", "conid": 2, "expiry": "2026-08-28", "symbol": "BTC", "exchange": None
    }


def test_probe_option_month_and_strike_are_predeclared_choices():
    raw = [{"sections": [
        {"secType": "FUT", "months": "SEP26;DEC26"},
        {"secType": "OPT", "months": "JUL26;SEP26;AUG26"},
    ]}]
    today = __import__("datetime").date(2026, 8, 18)
    assert _option_month(raw, today) == "AUG26"
    assert _nearest_strike({"call": [6300, 6400], "put": [6300, 6400]}, 6350) == 6300


def test_probe_availability_never_promotes_delayed_or_missing_data():
    assert _availability("RpB") == "HFT_READY"
    for code in ("DpB", "ZpB", "YpB", "NpB", "OpB", None):
        assert _availability(code) != "HFT_READY"
    assert _family_status([{"status": "BLOCKED_DELAYED"}]) == "BLOCKED_DELAYED"
    assert _family_status([]) == "BLOCKED_NO_CONTRACT"


def test_probe_quote_summary_is_market_data_only():
    summary = _quote_summary({
        "conid": 123, "_updated": 1_700_000_000_000, "6509": "RpB", "55": "BTC",
        "6070": "FUT", "6004": "CME", "6073": "20260828", "31": "C123.4",
        "84": "123.3", "88": "4", "86": "123.5", "85": "6",
        "acctId": "MUST_NOT_COPY", "position": 10,
    })
    assert summary["status"] == "HFT_READY" and summary["last"] == 123.4
    assert "acctId" not in summary and "position" not in summary


def test_probe_underlying_uses_section_sectype_not_smallest_conid():
    from collectors.probe_ibkr import _underlying
    raw = [
        {"conid": "137851301", "symbol": "XSP", "description": "CBOE",
         "sections": [{"secType": "IND", "exchange": "CBOE;"}, {"secType": "OPT", "months": "AUG26"}]},
        {"conid": "74580612", "symbol": "XSP", "description": "TSE",
         "sections": [{"secType": "STK"}, {"secType": "OPT", "months": "AUG26"}]},
    ]
    assert _underlying(raw, "XSP")["conid"] == 137851301


# ── /iserver/reauthenticate — added 2026-08-19 with operator approval ────────
# The allowlist is the safety boundary, so widening it by one endpoint has to come with proof
# that nothing ELSE opened up. These tests are the "negative tests" the governance rule requires.

def test_reauthenticate_is_allowlisted_as_post_with_an_exactly_empty_body():
    from lib.ibkr_readonly import READ_ONLY_HTTP_RULES
    rule = READ_ONLY_HTTP_RULES["/iserver/reauthenticate"]
    assert rule.method == "POST"
    assert rule.query_keys == frozenset() and rule.required_query_keys == frozenset()
    assert rule.exact_json_body == {}          # no credentials, no payload of any kind


def test_reauthenticate_refuses_a_non_empty_body():
    """A body is the only place a credential could be smuggled in. It must be exactly {}."""
    from lib.ibkr_readonly import IBKRReadOnlyClient, IBKRSafetyError
    c = IBKRReadOnlyClient()
    for bad in ({"user": "x"}, {"password": "y"}, {"a": 1}, [], "x"):
        try:
            c._request("POST", "/iserver/reauthenticate", json_body=bad)
        except IBKRSafetyError:
            continue
        except Exception as exc:                # a network error means the guard did NOT fire
            raise AssertionError(f"body {bad!r} reached transport: {type(exc).__name__}")
        raise AssertionError(f"body {bad!r} was accepted")


def test_reauthenticate_refuses_the_wrong_method():
    from lib.ibkr_readonly import IBKRReadOnlyClient, IBKRSafetyError
    c = IBKRReadOnlyClient()
    for method in ("GET", "PUT", "DELETE"):
        try:
            c._request(method, "/iserver/reauthenticate", json_body={})
        except IBKRSafetyError:
            continue
        except Exception as exc:
            raise AssertionError(f"{method} reached transport: {type(exc).__name__}")
        raise AssertionError(f"{method} was accepted")


def test_widening_did_not_open_any_order_or_account_management_surface():
    """The whole point of the boundary. One endpoint was added; nothing else may have appeared."""
    from lib.ibkr_readonly import READ_ONLY_HTTP_RULES
    assert set(READ_ONLY_HTTP_RULES) == {
        "/tickle", "/iserver/accounts", "/iserver/auth/status", "/iserver/reauthenticate",
        "/iserver/secdef/search", "/iserver/secdef/strikes", "/iserver/secdef/info",
        "/trsrv/futures", "/iserver/marketdata/snapshot",
    }
    forbidden = ("order", "trade", "logout", "portfolio", "pnl", "reply", "scanner",
                 "history", "position", "balance", "account/")
    for path in READ_ONLY_HTTP_RULES:
        assert not any(f in path for f in forbidden), path


def test_client_still_exposes_no_order_method():
    from lib.ibkr_readonly import IBKRReadOnlyClient
    names = [n for n in dir(IBKRReadOnlyClient) if not n.startswith("__")]
    for bad in ("order", "place", "cancel", "modify", "trade", "logout", "login",
                "authenticate_user", "portfolio", "pnl", "position"):
        assert not any(bad in n.lower() for n in names), f"{bad} surfaced in {names}"
    assert "reauthenticate" in names            # the one thing we DID add


def test_reauthenticate_forbidden_paths_still_rejected():
    """Neighbouring iserver paths must not have become reachable by prefix confusion."""
    from lib.ibkr_readonly import IBKRReadOnlyClient, IBKRSafetyError
    c = IBKRReadOnlyClient()
    for path in ("/iserver/reauthenticate/x", "/iserver/auth/logout", "/logout",
                 "/iserver/account", "/iserver/orders", "/iserver/reauthenticat"):
        try:
            c._request("POST", path, json_body={})
        except IBKRSafetyError:
            continue
        except Exception as exc:
            raise AssertionError(f"{path} reached transport: {type(exc).__name__}")
        raise AssertionError(f"{path} was accepted")
