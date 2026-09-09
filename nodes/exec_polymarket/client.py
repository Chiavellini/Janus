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
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, Sequence

from kernel.execution_protocol import Ack, Balance, FillRecord, OrderRequest, OrderState, Position
from kernel.redact import brief_error
from kernel.schema import Book, FillState, Mode
from nodes.execution.gate import admit
from nodes.execution.journal import Journal

ORDER_TYPE = {"fok": "FOK", "ioc": "FAK", "gtc": "GTC"}
FINAL_TRADE = {"CONFIRMED"}
DEAD_TRADE = {"FAILED"}
# The CLOB order lookup is eventually consistent with its trade feed. On 2026-09-08 two FAKs
# returned `not_found` immediately and then appeared as confirmed trades. Absence is ambiguous
# until both endpoints have disagreed for this long; the reservation stays held meanwhile.
NOT_FOUND_GRACE_S = 120.0
TRADE_CHECK_INTERVAL_S = 1.0


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
        self._orders: dict[str, dict] = {}
        self._trades: dict[str, dict[str, dict]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _get(d: dict, snake: str, camel: str | None = None, default=None):
        return d.get(snake, d.get(camel or snake, default))

    def handle(self, raw, *, now: float | None = None) -> list[str]:
        self.frames += 1
        if isinstance(raw, str):
            if raw.strip().upper() in ("PING", "PONG"):
                self.last_frame_utc = now or time.time()
                return ["pong"]
            try:
                raw = json.loads(raw)
            except ValueError:
                self.errors += 1
                self.last_error = "non-JSON user frame"
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
                        self._trades.setdefault(taker, {})[tid] = dict(payload)
                    for maker in self._get(payload, "maker_orders", "makerOrders", ()) or ():
                        oid = str(self._get(maker, "order_id", "orderId", "") or "")
                        if oid and tid:
                            row = dict(maker)
                            row["id"] = tid
                            row["status"] = payload.get("status")
                            row["size"] = self._get(maker, "matched_amount", "matchedAmount", 0)
                            self._trades.setdefault(oid, {})[tid] = row
                    if taker or self._get(payload, "maker_orders", "makerOrders"):
                        kinds.append("trade")
            self.last_frame_utc = now or time.time()
        return kinds

    def stats(self) -> dict:
        return {"connected": self.connected, "frames": self.frames, "errors": self.errors,
                "last_error": self.last_error,
                "age_s": round(time.time() - self.last_frame_utc, 2) if self.last_frame_utc else None}

    def order(self, order_id: str) -> dict | None:
        """Return a REST-order shaped match or terminal zero-fill seen by the socket."""
        with self._lock:
            trades = list(self._trades.get(order_id, {}).values())
            order = dict(self._orders.get(order_id, {}))
        good = [t for t in trades if str(t.get("status", "")).upper().replace("TRADE_STATUS_", "") not in DEAD_TRADE]
        if good:
            qty = sum(_f(self._get(t, "size", "matchedAmount")) for t in good)
            cost = sum(_f(self._get(t, "size", "matchedAmount")) * _f(t.get("price")) for t in good)
            return {"id": order_id, "status": "MATCHED", "size_matched": qty,
                    "price": (cost / qty if qty else None), "user_stream": True}
        matched = _f(self._get(order, "size_matched", "sizeMatched"))
        if matched > 0:
            return {"id": order_id, "status": str(order.get("status") or "MATCHED"),
                    "size_matched": matched, "price": order.get("price"), "user_stream": True}
        status = str(order.get("status") or "").upper()
        event_type = str(self._get(order, "order_event_type", "orderEventType", order.get("type") or "")).upper()
        order_type = str(self._get(order, "order_type", "orderType", "")).upper()
        # A cancellation is Polymarket's authoritative statement that the remaining amount is
        # gone.  UNMATCHED is terminal only for the immediate-or-cancel family: a resting GTC can
        # be unmatched and still live, whereas a FAK/FOK/IOC cannot survive the matching pass.
        zero_final = status in ("CANCELED", "CANCELLED") or event_type == "CANCELLATION"
        zero_final = zero_final or (status == "UNMATCHED" and order_type in ("FAK", "FOK", "IOC"))
        if zero_final:
            return {"id": order_id, "status": "CANCELED", "size_matched": 0.0,
                    "price": order.get("price"), "user_stream": True}
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
    def post_order(self, *, token_id: str, price: float, size: float, order_type: str, side: str = "BUY") -> dict: ...
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

    def post_order(self, *, token_id: str, price: float, size: float, order_type: str, side: str = "BUY") -> dict:
        # side "SELL" (2026-09-08): the protection layer selling a held token back. `size` is shares
        # either way; the library builds the maker/taker amounts from the side.
        args = self._T.OrderArgsV2(token_id=token_id, price=price, size=size, side=side)
        signed = self._c.create_order(args)
        # defer_exec: the library otherwise polls the fill's settlement hashes INSIDE the post
        # (best effort, seconds); the hedge needs the match, not the hash. fills() reads
        # CONFIRMED trades later (2026-09-07).
        return self._c.post_order(signed, getattr(self._T.OrderType, order_type), defer_exec=True)

    def get_order(self, order_id: str) -> dict:
        return self._c.get_order(order_id)

    def user_order(self, order_id: str) -> dict | None:
        return self.user_stream.order(order_id)

    def cancel(self, order_id: str) -> dict:
        return self._c.cancel_order(self._T.OrderPayload(orderID=order_id))

    def trades(self, *, after_ts: float) -> list[dict]:
        return list(self._c.get_trades(self._T.TradeParams(after=int(after_ts))))

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
        funder = os.environ.get("JANUS_PM_FUNDER")
        if not funder:
            return None
        try:
            from kernel.fetch import Client
            cl = Client("polymarket-data", rate=2, burst=4, cache_dir=None, timeout=10.0)
            d = cl.get_json(f"{PM_DATA_API}/positions", params={"user": funder, "sizeThreshold": 0}, use_cache=False)
            return list(d) if isinstance(d, list) else None
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


@dataclass
class PolymarketExecution:
    transport: ClobTransport
    journal: Journal
    mode: Mode
    clock: Callable[[], float] = time.time
    mono: Callable[[], float] = time.monotonic
    venue: str = "polymarket"
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
    #: Set when the CLOB answered 403 "Trading restricted in your region": this host cannot place
    #: Polymarket orders at all (2026-09-07, the Ashburn box's first real order). The lane refuses
    #: every cover cheaply from then on; only a restart from a permitted host clears it.
    geoblocked: str | None = None
    _requests: dict[str, OrderRequest] = field(default_factory=dict)
    #: Tokens whose sell allowance was set this process (once per token; the approval is on-chain).
    _sell_ok: set = field(default_factory=set)
    _last_trade_check: dict[str, float] = field(default_factory=dict)

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
        if req.is_sell and req.market_id not in self._sell_ok:
            # The exchange must be approved on the conditional token before a SELL (2026-09-08).
            # Best effort and remembered: a refused approval shows up as the venue's own rejection.
            ok = getattr(self.transport, "ensure_sell_allowance", lambda _t: True)(req.market_id)
            if ok:
                self._sell_ok.add(req.market_id)
        self.journal.pending(req, mode=self.mode.value, now=t)       # BEFORE the POST
        self._requests[req.client_order_id] = req
        self.submits += 1
        try:
            d = self.transport.post_order(token_id=req.market_id, price=req.price, size=req.contracts,
                                          order_type=ORDER_TYPE[req.time_in_force],
                                          side="SELL" if req.is_sell else "BUY")
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
            # 2026-09-07). Trusting the request size here would under-hedge by the improvement.
            # Every match is confirmed through status() before it is believed.
            return Ack(self.venue, req.client_order_id, oid, FillState.UNCONFIRMED, 0.0, None, None, status, t,
                       settlement_pending=True, detail="matched; size via status()")
        if status == "live":
            return Ack(self.venue, req.client_order_id, oid, FillState.UNFILLED, 0.0, None, None, status, t, open=True)
        # delayed / unmatched / anything else: the venue has the order and has not said what happened
        return Ack(self.venue, req.client_order_id, oid, FillState.UNCONFIRMED, 0.0, None, None, status or "unknown", t,
                   open=True, detail="placed; outcome not yet reported")

    def status(self, client_order_id: str) -> OrderState:
        row = self.journal.get(client_order_id)
        t = self.clock()
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
                          final=status in ("MATCHED", "CANCELED", "CANCELLED", "UNMATCHED"))

    def cancel(self, client_order_id: str) -> Ack:
        row = self.journal.get(client_order_id)
        t = self.clock()
        if row is None or not row.get("venue_order_id"):
            return Ack(self.venue, client_order_id, None, FillState.UNCONFIRMED, 0.0, None, None, "NOT_FOUND", t)
        try:
            self.transport.cancel(row["venue_order_id"])
        except Exception as exc:  # noqa: BLE001
            self.last_error = brief_error(exc)
        st = self.status(client_order_id)
        try:
            self.journal.record(st, kind="cancel")
        except Exception as exc:  # noqa: BLE001 -- the order is OUT; a store failure here must not hide the ack from the machine (2026-09-08)
            self.journal_failures = getattr(self, "journal_failures", 0) + 1
            print(f"  [polymarket] journal write failed after the wire: {type(exc).__name__}: {str(exc)[:80]}", flush=True)
        return st

    def fills(self, *, since_utc: float) -> Sequence[FillRecord]:
        out = []
        for tr in self.transport.trades(after_ts=since_utc):
            status = str(tr.get("status", "")).upper()
            if status in DEAD_TRADE:
                continue                     # a reversal: reconcile handles it, never a fill here
            size, price = _f(tr.get("size")), _f(tr.get("price"))
            taker = str(tr.get("trader_side", "TAKER")).upper() == "TAKER"
            fee = size * price * _f(tr.get("fee_rate_bps")) / 10_000.0
            fee_source = "venue"
            market_id = str(tr.get("asset_id") or "")
            fee_params = self.fee_params_by_market.get(market_id) or self.fee_params
            if fee <= 0 and taker and fee_params and size > 0:
                fee, fee_source = self._pinned_fee(tr, size, price, fee_params), "pinned (venue reported none)"
            rec = FillRecord(self.venue, str(tr.get("taker_order_id") or tr.get("order_id") or ""),
                             str(tr.get("id")), size, price, fee, taker, _f(tr.get("match_time"), since_utc), status in FINAL_TRADE,
                             market_id=market_id,
                             side="sell_yes" if str(tr.get("side", "")).upper() == "SELL" else "buy_yes")
            self.journal.record_fill(rec)
            self.last_fee_source = fee_source
            out.append(rec)
        return out

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
                "user_stream": None if user_stream is None else {
                    "connected": bool(user_stream.connected), "errors": user_stream.errors,
                    "last_frame_utc": user_stream.last_frame_utc,
                    "last_error": user_stream.last_error}}
