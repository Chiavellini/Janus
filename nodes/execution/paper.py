#!/usr/bin/env python3
"""The paper venue: fills against the SAME book the opportunity was priced from, with a latency
and an adverse-move model. Same journal, same three-way state, same clearance gate as a real
venue -- the coordinator cannot tell them apart, which is the point (spec §14: no mode may
silently escalate; the state machine is byte-identical across modes).

`RefusingVenue` is SHADOW_LIVE: it journals the intent and returns REJECTED("SHADOW").
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

from kernel.execution_protocol import Ack, Balance, FillRecord, OrderRequest, OrderState
from kernel.schema import Book, FillState, Mode, Quote
from nodes.execution.gate import admit
from nodes.execution.journal import Journal


@dataclass
class PaperVenue:
    venue: str
    journal: Journal
    mode: Mode = Mode.PAPER_EXECUTION
    #: (market_id, side) -> the Book to fill against, set from the priced offers. Keyed by SIDE
    #: too: a Kalshi market has a YES projection and a NO projection, and the complementary NO
    #: leg of one outcome shares a ticker with the YES leg of the other. A bare market_id key is
    #: accepted for a market with one side.
    books: dict = field(default_factory=dict)
    latency_s: float = 0.0
    #: Adverse move applied to every ask level at fill time, in price. 0.0 until measured
    #: (nodes/cover.Frontier.slippage_modelled); a test may set it.
    adverse_move: float = 0.0
    balance_usd: float = 1_000.0
    #: The venue's fee params for the markets being filled (as the pricer used them). When set, a
    #: paper fill carries the PINNED taker fee, so paper PnL is net as F3/F5 define it; until
    #: 2026-09-05 every paper order recorded fee_usd 0.0 and the +$5.00 of STL @ LAD was gross.
    fee_params: dict = field(default_factory=dict)
    seed: int = 0
    clock: Callable[[], float] = time.time
    mono: Callable[[], float] = time.monotonic
    _orders: dict[str, Ack] = field(default_factory=dict)
    _fills: list[FillRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def submit(self, req: OrderRequest, clearance) -> Ack:
        t = self.clock()
        refused = admit(req, clearance, venue=self.venue, mode=self.mode, needs=Mode.PAPER_EXECUTION, now=t,
                         now_mono=self.mono(), hedge=req.hedge)
        if refused is not None:
            return refused
        self.journal.pending(req, mode=self.mode.value, now=t)
        key = (req.market_id, req.side)
        book = self.books.get(key) or self.books.get(req.market_id)
        if book is not None and key not in self.books:
            key = req.market_id
        if book is None:
            ack = Ack(self.venue, req.client_order_id, None, FillState.REJECTED, 0.0, None, None, "NO_BOOK", t,
                      detail="paper venue has no book for this market")
            self.journal.record(ack, kind="ack", now=t)
            return ack
        need, gross, filled, taken = req.contracts, 0.0, 0.0, []
        for q in book.asks:
            px = min(0.99, q.price + self.adverse_move)
            if px > req.price + 1e-9:
                break
            take = min(need, q.size)
            gross += take * px
            filled += take
            need -= take
            taken.append((q.price, take))
            if need <= 1e-9:
                break
        if req.time_in_force == "fok" and need > 1e-9:
            filled, gross, taken = 0.0, 0.0, []
        if taken:
            # Liquidity is consumed: the next order sees what is left, as on a real book.
            used = dict(taken)
            left = tuple(Quote(q.price, q.size - used.get(q.price, 0.0), q.is_synthetic) for q in book.asks
                         if q.size - used.get(q.price, 0.0) > 1e-9)
            self.books[key] = Book(bids=book.bids, asks=left, fetched_utc=book.fetched_utc,
                                             source=book.source, server_utc=book.server_utc,
                                             received_mono=book.received_mono)
        state = (FillState.FILLED if filled >= req.contracts - 1e-9 else
                 FillState.PARTIAL if filled > 0 else FillState.UNFILLED)
        avg = gross / filled if filled else None
        fee = self._pinned_fee(req, taken) if filled else 0.0
        oid = f"paper-{req.client_order_id}"
        ack = Ack(self.venue, req.client_order_id, oid, state, filled, avg, fee, state.value.lower(),
                  t + self.latency_s, open=(req.time_in_force == "gtc" and need > 1e-9))
        self.balance_usd -= gross + fee
        self._orders[req.client_order_id] = ack
        if filled:
            self._fills.append(FillRecord(self.venue, oid, f"{oid}-f1", filled, avg, fee, True, t, True))
            self.journal.record_fill(self._fills[-1])
        self.journal.record(ack, kind="ack", now=t)
        return ack

    def _pinned_fee(self, req: OrderRequest, taken: list) -> float:
        """The pinned taker fee over the levels actually taken, through the same fee model the
        cover was priced with. 0.0 when this venue has no fee params set (tests, shadow)."""
        if not self.fee_params:
            return 0.0
        from nodes.fees.models import Fill
        from nodes.fees.registry import model_for, params_for
        fills = [Fill(venue=self.venue, market_id=req.market_id, outcome_id=req.outcome_id, side="yes",
                      price=px, contracts=n, liquidity="taker", order_seq=0) for px, n in taken]
        try:
            return float(model_for(self.venue).entry_cost(fills, params_for(self.venue, self.fee_params)))
        except Exception:  # noqa: BLE001 -- a fee model that cannot price this venue is not a reason to lose the fill
            return 0.0

    def cancel(self, client_order_id: str) -> Ack:
        a = self._orders.get(client_order_id)
        t = self.clock()
        if a is None:
            return Ack(self.venue, client_order_id, None, FillState.UNCONFIRMED, 0.0, None, None, "UNKNOWN", t)
        ack = Ack(self.venue, client_order_id, a.venue_order_id, a.state if a.filled_contracts else FillState.UNFILLED,
                  a.filled_contracts, a.avg_price, a.fee_usd, "canceled", t, open=False)
        self._orders[client_order_id] = ack
        self.journal.record(ack, kind="cancel", now=t)
        return ack

    def status(self, client_order_id: str) -> OrderState:
        a = self._orders.get(client_order_id)
        t = self.clock()
        if a is None:
            return OrderState(self.venue, client_order_id, None, FillState.UNCONFIRMED, 0.0, None, None, "UNKNOWN", t)
        return OrderState(self.venue, client_order_id, a.venue_order_id, a.state, a.filled_contracts, a.avg_price,
                          a.fee_usd, a.raw_status, t, open=a.open, final=not a.open)

    def fills(self, *, since_utc: float) -> Sequence[FillRecord]:
        return [f for f in self._fills if f.ts >= since_utc]

    def balance(self) -> Balance | None:
        return Balance(self.venue, self.balance_usd, self.clock())

    def cancel_all(self) -> int:
        n = 0
        for cid, a in list(self._orders.items()):
            if a.open:
                self.cancel(cid); n += 1
        return n


@dataclass
class RefusingVenue:
    """SHADOW_LIVE: records what would have been sent, sends nothing."""
    venue: str
    journal: Journal
    mode: Mode = Mode.SHADOW_LIVE
    clock: Callable[[], float] = time.time
    mono: Callable[[], float] = time.monotonic
    intents: int = 0

    def submit(self, req: OrderRequest, clearance) -> Ack:
        t = self.clock()
        self.intents += 1
        try:
            self.journal.pending(req, mode=self.mode.value, now=t)
        except ValueError:
            pass
        ack = Ack(self.venue, req.client_order_id, None, FillState.REJECTED, 0.0, None, None, "SHADOW", t,
                  detail="shadow mode: intent recorded, nothing sent")
        self.journal.record(ack, kind="refused", now=t)
        return ack

    def cancel(self, client_order_id: str) -> Ack:
        return Ack(self.venue, client_order_id, None, FillState.UNFILLED, 0.0, None, None, "SHADOW", self.clock())

    def status(self, client_order_id: str) -> OrderState:
        return OrderState(self.venue, client_order_id, None, FillState.REJECTED, 0.0, None, None, "SHADOW", self.clock(), final=True)

    def fills(self, *, since_utc: float) -> Sequence[FillRecord]:
        return []

    def balance(self) -> Balance | None:
        return None

    def cancel_all(self) -> int:
        return 0
