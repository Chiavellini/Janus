#!/usr/bin/env python3
"""The order-path contract every execution venue implements. Types and a Protocol; no I/O.

THE RULES, which are the reason these types look the way they do (spec §10):
  * `submit()` takes a `RiskClearance` and consumes it. No clearance, no order. A bool cannot be
    handed in by mistake because the adapter never had one.
  * Every order has a client order id chosen BEFORE submission and journaled BEFORE the POST, so
    a crash between the two leaves a row that says "an order may exist" -- which is
    UNCONFIRMED, never UNFILLED, and is reconciled before anything is retried.
  * The venue's answer is a three-way fact: FILLED / PARTIAL / UNFILLED as the venue reports it,
    or UNCONFIRMED when it did not answer. A transport error is UNCONFIRMED. A rejection is
    REJECTED. Nothing is inferred.
  * `status()` and `fills()` are how UNCONFIRMED becomes known. They are the only path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable

from kernel.schema import FillState, Mode

TIME_IN_FORCE = frozenset({"fok", "ioc", "gtc"})
#: buy_* opens a position in an outcome; sell_* REDUCES one already held (the unwind of the hedge
#: protection layer, 2026-09-08) and is never a way to open a short. On Kalshi's single YES book a
#: sell_yes is an `ask` at p and a sell_no a `bid` at 1-p, the same wire shape as the complementary
#: buy; the venue nets it against the position. On Polymarket a sell_yes is a SELL of the token.
SIDES = frozenset({"buy_yes", "buy_no", "sell_yes", "sell_no"})


@dataclass(frozen=True)
class OrderRequest:
    venue: str
    market_id: str                 # Kalshi ticker / Polymarket token id
    outcome_id: str
    side: str                      # "buy_yes" | "buy_no" | "sell_yes" | "sell_no" (a sell reduces a held position)
    price: float                   # limit, as a probability in [0,1] for the outcome named by the side
    contracts: float
    time_in_force: str             # "fok" | "ioc" | "gtc"
    client_order_id: str
    opportunity_id: str
    #: True for a PROTECTIVE leg (the hedge, a chased hedge, an unwind): the clearance admits it
    #: under the protect window, not the first-leg TTL.
    hedge: bool = False
    #: Venue price increment carried from the executable book. Polymarket needs it to find the
    #: nearest share-sized order whose collateral is exact to cents without widening the limit.
    tick: float | None = None

    @property
    def is_sell(self) -> bool:
        return self.side.startswith("sell_")

    def __post_init__(self) -> None:
        if self.side not in SIDES:
            raise ValueError(f"side must be one of {sorted(SIDES)}, got {self.side!r}")
        if self.time_in_force not in TIME_IN_FORCE:
            raise ValueError(f"time_in_force must be one of {sorted(TIME_IN_FORCE)}")
        if not (0.0 < self.price < 1.0):
            raise ValueError("price is a probability strictly inside (0, 1)")
        if self.contracts <= 0:
            raise ValueError("contracts must be positive")
        if self.tick is not None and self.tick <= 0:
            raise ValueError("tick must be positive when supplied")
        if not self.client_order_id:
            raise ValueError("client_order_id is required before submission")


@dataclass(frozen=True)
class Ack:
    """What the venue said when we submitted or cancelled. `state` is the three-way fact."""
    venue: str
    client_order_id: str
    venue_order_id: str | None
    state: FillState
    filled_contracts: float
    avg_price: float | None
    fee_usd: float | None
    raw_status: str
    received_utc: float
    open: bool = False             # resting on the book (gtc) -- not a terminal fact
    settlement_pending: bool = False   # Polymarket: matched off-chain, not yet CONFIRMED on-chain
    detail: str = ""


@dataclass(frozen=True)
class OrderState(Ack):
    """A later look at the same order. Same shape; `final` says whether it can still change."""
    final: bool = False


@dataclass(frozen=True)
class FillRecord:
    venue: str
    venue_order_id: str
    fill_id: str
    contracts: float
    price: float
    fee_usd: float
    is_taker: bool
    ts: float
    final: bool                    # venue-final (Polymarket: CONFIRMED on-chain)
    #: What was traded, as the venue names it (Polymarket asset id / Kalshi ticker) and which way
    #: ("buy_yes" style), so a fill no journal row claims can still be attributed (the position
    #: guard, 2026-09-08). Empty on venues that do not say.
    market_id: str = ""
    side: str = ""


@dataclass(frozen=True)
class Position:
    """What a venue says we hold right now: contracts of one outcome of one market."""
    venue: str
    market_id: str
    side: str                      # "yes" | "no" (Polymarket: the token is the side; "yes")
    contracts: float
    avg_price: float | None
    fetched_utc: float


@dataclass(frozen=True)
class Balance:
    venue: str
    available_usd: float
    fetched_utc: float


@runtime_checkable
class ExecutionVenue(Protocol):
    venue: str
    mode: Mode

    def submit(self, req: OrderRequest, clearance) -> Ack: ...
    def cancel(self, client_order_id: str) -> Ack: ...
    def status(self, client_order_id: str) -> OrderState: ...
    def fills(self, *, since_utc: float) -> Sequence[FillRecord]: ...
    def balance(self) -> Balance | None: ...
    def cancel_all(self) -> int: ...
    #: The two the protection layer reads (2026-09-08). Both best effort: None when the venue
    #: cannot say right now; never raise into the machine.
    def orderbook(self, market_id: str, side: str = "buy_yes"): ...
    def positions(self) -> Sequence[Position] | None: ...
