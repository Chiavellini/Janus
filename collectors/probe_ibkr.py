#!/usr/bin/env python3
"""Run registered L13: redacted, read-only IBKR capability/entitlement probe.

No raw account, session, user, hardware, or MAC identifiers are persisted.  Every network call is
made through IBKRReadOnlyClient; the script cannot express an order.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.ibkr_readonly import (  # noqa: E402
    IBKRReadOnlyClient,
    IBKRSafetyError,
    authorize_http,
    authorize_ws_message,
)

OUT_DIR = Path("research/exec/2026-08-18_ibkr-readonly-capability")
FIELDS = ("31", "55", "84", "85", "86", "88", "6004", "6008", "6070", "6073", "6119", "6509")
MONTHS = {name: i for i, name in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


def _safety_selftest() -> bool:
    authorize_http("GET", "/tickle")
    authorize_http("POST", "/iserver/auth/status", json_body={})
    authorize_ws_message('smd+1+{"fields":["31","84","86","6509"]}')
    for method, path in (
        ("POST", "/iserver/account/U1/orders"),
        ("DELETE", "/iserver/account/U1/order/1"),
        ("POST", "/iserver/reply/1"),
    ):
        try:
            authorize_http(method, path)
        except IBKRSafetyError:
            continue
        return False
    return True


def _dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _dicts(child)


def _conid(row: dict[str, Any]) -> int | None:
    for key in ("conid", "conId", "conidEx", "6008"):
        value = row.get(key)
        if value is None:
            continue
        match = re.match(r"^(\d+)", str(value))
        if match:
            return int(match.group(1))
    return None


def _date(value: Any) -> dt.date | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y%m", "%Y-%m"):
        try:
            parsed = dt.datetime.strptime(text[:10], fmt)
            return parsed.date()
        except ValueError:
            pass
    return None


def _expiry(row: dict[str, Any]) -> dt.date | None:
    for key in ("expirationDate", "expiry", "lastTradingDay", "maturityDate", "6073"):
        parsed = _date(row.get(key))
        if parsed:
            return parsed
    return None


def _select_future(raw: Any, root: str, today: dt.date) -> dict[str, Any] | None:
    candidates = []
    for row in _dicts(raw):
        conid, expiry = _conid(row), _expiry(row)
        symbol = str(row.get("symbol") or row.get("ticker") or row.get("underlyingSymbol") or "")
        if conid is None or expiry is None or expiry < today:
            continue
        if symbol and root.upper() not in symbol.upper():
            continue
        candidates.append((expiry, conid, row))
    if not candidates:
        return None
    expiry, conid, row = min(candidates, key=lambda item: (item[0], item[1]))
    return {
        "root": root,
        "conid": conid,
        "expiry": expiry.isoformat(),
        "symbol": str(row.get("symbol") or row.get("ticker") or root),
        "exchange": row.get("exchange") or row.get("listingExchange"),
    }


def _parse_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).replace(",", "").strip()
    text = re.sub(r"^[A-Z]", "", text)
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def _availability(code: Any) -> str:
    first = str(code or "")[:1]
    return {
        "R": "HFT_READY",
        "D": "BLOCKED_DELAYED",
        "Z": "BLOCKED_FROZEN",
        "Y": "BLOCKED_FROZEN_DELAYED",
        "N": "BLOCKED_NOT_SUBSCRIBED",
        "O": "BLOCKED_AGREEMENT",
    }.get(first, "BLOCKED_AVAILABILITY_UNKNOWN")


def _quote_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "conid": _conid(row),
        "updated_ms": row.get("_updated"),
        "availability": row.get("6509"),
        "status": _availability(row.get("6509")),
        "symbol": row.get("55"),
        "security_type": row.get("6070"),
        "exchange": row.get("6004"),
        "expiry": row.get("6073"),
        "last": _parse_number(row.get("31")),
        "bid": _parse_number(row.get("84")),
        "bid_size": _parse_number(row.get("88")),
        "ask": _parse_number(row.get("86")),
        "ask_size": _parse_number(row.get("85")),
    }


def _snapshot(client: IBKRReadOnlyClient, conids: list[int]) -> list[dict[str, Any]]:
    if not conids:
        return []
    client.snapshot(conids, FIELDS)  # required pre-flight
    time.sleep(1.1)
    raw = client.snapshot(conids, FIELDS)
    rows = raw if isinstance(raw, list) else []
    return [_quote_summary(row) for row in rows if isinstance(row, dict)]


def _underlying(raw: Any, symbol: str) -> dict[str, Any] | None:
    choices = []
    for row in _dicts(raw):
        conid = _conid(row)
        if conid is None:
            continue
        candidate_symbol = str(row.get("symbol") or row.get("ticker") or "")
        # /iserver/secdef/search carries the security type inside sections[], not at row level
        # (run 1 of L13 resolved XSP to a Toronto STK because every row scored equal).
        section_types = {str(s.get("secType") or "").upper()
                         for s in (row.get("sections") or []) if isinstance(s, dict)}
        sec_type = str(row.get("secType") or row.get("assetClass") or "")
        is_index = sec_type.upper() == "IND" or "IND" in section_types
        score = (candidate_symbol.upper() == symbol.upper(), is_index)
        choices.append((score, conid, row))
    if not choices:
        return None
    _, conid, row = max(choices, key=lambda item: (item[0], -item[1]))
    return {"symbol": symbol, "conid": conid, "raw": row}


def _option_month(raw: Any, today: dt.date) -> str | None:
    found: set[str] = set()
    for row in _dicts(raw):
        if str(row.get("secType") or "").upper() != "OPT":
            continue
        text = str(row.get("months") or "")
        found.update(re.findall(r"[A-Z]{3}\d{2}", text.upper()))
    eligible = []
    for month in found:
        year = 2000 + int(month[3:])
        number = MONTHS.get(month[:3])
        if number and (year, number) >= (today.year, today.month):
            eligible.append((year, number, month))
    return min(eligible)[2] if eligible else None


def _nearest_strike(raw: Any, spot: float) -> float | None:
    if not isinstance(raw, dict):
        return None
    values = []
    for key in ("call", "put"):
        for value in raw.get(key) or []:
            number = _parse_number(value)
            if number is not None:
                values.append(number)
    return min(set(values), key=lambda strike: (abs(strike - spot), strike)) if values else None


def _option_conid(raw: Any) -> int | None:
    candidates = sorted({_conid(row) for row in _dicts(raw) if _conid(row) is not None})
    return candidates[0] if candidates else None


def _family_status(quotes: list[dict[str, Any]]) -> str:
    statuses = [row["status"] for row in quotes]
    if any(status == "HFT_READY" for status in statuses):
        return "HFT_READY"
    return statuses[0] if statuses else "BLOCKED_NO_CONTRACT"


def run(client: IBKRReadOnlyClient, out_dir: Path = OUT_DIR) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "registered_spec": str(out_dir / "spec.yaml"),
        "evidence_tier": "M1 capability",
        "test_looks_spent": 0,
        "orders_placed": 0,
        "safety_gate": "PASS" if _safety_selftest() else "FAIL_STOP",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "families": {},
    }
    if result["safety_gate"] != "PASS":
        result["verdict"] = "FAIL_STOP_SAFETY"
        _write(result, out_dir)
        return result

    try:
        auth = client.auth_status()
    except Exception as exc:  # noqa: BLE001 - result is an operational blocker
        result.update({"session_gate": "BLOCKED_SESSION", "session_error": type(exc).__name__,
                       "verdict": "BLOCKED_SESSION"})
        _write(result, out_dir)
        return result
    session = {key: bool(auth.get(key)) for key in ("authenticated", "connected", "competing", "established")}
    result["session"] = session
    if not session["authenticated"] or not session["connected"] or session["competing"]:
        result.update({"session_gate": "BLOCKED_SESSION", "verdict": "BLOCKED_SESSION"})
        _write(result, out_dir)
        return result
    result["session_gate"] = "PASS"
    accounts = client.initialize_accounts()
    result["account"] = {
        "count": len(accounts.get("accounts") or []) if isinstance(accounts, dict) else None,
        "is_paper": bool(accounts.get("isPaper")) if isinstance(accounts, dict) else None,
        "identifiers_archived": False,
    }

    today = dt.datetime.now(dt.timezone.utc).date()
    futures_raw = client.futures("BTC", "MBT", "ZQ")
    selected = {root: _select_future(futures_raw, root, today) for root in ("BTC", "MBT", "ZQ")}
    future_conids = [item["conid"] for item in selected.values() if item]
    future_quotes = _snapshot(client, future_conids)
    quote_by_conid = {row["conid"]: row for row in future_quotes}
    for root, item in selected.items():
        if item:
            item["quote"] = quote_by_conid.get(item["conid"])
    crypto_quotes = [item["quote"] for root, item in selected.items()
                     if root in {"BTC", "MBT"} and item and item.get("quote")]
    zq_quotes = [item["quote"] for root, item in selected.items()
                 if root == "ZQ" and item and item.get("quote")]
    result["families"]["crypto_futures"] = {
        "status": _family_status(crypto_quotes),
        "contracts": [item for root, item in selected.items() if root in {"BTC", "MBT"} and item],
    }
    result["families"]["fed_funds"] = {
        "status": _family_status(zq_quotes),
        "contracts": [item for root, item in selected.items() if root == "ZQ" and item],
    }

    option_entries = []
    for symbol in ("SPX", "XSP"):
        search = client.search_contracts(symbol, sec_type="IND")
        underlying = _underlying(search, symbol)
        if not underlying:
            option_entries.append({"symbol": symbol, "status": "BLOCKED_NO_UNDERLYING"})
            continue
        underlying_quote = _snapshot(client, [underlying["conid"]])
        uq = underlying_quote[0] if underlying_quote else None
        spot = uq.get("last") if uq else None
        month = _option_month(search, today)
        if spot is None or month is None:
            option_entries.append({"symbol": symbol, "underlying_conid": underlying["conid"],
                                   "underlying_quote": uq, "status": "BLOCKED_CHAIN_INPUT",
                                   "month": month})
            continue
        strikes = client.option_strikes(underlying["conid"], month)
        strike = _nearest_strike(strikes, spot)
        if strike is None:
            option_entries.append({"symbol": symbol, "underlying_conid": underlying["conid"],
                                   "underlying_quote": uq, "status": "BLOCKED_NO_STRIKES",
                                   "month": month})
            continue
        conids = []
        contracts = []
        for right in ("C", "P"):
            raw = client.option_contracts(underlying["conid"], month, strike, right)
            conid = _option_conid(raw)
            contracts.append({"right": right, "conid": conid})
            if conid:
                conids.append(conid)
        quotes = _snapshot(client, conids)
        qmap = {row["conid"]: row for row in quotes}
        for contract in contracts:
            contract["quote"] = qmap.get(contract["conid"])
        option_entries.append({
            "symbol": symbol,
            "underlying_conid": underlying["conid"],
            "underlying_quote": uq,
            "month": month,
            "strike": strike,
            "expiration_day_status": "NEAR_EXPIRY_UNRESOLVED",
            "contracts": contracts,
            "status": _family_status(quotes),
        })
    option_quotes = [contract["quote"] for entry in option_entries
                     for contract in entry.get("contracts", []) if contract.get("quote")]
    result["families"]["index_options"] = {
        "status": _family_status(option_quotes), "underlyings": option_entries
    }
    crypto_ready = result["families"]["crypto_futures"]["status"] == "HFT_READY"
    options_ready = result["families"]["index_options"]["status"] == "HFT_READY"
    result["program_ready"] = crypto_ready and options_ready
    result["verdict"] = "PASS_HFT_READY" if result["program_ready"] else "BLOCKED_ENTITLEMENT_OR_CONTRACT"
    _write(result, out_dir)
    return result


def _write(result: dict[str, Any], out_dir: Path) -> None:
    (out_dir / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    family_lines = [f"- {name}: **{data.get('status')}**" for name, data in result.get("families", {}).items()]
    (out_dir / "verdict.md").write_text(
        "# IBKR read-only capability\n\n"
        f"**{result.get('verdict', 'UNKNOWN')}**. Safety: {result.get('safety_gate')}; "
        f"session: {result.get('session_gate', 'NOT_RUN')}.\n\n"
        + ("\n".join(family_lines) if family_lines else "No instrument request was made.\n")
        + "\n\nNo orders were placed. No account, user, session, hardware, or MAC identifier was archived.\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://localhost:5055/v1/api")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    result = run(IBKRReadOnlyClient(args.base_url, timeout=args.timeout))
    print(json.dumps({"verdict": result.get("verdict"), "safety_gate": result.get("safety_gate"),
                      "session_gate": result.get("session_gate"),
                      "families": {k: v.get("status") for k, v in result.get("families", {}).items()}},
                     indent=2, sort_keys=True))
    return 0 if result.get("verdict") in {"PASS_HFT_READY", "BLOCKED_SESSION", "BLOCKED_ENTITLEMENT_OR_CONTRACT"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

