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

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, Sequence

from kernel.execution_protocol import Ack, Balance, FillRecord, OrderRequest, OrderState
from kernel.redact import brief_error
from kernel.schema import FillState, Mode
from nodes.execution.gate import admit
from nodes.execution.journal import Journal

ORDER_TYPE = {"fok": "FOK", "ioc": "FAK", "gtc": "GTC"}
FINAL_TRADE = {"CONFIRMED"}
DEAD_TRADE = {"FAILED"}


class TransportUnavailable(RuntimeError):
    pass


class ClobTransport(Protocol):
    def post_order(self, *, token_id: str, price: float, size: float, order_type: str) -> dict: ...
    def get_order(self, order_id: str) -> dict: ...
    def cancel(self, order_id: str) -> dict: ...
    def trades(self, *, after_ts: float) -> list[dict]: ...
    def balance_usd(self) -> float | None: ...
    def cancel_all(self) -> int: ...


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
        self._T = T
        self._sig_type = sig_type
        self.last_error: str | None = None

    def post_order(self, *, token_id: str, price: float, size: float, order_type: str) -> dict:
        args = self._T.OrderArgsV2(token_id=token_id, price=price, size=size, side="BUY")
        signed = self._c.create_order(args)
        # defer_exec: the library otherwise polls the fill's settlement hashes INSIDE the post
        # (best effort, seconds); the hedge needs the match, not the hash. fills() reads
        # CONFIRMED trades later (2026-09-07).
        return self._c.post_order(signed, getattr(self._T.OrderType, order_type), defer_exec=True)

    def get_order(self, order_id: str) -> dict:
        return self._c.get_order(order_id)

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

    def submit(self, req: OrderRequest, clearance) -> Ack:
        t = self.clock()
        refused = admit(req, clearance, venue=self.venue, mode=self.mode, needs=Mode.LIMITED_LIVE, now=t,
                         now_mono=self.mono(), hedge=req.hedge)
        if refused is not None:
            return refused
        if req.side != "buy_yes":
            return Ack(self.venue, req.client_order_id, None, FillState.REJECTED, 0.0, None, None, "SIDE", t,
                       detail="Polymarket outcomes are separate tokens: pass the outcome's token id as "
                              "market_id with side buy_yes")
        self.journal.pending(req, mode=self.mode.value, now=t)       # BEFORE the POST
        self._requests[req.client_order_id] = req
        self.submits += 1
        try:
            d = self.transport.post_order(token_id=req.market_id, price=req.price, size=req.contracts,
                                          order_type=ORDER_TYPE[req.time_in_force])
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
        self.journal.record(ack, kind="ack", raw=d if isinstance(d, dict) else None)
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
        try:
            o = self.transport.get_order(row["venue_order_id"])
        except Exception as exc:  # noqa: BLE001
            self.last_error = brief_error(exc)
            return OrderState(self.venue, client_order_id, row["venue_order_id"], FillState.UNCONFIRMED, 0.0, None,
                              None, "TRANSPORT", t, detail=self.last_error)
        if not o:
            # The CLOB no longer has the order: a `delayed` FOK that did not match is dropped, and
            # a poll then finds nothing (2026-09-07, RSO @ ELC, the first real order from Mexico:
            # 13 polls to the deadline, UNKNOWN_PROVIDER_STATE, reservation held for nothing).
            # Nothing filled; fills() would still show a trade if one had. Final.
            st = OrderState(self.venue, client_order_id, row["venue_order_id"], FillState.UNFILLED, 0.0, None, None,
                            "not_found", t, open=False, final=True, detail="order not at the venue: a delayed order that did not match")
            self.journal.record(st, kind="status", raw={"not_found": True})
            return st
        st = self._state_from_order(o, client_order_id, float(row["contracts"]), t)
        self.journal.record(st, kind="status", raw=o)
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
                          open=live, settlement_pending=matched > 0, final=status in ("MATCHED", "CANCELED", "CANCELLED"))

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
        self.journal.record(st, kind="cancel")
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
            if fee <= 0 and taker and self.fee_params and size > 0:
                fee, fee_source = self._pinned_fee(tr, size, price), "pinned (venue reported none)"
            rec = FillRecord(self.venue, str(tr.get("taker_order_id") or tr.get("order_id") or ""),
                             str(tr.get("id")), size, price, fee, taker, _f(tr.get("match_time"), since_utc), status in FINAL_TRADE)
            self.journal.record_fill(rec)
            self.last_fee_source = fee_source
            out.append(rec)
        return out

    def _pinned_fee(self, tr: dict, size: float, price: float) -> float:
        from nodes.fees.models import Fill
        from nodes.fees.registry import model_for, params_for
        try:
            f = Fill(venue=self.venue, market_id=str(tr.get("asset_id") or ""), outcome_id=str(tr.get("asset_id") or ""),
                     side="yes", price=price, contracts=size, liquidity="taker", order_seq=0)
            return float(model_for(self.venue).entry_cost([f], params_for(self.venue, self.fee_params)))
        except Exception:  # noqa: BLE001
            return 0.0

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
        return {"venue": self.venue, "mode": self.mode.value, "submits": self.submits,
                "unconfirmed": self.unconfirmed, "last_error": self.last_error}
