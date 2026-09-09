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
from decimal import Decimal, ROUND_DOWN
from typing import Callable, Mapping

from kernel.execution_protocol import Ack, ExecutionVenue, OrderRequest
from kernel.schema import ExecutionState as X, FillState, Mode, OpportunityStatus as S
from nodes.execute.plan import LegPlan, Plan
from nodes.execute.protect import protect
from nodes.execute.records import Execution, ExecutionRecords
from nodes.risk.clearance import RiskClearance
from nodes.risk.flags import raise_flag

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
    #: The hedge protection layer (nodes/execute/protect.py, 2026-09-08): its limits (None = the
    #: checked-in defaults), a fresh-book reader `(venue, market_id, side) -> Book | None` for the
    #: chase, and the lane's hook for a position that could not be protected (kill + page).
    limits: object | None = None
    fresh_book: Callable | None = None
    on_unprotected: Callable | None = None
    executions: dict[str, Execution] = field(default_factory=dict)
    opp_refusals: dict[str, int] = field(default_factory=dict)
    _t0: dict[str, float] = field(default_factory=dict)      # execution_id -> mono at entry (stage stamps)
    _quantity_stop: str | None = field(default=None, init=False)

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
                                                      "max_cost": plan.max_cost_per_contract, "fee": plan.fee_per_contract,
                                                      "settlement_buffer": plan.settlement_buffer_per_contract},
                    books=offers_books or {})
        self._opp(ex, S.EXECUTION_PENDING, t)
        try:
            return self._run(ex, plan, clearance, venues_connected=venues_connected)
        except Exception as exc:  # noqa: BLE001 -- a machine error after leg A is out is a position of unknown state
            # 2026-09-08 01:17Z: the worker's journal write raised after the leg A POST and the
            # execution stayed LEG_A_SUBMITTED with nothing alarming on it. Recorded here as the
            # failure it is: UNKNOWN_PROVIDER_STATE (holds the reservation, alarms) once leg A was
            # submitted, ORDER_REJECTED (released) before. If even that write fails, the caller
            # gets the original exception.
            sent = ex.state not in (X.DETECTED, X.VALIDATED, X.CAPITAL_RESERVED)
            detail = f"machine error after {ex.state.value}: {type(exc).__name__}: {str(exc)[:160]}"
            try:
                if sent:
                    self._fail(ex, X.UNKNOWN_PROVIDER_STATE, detail, release=False)
                else:
                    self._fail(ex, X.ORDER_REJECTED, detail, release=True)
            except Exception:  # noqa: BLE001
                raise exc
            ex.machine_error = exc
            return ex

    def _run(self, ex: Execution, plan: Plan, clearance: RiskClearance, *, venues_connected) -> Execution:
        if self.mode.risks_capital and self._quantity_stop:
            return self._fail(ex, X.ORDER_REJECTED, self._quantity_stop, release=True)
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

        # LEG A: Polymarket, FAK (`ioc` in the internal protocol). Ambiguity here costs nothing;
        # that is why it goes first.
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
            tif = "FAK" if plan.first.time_in_force == "ioc" else plan.first.time_in_force.upper()
            return self._fail(ex, X.ORDER_REJECTED, f"leg A unfilled ({tif}): no position", release=True)
        ex.first_filled, ex.first_avg_price = ack.filled_contracts, ack.avg_price
        self._check_overfill(ex, req_a, ack)
        self._move(ex, X.LEG_A_FILLED if ack.state is FillState.FILLED else X.LEG_A_PARTIAL,
                   detail=f"filled {ack.filled_contracts} @ {ack.avg_price}")
        if ack.state is FillState.PARTIAL:
            self._opp(ex, S.PARTIALLY_FILLED, self.clock())

        # LEG B and everything after it: the protection layer (nodes/execute/protect.py, 2026-09-08).
        # The hedge at the walked limit as before, then the chase to the budget and to the loss cap,
        # then the unwind; a position still naked at the end is a holding failure AND on_unprotected.
        return protect(self, ex, plan, clearance, limits=self.limits, fresh_book=self.fresh_book,
                       on_unprotected=self.on_unprotected)

    def protect_existing(self, ex: Execution, plan: Plan, clearance: RiskClearance) -> Execution:
        """The position guard's re-run on an execution the machine left naked (loaded from its row
        with its plan, under a `clear_protect` clearance): the layer from the position as it stands.
        A machine error here is recorded like `execute`'s."""
        self._t0[ex.execution_id] = self.mono()
        self.executions[ex.execution_id] = ex
        ex.stages["guard_rerun"] = ex.stages.get("guard_rerun", 0) + 1
        try:
            return protect(self, ex, plan, clearance, limits=self.limits, fresh_book=self.fresh_book,
                           on_unprotected=self.on_unprotected)
        except Exception as exc:  # noqa: BLE001
            detail = f"machine error in the protection re-run after {ex.state.value}: {type(exc).__name__}: {str(exc)[:160]}"
            try:
                self._fail(ex, X.UNKNOWN_PROVIDER_STATE, detail, release=False)
            except Exception:  # noqa: BLE001
                raise exc
            ex.machine_error = exc
            return ex

    # ── pieces ───────────────────────────────────────────────────────────
    def _check_overfill(self, ex: Execution, req: OrderRequest, ack: Ack) -> None:
        """Preserve venue quantity and stop later entries before protecting the held position."""
        if ack.filled_contracts <= req.contracts + 1e-9:
            return
        detail = (f"ORDER_OVERFILL {ack.venue} {req.client_order_id}: requested {req.contracts:g}, "
                  f"venue filled {ack.filled_contracts:g}")
        ex.protect.setdefault("quantity_violations", []).append({
            "client_order_id": req.client_order_id, "venue": ack.venue,
            "requested": req.contracts, "filled": ack.filled_contracts,
        })
        if self.mode.risks_capital:
            self._quantity_stop = detail  # In-process fail-closed even if the kill filesystem fails.
            # Alarm failures cannot hide the held fill or prevent its protective hedge.
            if self.kill is not None:
                try:
                    self.kill.latch("live", detail)
                except Exception as exc:  # noqa: BLE001
                    ex.protect["overfill_latch_error"] = f"{type(exc).__name__}: {exc}"
            try:
                raise_flag(self.records.store, "ORDER_OVERFILL", detail, now=self.clock())
            except Exception as exc:  # noqa: BLE001
                ex.protect["overfill_flag_error"] = f"{type(exc).__name__}: {exc}"

    def _request(self, plan: Plan, leg: LegPlan, contracts: float, limit: float, *, hedge: bool,
                 side: str | None = None) -> OrderRequest:
        # Never round a protective buy above the held quantity (10.166667 -> 10.16,
        # not 10.17), or a sell above the held tokens. Precision dust remains visible.
        quantity = float(Decimal(str(contracts)).quantize(Decimal("0.01"), rounding=ROUND_DOWN))
        return OrderRequest(leg.venue, leg.market_id, leg.outcome_id, side or leg.side, round(min(max(limit, 0.01), 0.99), 4),
                            quantity, leg.time_in_force, uuid.uuid4().hex, plan.opportunity_id,
                            hedge=hedge, tick=leg.tick)

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
        # An order submitted over the wire but not authoritatively resolved is exposure, even
        # when the last known filled quantity is zero. Fail closed on the execution host before
        # the opportunity can be retried; the guard will either recover the trade or prove a
        # terminal zero-fill and an operator can then clear the latched switch.
        if state is X.UNKNOWN_PROVIDER_STATE and self.mode.risks_capital and self.kill is not None:
            try:
                self.kill.latch("live", f"unknown provider state: {ex.execution_id[:8]} {ex.event_id} {detail[:120]}")
            except Exception:
                pass
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
        try:
            # `live` first: the machine may run in a worker thread (2026-09-08) and the store's
            # own connection belongs to the loop; the lane owns the record on the loop before
            # dispatch, so it is in `live` for the flight. `load` is the harness/paper path.
            live = getattr(self.opportunities, "live", None)
            opp = live.get(ex.opportunity_id) if live is not None else None
            if opp is None:
                load = getattr(self.opportunities, "load", None)
                opp = load(ex.opportunity_id) if load is not None else None
            if opp is None:
                return
            self.opportunities.move(opp, status, now=now, detail=ex.state.value)
        except Exception as exc:  # noqa: BLE001 -- the record must not break the machine; the transition table is pinned by tests
            key = f"{type(exc).__name__}:{opp.status.value}->{status.value}"
            self.opp_refusals[key] = self.opp_refusals.get(key, 0) + 1
            if self.opp_refusals[key] == 1:
                print(f"  [exec] opportunity record refused {key}: {exc}", flush=True)
