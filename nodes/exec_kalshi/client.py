#!/usr/bin/env python3
"""Kalshi order path. Disarmed by construction: nothing here runs below DEMO_EXECUTION, nothing
runs without a RiskClearance, and nothing is ever retried after an ambiguous answer.

Verified 2026-09-03 against production with read-only calls: the REST scheme is the socket's
(RSA-PSS over timestamp + METHOD + path, `KALSHI-ACCESS-*` headers); GET /portfolio/balance and
GET /portfolio/orders answer. Order endpoints from the v2 docs:
    POST   /portfolio/events/orders            side bid|ask (YES terms), count/price fixed-point
    DELETE /portfolio/events/orders/{order_id}
    GET    /portfolio/orders/{order_id}        status resting|canceled|executed, *_fp counts
    GET    /portfolio/fills                    fee_cost, is_taker, count_fp
Buying NO is an `ask` at 1 - price: the venue quotes everything in YES terms.

The demo host (`external-api.demo.kalshi.co`) has its own credentials; DEMO_EXECUTION points
here with those. LIMITED_LIVE and PRODUCTION point at production under the arming override.
"""

from __future__ import annotations

import base64
import time
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from kernel.execution_protocol import Ack, Balance, FillRecord, OrderRequest, OrderState
from kernel.fetch import Client
from kernel.redact import brief_error
from kernel.schema import FillState, Mode
from nodes.execution.gate import admit
from nodes.execution.journal import Journal

PROD_BASE = "https://api.elections.kalshi.com"
DEMO_BASE = "https://external-api.demo.kalshi.co"
API = "/trade-api/v2"
TIF = {"fok": "fill_or_kill", "ioc": "immediate_or_cancel", "gtc": "good_till_canceled"}


def sign(private_key, method: str, path: str, ts_ms: int | None = None) -> tuple[str, str]:
    """(timestamp, base64 signature) over timestamp + METHOD + path. Same scheme as the socket."""
    ts = str(ts_ms if ts_ms is not None else int(time.time() * 1000))
    sig = private_key.sign((ts + method.upper() + path).encode(),
                           padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
                           hashes.SHA256())
    return ts, base64.b64encode(sig).decode()


def order_body(req: OrderRequest) -> dict:
    """The v2 body. YES terms only: buy_no is an ask at 1 - price."""
    if req.side == "buy_yes":
        side, price = "bid", req.price
    else:
        side, price = "ask", 1.0 - req.price
    return {"ticker": req.market_id, "side": side, "count": f"{req.contracts:.2f}",
            "price": f"{price:.4f}", "time_in_force": TIF[req.time_in_force],
            "self_trade_prevention_type": "taker_at_cross", "client_order_id": req.client_order_id,
            "post_only": False, "cancel_order_on_pause": True}


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def state_of(filled: float, requested: float, *, resting: bool) -> FillState:
    if filled >= requested - 1e-9 and requested > 0:
        return FillState.FILLED
    if filled > 1e-9:
        return FillState.PARTIAL
    return FillState.UNFILLED


@dataclass
class KalshiExecution:
    api_key: str
    private_key: Any
    journal: Journal
    mode: Mode
    base_url: str = DEMO_BASE
    client: Client | None = None
    clock: Callable[[], float] = time.time
    mono: Callable[[], float] = time.monotonic
    venue: str = "kalshi"
    submits: int = 0
    unconfirmed: int = 0
    last_error: str = ""
    _requests: dict[str, OrderRequest] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = Client("kalshi-exec", rate=8, burst=8, cache_dir=None, timeout=10.0)
        if self.mode.risks_capital and self.base_url == DEMO_BASE:
            raise ValueError("a capital-risking mode on the demo host is a configuration error")
        if not self.mode.risks_capital and self.base_url == PROD_BASE and self.mode is not Mode.DEMO_EXECUTION:
            pass

    def _headers(self, method: str, path: str) -> dict:
        ts, sig = sign(self.private_key, method, path)
        return {"KALSHI-ACCESS-KEY": self.api_key, "KALSHI-ACCESS-TIMESTAMP": ts,
                "KALSHI-ACCESS-SIGNATURE": sig, "Accept": "application/json"}

    # ── the order path ───────────────────────────────────────────────────
    def submit(self, req: OrderRequest, clearance) -> Ack:
        t = self.clock()
        refused = admit(req, clearance, venue=self.venue, mode=self.mode, needs=Mode.DEMO_EXECUTION, now=t,
                         now_mono=self.mono(), hedge=req.hedge)
        if refused is not None:
            return refused
        self.journal.pending(req, mode=self.mode.value, now=t)       # BEFORE the POST
        self._requests[req.client_order_id] = req
        path = f"{API}/portfolio/events/orders"
        self.submits += 1
        try:
            d = self.client.post_json_once(self.base_url + path, order_body(req), headers=self._headers("POST", path))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode()[:300]
            except Exception:  # noqa: BLE001
                pass
            ack = Ack(self.venue, req.client_order_id, None, FillState.REJECTED, 0.0, None, None,
                      f"HTTP {e.code}", self.clock(), detail=body)
            self.journal.record(ack, kind="reject", raw={"http": e.code, "body": body})
            return ack
        except Exception as exc:  # noqa: BLE001 -- ambiguous: the venue may hold the order
            self.unconfirmed += 1
            self.last_error = brief_error(exc)
            ack = Ack(self.venue, req.client_order_id, None, FillState.UNCONFIRMED, 0.0, None, None,
                      "TRANSPORT", self.clock(), detail=self.last_error)
            self.journal.record(ack, kind="unconfirmed", raw={"error": self.last_error})
            return ack
        ack = self._ack_from_create(req, d if isinstance(d, dict) else {})
        self.journal.record(ack, kind="ack", raw=d if isinstance(d, dict) else None)
        return ack

    def _ack_from_create(self, req: OrderRequest, d: dict) -> Ack:
        o = d.get("order") if isinstance(d.get("order"), dict) else d
        filled = _f(o.get("fill_count", o.get("fill_count_fp")))
        remaining = _f(o.get("remaining_count", o.get("remaining_count_fp")), req.contracts - filled)
        avg = o.get("average_fill_price")
        avg_fee = o.get("average_fee_paid")
        fee = None if avg_fee is None else _f(avg_fee) * filled
        if req.side == "buy_no" and avg is not None:
            avg = 1.0 - _f(avg)
        resting = req.time_in_force == "gtc" and remaining > 1e-9
        st = state_of(filled, req.contracts, resting=resting)
        return Ack(self.venue, req.client_order_id, o.get("order_id"), st, filled,
                   None if avg is None else _f(avg), fee, "created", self.clock(), open=resting)

    def status(self, client_order_id: str) -> OrderState:
        row = self.journal.get(client_order_id)
        t = self.clock()
        if row is None or not row.get("venue_order_id"):
            # No venue id: the POST never answered. The venue may still hold it under our client id.
            found = self._find_by_client_id(client_order_id)
            if found is None:
                return OrderState(self.venue, client_order_id, None, FillState.UNCONFIRMED, 0.0, None, None,
                                  "NOT_FOUND", t, detail="no venue order id and no order carrying this client id")
            row = {**(row or {}), "venue_order_id": found.get("order_id"), "contracts": _f(found.get("initial_count_fp")),
                   "side": (row or {}).get("side", "buy_yes")}
            o = found
        else:
            path = f"{API}/portfolio/orders/{row['venue_order_id']}"
            try:
                d = self.client.get_json(self.base_url + path, use_cache=False, headers=self._headers("GET", path))
            except Exception as exc:  # noqa: BLE001
                self.last_error = brief_error(exc)
                return OrderState(self.venue, client_order_id, row["venue_order_id"], FillState.UNCONFIRMED, 0.0,
                                  None, None, "TRANSPORT", t, detail=self.last_error)
            o = d.get("order", d)
        st = self._state_from_order(o, client_order_id, float(row.get("contracts") or _f(o.get("initial_count_fp"))),
                                    row.get("side", "buy_yes"), t)
        self.journal.record(st, kind="status", raw=o)
        return st

    def _state_from_order(self, o: dict, cid: str, requested: float, side: str, t: float) -> OrderState:
        status = str(o.get("status", "")).lower()
        filled = _f(o.get("fill_count_fp", o.get("fill_count")))
        fee = _f(o.get("taker_fees_dollars")) + _f(o.get("maker_fees_dollars"))
        cost = _f(o.get("taker_fill_cost_dollars")) + _f(o.get("maker_fill_cost_dollars"))
        avg = (cost / filled) if filled else None
        if avg is not None and side == "buy_no":
            avg = 1.0 - avg if _f(o.get("yes_price_dollars")) else avg
        resting = status == "resting"
        state = state_of(filled, requested, resting=resting)
        return OrderState(self.venue, cid, o.get("order_id"), state, filled, avg, fee if filled else None, status, t,
                          open=resting, final=status in ("executed", "canceled"))

    def _find_by_client_id(self, client_order_id: str) -> dict | None:
        path = f"{API}/portfolio/orders"
        try:
            d = self.client.get_json(self.base_url + path, params={"limit": 200}, use_cache=False,
                                     headers=self._headers("GET", path))
        except Exception as exc:  # noqa: BLE001
            self.last_error = brief_error(exc)
            return None
        for o in d.get("orders") or []:
            if o.get("client_order_id") == client_order_id:
                return o
        return None

    def cancel(self, client_order_id: str) -> Ack:
        row = self.journal.get(client_order_id)
        t = self.clock()
        if row is None or not row.get("venue_order_id"):
            st = self.status(client_order_id)
            if st.venue_order_id is None:
                return Ack(self.venue, client_order_id, None, FillState.UNCONFIRMED, 0.0, None, None, "NOT_FOUND", t)
            row = self.journal.get(client_order_id)
        path = f"{API}/portfolio/events/orders/{row['venue_order_id']}"
        try:
            self.client.delete_json(self.base_url + path, headers=self._headers("DELETE", path))
        except urllib.error.HTTPError as e:
            if e.code != 404:
                self.last_error = f"HTTP {e.code}"
        except Exception as exc:  # noqa: BLE001
            self.last_error = brief_error(exc)
        st = self.status(client_order_id)         # the venue's word on what was filled before the cancel
        self.journal.record(st, kind="cancel")
        return st

    def fills(self, *, since_utc: float) -> Sequence[FillRecord]:
        path = f"{API}/portfolio/fills"
        d = self.client.get_json(self.base_url + path, params={"min_ts": int(since_utc), "limit": 1000},
                                 use_cache=False, headers=self._headers("GET", path))
        out = []
        for f in d.get("fills") or []:
            side = f.get("outcome_side") or f.get("side") or "yes"
            price = _f(f.get("yes_price_dollars")) if side == "yes" else _f(f.get("no_price_dollars"))
            rec = FillRecord(self.venue, str(f.get("order_id")), str(f.get("fill_id") or f.get("trade_id")),
                             _f(f.get("count_fp", f.get("count"))), price, _f(f.get("fee_cost")),
                             bool(f.get("is_taker")), _f(f.get("ts"), since_utc), True)
            self.journal.record_fill(rec)
            out.append(rec)
        return out

    def balance(self) -> Balance | None:
        path = f"{API}/portfolio/balance"
        try:
            d = self.client.get_json(self.base_url + path, use_cache=False, headers=self._headers("GET", path))
        except Exception as exc:  # noqa: BLE001
            self.last_error = brief_error(exc)
            return None
        return Balance(self.venue, _f(d.get("balance_dollars")), self.clock())

    def cancel_all(self) -> int:
        path = f"{API}/portfolio/orders"
        try:
            d = self.client.get_json(self.base_url + path, params={"status": "resting", "limit": 200},
                                     use_cache=False, headers=self._headers("GET", path))
        except Exception as exc:  # noqa: BLE001
            self.last_error = brief_error(exc)
            return 0
        n = 0
        for o in d.get("orders") or []:
            p = f"{API}/portfolio/events/orders/{o['order_id']}"
            try:
                self.client.delete_json(self.base_url + p, headers=self._headers("DELETE", p))
                n += 1
            except Exception as exc:  # noqa: BLE001
                self.last_error = brief_error(exc)
        return n

    def stats(self) -> dict:
        return {"venue": self.venue, "mode": self.mode.value, "host": self.base_url, "submits": self.submits,
                "unconfirmed": self.unconfirmed, "last_error": self.last_error}
