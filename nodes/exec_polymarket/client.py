#!/usr/bin/env python3
"""Polymarket order path. Disarmed by construction, like Kalshi's, with two venue-specific facts.

EVERY OUTCOME IS ITS OWN TOKEN. There is no "buy NO" on this venue: the NO outcome is a separate
ERC-1155 token with its own book. An OrderRequest here is always `buy_yes` of the token named
by `market_id`; `buy_no` is refused with the explanation.

MATCHED IS NOT SETTLED. POST /order answering `matched` means the CLOB matched the order; the
trade then goes MATCHED -> MINED -> CONFIRMED on-chain, or RETRYING/FAILED. A matched fill is
FILLED for the purpose of HEDGING -- the venue reported it authoritatively and the other leg
must be sent -- and carries `settlement_pending=True` until `fills()` sees CONFIRMED. A FAILED
trade is a reversal the reconcile node has to handle; it is never silently a no-fill.

The wire work (EIP-712 order signing against the CTF or neg-risk exchange, tick-size rounding,
L1/L2 auth) is delegated to a transport. `PyClobTransport` wraps `py_clob_client_v2` and imports it
lazily; when the library is absent the adapter cannot be built for a real-order mode, and says
so. Tests inject a fake transport. There is no demo host: DEMO_EXECUTION uses the paper venue
for this leg (spec pushback recorded in GATE_TO_LIVE).

The wallet private key is a different custody class from Kalshi's RSA key: it moves funds. It
lives in its own 600-mode file named by JANUS_PM_WALLET_KEY_PATH, never in JANUS_CREDS, never on
an EC2 instance without a KMS, and it is read by the transport only.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import threading
import time
from dataclasses import dataclass, field, replace
from decimal import Decimal, ROUND_DOWN
from typing import Any, Callable, Protocol, Sequence

from kernel.execution_protocol import Ack, Balance, FillRecord, OrderRequest, OrderState, Position
from kernel.redact import brief_error
from kernel.schema import Book, FillState, Mode
from nodes.execution.gate import admit
from nodes.execution.journal import Journal
from nodes.exec_polymarket.quantity import BUY_CAP_UNPROVEN, taker_trade_vwap
from nodes.exec_polymarket.fill_projection import project_account_trade
from nodes.exec_polymarket.post_only import post_only_order, check_post_only_quantity
from nodes.exec_polymarket.post_only import (
    POST_ONLY_TERMINAL_GRACE_S, ensure_post_only_tables, claim_post_only, release_post_only, reviewed_signing_domain,
    record_post_only_violation,
)
from nodes.exec_polymarket.post_only_sizing import validate_post_only_amounts

ORDER_TYPE = {"fok": "FOK", "ioc": "FAK", "gtc": "GTC"}
FINAL_TRADE = {"CONFIRMED"}
DEAD_TRADE = {"FAILED"}
# The CLOB order lookup is eventually consistent with its trade feed. On 2026-09-08 two FAKs
# returned `not_found` immediately and then appeared as confirmed trades. Absence is ambiguous
# until both endpoints have disagreed for this long; the reservation stays held meanwhile.
NOT_FOUND_GRACE_S = 120.0
TRADE_CHECK_INTERVAL_S = 1.0

# Append-only source authority, separate from the mutable execution projection. Orphan fills
# need this too: they may acquire an order/client id only on a later guard adoption pass.
PM_CASH_SOURCES_DDL = """
CREATE TABLE IF NOT EXISTS pm_cash_sources(
  id INTEGER PRIMARY KEY AUTOINCREMENT, fill_id TEXT NOT NULL, source_sha256 TEXT NOT NULL,
  source_json TEXT NOT NULL, observed_utc REAL NOT NULL);
CREATE INDEX IF NOT EXISTS pm_cash_sources_fill ON pm_cash_sources(fill_id, id);
"""

# L65/F20: operator-accepted immediate entry is deliberately narrower than the signed arm.  These
# constants remain hard even if a future override grows; the generic BUY signer stays blocked.
#: F21 (GATE_TO_LIVE 2026-09-11): one rung up from the smallest size. The override arms the caps;
#: this is the wire's own ceiling, so a larger override alone can never send more than this.
BOUNDED_TAKER_MAX_CONTRACTS = Decimal("25")
BOUNDED_TAKER_MAX_COLLATERAL_USD = Decimal("30")
BOUNDED_TAKER_MAX_ACCEPTED_EXCESS = Decimal("1")
BOUNDED_TAKER_DDL = """
CREATE TABLE IF NOT EXISTS pm_bounded_taker_orders(
  client_order_id TEXT PRIMARY KEY, requested_contracts TEXT NOT NULL,
  max_requested_contracts TEXT NOT NULL, max_collateral_usd TEXT NOT NULL,
  max_accepted_excess TEXT NOT NULL, authorized_utc REAL NOT NULL);
"""


class TransportUnavailable(RuntimeError):
    pass


PM_DATA_API = "https://data-api.polymarket.com"
PM_USER_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/user"


class PolymarketUserStream:
    """Authenticated order/trade FIFO used to hedge on MATCHED, before REST finality.

    Polymarket documents the user channel as the real-time source for account order changes and
    trade matches. REST remains the reconnect/backfill authority; this cache only closes the
    several-minute blind spot between a `delayed` POST and the trade appearing in REST.
    """

    def __init__(self, creds, *, url: str = PM_USER_WS):
        self.url = url
        self.auth = {"apiKey": creds.api_key, "secret": creds.api_secret,
                     "passphrase": creds.api_passphrase}
        self.connected = False
        self.frames = 0
        self.errors = 0
        self.last_error = ""
        self.last_frame_utc = 0.0
        #: L112: what the account channel actually delivers, by kind. `frames` alone cannot tell a
        #: working feed from a firehose being discarded -- `handle` increments it before the
        #: PING/PONG branch and drops every kind that is not `order` or `trade`. Measured as a rate
        #: the channel takes 0.099 frames/s against 542 and 971 on the public streams, which is
        #: about one per ten seconds: nearly all keepalive. Whether the few real events are enough
        #: is the question this counter answers, and it costs one dict.
        self.kinds: dict[str, int] = {}
        self._orders: dict[str, dict] = {}
        self._trades: dict[str, dict[str, dict]] = {}
        self._role_evidence: dict[str, dict[str, set[str]]] = {}
        self._quantity_evidence: dict[str, dict[str, Decimal]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _get(d: dict, snake: str, camel: str | None = None, default=None):
        return d.get(snake, d.get(camel or snake, default))

    def _remember_quantity(self, oid, tid, value):
        try:
            quantity = Decimal(str(value))
            if quantity.is_finite() and quantity >= 0:
                previous = self._quantity_evidence.setdefault(oid, {}).get(tid, Decimal(0))
                self._quantity_evidence[oid][tid] = max(previous, quantity)
        except ArithmeticError:
            pass

    def _count(self, kind: str) -> None:
        self.kinds[kind] = self.kinds.get(kind, 0) + 1

    def handle(self, raw, *, now: float | None = None) -> list[str]:
        self.frames += 1
        if isinstance(raw, str):
            if raw.strip().upper() in ("PING", "PONG"):
                self.last_frame_utc = now or time.time()
                self._count("pong")
                return ["pong"]
            try:
                raw = json.loads(raw)
            except ValueError:
                self.errors += 1
                self.last_error = "non-JSON user frame"
                self._count("error")
                return ["error"]
        events = raw if isinstance(raw, list) else [raw]
        kinds = []
        with self._lock:
            for ev in events:
                if not isinstance(ev, dict):
                    continue
                payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else ev
                kind = str(ev.get("event_type") or ev.get("type") or "").lower()
                if kind == "order":
                    oid = str(payload.get("id") or "")
                    if oid:
                        self._orders[oid] = dict(payload)
                        kinds.append("order")
                elif kind == "trade":
                    tid = str(payload.get("id") or "")
                    taker = str(self._get(payload, "taker_order_id", "takerOrderId", "") or "")
                    if taker and tid:
                        self._trades.setdefault(taker, {})[tid] = {**payload, "_janus_trade_role": "taker"}
                        if str(payload.get("status", "")).upper().replace("TRADE_STATUS_", "") not in DEAD_TRADE:
                            self._role_evidence.setdefault(taker, {}).setdefault(tid, set()).add("taker")
                            self._remember_quantity(taker, tid, self._get(payload, "size", "matchedAmount", 0))
                    for maker in self._get(payload, "maker_orders", "makerOrders", ()) or ():
                        oid = str(self._get(maker, "order_id", "orderId", "") or "")
                        if oid and tid:
                            row = dict(maker)
                            row["id"] = tid
                            row["status"] = payload.get("status")
                            row["size"] = self._get(maker, "matched_amount", "matchedAmount", 0)
                            row["_janus_trade_role"] = "maker"
                            self._trades.setdefault(oid, {})[tid] = row
                            if str(payload.get("status", "")).upper().replace("TRADE_STATUS_", "") not in DEAD_TRADE:
                                self._role_evidence.setdefault(oid, {}).setdefault(tid, set()).add("maker")
                                self._remember_quantity(oid, tid, row["size"])
                    if taker or self._get(payload, "maker_orders", "makerOrders"):
                        kinds.append("trade")
            self.last_frame_utc = now or time.time()
        for k in kinds or ["dropped"]:
            self._count(k)
        return kinds

    def stats(self) -> dict:
        # `snapshots` and `deltas` are the socket_health columns the account channel never used;
        # orders and trades ride in them so the split persists with no schema change.
        return {"connected": self.connected, "frames": self.frames, "errors": self.errors,
                "last_error": self.last_error, "kinds": dict(self.kinds),
                "snapshots": self.kinds.get("order", 0), "deltas": self.kinds.get("trade", 0),
                "age_s": round(time.time() - self.last_frame_utc, 2) if self.last_frame_utc else None}

    def order(self, order_id: str) -> dict | None:
        """Return a REST-order shaped match or terminal zero-fill seen by the socket."""
        with self._lock:
            trades = list(self._trades.get(order_id, {}).values())
            order = dict(self._orders.get(order_id, {}))
            evidence = {tid: sorted(roles) for tid, roles in self._role_evidence.get(order_id, {}).items()}
            observed = float(sum(self._quantity_evidence.get(order_id, {}).values(), Decimal(0)))
        role_detail = {"_janus_trade_roles": sorted({role for roles in evidence.values() for role in roles}),
                       "_janus_role_evidence": evidence} if evidence else {}
        good = [t for t in trades if str(t.get("status", "")).upper().replace("TRADE_STATUS_", "") not in DEAD_TRADE]
        if good:
            qty = sum(_f(self._get(t, "size", "matchedAmount")) for t in good)
            prices = [(taker_trade_vwap(t) if t.get("_janus_trade_role") == "taker"
                       else _f(t.get("price"), None)) for t in good]
            cost = (sum(_f(self._get(t, "size", "matchedAmount")) * price
                        for t, price in zip(good, prices)) if all(p is not None for p in prices) else None)
            return {"id": order_id, "status": "MATCHED", "size_matched": max(qty, observed),
                    "price": (cost / qty if cost is not None and qty and qty >= observed else None), "user_stream": True, **role_detail}
        matched = _f(self._get(order, "size_matched", "sizeMatched"))
        if matched > 0:
            return {"id": order_id, "status": str(order.get("status") or "MATCHED"),
                    "size_matched": max(matched, observed), "price": order.get("price"), "user_stream": True, **role_detail}
        status = str(order.get("status") or "").upper()
        event_type = str(self._get(order, "order_event_type", "orderEventType", order.get("type") or "")).upper()
        order_type = str(self._get(order, "order_type", "orderType", "")).upper()
        # A cancellation is Polymarket's authoritative statement that the remaining amount is
        # gone.  UNMATCHED is terminal only for the immediate-or-cancel family: a resting GTC can
        # be unmatched and still live, whereas a FAK/FOK/IOC cannot survive the matching pass.
        zero_final = status in ("CANCELED", "CANCELLED") or event_type == "CANCELLATION"
        zero_final = zero_final or (status == "UNMATCHED" and order_type in ("FAK", "FOK", "IOC"))
        if zero_final:
            return {"id": order_id, "status": "CANCELED", "size_matched": observed,
                    "price": order.get("price"), "user_stream": True, **role_detail}
        if evidence:
            return {"id": order_id, "status": "UNKNOWN", "size_matched": observed,
                    "price": None, "user_stream": True, **role_detail}
        return None

    async def run(self, stop: asyncio.Event, *, connect=None, on_state=None) -> None:
        import websockets
        connect = connect or (lambda url: websockets.connect(url, ping_interval=None, max_size=2 ** 20))
        backoff = 1.0
        while not stop.is_set():
            ping_task = None
            try:
                async with connect(self.url) as ws:
                    await ws.send(json.dumps({"auth": self.auth, "type": "user"}))
                    self.connected = True
                    backoff = 1.0
                    if on_state:
                        on_state("connected", "authenticated account feed")

                    async def pinger():
                        while True:
                            await asyncio.sleep(10.0)
                            await ws.send("PING")

                    ping_task = asyncio.create_task(pinger())
                    while not stop.is_set():
                        raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                        self.handle(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 -- reconnect plus REST backfill is the contract
                self.connected = False
                self.errors += 1
                self.last_error = brief_error(exc)
                if on_state:
                    on_state("reconnect", self.last_error)
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 2)
            finally:
                if ping_task:
                    ping_task.cancel()
        self.connected = False


class ClobTransport(Protocol):
    def buy_contract_cap_error(self) -> str | None: ...
    def post_order(self, *, token_id: str, price: float, size: float, order_type: str,
                   side: str = "BUY", tick: float | None = None) -> dict: ...
    def get_order(self, order_id: str) -> dict: ...
    def cancel(self, order_id: str) -> dict: ...
    def trades(self, *, after_ts: float) -> list[dict]: ...
    def balance_usd(self) -> float | None: ...
    def cancel_all(self) -> int: ...
    #: The protection layer's reads (2026-09-08); a transport may raise, the client turns it into None.
    def book(self, token_id: str) -> dict: ...
    def positions(self) -> list[dict] | None: ...
    def ensure_sell_allowance(self, token_id: str) -> bool: ...
    def user_order(self, order_id: str) -> dict | None: ...


class PyClobTransport:
    """The real thing, through py_clob_client_v2. Built only for real-order modes.

    CLOB V2 (2026-04-28): Polymarket replaced the exchange contracts, the order format (EIP-712
    domain version 2; no fee/nonce/taker fields) and the collateral -- pUSD, not USDC.e. The V1
    client this wrapped kept working for reads and reported the account's collateral as 0.00
    while the account held 95.60 pUSD (2026-09-07); V1-signed orders are refused outright."""
    last_error: str | None = None

    def __init__(self, host: str = "https://clob.polymarket.com", chain_id: int = 137):
        try:
            from py_clob_client_v2.client import ClobClient  # type: ignore
            from py_clob_client_v2 import clob_types as T  # type: ignore
        except ImportError as exc:
            raise TransportUnavailable("py_clob_client_v2 is not installed; `pip install py-clob-client-v2` before "
                                       "a real-order Polymarket mode. PAPER and SHADOW do not need it.") from exc
        key_path = os.environ.get("JANUS_PM_WALLET_KEY_PATH")
        if not key_path or not os.path.exists(key_path):
            raise TransportUnavailable("JANUS_PM_WALLET_KEY_PATH is unset or missing")
        if (os.stat(key_path).st_mode & 0o077) != 0:
            raise TransportUnavailable(f"{key_path} must be mode 600")
        key = open(key_path).read().strip()
        funder = os.environ.get("JANUS_PM_FUNDER")
        sig_type = int(os.environ.get("JANUS_PM_SIGNATURE_TYPE", "0"))
        self._c = ClobClient(host, chain_id, key=key, signature_type=sig_type, funder=funder)
        self._c.set_api_creds(self._c.create_or_derive_api_key())
        self.user_stream = PolymarketUserStream(self._c.creds)
        self._T = T
        self._sig_type = sig_type
        self.last_error: str | None = None

    @staticmethod
    def _cent_exact_buy(*, size: float, price: float, tick: float | None) -> tuple[float, float] | None:
        """Nominal SDK size/price with whole-cent collateral; NOT a received-share cap.

        CLOB V2's marketable BUY validator accepts two maker decimals, while the SDK's ordinary
        limit builder otherwise follows the market tick.  A collateral-sized market BUY fixes
        that precision but lets price improvement increase shares (F14: 5 became 7.769231). Search
        the finite size/tick grid instead. Preserve the limit first (fill probability), then take
        the largest valid nominal size. L53 proved the exchange can still return excess shares,
        so this precision helper cannot authorize a BUY and the real transport refuses it.
        """
        size_d = Decimal(str(size)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        price_d = Decimal(str(price))
        if size_d < Decimal("5.00") or price_d <= 0:
            return None
        if tick is None:
            places = max(0, -price_d.normalize().as_tuple().exponent)
            tick_d = Decimal(1).scaleb(-places)
        else:
            tick_d = Decimal(str(tick))
        places = max(0, -tick_d.normalize().as_tuple().exponent,
                     -price_d.normalize().as_tuple().exponent)
        scale = 10 ** places
        tick_units = int(tick_d * scale)
        if tick_units <= 0:
            return None
        max_k = int((price_d / tick_d).to_integral_value(rounding=ROUND_DOWN))
        target_n = int(size_d * 100)
        for k in range(max_k, 0, -1):
            divisor = scale // math.gcd(k * tick_units, scale)
            n = (target_n // divisor) * divisor
            if n < 500:
                continue
            candidate_price = tick_d * k
            maker = (Decimal(n) / 100) * candidate_price
            if maker < Decimal("1.00") or maker != maker.quantize(Decimal("0.01")):
                continue
            return float(candidate_price), float(Decimal(n) / 100)
        return None

    @staticmethod
    def buy_contract_cap_error() -> str:
        # There is no max-received-share field in the installed V2 wire. GTC also
        # crosses as taker unless post-only, which this execution route does not use.
        # This is deliberately not an environment flag or operator-configurable bypass.
        return BUY_CAP_UNPROVEN

    def post_order(self, *, token_id: str, price: float, size: float, order_type: str,
                   side: str = "BUY", tick: float | None = None) -> dict:
        # Defence at the actual signing boundary, including callers outside submit().
        if side != "SELL":
            return {"success": False, "status": "rejected", "errorMsg": BUY_CAP_UNPROVEN,
                    "prewire": True, "code": "QUANTITY_CAP_UNPROVEN"}
        # side "SELL" (2026-09-08): the protection layer sells held shares back and the market
        # builder's maker amount is share-sized, limiting how many held tokens can be sold.
        typ = getattr(self._T.OrderType, order_type)
        if order_type in ("FAK", "FOK") and side == "SELL":
            amount = Decimal(str(size))
            amount = float(amount.quantize(Decimal("0.01"), rounding=ROUND_DOWN))
            args = self._T.MarketOrderArgsV2(token_id=token_id, amount=amount, price=price,
                                             side=side, order_type=typ)
            signed = self._c.create_market_order(args)
        else:
            args = self._T.OrderArgsV2(token_id=token_id, price=price, size=size, side=side)
            signed = self._c.create_order(args)
        # defer_exec: the library otherwise polls the fill's settlement hashes INSIDE the post
        # (best effort, seconds); the hedge needs the match, not the hash. fills() reads
        # CONFIRMED trades later (2026-09-07).
        return self._c.post_order(signed, typ, defer_exec=True)

    def post_bounded_taker_buy(self, *, token_id: str, price: float, size: float,
                              order_type: str, tick: float | None = None) -> dict:
        """The only immediate BUY signer: a fixed small collateral envelope, never generic."""
        typ = getattr(self._T.OrderType, order_type)
        q, px = Decimal(str(size)), Decimal(str(price))
        collateral = q * px
        if (order_type not in ("FAK", "FOK") or not q.is_finite() or not px.is_finite()
                or q <= 0 or q > BOUNDED_TAKER_MAX_CONTRACTS
                or collateral > BOUNDED_TAKER_MAX_COLLATERAL_USD
                or collateral != collateral.quantize(Decimal("0.01"))):
            return {"success": False, "status": "rejected", "prewire": True,
                    "code": "BOUNDED_TAKER_CAP", "errorMsg": "bounded taker envelope/precision refused"}
        args = self._T.MarketOrderArgsV2(token_id=token_id, amount=float(collateral), price=float(px),
                                         side="BUY", order_type=typ)
        signed = self._c.create_market_order(args)
        return self._c.post_order(signed, typ, defer_exec=True)

    def get_order(self, order_id: str) -> dict:
        return self._c.get_order(order_id)

    def prepare_post_only_buy(self, req: OrderRequest) -> dict:
        """Sign one V2 maker order, but do not post; caller must durably journal it first."""
        from py_clob_client_v2.order_utils.exchange_order_builder_v2 import ExchangeOrderBuilderV2
        from py_clob_client_v2.order_utils.model.order_data_v2 import order_to_json_v2
        if not req.post_only or req.time_in_force != "gtc" or req.side != "buy_yes" or req.hedge:
            raise ValueError("only post-only GTC first-leg BUY is supported")
        config = reviewed_signing_domain(self._c)
        tick = str(Decimal(str(req.tick)).normalize())
        neg = self._c.get_neg_risk(req.market_id)
        options = self._T.CreateOrderOptions(tick_size=tick, neg_risk=neg)
        signed = self._c.builder.build_order(
            self._T.OrderArgsV2(token_id=req.market_id, price=req.price, size=req.contracts, side="BUY"),
            options, version=2)
        validate_post_only_amounts(maker_amount=signed.makerAmount, taker_amount=signed.takerAmount,
                                  requested_contracts=req.contracts, limit_price=req.price)
        address = config.neg_risk_exchange_v2 if neg else config.exchange_v2
        builder = ExchangeOrderBuilderV2(address, self._c.chain_id, self._c.signer)
        order_id = builder.build_order_hash(builder.build_order_typed_data(signed))
        wire = order_to_json_v2(signed, "redacted", "GTC", True, True)
        wire["order"]["signature"] = "redacted"  # Exact economic fields, not a replayable authorization.
        wire["_janus_reviewed_domain"] = {"chainId": 137, "version": "2", "verifyingContract": address,
                                          "collateral": config.collateral, "conditional_tokens": config.conditional_tokens}
        return {"signed": signed, "venue_order_id": order_id, "maker_amount": signed.makerAmount,
                "taker_amount": signed.takerAmount, "wire": wire}

    def post_prepared_post_only(self, prepared: dict) -> dict:
        # Separate from generic post_order: neither FAK/FOK nor ordinary GTC is unblocked.
        return self._c.post_order(prepared["signed"], self._T.OrderType.GTC, post_only=True, defer_exec=True)

    def user_order(self, order_id: str) -> dict | None:
        return self.user_stream.order(order_id)

    def cancel(self, order_id: str) -> dict:
        return self._c.cancel_order(self._T.OrderPayload(orderID=order_id))

    def trades(self, *, after_ts: float) -> list[dict]:
        return list(self._c.get_trades(self._T.TradeParams(after=int(after_ts))))

    def trade_activity(self, *, after_ts: float) -> list[dict]:
        """Authoritative cash movements, kept as decimals and joined by transaction/token/side.

        CLOB V2's top-level trade price can describe only the first maker, and fee_rate_bps
        can be zero despite a charged fee. Data API activity supplies actual cash including
        fees. This is a read-side call; never used while encoding or posting an order.
        """
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen
        funder = os.environ.get("JANUS_PM_FUNDER")
        if not funder:
            raise ValueError("cash activity requires JANUS_PM_FUNDER")
        rows, offset = [], 0
        while offset <= 5000:
            params = {"user": funder, "type": "TRADE", "start": max(1, int(after_ts) - 120),
                      "sortBy": "TIMESTAMP", "sortDirection": "ASC", "limit": 500, "offset": offset}
            request = Request(f"{PM_DATA_API}/activity?{urlencode(params)}", method="GET",
                              headers={"Accept": "application/json", "User-Agent": "Janus-accounting"})
            with urlopen(request, timeout=5) as response:
                page = json.loads(response.read(), parse_float=Decimal)
            if not isinstance(page, list):
                raise ValueError("cash activity response is not a list")
            if not page:
                return rows
            rows.extend(page)
            offset += len(page)
        raise ValueError("cash activity pagination incomplete")

    def balance_usd(self) -> float | None:
        """The account's collateral (pUSD since 2026-04-28), in dollars. The error is kept, never
        swallowed into 'balance could not be confirmed'."""
        try:
            params = self._T.BalanceAllowanceParams(asset_type=self._T.AssetType.COLLATERAL, signature_type=self._sig_type)
            d = self._c.get_balance_allowance(params)
            return float(d.get("balance", 0)) / 1e6
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None

    def cancel_all(self) -> int:
        d = self._c.cancel_all()
        return len(d.get("canceled", [])) if isinstance(d, dict) else 0

    def book(self, token_id: str) -> dict:
        ob = self._c.get_order_book(token_id)
        return dict(ob.__dict__) if hasattr(ob, "__dict__") and not isinstance(ob, dict) else dict(ob)

    def positions(self) -> list[dict] | None:
        """What the data API says the funder holds (asset, size, avgPrice, ...). No signature: a
        public read of a public address. None when unreachable."""
        self.position_read_evidence = None
        funder = os.environ.get("JANUS_PM_FUNDER")
        if not funder:
            return None
        try:
            from kernel.fetch import Client
            from nodes.exec_polymarket.position_evidence import ENDPOINT, PAGE_LIMIT, MAX_OFFSET, sha
            cl = Client("polymarket-data", rate=2, burst=4, cache_dir=None, timeout=10.0)
            rows, pages = [], []
            for offset in range(0, MAX_OFFSET + 1, PAGE_LIMIT):
                page = cl.get_json(ENDPOINT, params={"user": funder, "sizeThreshold": 0,
                                                    "limit": PAGE_LIMIT, "offset": offset}, use_cache=False)
                if not isinstance(page, list) or len(page) > PAGE_LIMIT:
                    raise ValueError('malformed positions page')
                pages.append(dict(offset=offset, count=len(page), sha256=sha(page)))
                rows.extend(page)
                if len(page) < PAGE_LIMIT:
                    self.position_read_evidence = dict(user=funder, sizeThreshold=0, limit=PAGE_LIMIT,
                                                       pages=pages, complete=True)
                    return rows
            raise ValueError('positions pagination cap reached without terminal page')
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None

    def ensure_sell_allowance(self, token_id: str) -> bool:
        """A SELL needs the exchange approved on the conditional token; the library sets it (an
        on-chain approval, once per token). True when the venue accepts the call."""
        try:
            params = self._T.BalanceAllowanceParams(asset_type=self._T.AssetType.CONDITIONAL, token_id=token_id,
                                                    signature_type=self._sig_type)
            self._c.update_balance_allowance(params)
            return True
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _activity_key(row: dict, *, trade: bool) -> tuple[str, str, str]:
    return (str(row.get("transaction_hash" if trade else "transactionHash") or "").lower(),
            str(row.get("asset_id" if trade else "asset") or ""), str(row.get("side") or "").upper())


def authoritative_cash_fill(trade: dict, activity: dict) -> tuple[float, float]:
    """Return source VWAP and cash-derived fee for an exact one-trade activity match.

    Do not reconstruct cash from a CLOB top-level price or a model fee. Data API price is
    its volume-weighted notional price; usdcSize is actual cash including paid fees. Its
    decimal price can be rounded, so fee is the residual that preserves exact total cash.
    """
    if not all(_activity_key(trade, trade=True)) or _activity_key(trade, trade=True) != _activity_key(activity, trade=False):
        raise ValueError("cash activity identity does not match trade")
    if activity.get("type") != "TRADE" or activity.get("side") not in {"BUY", "SELL"}:
        raise ValueError("cash activity is not a trade")
    size = Decimal(str(trade.get("size")))
    activity_size = Decimal(str(activity.get("size")))
    price = Decimal(str(activity.get("price")))
    cash = Decimal(str(activity.get("usdcSize")))
    if not all(x.is_finite() for x in (size, activity_size, price, cash)):
        raise ValueError("nonfinite cash activity")
    if size != activity_size or size <= 0 or not 0 < price < 1 or cash < 0:
        raise ValueError("cash activity quantity/price is inconsistent")
    if trade.get('_janus_projection_role') == 'MAKER':
        maker_price = Decimal(str(trade.get('price')))
        if not maker_price.is_finite() or not 0 < maker_price < 1 or abs(maker_price - price) > Decimal('0.000000001'):
            raise ValueError('cash VWAP disagrees with owned maker price')
        price = maker_price  # Maker price belongs to this order, never the taker top-level price.
    notional = size * price
    fee = cash - notional if activity["side"] == "BUY" else notional - cash
    # A ten-decimal reported VWAP may create a sub-micro-dollar negative residual at zero
    # fee. Keep its precision; a larger credit is a different activity requiring review.
    if fee < Decimal('-0.000001'):
        raise ValueError("cash activity implies an unexplained credit")
    return float(price), float(fee)


@dataclass
class PolymarketExecution:
    transport: ClobTransport
    journal: Journal
    mode: Mode
    clock: Callable[[], float] = time.time
    mono: Callable[[], float] = time.monotonic
    venue: str = "polymarket"
    #: Coordinator-visible part of this adapter's terminality contract. Cancel is still dispatched
    #: at the maker deadline; this only lets two stable terminal GETs mature before a false latch.
    terminal_proof_grace_s: float = POST_ONLY_TERMINAL_GRACE_S
    #: The market's fee params (Gamma feeSchedule) for the pinned fee. CLOB V2 charges the taker
    #: fee against collateral but reports fee_rate_bps 0 on the trade record (2026-09-07: balance
    #: moved by fills + exactly the pinned 0.0604 while the trade said 0). When the venue reports
    #: no fee and params are known, the fill carries the pinned fee, labelled so in the journal.
    fee_params: Any = None
    #: Live supervision shares one venue client across many concurrent games. Fee schedules are
    #: market-specific, so a single mutable ``fee_params`` slot races with whichever poller ran
    #: last. The live grid fills this map by token; ``fee_params`` remains the proof/test fallback.
    fee_params_by_market: dict[str, Any] = field(default_factory=dict)
    submits: int = 0
    unconfirmed: int = 0
    rejected_http: int = 0
    last_fee_source: str = ""
    last_error: str = ""
    #: A partial trade batch still returns validated quantities, but cannot prove cash
    #: uniqueness or terminal lifecycle coverage. Guard/status consume this separately.
    projection_batch_error: str = ""
    #: A failed disk write cannot erase already observed inventory. Retain exact fill
    #: identities/high-water quantities in this process until operator repair.
    _unpersisted_fills: dict[tuple[str, str], FillRecord] = field(default_factory=dict)
    kill: Any = None
    #: Set when the CLOB answered 403 "Trading restricted in your region": this host cannot place
    #: Polymarket orders at all (2026-09-07, the Ashburn box's first real order). The lane refuses
    #: every cover cheaply from then on; only a restart from a permitted host clears it.
    geoblocked: str | None = None
    _requests: dict[str, OrderRequest] = field(default_factory=dict)
    #: Tokens whose sell allowance was set this process (once per token; the approval is on-chain).
    _sell_ok: set = field(default_factory=set)
    _last_trade_check: dict[str, float] = field(default_factory=dict)
    _post_only_cancel_attempts: dict[str, float] = field(default_factory=dict)
    _post_only_observed: dict[str, Decimal] = field(default_factory=dict)
    persistence_error: str = ""

    def __post_init__(self) -> None:
        self.journal.store.ensure_ddl(PM_CASH_SOURCES_DDL)
        self.journal.store.ensure_ddl(BOUNDED_TAKER_DDL)
        ensure_post_only_tables(self.journal)

    def _post_only_violation(self, cid, code, detail):
        record_post_only_violation(self.journal, cid, code, detail, now=self.clock(), kill=self.kill)

    def _persistence_failure(self, cid, exc):
        self.persistence_error = f"POST_ONLY_PERSISTENCE_FAILED: {cid}: {brief_error(exc)}"
        self.last_error = self.persistence_error
        self.journal_failures = getattr(self, "journal_failures", 0) + 1
        try:
            record_post_only_violation(self.journal, cid, "POST_ONLY_PERSISTENCE_FAILED",
                                       self.persistence_error, now=self.clock(), kill=self.kill)
        except Exception as audit_exc:
            self.persistence_error += "; durable audit also failed: " + brief_error(audit_exc)
        return self.persistence_error

    def _legacy_fill_persistence_failure(self, cid, exc):
        """A historical non-maker order cannot manufacture a post-only violation."""
        from nodes.risk.flags import raise_flag
        self.persistence_error = f"ORDER_PERSISTENCE_FAILED: {cid}: {brief_error(exc)}"
        self.journal_failures = getattr(self, "journal_failures", 0) + 1
        if self.kill is not None:
            try:
                self.kill.latch("live", self.persistence_error)
            except Exception as kill_exc:
                self.persistence_error += "; independent kill failed: " + brief_error(kill_exc)
        try:
            raise_flag(self.journal.store, "ORDER_PERSISTENCE_FAILED", self.persistence_error, now=self.clock())
        except Exception as audit_exc:
            self.persistence_error += "; durable audit also failed: " + brief_error(audit_exc)
        self.last_error = self.persistence_error
        return self.persistence_error

    def _record_post_only_after_wire(self, ack, *, kind, raw, terminal_proof=False):
        try:
            if terminal_proof:
                self.journal.store.con.execute("UPDATE pm_post_only_orders SET terminal_proved=1 WHERE client_order_id=?", (ack.client_order_id,))
            self.journal.record(ack, kind=kind, raw=raw)
            if terminal_proof:
                release_post_only(self.journal, ack.client_order_id, now=self.clock(), reason="explicit post-only rejection")
        except Exception as exc:
            try:
                self.journal.store.con.rollback()
            except Exception:
                pass
            self._persistence_failure(ack.client_order_id, exc)
            return replace(ack, state=ack.state if ack.filled_contracts > 0 else FillState.UNCONFIRMED,
                           open=True, settlement_pending=True, detail=self.persistence_error)
        return ack

    def _submit_post_only(self, req, t, clearance):
        con = self.journal.store.con
        if self.journal.get(req.client_order_id) is not None:
            # A duplicate caller must not replace the held order's quantity/open state
            # with this refusal. The original lifecycle owns that journal row.
            ack = Ack(self.venue, req.client_order_id, None, FillState.REJECTED, 0, None, None,
                      "POST_ONLY_BLOCKED", t, detail="client order id already exists; no resubmission")
            self.journal._event(req.client_order_id, "post_only_duplicate_rejected", None, {"prewire": True}, t)
            con.commit()
            return ack
        # Convert the ORIGINAL monotonic clearance once, conservatively, for restart.
        # Preparation/persistence never grants another rest window.
        rest_deadline_mono = getattr(clearance, "maker_rest_deadline_mono", None)
        cancel_deadline = t + max(0, (rest_deadline_mono if rest_deadline_mono is not None
                                     else clearance.expires_mono) - self.mono())
        if req.entry_expires_utc is not None:
            cancel_deadline = min(cancel_deadline, req.entry_expires_utc)
        if self.kill is None or not callable(getattr(self.transport, "prepare_post_only_buy", None)):
            error = "post-only requires a bounded V2 transport and host-local kill binding"
        elif con.execute("SELECT 1 FROM pm_post_only_orders WHERE terminal_proved=0 OR violated=1 LIMIT 1").fetchone():
            error = "an earlier post-only order is unresolved or violated its contract; no replacement"
        elif any(r["venue"] == self.venue for r in self.journal.unconfirmed()):
            error = "an earlier Polymarket order is unresolved; one order at a time"
        elif not claim_post_only(self.journal, req.client_order_id, now=t):
            error = "another connection or interrupted process owns post-only admission; no replacement"
        else:
            error = None
        if error:
            self.journal.pending(req, mode=self.mode.value, now=t)
            ack = Ack(self.venue, req.client_order_id, None, FillState.REJECTED, 0, None, None,
                      "POST_ONLY_BLOCKED", t, detail=error)
            self.journal.record(ack, kind="reject", raw={"prewire": True})
            return ack
        # Preparation may sign but cannot post. A failed durable write below propagates and
        # prevents the transport's post method from being reached.
        self.journal.pending(req, mode=self.mode.value, now=t)
        try:
            prepared = self.transport.prepare_post_only_buy(req)
            validate_post_only_amounts(maker_amount=prepared["maker_amount"], taker_amount=prepared["taker_amount"],
                                      requested_contracts=req.contracts, limit_price=req.price)
        except Exception as exc:
            ack = Ack(self.venue, req.client_order_id, None, FillState.REJECTED, 0, None, None,
                      "POST_ONLY_PREPARE_FAILED", self.clock(), detail=brief_error(exc))
            self.journal.record(ack, kind="post_only_no_send", raw={"prewire": True})
            release_post_only(self.journal, req.client_order_id, now=self.clock(), reason="preparation failed; no POST")
            return ack
        if self.mono() >= clearance.expires_mono or (req.entry_expires_utc is not None and self.clock() >= req.entry_expires_utc):
            ack = Ack(self.venue, req.client_order_id, None, FillState.REJECTED, 0, None, None,
                      "POST_ONLY_EXPIRED", self.clock(), detail="economic proof expired during preparation; no POST")
            self.journal.record(ack, kind="reject", raw={"prewire": True})
            release_post_only(self.journal, req.client_order_id, now=self.clock(), reason="expired before POST")
            return ack
        oid = prepared["venue_order_id"]
        con.execute("INSERT INTO pm_post_only_orders(client_order_id,venue_order_id,maker_amount,taker_amount,wire_json,cancel_deadline_utc) "
                    "VALUES(?,?,?,?,?,?)", (req.client_order_id, oid, str(prepared["maker_amount"]),
                                           str(prepared["taker_amount"]), json.dumps(prepared["wire"]), cancel_deadline))
        pending = Ack(self.venue, req.client_order_id, oid, FillState.UNCONFIRMED, 0, None, None,
                      "post_only_prepared", t, open=True)
        self.journal.record(pending, kind="post_only_prepared", raw=prepared["wire"])
        self._requests[req.client_order_id] = req
        if (self.persistence_error or self.kill.active(live=True)
                or con.execute("SELECT 1 FROM pm_post_only_orders WHERE violated=1 LIMIT 1").fetchone()
                or not con.execute("SELECT 1 FROM pm_post_only_admission WHERE slot=1 AND client_order_id=?", (req.client_order_id,)).fetchone()):
            con.execute("UPDATE pm_post_only_orders SET terminal_proved=1 WHERE client_order_id=?", (req.client_order_id,))
            ack = replace(pending, state=FillState.REJECTED, open=False, raw_status="POST_ONLY_STOPPED",
                          detail="live stop, durable violation or lost admission at final prewire check; no POST")
            self.journal.record(ack, kind="post_only_no_send", raw={"prewire": True})
            release_post_only(self.journal, req.client_order_id, now=self.clock(), reason="final prewire stop; no POST")
            return ack
        if self.mono() >= clearance.expires_mono or (req.entry_expires_utc is not None and self.clock() >= req.entry_expires_utc):
            con.execute("UPDATE pm_post_only_orders SET terminal_proved=1 WHERE client_order_id=?", (req.client_order_id,))
            ack = replace(pending, state=FillState.REJECTED, open=False, raw_status="POST_ONLY_EXPIRED",
                          detail="economic proof expired during durable journal; no POST")
            self.journal.record(ack, kind="post_only_no_send", raw={"prewire": True})
            release_post_only(self.journal, req.client_order_id, now=self.clock(), reason="expired during journal; no POST")
            return ack
        self.submits += 1
        try:
            response = self.transport.post_prepared_post_only(prepared)
        except Exception as exc:  # A signed hash is known even if POST delivery is unknown.
            self.last_error = brief_error(exc)
            if getattr(exc, "status_code", None) in {400, 401, 403, 422}:
                ack = replace(pending, state=FillState.REJECTED, open=False, raw_status="post_only_rejected",
                              received_utc=self.clock(), detail=self.last_error)
                return self._record_post_only_after_wire(ack, kind="post_only_reject",
                    raw={"status_code": exc.status_code, "error": self.last_error}, terminal_proof=True)
            ack = replace(pending, raw_status="TRANSPORT", received_utc=self.clock(), detail=self.last_error)
            return self._record_post_only_after_wire(ack, kind="unconfirmed", raw={"error": self.last_error})
        if not isinstance(response, dict):
            response = {}
        returned_id = response.get("orderID") or response.get("orderId") or response.get("id")
        if returned_id and returned_id != oid:
            try:
                self._post_only_violation(req.client_order_id, "POST_ONLY_ROLE_VIOLATION", "response order hash differs from signed hash")
            except Exception as exc:
                self._persistence_failure(req.client_order_id, exc)
        if response.get("success") is False and not returned_id:
            # Explicit venue rejection is no order; never infer it from an empty response.
            ack = replace(pending, state=FillState.REJECTED, open=False, raw_status="post_only_rejected",
                          detail=str(response.get("errorMsg") or response.get("error") or "venue rejection"))
        else:
            ack = replace(pending, raw_status=str(response.get("status") or "unknown"),
                          detail="post-only accepted or delivery unresolved; reconcile exact signed hash")
        return self._record_post_only_after_wire(ack, kind="post_only_ack", raw=response,
                                                terminal_proof=ack.state is FillState.REJECTED)

    def submit(self, req: OrderRequest, clearance) -> Ack:
        t = self.clock()
        refused = admit(req, clearance, venue=self.venue, mode=self.mode, needs=Mode.LIMITED_LIVE, now=t,
                         now_mono=self.mono(), hedge=req.hedge)
        if refused is not None:
            return refused
        if req.side not in ("buy_yes", "sell_yes"):
            return Ack(self.venue, req.client_order_id, None, FillState.REJECTED, 0.0, None, None, "SIDE", t,
                       detail="Polymarket outcomes are separate tokens: pass the outcome's token id as "
                              "market_id with side buy_yes (or sell_yes to reduce a held position)")
        if req.post_only:
            return self._submit_post_only(req, t, clearance)
        bounded_post = None
        if not req.is_sell:
            bounded_post = getattr(self.transport, "post_bounded_taker_buy", None)
            cap_check = getattr(self.transport, "buy_contract_cap_error", None)
            cap_error = cap_check() if cap_check is not None else BUY_CAP_UNPROVEN
            q, collateral = Decimal(str(req.contracts)), Decimal(str(req.contracts)) * Decimal(str(req.price))
            bounded = (callable(bounded_post) and req.time_in_force in ("ioc", "fok")
                       and q <= BOUNDED_TAKER_MAX_CONTRACTS
                       and collateral <= BOUNDED_TAKER_MAX_COLLATERAL_USD)
            if not bounded and cap_error is not None:
                self.journal.pending(req, mode=self.mode.value, now=t)
                ack = Ack(self.venue, req.client_order_id, None, FillState.REJECTED, 0.0, None, None,
                          "QUANTITY_CAP_UNPROVEN", t, detail=cap_error)
                self.journal.record(ack, kind="reject", raw={"prewire": True})
                return ack
        if req.is_sell and req.market_id not in self._sell_ok:
            # The exchange must be approved on the conditional token before a SELL (2026-09-08).
            # Best effort and remembered: a refused approval shows up as the venue's own rejection.
            ok = getattr(self.transport, "ensure_sell_allowance", lambda _t: True)(req.market_id)
            if ok:
                self._sell_ok.add(req.market_id)
        wire_size = req.contracts
        if not req.is_sell and req.time_in_force in ("ioc", "fok"):
            # L83: the venue delivers collateral / fill price shares. A ceiling from the venue's own
            # ask bounds the collateral so a fill at the ask is exactly `contracts`; the journal
            # keeps `contracts` as the reference size (what the hedge covers, what an overfill
            # is measured against); only the wire's nominal size shrinks.
            if req.max_collateral_usd is not None and req.price > 0:
                wire_size = min(float(req.contracts), float(req.max_collateral_usd) / float(req.price))
            exact = PyClobTransport._cent_exact_buy(size=wire_size, price=req.price, tick=req.tick)
            if exact is None:
                self.journal.pending(req, mode=self.mode.value, now=t)
                ack = Ack(self.venue, req.client_order_id, None, FillState.REJECTED, 0.0, None, None,
                          "PRECISION", t, detail="no cent-exact share-sized BUY inside requested "
                                                 "size/price and $1 minimum; nothing sent")
                self.journal.record(ack, kind="reject", raw={"prewire": True})
                return ack
            exact_price, exact_size = exact
            wire_size = exact_size
            req = replace(req, price=exact_price,
                          contracts=exact_size if req.max_collateral_usd is None else req.contracts)
        self.journal.pending(req, mode=self.mode.value, now=t)       # BEFORE the POST
        if bounded_post is not None and not req.is_sell:
            self.journal.store.con.execute(
                "INSERT INTO pm_bounded_taker_orders VALUES(?,?,?,?,?,?)",
                (req.client_order_id, str(wire_size), str(BOUNDED_TAKER_MAX_CONTRACTS),
                 str(BOUNDED_TAKER_MAX_COLLATERAL_USD), str(BOUNDED_TAKER_MAX_ACCEPTED_EXCESS), t))
            self.journal.store.con.commit()                         # authorization BEFORE the wire
        self._requests[req.client_order_id] = req
        self.submits += 1
        try:
            if bounded_post is not None and not req.is_sell:
                d = bounded_post(token_id=req.market_id, price=req.price, size=wire_size,
                                 order_type=ORDER_TYPE[req.time_in_force], tick=req.tick)
            else:
                d = self.transport.post_order(token_id=req.market_id, price=req.price, size=req.contracts,
                                              order_type=ORDER_TYPE[req.time_in_force],
                                              side="SELL" if req.is_sell else "BUY", tick=req.tick)
        except Exception as exc:  # noqa: BLE001 -- ambiguous unless the venue itself answered
            self.last_error = brief_error(exc)
            code = getattr(exc, "status_code", None)
            if code in (400, 401, 403, 404, 422):
                # The CLOB answered and did not take the order: a definite refusal, not an ambiguous
                # transport failure. Read as UNCONFIRMED it held the reservation, polled status for
                # 3 s and left the game EVENT_IN_FLIGHT (2026-09-07, HTTP 403 on the box).
                self.rejected_http += 1
                if code == 403 and "region" in self.last_error.lower():
                    self.geoblocked = self.last_error
                if code == 400 and req.time_in_force in ("ioc", "fok") and "no orders found to match" in self.last_error.lower():
                    # The matching engine answered an immediate order with "nothing to match": a
                    # definite ZERO FILL of a well-formed order, not a refusal of its form. The
                    # 2026-09-11 audit found two such answers journaled as ORDER_REJECTED beside 18
                    # economically identical ORDER_UNFILLED rows. Same release, same terminal proof;
                    # only the label the audit reads changes.
                    ack = Ack(self.venue, req.client_order_id, None, FillState.UNFILLED, 0.0, None, None,
                              f"HTTP_{code}_NO_MATCH", self.clock(), detail=self.last_error)
                    self.journal.record(ack, kind="unfilled", raw={"error": self.last_error, "status_code": code})
                    return ack
                ack = Ack(self.venue, req.client_order_id, None, FillState.REJECTED, 0.0, None, None,
                          f"HTTP_{code}", self.clock(), detail=self.last_error)
                self.journal.record(ack, kind="reject", raw={"error": self.last_error, "status_code": code})
                return ack
            self.unconfirmed += 1
            ack = Ack(self.venue, req.client_order_id, None, FillState.UNCONFIRMED, 0.0, None, None,
                      "TRANSPORT", self.clock(), detail=self.last_error)
            self.journal.record(ack, kind="unconfirmed", raw={"error": self.last_error})
            return ack
        ack = self._ack_from_post(req, d if isinstance(d, dict) else {})
        try:
            self.journal.record(ack, kind="ack", raw=d if isinstance(d, dict) else None)
        except Exception as exc:  # noqa: BLE001 -- the order is OUT; a store failure here must not hide the ack from the machine (2026-09-08)
            self.journal_failures = getattr(self, "journal_failures", 0) + 1
            print(f"  [polymarket] journal write failed after the wire: {type(exc).__name__}: {str(exc)[:80]}", flush=True)
        return ack

    def _ack_from_post(self, req: OrderRequest, d: dict) -> Ack:
        t = self.clock()
        oid = d.get("orderID") or d.get("orderId") or d.get("id")
        status = str(d.get("status", "")).lower()
        if d.get("success") is False or (not oid and not status):
            return Ack(self.venue, req.client_order_id, oid, FillState.REJECTED, 0.0, None, None,
                       status or "rejected", t, detail=str(d.get("errorMsg") or d.get("error") or "")[:300])
        if status == "matched":
            # The CLOB matched it. The venue's order record says HOW MUCH: CLOB V2 fills a BUY by
            # notional, so a FOK for 5 @ 0.39 came back as 5.131577 @ 0.38 (the first real fill,
            # 2026-09-07). Trusting the REQUEST size would under-hedge by the improvement.
            # L84 (2026-09-12): the POST response itself carries the matched amounts -- LAA @ WSH
            # answered `takingAmount 32.142858, makingAmount 4.5` at +0.30 s (32.14 @ 0.14, exactly
            # what cash later confirmed) while status() took 6.4 s and gave up; VARILLA V WILD
            # learned its 25.32 at +1.7 s. For a BUY the taker takes shares and makes collateral;
            # for a SELL the reverse. When both amounts are present the ack IS the venue's size and
            # the hedge goes out on it; cash, fee and finality still arrive through status()/fills.
            # A "matched" without amounts (a DELAYED-then-matched answer) stays UNCONFIRMED as before.
            taking, making = _f(d.get("takingAmount")), _f(d.get("makingAmount"))
            shares, cash = (making, taking) if req.is_sell else (taking, making)
            if shares > 1e-9 and cash > 0:
                state = FillState.FILLED if shares >= float(req.contracts) - 1e-6 else FillState.PARTIAL
                return Ack(self.venue, req.client_order_id, oid, state, shares, cash / shares, None, status, t,
                           settlement_pending=True,
                           detail="matched; size and average from the venue's response; cash via status()")
            return Ack(self.venue, req.client_order_id, oid, FillState.UNCONFIRMED, 0.0, None, None, status, t,
                       settlement_pending=True, detail="matched; size via status()")
        if status == "live":
            # An immediate order is not allowed to rest, but the venue has explicitly said this one
            # is live.  It is therefore unresolved exposure, never an authoritative zero-fill.  The
            # coordinator will poll and cancel it before deciding whether anything filled.
            return Ack(self.venue, req.client_order_id, oid, FillState.UNCONFIRMED, 0.0, None, None,
                       status, t, open=True, detail="unexpected open immediate order; poll and cancel")
        # delayed / unmatched / anything else: the venue has the order and has not said what happened
        return Ack(self.venue, req.client_order_id, oid, FillState.UNCONFIRMED, 0.0, None, None, status or "unknown", t,
                   open=True, detail="placed; outcome not yet reported")

    def status(self, client_order_id: str) -> OrderState:
        row = self.journal.get(client_order_id)
        t = self.clock()
        if row and self.journal.store.con.execute(
                "SELECT 1 FROM pm_post_only_orders WHERE client_order_id=?", (client_order_id,)).fetchone():
            return self._post_only_status(row, t)
        if row is None or not row.get("venue_order_id"):
            return OrderState(self.venue, client_order_id, None, FillState.UNCONFIRMED, 0.0, None, None, "NOT_FOUND", t,
                              detail="no venue order id; reconcile through trades() before any retry")
        # The authenticated user channel reports MATCHED immediately; REST can omit a consumed
        # FAK for minutes. A match is enough to hedge (settlement finality is tracked separately).
        streamed = getattr(self.transport, "user_order", lambda _oid: None)(row["venue_order_id"])
        if streamed:
            st = self._state_from_order(streamed, client_order_id, float(row["contracts"]), t)
            try:
                self.journal.record(st, kind="status_user_stream", raw=streamed)
            except Exception as exc:  # noqa: BLE001
                self.journal_failures = getattr(self, "journal_failures", 0) + 1
                print(f"  [polymarket] journal write failed after the wire: {type(exc).__name__}: {str(exc)[:80]}", flush=True)
            return st
        try:
            o = self.transport.get_order(row["venue_order_id"])
        except Exception as exc:  # noqa: BLE001
            self.last_error = brief_error(exc)
            return OrderState(self.venue, client_order_id, row["venue_order_id"], FillState.UNCONFIRMED, 0.0, None,
                              None, "TRANSPORT", t, detail=self.last_error)
        if not o:
            # `not_found` is not a terminal no-fill: two FAKs on 2026-09-08 returned it and then
            # appeared as confirmed trades. Ask the trade feed (throttled), whose records are the
            # durable truth, before interpreting absence.
            last = self._last_trade_check.get(client_order_id, float("-inf"))
            if self.mono() - last >= TRADE_CHECK_INTERVAL_S:
                self._last_trade_check[client_order_id] = self.mono()
                try:
                    self.fills(since_utc=max(0.0, float(row["submitted_utc"]) - 1.0))
                except Exception as exc:  # noqa: BLE001 -- ambiguity stays UNCONFIRMED
                    self.last_error = brief_error(exc)
            known = self.journal.store.con.execute(
                "SELECT COALESCE(SUM(contracts),0),COALESCE(SUM(contracts*price),0),"
                "COALESCE(SUM(fee_usd),0),MIN(final) FROM venue_fills WHERE venue_order_id=?",
                (row["venue_order_id"],),
            ).fetchone()
            qty = float(known[0] or 0.0)
            if qty > 1e-9:
                state = FillState.FILLED if qty >= float(row["contracts"]) - 1e-6 else FillState.PARTIAL
                st = OrderState(self.venue, client_order_id, row["venue_order_id"], state, qty,
                                float(known[1]) / qty, float(known[2] or 0.0), "trade_feed", t,
                                open=False, settlement_pending=not bool(known[3]), final=bool(known[3]),
                                detail="order lookup absent; venue trade feed proves the fill")
                try:
                    self.journal.record(st, kind="status_trade")
                except Exception as exc:  # noqa: BLE001
                    self.journal_failures = getattr(self, "journal_failures", 0) + 1
                    print(f"  [polymarket] journal write failed after the wire: {type(exc).__name__}: {str(exc)[:80]}", flush=True)
                return st
            age = max(0.0, t - float(row["submitted_utc"]))
            if age < NOT_FOUND_GRACE_S:
                st = OrderState(self.venue, client_order_id, row["venue_order_id"], FillState.UNCONFIRMED,
                                0.0, None, None, "not_found_pending", t, open=False, final=False,
                                detail=f"order lookup absent and no trade yet; {age:.1f}s < {NOT_FOUND_GRACE_S:g}s finality grace")
                try:
                    self.journal.record(st, kind="status")
                except Exception as exc:  # noqa: BLE001
                    self.journal_failures = getattr(self, "journal_failures", 0) + 1
                    print(f"  [polymarket] journal write failed after the wire: {type(exc).__name__}: {str(exc)[:80]}", flush=True)
                return st
            # Absent from both order and trade endpoints beyond the grace: terminal zero-fill.
            st = OrderState(self.venue, client_order_id, row["venue_order_id"], FillState.UNFILLED, 0.0, None, None,
                            "not_found", t, open=False, final=True,
                            detail=f"absent from order and trade endpoints for {age:.1f}s")
            try:
                self.journal.record(st, kind="status", raw={"not_found": True})
            except Exception as exc:  # noqa: BLE001 -- the order is OUT; a store failure here must not hide the ack from the machine (2026-09-08)
                self.journal_failures = getattr(self, "journal_failures", 0) + 1
                print(f"  [polymarket] journal write failed after the wire: {type(exc).__name__}: {str(exc)[:80]}", flush=True)
            return st
        st = self._state_from_order(o, client_order_id, float(row["contracts"]), t)
        try:
            self.journal.record(st, kind="status", raw=o)
        except Exception as exc:  # noqa: BLE001 -- the order is OUT; a store failure here must not hide the ack from the machine (2026-09-08)
            self.journal_failures = getattr(self, "journal_failures", 0) + 1
            print(f"  [polymarket] journal write failed after the wire: {type(exc).__name__}: {str(exc)[:80]}", flush=True)
        return st

    def observed(self, client_order_id: str) -> OrderState:
        """Return only authenticated socket/durable high-water evidence; never call REST.

        The maker-rest supervisor uses this on a tight loop.  Terminality remains the job of
        ``status()`` after cancel; a socket match is enough to protect quantity but never enough
        to release the post-only admission lock.
        """
        row = self.journal.get(client_order_id)
        t = self.clock()
        if row is None or not row.get("venue_order_id"):
            return OrderState(self.venue, client_order_id, None, FillState.UNCONFIRMED, 0.0,
                              None, None, "NOT_FOUND", t, open=True, final=False)
        cid, oid = row["client_order_id"], row["venue_order_id"]
        marker = self.journal.store.con.execute(
            "SELECT taker_amount,maker_amount FROM pm_post_only_orders WHERE client_order_id=?", (cid,)
        ).fetchone()
        if marker is None:
            return OrderState(self.venue, cid, oid, FillState.UNCONFIRMED,
                              float(row.get("filled_contracts") or 0.0), row.get("avg_price"),
                              row.get("fee_usd"), "not_post_only", t, open=True, final=False)
        known = max(Decimal(str(row.get("filled_contracts") or 0)),
                    self._post_only_observed.get(cid, Decimal(0)))
        raw = getattr(self.transport, "user_order", lambda _oid: None)(oid)
        if raw:
            try:
                quantity = Decimal(str(raw.get("size_matched") or 0))
                if quantity.is_finite() and quantity >= 0:
                    known = max(known, quantity)
                    self._post_only_observed[cid] = known
                if "taker" in raw.get("_janus_trade_roles", ()):
                    self._post_only_violation(cid, "POST_ONLY_ROLE_VIOLATION",
                                              "user-stream owned taker/conflicting role: " +
                                              json.dumps(raw.get("_janus_role_evidence", {}), sort_keys=True))
                from nodes.exec_polymarket.post_only import check_post_only_quantity
                check_post_only_quantity(self.journal, oid, known, now=t, kill=self.kill)
            except Exception as exc:
                self.last_error = brief_error(exc)
            state = FillState.FILLED if known >= Decimal(marker[0]) / 1_000_000 else (
                FillState.PARTIAL if known > 0 else FillState.UNCONFIRMED)
            price = float(Decimal(marker[1]) / Decimal(marker[0])) if known else None
            st = OrderState(self.venue, cid, oid, state, float(known), price, None,
                            "user_stream_high_water", t, open=True, final=False,
                            settlement_pending=known > 0,
                            detail="socket fill high-water; maker terminality unresolved")
            try:
                self.journal.record(st, kind="maker_observed", raw=raw)
            except Exception as exc:
                self._persistence_failure(cid, exc)
                return replace(st, detail=self.persistence_error)
            return st
        state = FillState.PARTIAL if known > 0 else FillState.UNCONFIRMED
        price = float(Decimal(marker[1]) / Decimal(marker[0])) if known else None
        return OrderState(self.venue, cid, oid, state, float(known), price, None,
                          "maker_observed_cached", t, open=True, final=False,
                          settlement_pending=known > 0)

    def _post_only_status(self, row, t):
        from nodes.exec_polymarket.post_only import check_post_only_quantity
        cid, oid, con = row["client_order_id"], row["venue_order_id"], self.journal.store.con
        marker = con.execute(
            "SELECT taker_amount,maker_amount,terminal_seen_utc,terminal_fingerprint,terminal_proved,violated,cancel_deadline_utc "
            "FROM pm_post_only_orders WHERE client_order_id=?", (cid,)).fetchone()
        if not marker[4] and (marker[6] is None or t >= marker[6]):
            # On recovery this process-local retry cache is empty: dispatch cancel
            # immediately, before any possibly slow status/trade/cash read. Persisted
            # intent alone never means a prior process reached the wire.
            attempted = self._post_only_cancel_attempts.get(cid)
            if attempted is None or self.mono() - attempted >= 1.0:
                try:
                    self._post_only_cancel_wire(row)
                except Exception as exc:
                    self._persistence_failure(cid, exc)
        known = max(Decimal(str(row.get("filled_contracts") or 0)), self._post_only_observed.get(cid, Decimal(0)))
        payload, reads_ok = None, False
        # Socket cache is local, so role/quantity evidence must not wait behind REST
        # or be lost when REST fails. Conflicting roles remain durable stop evidence.
        try:
            streamed = getattr(self.transport, "user_order", lambda _: None)(oid)
            if streamed:
                streamed_qty = Decimal(str(streamed.get("size_matched")))
                if streamed_qty.is_finite() and streamed_qty >= 0:
                    known = max(known, streamed_qty)
                    self._post_only_observed[cid] = known
                if "taker" in streamed.get("_janus_trade_roles", ()):
                    self._post_only_violation(cid, "POST_ONLY_ROLE_VIOLATION",
                                              "user-stream owned taker/conflicting role: " +
                                              json.dumps(streamed.get("_janus_role_evidence", {}), sort_keys=True))
            check_post_only_quantity(self.journal, oid, known, now=t, kill=self.kill)
        except Exception as exc:
            self.last_error = brief_error(exc)
        # Even an independent guard status call cannot start slow REST I/O while
        # deliberately resting. Expired recovery above dispatches cancel first.
        if marker[4] or cid in self._post_only_cancel_attempts:
            try:
                payload = self.transport.get_order(oid)
                if payload:
                    reported = Decimal(str(payload.get("size_matched")))
                    if not reported.is_finite() or reported < 0:
                        raise ValueError("invalid order size")
                    known = max(known, reported)
                    self._post_only_observed[cid] = known
                check_post_only_quantity(self.journal, oid, known, now=t, kill=self.kill)
                observed_fills = self.fills(since_utc=max(0, float(row["submitted_utc"]) - 1))
                returned_qty = sum((Decimal(str(f.contracts)) for f in observed_fills if f.venue_order_id == oid), Decimal(0))
                known = max(known, returned_qty)
                self._post_only_observed[cid] = known
                reads_ok = not bool(getattr(self, "projection_batch_error", "") or self.persistence_error)
            except Exception as exc:
                self.last_error = brief_error(exc)
        try:
            fills = con.execute("SELECT fill_id,contracts,final,is_taker FROM venue_fills WHERE venue_order_id=?", (oid,)).fetchall()
        except Exception as exc:
            self._persistence_failure(cid, exc)
            fills = []
        fifo = sum((Decimal(str(f[1])) for f in fills), Decimal(0))
        known = max(known, fifo)
        self._post_only_observed[cid] = known
        try:
            check_post_only_quantity(self.journal, oid, known, now=t, kill=self.kill)
            return self._finish_post_only_status(cid, oid, con, marker, known, payload, reads_ok, fills, fifo, t)
        except Exception as exc:
            try:
                con.rollback()
            except Exception:
                pass  # The independent kill is still attempted when the store is unusable.
            self._persistence_failure(cid, exc)
            cap = Decimal(marker[0]) / 1_000_000
            state = FillState.FILLED if known >= cap else FillState.PARTIAL if known > 0 else FillState.UNCONFIRMED
            return OrderState(self.venue, cid, oid, state, float(known),
                              float(Decimal(marker[1]) / Decimal(marker[0])) if known else None,
                              None, "post_only_persistence_failed", t, open=True, final=False,
                              settlement_pending=True, detail=self.persistence_error)

    def _finish_post_only_status(self, cid, oid, con, marker, known, payload, reads_ok, fills, fifo, t):
        # A cancel response alone is not proof that no earlier match can arrive late.
        # Require two stable terminal GET observations, associated-trade coverage, and a
        # fresh successful fill read with complete maker-confirmed cash before reuse.
        terminal = False
        if payload and str(payload.get("status", "")).upper() in {"CANCELED", "CANCELLED", "MATCHED"}:
            associations = payload.get("associate_trades")
            if isinstance(associations, list) and all(isinstance(x, str) for x in associations):
                fingerprint = json.dumps([str(payload.get("status")).upper(), str(payload.get("size_matched")), sorted(associations)])
                if marker[3] != fingerprint:
                    con.execute("UPDATE pm_post_only_orders SET terminal_seen_utc=?,terminal_fingerprint=? WHERE client_order_id=?",
                                (t, fingerprint, cid))
                else:
                    ids = {str(f[0]).split(":maker:")[0] for f in fills}
                    terminal = bool(reads_ok and t - float(marker[2] or t) >= POST_ONLY_TERMINAL_GRACE_S
                                    and fifo == known and set(associations) == ids
                                    and all(f[2] and not f[3] for f in fills)
                                    and not con.execute("SELECT violated FROM pm_post_only_orders WHERE client_order_id=?", (cid,)).fetchone()[0])
        else:
            con.execute("UPDATE pm_post_only_orders SET terminal_seen_utc=NULL,terminal_fingerprint=NULL WHERE client_order_id=?", (cid,))
        # A later contradictory fact reopens the lock; historical source/audit stays intact.
        con.execute("UPDATE pm_post_only_orders SET terminal_proved=? WHERE client_order_id=?", (int(terminal), cid))
        qty = float(known)
        cap = Decimal(marker[0]) / 1_000_000
        state = (FillState.FILLED if known >= cap and qty > 0 else FillState.PARTIAL if qty > 0
                 else FillState.UNFILLED if terminal else FillState.UNCONFIRMED)
        price = float(Decimal(marker[1]) / Decimal(marker[0])) if qty else None
        st = OrderState(self.venue, cid, oid, state, qty, price, None, "post_only_terminal" if terminal else "post_only_pending",
                        t, open=not terminal, final=terminal, settlement_pending=not terminal,
                        detail="maker lifecycle reconciled" if terminal else "maker order/late-fill coverage remains unresolved")
        try:
            self.journal.record(st, kind="post_only_status", raw=payload if isinstance(payload, dict) else {"missing": True})
            if terminal:
                release_post_only(self.journal, cid, now=self.clock(), reason="stable terminal order and complete maker/cash coverage")
        except Exception as exc:
            # Do not commit the tentative terminal update when its evidence failed.
            con.rollback()
            self._persistence_failure(cid, exc)
            return replace(st, open=True, final=False, settlement_pending=True, detail=self.persistence_error)
        if self.persistence_error:
            return replace(st, open=True, final=False, settlement_pending=True, detail=self.persistence_error)
        return st

    def _state_from_order(self, o: dict, cid: str, requested: float, t: float) -> OrderState:
        status = str(o.get("status", "")).upper()
        matched = _f(o.get("size_matched"))
        price = _f(o.get("price"), 0.0) or None
        if matched >= requested - 1e-9 and requested > 0:
            state = FillState.FILLED
        elif matched > 1e-9:
            state = FillState.PARTIAL
        else:
            state = FillState.UNFILLED
        live = status == "LIVE"
        return OrderState(self.venue, cid, o.get("id"), state, matched, price, None, status.lower(), t,
                          open=live, settlement_pending=matched > 0,
                          detail="order price provisional; cash accounting pending" if matched > 0 else "",
                          final=status in ("MATCHED", "CANCELED", "CANCELLED", "UNMATCHED"))

    def _post_only_cancel_wire(self, row):
        cid, oid, con, t = row["client_order_id"], row["venue_order_id"], self.journal.store.con, self.clock()
        # A DB failure must prevent the network call, including recovery/retries.
        self.journal._event(cid, "post_only_cancel_intent", None, {"venue_order_id": oid}, t)
        con.execute("UPDATE pm_post_only_orders SET cancel_attempt_utc=? WHERE client_order_id=?", (t, cid))
        con.commit()
        self._post_only_cancel_attempts[cid] = self.mono()
        try:
            result = self.transport.cancel(oid)
        except Exception as exc:
            self.last_error = brief_error(exc)
            return
        try:
            self.journal._event(cid, "post_only_cancel_response", None, result, self.clock())
            con.commit()
        except Exception as exc:
            self._persistence_failure(cid, exc)

    def cancel(self, client_order_id: str) -> Ack:
        row = self.journal.get(client_order_id)
        t = self.clock()
        if row is None or not row.get("venue_order_id"):
            return Ack(self.venue, client_order_id, None, FillState.UNCONFIRMED, 0.0, None, None, "NOT_FOUND", t)
        if self.journal.store.con.execute("SELECT 1 FROM pm_post_only_orders WHERE client_order_id=?", (client_order_id,)).fetchone():
            try:
                self._post_only_cancel_wire(row)
            except Exception as exc:
                self._persistence_failure(client_order_id, exc)
        else:
            try:
                self.transport.cancel(row["venue_order_id"])
            except Exception as exc:  # noqa: BLE001
                self.last_error = brief_error(exc)
        st = self.status(client_order_id)
        try:
            self.journal.record(st, kind="cancel")
        except Exception as exc:  # noqa: BLE001 -- the order is OUT; a store failure here must not hide the ack from the machine (2026-09-08)
            if self.journal.store.con.execute("SELECT 1 FROM pm_post_only_orders WHERE client_order_id=?", (client_order_id,)).fetchone():
                self._persistence_failure(client_order_id, exc)
                return replace(st, open=True, final=False, settlement_pending=True, detail=self.persistence_error)
            self.journal_failures = getattr(self, "journal_failures", 0) + 1
            print(f"  [polymarket] journal write failed after the wire: {type(exc).__name__}: {str(exc)[:80]}", flush=True)
        return st

    def cancel_only(self, client_order_id: str) -> Ack:
        """Durably dispatch maker cancel and return local high-water without a REST read."""
        row = self.journal.get(client_order_id)
        t = self.clock()
        if row is None or not row.get("venue_order_id"):
            return Ack(self.venue, client_order_id, None, FillState.UNCONFIRMED, 0.0,
                       None, None, "NOT_FOUND", t, open=True)
        if not self.journal.store.con.execute(
                "SELECT 1 FROM pm_post_only_orders WHERE client_order_id=?", (client_order_id,)).fetchone():
            return self.cancel(client_order_id)
        try:
            self._post_only_cancel_wire(row)
        except Exception as exc:
            self._persistence_failure(client_order_id, exc)
        return self.observed(client_order_id)

    def _fill_violation(self, cid: str, code: str, detail: str) -> None:
        try:
            self._post_only_violation(cid, code, detail)
        except Exception as exc:
            # The independent kill is attempted even when its DB audit fails. The
            # failed audit must not turn a known held quantity into an empty result.
            self._persistence_failure(cid, exc)

    def fills(self, *, since_utc: float) -> Sequence[FillRecord]:
        self.projection_batch_error = ""
        projection_errors = []
        raw_trades = []
        try:
            for raw in self.transport.trades(after_ts=since_utc):
                raw_trades.append(raw)
        except Exception as exc:  # A valid prefix is quantity evidence, not completeness.
            projection_errors.append('trade read: ' + brief_error(exc))
        # An unrelated malformed maker row must not hide an already observed owned taker.
        for raw in raw_trades:
            if not isinstance(raw, dict):
                continue
            marker = post_only_order(self.journal, str(raw.get('taker_order_id') or ''))
            if marker is not None and str(raw.get('status', '')).upper() not in DEAD_TRADE:
                self._fill_violation(marker['client_order_id'], 'POST_ONLY_ROLE_VIOLATION',
                                     f"trade {raw.get('id')}: owned order observed in taker/conflicting role")
        owned_ids = {row[0] for row in self.journal.store.con.execute(
            "SELECT venue_order_id FROM orders WHERE venue=? AND venue_order_id IS NOT NULL", (self.venue,))}
        trades = []
        for index, raw in enumerate(raw_trades):
            try:
                if not isinstance(raw, dict):
                    raise ValueError('trade is not an object')
                if str(raw.get('status', '')).upper() in DEAD_TRADE:
                    continue
                projections = project_account_trade(
                    raw, owned_order_ids=owned_ids, funder=os.environ.get('JANUS_PM_FUNDER', ''))
                for projected in projections:
                    quantity = Decimal(str(projected.get('size')))
                    if not quantity.is_finite() or quantity <= 0:
                        raise ValueError('invalid projected fill quantity')
                    trades.append(projected)
            except Exception as exc:
                projection_errors.append(f'trade row {index}: ' + brief_error(exc))
        if projection_errors:
            self.projection_batch_error = 'PROJECTION_BATCH_INCOMPLETE: ' + '; '.join(projection_errors)
            self.last_error = self.projection_batch_error
        # Role/cumulative-cap STOP evidence precedes fresh cash reads and accounting writes.
        post_markers = {}
        for tr in trades:
            if str(tr.get('status', '')).upper() in DEAD_TRADE:
                continue
            oid = str(tr.get('taker_order_id') or tr.get('order_id') or '')
            marker = post_only_order(self.journal, oid)
            if marker is None:
                continue
            post_markers[oid] = marker
            if tr.get('_janus_projection_role') == 'TAKER' or tr.get('_janus_role_conflict'):
                self._fill_violation(marker['client_order_id'], 'POST_ONLY_ROLE_VIOLATION',
                                     f"trade {tr.get('_janus_source_trade_id')}: owned order observed in taker/conflicting role")
            request = self.journal.store.con.execute(
                'SELECT market_id,side FROM orders WHERE client_order_id=?', (marker['client_order_id'],)).fetchone()
            if request is None or tr.get('side') != 'BUY' or request[1] != 'buy_yes' or tr.get('asset_id') != request[0]:
                self._fill_violation(marker['client_order_id'], 'POST_ONLY_ROLE_VIOLATION',
                                     f"trade {tr.get('_janus_source_trade_id')}: maker token/side contradicts signed BUY order")
        for oid, marker in post_markers.items():
            quantities = {row[0]: Decimal(str(row[1])) for row in self.journal.store.con.execute(
                "SELECT fill_id,contracts FROM venue_fills WHERE venue_order_id=?", (oid,))}
            for (pending_oid, fill_id), pending in self._unpersisted_fills.items():
                if pending_oid == oid:
                    quantities[fill_id] = max(quantities.get(fill_id, Decimal(0)), Decimal(str(pending.contracts)))
            for tr in trades:
                if str(tr.get('taker_order_id') or tr.get('order_id') or '') == oid and str(tr.get('status', '')).upper() not in DEAD_TRADE:
                    quantity = Decimal(str(tr.get('size')))
                    quantities[str(tr.get('id'))] = max(quantity, quantities.get(str(tr.get('id')), Decimal(0)))
            row = self.journal.store.con.execute('SELECT filled_contracts FROM orders WHERE venue_order_id=?', (oid,)).fetchone()
            quantity = max(sum(quantities.values(), Decimal(0)), Decimal(str(row[0] or 0)) if row else Decimal(0))
            try:
                check_post_only_quantity(self.journal, oid, quantity, now=self.clock(), kill=self.kill)
            except Exception as exc:
                self._persistence_failure(marker['client_order_id'], exc)
        cash_reader = getattr(self.transport, "trade_activity", None)
        activities: dict[tuple, list[dict]] = {}
        trade_counts: dict[tuple, int] = {}
        for tr in trades:
            if str(tr.get("status", "")).upper() not in DEAD_TRADE:
                key = _activity_key(tr, trade=True)
                trade_counts[key] = trade_counts.get(key, 0) + 1
        confirmed = [tr for tr in trades if str(tr.get("status", "")).upper() in FINAL_TRADE]
        if callable(cash_reader) and confirmed and not self.projection_batch_error and not self.persistence_error:
            try:
                # Publish the fresh index only after the entire read/iteration succeeds.
                # Keeping a valid prefix after a malformed row or lazy-reader exception
                # could hide a later duplicate and manufacture unambiguous cash authority.
                complete_batch: dict[tuple, list[dict]] = {}
                earliest = min(_f(tr.get("match_time"), since_utc) for tr in confirmed)
                for activity in cash_reader(after_ts=earliest):
                    key = _activity_key(activity, trade=False)
                    complete_batch.setdefault(key, []).append(activity)
                activities = complete_batch
            except Exception as exc:  # noqa: BLE001 -- fills remain known; cash finality does not
                activities = {}  # Durable prior source remains allowed; no fresh prefix does.
                self.last_error = "CASH_ACTIVITY_PENDING: " + brief_error(exc)
        out = []
        for tr in trades:
            status = str(tr.get("status", "")).upper()
            if status in DEAD_TRADE:
                continue                     # a reversal: reconcile handles it, never a fill here
            size = _f(tr.get("size"))
            order_id = str(tr.get("taker_order_id") or tr.get("order_id") or "")
            pending_key = (order_id, str(tr.get('id')))
            pending = self._unpersisted_fills.get(pending_key)
            previous = self.journal.store.con.execute(
                'SELECT contracts FROM venue_fills WHERE fill_id=? AND venue_order_id=?',
                (str(tr.get('id')), order_id)).fetchone()
            # Missing cash or a stale smaller trade is not reversal authority. Preserve
            # the largest independently observed exposure across rereads and restarts.
            size = max(size, float(previous[0]) if previous else 0.0, pending.contracts if pending else 0.0)
            order = self.journal.store.con.execute(
                "SELECT client_order_id,price FROM orders WHERE venue_order_id=?", (order_id,)).fetchone()
            taker = str(tr.get("trader_side", "")).upper() == "TAKER"
            price = _f(tr.get('price'), None) if tr.get('_janus_projection_role') == 'MAKER' else taker_trade_vwap(tr) if taker else None
            if price is None:
                # No cash and no maker-leg VWAP: the top-level price is NOT an average.
                # Use the durable request ceiling for a BUY. An orphan BUY without a
                # request uses the binary payout bound; SELL proceeds use a zero floor.
                price = float(order[1]) if order else (0.0 if str(tr.get("side", "")).upper() == "SELL" else 1.0)
            fee = size * price * _f(tr.get("fee_rate_bps")) / 10_000.0
            fee_source = "venue"
            market_id = str(tr.get("asset_id") or "")
            fee_params = self.fee_params_by_market.get(market_id) or self.fee_params
            if fee <= 0 and taker and fee_params and size > 0:
                fee, fee_source = self._pinned_fee(tr, size, price, fee_params), "pinned (venue reported none)"
            cash_final = False
            activity = None
            key = _activity_key(tr, trade=True)
            candidates = activities.get(key, [])
            marker = post_only_order(self.journal, order_id)
            role_proved = bool(tr.get('_janus_role_verified'))
            role_blocked = bool(marker and (marker['violated'] or not role_proved or not tr.get('_janus_projection_role') == 'MAKER'))
            try:
                if self.projection_batch_error:
                    raise ValueError('trade projection batch incomplete; cash uniqueness unproved')
                if self.persistence_error:
                    raise ValueError('persistence STOP requires operator repair')
                if not role_proved or role_blocked:
                    raise ValueError('owned fill role unproved or post-only role/cap violated')
                if trade_counts.get(key) != 1 or len(candidates) != 1:
                    raise ValueError("cash activity absent or ambiguous")
                if Decimal(str(size)) != Decimal(str(tr.get('size'))):
                    raise ValueError('cash candidate covers a stale smaller quantity, not all observed exposure')
                candidate = candidates[0]
                price, fee = authoritative_cash_fill(tr, candidate)
                activity = candidate  # Do not audit an invalid candidate as source authority.
                cash_final, fee_source = True, "venue activity cash"
            except (ValueError, ArithmeticError) as exc:
                self.last_error = "CASH_ACTIVITY_PENDING: " + str(exc)
                fee_source = "provisional; authoritative cash pending"
            rec = FillRecord(self.venue, order_id,
                             str(tr.get("id")), size, price, fee, taker, _f(tr.get("match_time"), since_utc), status in FINAL_TRADE and cash_final,
                             market_id=market_id,
                             side="sell_yes" if str(tr.get("side", "")).upper() == "SELL" else "buy_yes")
            prior = self._durable_cash_fill(rec.fill_id, current_trade=tr)
            if cash_final:
                # Cash read succeeded. An explicit changed authoritative source may revise
                # price/fee/quantity; a stale chain status alone cannot undo confirmation.
                if prior is not None and prior.final and prior.contracts == rec.contracts:
                    rec = replace(rec, final=True)
            elif prior is not None:
                same_identity = (prior.venue_order_id == rec.venue_order_id
                                 and prior.market_id == rec.market_id and prior.side == rec.side)
                if same_identity and prior.contracts == rec.contracts:
                    rec = prior
                    fee_source = "venue activity cash (durable; reread unavailable)"
                else:
                    # Source authority remains in the append-only cash table for its
                    # covered quantity only. Never substitute six cash-covered shares
                    # for eleven observed shares or extrapolate its cash/fee to eleven.
                    rec = replace(rec, final=False)
                    fee_source = f"provisional; durable cash covers {prior.contracts:g} of {rec.contracts:g} observed contracts"
            if role_blocked or self.projection_batch_error or self.persistence_error:
                # Proved cash is retained, but an unproved/violated post-only role cannot
                # become accounting-final merely through a durable cash fallback.
                rec = replace(rec, final=False)
            try:
                # Publish source, audit and projection together. record_fill commits
                # last; no failed prefix may mint fresh durable cash authority.
                con = self.journal.store.con
                if not con.in_transaction:
                    # The production execution store is configured for IMMEDIATE writes so a
                    # concurrent loop transaction enters SQLite's busy handler and waits. An
                    # explicit deferred BEGIN here bypassed that protection: after the network
                    # reads it failed instantly while upgrading to a writer (2026-09-10 flag 530).
                    con.execute('BEGIN IMMEDIATE')
                if cash_final and activity is not None:
                    self._remember_cash_source(tr, activity)
                    source = {"fill_id": rec.fill_id, "endpoint": "data-api.polymarket.com/activity",
                              "activity": json.loads(json.dumps(activity, default=str))}
                    raw = json.dumps(source)
                    if order and not con.execute(
                            "SELECT 1 FROM order_events WHERE client_order_id=? AND kind='authoritative_cash' AND raw_json=?",
                            (order[0], raw)).fetchone():
                        self.journal._event(order[0], "authoritative_cash", None, source, self.clock())
                self.journal.record_fill(rec)
            except Exception as exc:
                rec = replace(rec, final=False)
                self._unpersisted_fills[pending_key] = rec
                try:
                    self.journal.store.con.rollback()
                except Exception:
                    pass  # The persistent STOP below remains visible even with a dead connection.
                failure = self._persistence_failure if marker is not None else self._legacy_fill_persistence_failure
                failure(order[0] if order else order_id, exc)
                fee_source = 'provisional; persistence STOP'
            self.last_fee_source = fee_source
            out.append(rec)
        if self.persistence_error:
            # A later failing row cannot leave an earlier returned prefix final. Also
            # replay unpersisted inventory when subsequent reads are empty or stale.
            returned = {}
            for rec in [*out, *self._unpersisted_fills.values()]:
                key = (rec.venue_order_id, rec.fill_id)
                if key not in returned or rec.contracts >= returned[key].contracts:
                    returned[key] = rec
            out = [replace(rec, final=False) for rec in returned.values()]
            self.last_error = self.persistence_error
        elif self.projection_batch_error:
            self.last_error = self.projection_batch_error
        return out

    def _durable_cash_fill(self, fill_id: str, *, current_trade: dict) -> FillRecord | None:
        """Only source-proved cash is durable; a legacy final bit/model fee is not proof."""
        row = self.journal.store.con.execute(
            "SELECT source_json,source_sha256 FROM pm_cash_sources WHERE fill_id=? ORDER BY id DESC LIMIT 1",
            (fill_id,)).fetchone()
        if row is None:
            return None
        if hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
            raise ValueError("durable cash source SHA256 mismatch")
        source = json.loads(row[0], parse_float=Decimal)
        tr, activity = source['trade'], source['activity']
        price, fee = authoritative_cash_fill(tr, activity)
        order_id = str(tr.get('taker_order_id') or tr.get('order_id') or '')
        previous = self.journal.store.con.execute(
            "SELECT final,contracts,venue_order_id FROM venue_fills WHERE fill_id=?", (fill_id,)).fetchone()
        was_final = bool(previous and previous[0] and previous[1] == float(tr['size']) and previous[2] == order_id)
        same_match = (_activity_key(current_trade, trade=True) == _activity_key(tr, trade=True)
                      and str(current_trade.get('size')) == str(tr.get('size'))
                      and str(current_trade.get('taker_order_id') or current_trade.get('order_id') or '') == order_id)
        now_confirmed = same_match and str(current_trade.get('status', '')).upper() in FINAL_TRADE
        return FillRecord(self.venue, order_id, fill_id,
                          float(tr['size']), price, fee, str(tr.get('trader_side', 'TAKER')).upper() == 'TAKER',
                          _f(tr.get('match_time')), was_final or now_confirmed or str(tr.get('status', '')).upper() in FINAL_TRADE,
                          market_id=str(tr.get('asset_id') or ''),
                          side='sell_yes' if str(tr.get('side', '')).upper() == 'SELL' else 'buy_yes')

    def _remember_cash_source(self, trade: dict, activity: dict) -> None:
        """Stage source evidence; fills() commits it atomically with audit/projection."""
        source = json.dumps({'trade': trade, 'activity': activity}, default=str, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(source.encode()).hexdigest()
        previous = self.journal.store.con.execute(
            "SELECT source_sha256 FROM pm_cash_sources WHERE fill_id=? ORDER BY id DESC LIMIT 1",
            (str(trade['id']),)).fetchone()
        if previous is None or previous[0] != digest:
            self.journal.store.con.execute(
                "INSERT INTO pm_cash_sources(fill_id,source_sha256,source_json,observed_utc) VALUES(?,?,?,?)",
                (str(trade['id']), digest, source, self.clock()))

    def _pinned_fee(self, tr: dict, size: float, price: float, fee_params: Any) -> float:
        from nodes.fees.models import Fill
        from nodes.fees.registry import model_for, params_for
        try:
            f = Fill(venue=self.venue, market_id=str(tr.get("asset_id") or ""), outcome_id=str(tr.get("asset_id") or ""),
                     side="yes", price=price, contracts=size, liquidity="taker", order_seq=0)
            return float(model_for(self.venue).entry_cost([f], params_for(self.venue, fee_params)))
        except Exception:  # noqa: BLE001
            return 0.0

    # ── the protection layer's reads (2026-09-08) ────────────────────────
    def orderbook(self, market_id: str, side: str = "buy_yes") -> Book | None:
        """The token's live CLOB book (asks for a buy, bids for a sell), or None."""
        try:
            from nodes.venue_polymarket.books import pm_book
            return pm_book(self.transport.book(market_id), self.clock())
        except Exception as exc:  # noqa: BLE001
            self.last_error = brief_error(exc)
            return None

    def positions(self) -> Sequence[Position] | None:
        self.position_evidence = None
        self.position_evidence_error = ''
        try:
            rows = self.transport.positions()
        except Exception as exc:  # noqa: BLE001
            self.last_error = brief_error(exc)
            return None
        if rows is None:
            return None
        t = self.clock()
        out = []
        for r in rows:
            size = _f(r.get("size"))
            if size <= 0:
                continue
            out.append(Position(self.venue, str(r.get("asset") or r.get("asset_id") or ""), "yes", size,
                                _f(r.get("avgPrice"), None) if r.get("avgPrice") is not None else None, t))
        try:
            from nodes.exec_polymarket.position_evidence import capture
            self.position_evidence = capture(rows, getattr(self.transport, 'position_read_evidence', None), observed_utc=t)
        except Exception as exc:
            # Keep the physical holdings unchanged; only the narrow economic-zero
            # incident classifier requires complete source evidence.
            self.position_evidence_error = brief_error(exc)
        return out

    def balance(self) -> Balance | None:
        try:
            usd = self.transport.balance_usd()
        except Exception as exc:  # noqa: BLE001
            self.last_error = brief_error(exc)
            return None
        return None if usd is None else Balance(self.venue, usd, self.clock())

    def cancel_all(self) -> int:
        try:
            return int(self.transport.cancel_all())
        except Exception as exc:  # noqa: BLE001
            self.last_error = brief_error(exc)
            return 0

    def stats(self) -> dict:
        user_stream = getattr(self.transport, "user_stream", None)
        return {"venue": self.venue, "mode": self.mode.value, "submits": self.submits,
                "unconfirmed": self.unconfirmed, "last_error": self.last_error,
                "persistence_error": self.persistence_error, "projection_batch_error": self.projection_batch_error,
                "user_stream": None if user_stream is None else {
                    "connected": bool(user_stream.connected), "errors": user_stream.errors,
                    "last_frame_utc": user_stream.last_frame_utc,
                    "last_error": user_stream.last_error}}
