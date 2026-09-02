#!/usr/bin/env python3
"""Fail-closed IBKR Client Portal transport for research market data.

The authenticated Client Portal session may be attached to a live brokerage account.  This
module therefore exposes a deliberately tiny capability surface instead of a generic HTTP
client: loopback only, exact endpoint/method pairs, bounded query values, no redirects, and no
order/account-management endpoints.  Additions require a code change and a test.

The local gateway's certificate is self-signed.  TLS verification is disabled only after the
base URL has been proven to be HTTPS on a loopback host; redirects are rejected so that this
exception can never escape localhost.
"""

from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping


class IBKRSafetyError(RuntimeError):
    """The requested operation is outside Janus' read-only IBKR capability."""


class IBKRResponseError(RuntimeError):
    """The local gateway returned an invalid or unsuccessful response."""


@dataclass(frozen=True)
class EndpointRule:
    method: str
    query_keys: frozenset[str]
    required_query_keys: frozenset[str] = frozenset()
    exact_json_body: Mapping[str, Any] | None = None


# Exact, research-only surface.  In particular, there is no wildcard, no account-id path,
# no /orders, no /trades, no reply endpoint, and no account-management endpoint.
READ_ONLY_HTTP_RULES: dict[str, EndpointRule] = {
    "/tickle": EndpointRule("GET", frozenset()),
    "/iserver/accounts": EndpointRule("GET", frozenset()),
    "/iserver/auth/status": EndpointRule(
        "POST", frozenset(), exact_json_body={}
    ),
    # SESSION MAINTENANCE ONLY.  Added 2026-08-19 with explicit operator approval after the
    # BROKERAGE session was measured dropping repeatedly (capture windows of 7.5 and ~24 minutes)
    # while the SSO session stayed alive -- /sso/ping 200 alongside iserver 401.
    #
    # This endpoint takes NO credentials and an exactly-empty body; it revives a brokerage session
    # from an SSO session a HUMAN already established.  It cannot place, modify, cancel, or read an
    # order, position, or balance.  When the SSO session itself is dead it returns
    # {"error": "not logged in"} and only a human can fix it at https://localhost:5055 -- callers
    # MUST NOT retry-loop on that response.  This is NOT login automation, which remains forbidden.
    "/iserver/reauthenticate": EndpointRule(
        "POST", frozenset(), exact_json_body={}
    ),
    "/iserver/secdef/search": EndpointRule(
        "GET", frozenset({"symbol", "name", "secType"}), frozenset({"symbol"})
    ),
    "/iserver/secdef/strikes": EndpointRule(
        "GET",
        frozenset({"conid", "sectype", "secType", "month", "exchange"}),
        frozenset({"conid", "month"}),
    ),
    "/iserver/secdef/info": EndpointRule(
        "GET",
        frozenset({"conid", "sectype", "secType", "month", "exchange", "strike", "right"}),
        frozenset({"conid"}),
    ),
    "/trsrv/futures": EndpointRule(
        "GET", frozenset({"symbols"}), frozenset({"symbols"})
    ),
    "/iserver/marketdata/snapshot": EndpointRule(
        "GET", frozenset({"conids", "fields"}), frozenset({"conids", "fields"})
    ),
}

# Quote/identity fields only.  Position, PnL, balance, order, and account fields are excluded.
ALLOWED_MARKET_DATA_FIELDS = frozenset(
    {"31", "55", "84", "85", "86", "87", "88", "6004", "6008", "6070", "6073", "6119", "6509", "7059", "7762"}
)
ALLOWED_SECURITY_TYPES = frozenset({"STK", "IND", "FUT", "OPT", "FOP", "WAR", "BOND"})
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
DEFAULT_BASE_URL = "https://localhost:5055/v1/api"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024

_SYMBOL_RE = re.compile(r"[A-Za-z0-9 ._/^-]{1,40}\Z")
_CONID_RE = re.compile(r"[0-9]{1,18}\Z")
_EXCHANGE_RE = re.compile(r"[A-Z0-9._-]{1,24}\Z")
_MONTH_RE = re.compile(r"[A-Z]{3}[0-9]{2}\Z")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise IBKRSafetyError(f"IBKR gateway redirect refused ({code})")


def validate_base_url(base_url: str) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme != "https" or parsed.hostname not in LOOPBACK_HOSTS:
        raise IBKRSafetyError("IBKR base URL must be HTTPS on a loopback host")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise IBKRSafetyError("IBKR base URL may not contain credentials, query, or fragment")
    if parsed.path.rstrip("/") != "/v1/api":
        raise IBKRSafetyError("IBKR base URL must end exactly in /v1/api")
    if parsed.port is None:
        raise IBKRSafetyError("IBKR base URL must pin an explicit local port")
    return base_url.rstrip("/")


def _csv(value: Any, *, label: str, max_items: int) -> list[str]:
    parts = [item.strip() for item in str(value).split(",") if item.strip()]
    if not parts or len(parts) > max_items:
        raise IBKRSafetyError(f"{label} must contain 1..{max_items} values")
    return parts


def _validate_params(path: str, params: Mapping[str, Any], rule: EndpointRule) -> None:
    keys = set(params)
    if not keys <= rule.query_keys:
        raise IBKRSafetyError(f"query keys not allowed for {path}: {sorted(keys - rule.query_keys)}")
    if not rule.required_query_keys <= keys:
        raise IBKRSafetyError(
            f"missing query keys for {path}: {sorted(rule.required_query_keys - keys)}"
        )

    if "symbol" in params and not _SYMBOL_RE.fullmatch(str(params["symbol"])):
        raise IBKRSafetyError("invalid IBKR symbol")
    if "symbols" in params:
        symbols = _csv(params["symbols"], label="symbols", max_items=20)
        if any(not _SYMBOL_RE.fullmatch(symbol) for symbol in symbols):
            raise IBKRSafetyError("invalid IBKR futures symbol")
    if "name" in params and str(params["name"]).lower() not in {"true", "false"}:
        raise IBKRSafetyError("name must be true or false")
    for key in ("secType", "sectype"):
        if key in params and str(params[key]).upper() not in ALLOWED_SECURITY_TYPES:
            raise IBKRSafetyError(f"invalid {key}")
    if "conid" in params and not _CONID_RE.fullmatch(str(params["conid"])):
        raise IBKRSafetyError("invalid conid")
    if "conids" in params:
        conids = _csv(params["conids"], label="conids", max_items=100)
        if any(not _CONID_RE.fullmatch(conid) for conid in conids):
            raise IBKRSafetyError("conids must be numeric contract identifiers")
    if "fields" in params:
        fields = _csv(params["fields"], label="fields", max_items=50)
        unknown = set(fields) - ALLOWED_MARKET_DATA_FIELDS
        if unknown:
            raise IBKRSafetyError(f"market-data fields not allowed: {sorted(unknown)}")
    if "month" in params and not _MONTH_RE.fullmatch(str(params["month"]).upper()):
        raise IBKRSafetyError("month must have form AUG26")
    if "exchange" in params and not _EXCHANGE_RE.fullmatch(str(params["exchange"]).upper()):
        raise IBKRSafetyError("invalid exchange")
    if "right" in params and str(params["right"]).upper() not in {"C", "P"}:
        raise IBKRSafetyError("right must be C or P")
    if "strike" in params:
        try:
            strike = float(params["strike"])
        except (TypeError, ValueError) as exc:
            raise IBKRSafetyError("strike must be numeric") from exc
        if not (0 <= strike < 1e9):
            raise IBKRSafetyError("strike outside safety bounds")


def authorize_http(
    method: str,
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
    json_body: Mapping[str, Any] | None = None,
) -> EndpointRule:
    """Validate one exact localhost operation or fail closed."""
    method = method.upper()
    parsed = urllib.parse.urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise IBKRSafetyError("endpoint must be a bare path; URL/query injection refused")
    if not path.startswith("/") or "//" in path or any(p in {".", ".."} for p in path.split("/")):
        raise IBKRSafetyError("endpoint path is not canonical")
    rule = READ_ONLY_HTTP_RULES.get(path)
    if rule is None or method != rule.method:
        raise IBKRSafetyError(f"IBKR operation not allowlisted: {method} {path}")
    supplied_params = params or {}
    _validate_params(path, supplied_params, rule)
    if rule.exact_json_body is None:
        if json_body is not None:
            raise IBKRSafetyError(f"request body not allowed for {method} {path}")
    elif not isinstance(json_body, Mapping) or dict(json_body) != dict(rule.exact_json_body):
        # FAIL CLOSED.  This used to read `dict(json_body or {}) != ...`, which let ANY falsy body
        # ([], None, "", 0, False) collapse to {} and be accepted on a pinned-body endpoint, and
        # made a str body raise ValueError from dict() instead of a safety error.  Caught
        # 2026-08-19 by the negative tests written for /iserver/reauthenticate.  The body is the
        # only place a credential could ride along, so it must be a Mapping equal to the pin --
        # nothing else, and no coercion.
        raise IBKRSafetyError(f"only the pinned body is allowed for {method} {path}")
    return rule


def authorize_ws_message(message: str) -> tuple[str, int]:
    """Permit only top-of-book subscribe/unsubscribe topics.

    Account, order, trade, PnL, historical, scanner, and price-ladder topics are denied.  Ladder
    access can be added only after its current protocol is pinned from official documentation.
    """
    try:
        topic, target, raw_params = message.split("+", 2)
        conid = int(target)
        params = json.loads(raw_params)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise IBKRSafetyError("malformed IBKR websocket message") from exc
    if conid <= 0 or not _CONID_RE.fullmatch(target):
        raise IBKRSafetyError("websocket target must be a numeric conid")
    if topic == "smd":
        if set(params) != {"fields"} or not isinstance(params["fields"], list):
            raise IBKRSafetyError("smd requires exactly one fields array")
        fields = [str(field) for field in params["fields"]]
        if not fields or len(fields) > 50 or set(fields) - ALLOWED_MARKET_DATA_FIELDS:
            raise IBKRSafetyError("smd fields are outside the read-only quote allowlist")
    elif topic == "umd":
        if params != {}:
            raise IBKRSafetyError("umd requires an empty parameter object")
    else:
        raise IBKRSafetyError(f"IBKR websocket topic not allowlisted: {topic}")
    return topic, conid


class IBKRReadOnlyClient:
    """Minimal JSON client whose public methods cannot express an order."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, *, timeout: float = 10.0):
        self.base_url = validate_base_url(base_url)
        self.timeout = float(timeout)
        if not (0 < self.timeout <= 60):
            raise IBKRSafetyError("timeout must be in (0, 60] seconds")
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=context), _NoRedirectHandler()
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> Any:
        authorize_http(method, path, params=params, json_body=json_body)
        query = urllib.parse.urlencode(params or {})
        url = self.base_url + path + ("?" + query if query else "")
        body = None if json_body is None else json.dumps(dict(json_body)).encode("utf-8")
        headers = {"Accept": "application/json", "User-Agent": "janus-ibkr-readonly/1"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            detail = exc.read(500).decode("utf-8", "replace")
            raise IBKRResponseError(f"IBKR HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise IBKRResponseError(f"IBKR gateway request failed: {exc}") from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise IBKRResponseError("IBKR response exceeded 5 MiB safety limit")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IBKRResponseError("IBKR response was not valid JSON") from exc

    def auth_status(self) -> Mapping[str, Any]:
        return self._request("POST", "/iserver/auth/status", json_body={})

    def reauthenticate(self) -> Mapping[str, Any]:
        """Revive the BROKERAGE session from an SSO session a human already established.

        No credentials are sent and the body is exactly {}.  Returns the gateway's body:
        `{"error": "not logged in"}` means the SSO session is dead too and only a human can fix it
        -- never retry-loop on that response.  This is session maintenance, NOT login automation.
        """
        return self._request("POST", "/iserver/reauthenticate", json_body={})

    def tickle(self) -> Mapping[str, Any]:
        return self._request("GET", "/tickle")

    def initialize_accounts(self) -> Mapping[str, Any]:
        return self._request("GET", "/iserver/accounts")

    def search_contracts(self, symbol: str, *, sec_type: str | None = None) -> Any:
        params: dict[str, str] = {"symbol": symbol}
        if sec_type:
            params["secType"] = sec_type.upper()
        return self._request("GET", "/iserver/secdef/search", params=params)

    def futures(self, *symbols: str) -> Any:
        return self._request("GET", "/trsrv/futures", params={"symbols": ",".join(symbols)})

    def option_strikes(
        self, underlying_conid: int, month: str, *, exchange: str | None = None
    ) -> Any:
        params: dict[str, str] = {
            "conid": str(underlying_conid), "sectype": "OPT", "month": month.upper()
        }
        if exchange:
            params["exchange"] = exchange.upper()
        return self._request("GET", "/iserver/secdef/strikes", params=params)

    def option_contracts(
        self,
        underlying_conid: int,
        month: str,
        strike: float,
        right: str,
        *,
        exchange: str | None = None,
    ) -> Any:
        params: dict[str, str] = {
            "conid": str(underlying_conid),
            "sectype": "OPT",
            "month": month.upper(),
            "strike": str(strike),
            "right": right.upper(),
        }
        if exchange:
            params["exchange"] = exchange.upper()
        return self._request("GET", "/iserver/secdef/info", params=params)

    def snapshot(self, conids: list[int], fields: tuple[str, ...]) -> Any:
        return self._request(
            "GET",
            "/iserver/marketdata/snapshot",
            params={"conids": ",".join(map(str, conids)), "fields": ",".join(fields)},
        )
