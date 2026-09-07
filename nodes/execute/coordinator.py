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
    #: How long leg A may stay UNCONFIRMED before UNKNOWN_PROVIDER_STATE. Its own window, not the
    #: hedge's: a marketable CLOB order can sit `delayed` for seconds, and the hedge window is armed
    #: only once leg A is known (2026-09-07).
    leg_a_settle_s: float = 6.0
    poll_interval_s: float = 0.1
    clock: Callable[[], float] = time.time
    mono: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    opportunities: object | None = None       # nodes/opportunity.OpportunityStore, optional
    kill: object | None = None                # nodes/risk.KillSwitches, optional
    balances: Callable[[], Mapping[str, float] | None] | None = None
    executions: dict[str, Execution] = field(default_factory=dict)
    opp_refusals: dict[str, int] = field(default_factory=dict)
    _t0: dict[str, float] = field(default_factory=dict)      # execution_id -> mono at entry (stage stamps)

    # ── the machine ──────────────────────────────────────────────────────
    def execute(self, plan: Plan, clearance: RiskClearance, *, offers_books: dict | None = None,
                venues_connected: Mapping[str, bool] | None = None,
                pre_stages: Mapping[str, float] | None = None) -> Execution:
        t = self.clock()
        ex = Execution(uuid.uuid4().hex, plan.opportunity_id, plan.event_id, plan.league, self.mode.value,
                       plan.quantity, t, reservation_id=clearance.reservation.reservation_id)
        # Stage stamps (ms from here; the caller's pre-machine stages ride along). Every deliberate
        # wait and round trip on this path is named so ops/latency_report.py can blame it (2026-09-07).
        ex.stages = dict(pre_stages or {})
        self._t0[ex.execution_id] = self.mono()
        self.executions[ex.execution_id] = ex
        self._timed(ex, self.records.start, ex, plan={"first": plan.first.__dict__, "hedge": plan.hedge.__dict__,
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
        self._move(ex, X.VALIDATED)

        # CAPITAL_RESERVED: the clearance carries the reservation; in real-order modes re-check balances now.
        if self.mode.sends_real_orders and self.balances is not None:
            bal = self.balances()
            need = {plan.first.venue: plan.first.contracts * plan.first.limit_price,
                    plan.hedge.venue: plan.hedge.contracts * plan.hedge.limit_price}
            if bal is None or any(bal.get(v, 0.0) < usd for v, usd in need.items()):
                return self._fail(ex, X.BALANCE_CHANGED, f"balances {bal} below {need}", release=True)
        self._move(ex, X.CAPITAL_RESERVED)

        # LEG A: Polymarket, FOK. Ambiguity here costs nothing; that is why it goes first.
        req_a = self._request(plan, plan.first, plan.first.contracts, plan.first.limit_price, hedge=False)
        ex.first_client_id = req_a.client_order_id
        self._move(ex, X.LEG_A_SUBMITTED)
        self._stamp(ex, "a_submit_ms")
        ack = self.venues[plan.first.venue].submit(req_a, clearance)
        self._stamp(ex, "a_ack_ms")
        ack = self._settle_ack(plan.first.venue, ack, deadline_mono=self.mono() + self.leg_a_settle_s, ex=ex, key="a")
        self._stamp(ex, "a_settled_ms")
        if ack.state is FillState.UNCONFIRMED:
            return self._fail(ex, X.UNKNOWN_PROVIDER_STATE, f"leg A unconfirmed: {ack.raw_status} {ack.detail}", release=False)
        if ack.state is FillState.REJECTED:
            return self._fail(ex, X.ORDER_REJECTED, f"leg A rejected: {ack.raw_status} {ack.detail}", release=True)
        if ack.state is FillState.UNFILLED:
            return self._fail(ex, X.ORDER_REJECTED, "leg A unfilled (FOK): no position", release=True)
        ex.first_filled, ex.first_avg_price = ack.filled_contracts, ack.avg_price
        self._move(ex, X.LEG_A_FILLED if ack.state is FillState.FILLED else X.LEG_A_PARTIAL,
                   detail=f"filled {ack.filled_contracts} @ {ack.avg_price}")
        if ack.state is FillState.PARTIAL:
            self._opp(ex, S.PARTIALLY_FILLED, self.clock())

        # LEG B: Kalshi, IOC, for exactly what leg A filled, at the walked level (the limit); the
        # VWAP budget rides beside it in the record (nodes/execute/plan.py, 2026-09-05).
        paid = ex.first_avg_price or plan.first.limit_price
        limit, budget = plan.hedge_limit(paid), plan.hedge_budget(paid)
        if limit < 0.01:
            return self._fail(ex, X.HEDGE_SLIPPAGE_EXCEEDED, f"hedge limit {limit:.4f} is not a price (budget {budget:.4f})", release=False)
        # ONE hedge window, the clearance's, armed now that the position exists: the coordinator
        # and the token used to count separate 3 s windows (the token's from the mint), so a slow
        # leg A settle spent the token's before the first hedge went out (2026-09-07).
        deadline = clearance.arm_hedge(self.mono()) if hasattr(clearance, "arm_hedge") else self.mono() + self.hedge_deadline_s
        attempts = 0
        while ex.unhedged > 1e-9 and self.mono() < deadline and attempts < clearance.max_hedge_submits:
            attempts += 1
            req_b = self._request(plan, plan.hedge, ex.unhedged, max(limit, 0.01), hedge=True)
            ex.hedge_client_ids.append(req_b.client_order_id)
            self._move(ex, X.LEG_B_SUBMITTED, detail=f"attempt {attempts} limit {limit:.4f} budget {budget:.4f}")
            self._stamp(ex, "b_submit_ms")
            hb = self.venues[plan.hedge.venue].submit(req_b, clearance)
            self._stamp(ex, "b_ack_ms")
            hb = self._settle_ack(plan.hedge.venue, hb, deadline_mono=deadline, ex=ex, key="b")
            self._stamp(ex, "b_settled_ms")
            ex.stages["b_attempts"] = attempts
            if hb.state is FillState.UNCONFIRMED:
                return self._fail(ex, X.UNKNOWN_PROVIDER_STATE, f"hedge unconfirmed: {hb.detail}", release=False)
            if hb.state is FillState.REJECTED:
                return self._fail(ex, X.HEDGE_UNAVAILABLE, f"hedge rejected: {hb.raw_status} {hb.detail}", release=False)
            if hb.filled_contracts > 0:
                prev = ex.hedge_filled
                ex.hedge_filled += hb.filled_contracts
                ex.hedge_avg_price = ((prev * (ex.hedge_avg_price or 0.0)) + hb.filled_contracts * (hb.avg_price or 0.0)) / ex.hedge_filled
                self._move(ex, X.LEG_B_FILLED if ex.unhedged <= 1e-9 else X.LEG_B_PARTIAL,
                           detail=f"hedge filled {hb.filled_contracts} @ {hb.avg_price}")
            elif hb.state is FillState.UNFILLED:
                # The book moved above the limit. Chasing is HEDGE_SLIPPAGE_EXCEEDED by definition.
                self._timed(ex, self.records.sync, ex, now=self.clock())
                if self.mono() >= deadline:
                    break
                self.sleep(self.poll_interval_s)
        if ex.unhedged <= 1e-9:
            above = (ex.hedge_avg_price or 0.0) > budget + 1e-9
            self._stamp(ex, "done_ms")
            self._move(ex, X.HEDGED, detail=f"{ex.hedge_filled} hedged @ {ex.hedge_avg_price}"
                       + (f" ABOVE_BUDGET {budget:.4f}: below the hurdle, still a cover" if above else ""))
            self._opp(ex, S.HEDGED, self.clock())
            return ex
        reason = X.HEDGE_SLIPPAGE_EXCEEDED if attempts and ex.hedge_filled == 0 else X.PARTIAL_FILL
        return self._fail(ex, reason, f"{ex.unhedged} contracts unhedged after {attempts} attempts", release=False)

    # ── pieces ───────────────────────────────────────────────────────────
    def _request(self, plan: Plan, leg: LegPlan, contracts: float, limit: float, *, hedge: bool) -> OrderRequest:
        return OrderRequest(leg.venue, leg.market_id, leg.outcome_id, leg.side, round(min(max(limit, 0.01), 0.99), 4),
                            round(contracts, 2), leg.time_in_force, uuid.uuid4().hex, plan.opportunity_id, hedge=hedge)

    def _settle_ack(self, venue: str, ack: Ack, *, deadline_mono: float,
                    ex: Execution | None = None, key: str = "") -> Ack:
        """An UNCONFIRMED ack is polled through status() until it is known or the deadline passes.
        Never resubmitted: the venue may hold the order.

        The first poll is immediate; the poll interval is slept BETWEEN polls (a matched
        Polymarket FOK always comes back UNCONFIRMED, and until 2026-09-07 every one paid a blind
        100 ms before its first poll). A status is an answer only when the venue says it is final,
        or something filled, or it was rejected: a non-final UNFILLED (Polymarket DELAYED, a poll
        that failed) used to be read as "no position" and released the reservation while the venue
        could still fill it."""
        polls = 0
        while ack.state is FillState.UNCONFIRMED and self.mono() < deadline_mono:
            if polls:
                self.sleep(self.poll_interval_s)
            polls += 1
            st = self.venues[venue].status(ack.client_order_id)
            if st.state in _TERMINAL_FILL and not st.open and (st.final or st.filled_contracts > 0
                                                               or st.state is FillState.REJECTED):
                ack = Ack(st.venue, st.client_order_id, st.venue_order_id, st.state, st.filled_contracts,
                          st.avg_price, st.fee_usd, st.raw_status, st.received_utc,
                          settlement_pending=st.settlement_pending, detail=st.detail)
                break
            if st.open:
                self.venues[venue].cancel(ack.client_order_id)       # nothing may rest; take what filled
        if ex is not None and key:
            ex.stages[f"{key}_polls"] = polls
        return ack

    # ── stage stamps ─────────────────────────────────────────────────────
    def _stamp(self, ex: Execution, key: str) -> None:
        t0 = self._t0.get(ex.execution_id)
        if t0 is not None:
            ex.stages[key] = round((self.mono() - t0) * 1000.0, 2)

    def _timed(self, ex: Execution, fn, *args, **kwargs):
        """A store write, its cost accumulated in stages['db_ms'] (a commit is an fsync)."""
        m = self.mono()
        try:
            return fn(*args, **kwargs)
        finally:
            ex.stages["db_ms"] = round(ex.stages.get("db_ms", 0.0) + (self.mono() - m) * 1000.0, 2)

    def _move(self, ex: Execution, to: X, *, detail: str = "") -> None:
        self._timed(ex, self.records.move, ex, to, now=self.clock(), detail=detail)

    def _fail(self, ex: Execution, state: X, detail: str, *, release: bool) -> Execution:
        t = self.clock()
        self._stamp(ex, "done_ms")
        self._timed(ex, self.records.move, ex, state, now=t, detail=detail)
        if release:
            ex.released = True                     # nothing filled anywhere: reconcile may release at once
            self._timed(ex, self.records.sync, ex, now=t)
            self._opp(ex, S.PROFITABLE_UNEXECUTED, t)
        else:
            self._opp(ex, S.FAILED_HEDGE if ex.first_filled > 0 else S.PROFITABLE_UNEXECUTED, t)
        return ex

    def _opp(self, ex: Execution, status: S, now: float) -> None:
        """The opportunity record follows the execution. Persisted WITH its transition row
        (`OpportunityStore.move`); a refused move is counted and printed once per cause rather
        than swallowed -- the machine must not break, but silence is how F3's predicate went
        uncountable (2026-09-05)."""
        if self.opportunities is None:
            return
        load = getattr(self.opportunities, "load", None)
        opp = load(ex.opportunity_id) if load is not None else self.opportunities.live.get(ex.opportunity_id)
        if opp is None:
            return
        try:
            self.opportunities.move(opp, status, now=now, detail=ex.state.value)
        except Exception as exc:  # noqa: BLE001 -- the record must not break the machine; the transition table is pinned by tests
            key = f"{type(exc).__name__}:{opp.status.value}->{status.value}"
            self.opp_refusals[key] = self.opp_refusals.get(key, 0) + 1
            if self.opp_refusals[key] == 1:
                print(f"  [exec] opportunity record refused {key}: {exc}", flush=True)
