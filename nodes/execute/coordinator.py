#!/usr/bin/env python3
"""The two-leg state machine. One code path for every mode; only the venues differ.

    DETECTED -> VALIDATED -> CAPITAL_RESERVED -> LEG_A_SUBMITTED -> LEG_A_FILLED
             -> LEG_B_SUBMITTED -> LEG_B_FILLED | LEG_B_PARTIAL -> HEDGED
    failures: ORDER_REJECTED, ORDER_TIMEOUT, UNKNOWN_PROVIDER_STATE, PARTIAL_FILL, HEDGE_UNAVAILABLE,
              HEDGE_SLIPPAGE_EXCEEDED, MARKET_SUSPENDED, VENUE_DISCONNECTED, BALANCE_CHANGED

The rules, each of which is a line below and a test beside it (spec §10):
  * idempotent client order ids, chosen before submission, journaled by the venue adapter;
  * an UNCONFIRMED leg A is polled, never resubmitted; still unknown at the deadline is
    UNKNOWN_PROVIDER_STATE and the reservation is NOT released -- an order may exist;
  * hedge only the quantity leg A actually filled;
  * the hedge is an IOC at a limit derived from what leg A paid; a book above it is
    HEDGE_SLIPPAGE_EXCEEDED, not a chase;
  * after the hedge deadline, whatever is unhedged is recorded as such (FAILED_HEDGE on the
    opportunity), the reservation stays open, and the watchdog alarms;
  * a kill switch or a disconnect before leg A aborts; after leg A fills, the hedge is still
    sent -- an unhedged position is the larger risk -- and the reason is recorded;
  * capital is released only by the reconcile node, after both venues reconcile.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Mapping

from kernel.execution_protocol import Ack, ExecutionVenue, OrderRequest
from kernel.schema import ExecutionState as X, FillState, Mode, OpportunityStatus as S
from nodes.execute.plan import LegPlan, Plan
from nodes.execute.records import Execution, ExecutionRecords
from nodes.risk.clearance import RiskClearance

_TERMINAL_FILL = {FillState.FILLED, FillState.PARTIAL, FillState.UNFILLED, FillState.REJECTED}


@dataclass
class Coordinator:
    venues: Mapping[str, ExecutionVenue]
    records: ExecutionRecords
    mode: Mode
    #: The hedge window in seconds (the risk limit max_hedge_latency_ms), and how often to poll.
    hedge_deadline_s: float = 3.0
    poll_interval_s: float = 0.1
    clock: Callable[[], float] = time.time
    mono: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    opportunities: object | None = None       # nodes/opportunity.OpportunityStore, optional
    kill: object | None = None                # nodes/risk.KillSwitches, optional
    balances: Callable[[], Mapping[str, float] | None] | None = None
    executions: dict[str, Execution] = field(default_factory=dict)

    # ── the machine ──────────────────────────────────────────────────────
    def execute(self, plan: Plan, clearance: RiskClearance, *, offers_books: dict | None = None,
                venues_connected: Mapping[str, bool] | None = None) -> Execution:
        t = self.clock()
        ex = Execution(uuid.uuid4().hex, plan.opportunity_id, plan.event_id, plan.league, self.mode.value,
                       plan.quantity, t, reservation_id=clearance.reservation.reservation_id)
        self.executions[ex.execution_id] = ex
        self.records.start(ex, plan={"first": plan.first.__dict__, "hedge": plan.hedge.__dict__,
                                     "max_cost": plan.max_cost_per_contract, "fee": plan.fee_per_contract},
                           books=offers_books or {})
        self._opp(ex, S.EXECUTION_PENDING, t)

        # VALIDATED: the clearance is for this plan and still live; both venues present and connected.
        if clearance.opportunity_id != plan.opportunity_id or not clearance.valid(self.mono()):
            return self._fail(ex, X.ORDER_REJECTED, "clearance does not cover this plan or has expired", release=True)
        for v in (plan.first.venue, plan.hedge.venue):
            if v not in self.venues:
                return self._fail(ex, X.VENUE_DISCONNECTED, f"no {v} adapter in this mode", release=True)
            if venues_connected is not None and not venues_connected.get(v, False):
                return self._fail(ex, X.VENUE_DISCONNECTED, f"{v} not connected", release=True)
        if self.kill is not None and self.kill.active(event_id=plan.event_id, strategy=plan.strategy_version,
                                                      live=self.mode.risks_capital,
                                                      venues=(plan.first.venue, plan.hedge.venue)):
            return self._fail(ex, X.ORDER_REJECTED, "kill switch active before leg A", release=True)
        self.records.move(ex, X.VALIDATED, now=self.clock())

        # CAPITAL_RESERVED: the clearance carries the reservation; in real-order modes re-check balances now.
        if self.mode.sends_real_orders and self.balances is not None:
            bal = self.balances()
            need = {plan.first.venue: plan.first.contracts * plan.first.limit_price,
                    plan.hedge.venue: plan.hedge.contracts * plan.hedge.limit_price}
            if bal is None or any(bal.get(v, 0.0) < usd for v, usd in need.items()):
                return self._fail(ex, X.BALANCE_CHANGED, f"balances {bal} below {need}", release=True)
        self.records.move(ex, X.CAPITAL_RESERVED, now=self.clock())

        # LEG A: Polymarket, FOK. Ambiguity here costs nothing; that is why it goes first.
        req_a = self._request(plan, plan.first, plan.first.contracts, plan.first.limit_price, hedge=False)
        ex.first_client_id = req_a.client_order_id
        self.records.move(ex, X.LEG_A_SUBMITTED, now=self.clock())
        ack = self.venues[plan.first.venue].submit(req_a, clearance)
        ack = self._settle_ack(plan.first.venue, ack, deadline_mono=self.mono() + self.hedge_deadline_s)
        if ack.state is FillState.UNCONFIRMED:
            return self._fail(ex, X.UNKNOWN_PROVIDER_STATE, f"leg A unconfirmed: {ack.raw_status} {ack.detail}", release=False)
        if ack.state is FillState.REJECTED:
            return self._fail(ex, X.ORDER_REJECTED, f"leg A rejected: {ack.raw_status} {ack.detail}", release=True)
        if ack.state is FillState.UNFILLED:
            return self._fail(ex, X.ORDER_REJECTED, "leg A unfilled (FOK): no position", release=True)
        ex.first_filled, ex.first_avg_price = ack.filled_contracts, ack.avg_price
        self.records.move(ex, X.LEG_A_FILLED if ack.state is FillState.FILLED else X.LEG_A_PARTIAL,
                          now=self.clock(), detail=f"filled {ack.filled_contracts} @ {ack.avg_price}")
        if ack.state is FillState.PARTIAL:
            self._opp(ex, S.PARTIALLY_FILLED, self.clock())

        # LEG B: Kalshi, IOC, for exactly what leg A filled, at the hedge limit.
        limit = plan.hedge_limit(ex.first_avg_price or plan.first.limit_price)
        if limit < plan.hedge.limit_price - 1e-9 and limit < 0.01:
            return self._fail(ex, X.HEDGE_SLIPPAGE_EXCEEDED, f"hedge limit {limit:.4f} is not a price", release=False)
        deadline = self.mono() + self.hedge_deadline_s
        attempts = 0
        while ex.unhedged > 1e-9 and self.mono() < deadline and attempts < clearance.max_hedge_submits:
            attempts += 1
            req_b = self._request(plan, plan.hedge, ex.unhedged, max(limit, 0.01), hedge=True)
            ex.hedge_client_ids.append(req_b.client_order_id)
            self.records.move(ex, X.LEG_B_SUBMITTED, now=self.clock(), detail=f"attempt {attempts} limit {limit:.4f}")
            hb = self.venues[plan.hedge.venue].submit(req_b, clearance)
            hb = self._settle_ack(plan.hedge.venue, hb, deadline_mono=deadline)
            if hb.state is FillState.UNCONFIRMED:
                return self._fail(ex, X.UNKNOWN_PROVIDER_STATE, f"hedge unconfirmed: {hb.detail}", release=False)
            if hb.state is FillState.REJECTED:
                return self._fail(ex, X.HEDGE_UNAVAILABLE, f"hedge rejected: {hb.raw_status} {hb.detail}", release=False)
            if hb.filled_contracts > 0:
                prev = ex.hedge_filled
                ex.hedge_filled += hb.filled_contracts
                ex.hedge_avg_price = ((prev * (ex.hedge_avg_price or 0.0)) + hb.filled_contracts * (hb.avg_price or 0.0)) / ex.hedge_filled
                self.records.move(ex, X.LEG_B_FILLED if ex.unhedged <= 1e-9 else X.LEG_B_PARTIAL,
                                  now=self.clock(), detail=f"hedge filled {hb.filled_contracts} @ {hb.avg_price}")
            elif hb.state is FillState.UNFILLED:
                # The book moved above the limit. Chasing is HEDGE_SLIPPAGE_EXCEEDED by definition.
                self.records.sync(ex, now=self.clock())
                if self.mono() >= deadline:
                    break
                self.sleep(self.poll_interval_s)
        if ex.unhedged <= 1e-9:
            self.records.move(ex, X.HEDGED, now=self.clock(), detail=f"{ex.hedge_filled} hedged @ {ex.hedge_avg_price}")
            self._opp(ex, S.HEDGED, self.clock())
            return ex
        reason = X.HEDGE_SLIPPAGE_EXCEEDED if attempts and ex.hedge_filled == 0 else X.PARTIAL_FILL
        return self._fail(ex, reason, f"{ex.unhedged} contracts unhedged after {attempts} attempts", release=False)

    # ── pieces ───────────────────────────────────────────────────────────
    def _request(self, plan: Plan, leg: LegPlan, contracts: float, limit: float, *, hedge: bool) -> OrderRequest:
        return OrderRequest(leg.venue, leg.market_id, leg.outcome_id, leg.side, round(min(max(limit, 0.01), 0.99), 4),
                            round(contracts, 2), leg.time_in_force, uuid.uuid4().hex, plan.opportunity_id, hedge=hedge)

    def _settle_ack(self, venue: str, ack: Ack, *, deadline_mono: float) -> Ack:
        """An UNCONFIRMED ack is polled through status() until it is known or the deadline passes.
        Never resubmitted: the venue may hold the order."""
        while ack.state is FillState.UNCONFIRMED and self.mono() < deadline_mono:
            self.sleep(self.poll_interval_s)
            st = self.venues[venue].status(ack.client_order_id)
            if st.state in _TERMINAL_FILL and not st.open:
                return Ack(st.venue, st.client_order_id, st.venue_order_id, st.state, st.filled_contracts,
                           st.avg_price, st.fee_usd, st.raw_status, st.received_utc,
                           settlement_pending=st.settlement_pending, detail=st.detail)
            if st.open:
                self.venues[venue].cancel(ack.client_order_id)       # nothing may rest; take what filled
        return ack

    def _fail(self, ex: Execution, state: X, detail: str, *, release: bool) -> Execution:
        t = self.clock()
        self.records.move(ex, state, now=t, detail=detail)
        if release:
            ex.released = True                     # nothing filled anywhere: reconcile may release at once
            self.records.sync(ex, now=t)
            self._opp(ex, S.PROFITABLE_UNEXECUTED, t)
        else:
            self._opp(ex, S.FAILED_HEDGE if ex.first_filled > 0 else S.PROFITABLE_UNEXECUTED, t)
        return ex

    def _opp(self, ex: Execution, status: S, now: float) -> None:
        if self.opportunities is None:
            return
        opp = self.opportunities.live.get(ex.opportunity_id)
        if opp is None:
            return
        try:
            if opp.transition(status, now=now, detail=ex.state.value):
                self.opportunities._upsert(opp)
        except Exception:  # noqa: BLE001 -- the record must not break the machine; the transition table is pinned by tests
            pass
