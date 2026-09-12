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

import concurrent.futures
import time
import uuid
from dataclasses import dataclass, field, replace
from decimal import Decimal, ROUND_DOWN
from typing import Callable, Mapping

from kernel.execution_protocol import Ack, ExecutionVenue, OrderRequest
from kernel.schema import ExecutionState as X, FillState, Mode, OpportunityStatus as S
from nodes.execute.plan import LegPlan, Plan, marginal_price, vwap_for_size
from nodes.execute.maker import MakerFillSession, MakerRestAuthorization
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
                pre_stages: Mapping[str, float] | None = None,
                maker_guard: Callable[[float], str | None] | None = None) -> Execution:
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
                                                      "settlement_buffer": plan.settlement_buffer_per_contract,
                                                      "quote_expires_utc": plan.quote_expires_utc,
                                                      "sizing": dict(plan.sizing or {})},
                    books=offers_books or {})
        self._opp(ex, S.EXECUTION_PENDING, t)
        try:
            return self._run(ex, plan, clearance, venues_connected=venues_connected,
                             maker_guard=maker_guard)
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

    def _run(self, ex: Execution, plan: Plan, clearance: RiskClearance, *, venues_connected,
             maker_guard=None) -> Execution:
        if self.mode.risks_capital and self._quantity_stop:
            return self._fail(ex, X.ORDER_REJECTED, self._quantity_stop, release=True)
        # VALIDATED: the clearance is for this plan and still live; both venues present and connected.
        if clearance.opportunity_id != plan.opportunity_id or not clearance.valid(self.mono()):
            return self._fail(ex, X.ORDER_REJECTED, "clearance does not cover this plan or has expired", release=True)
        if plan.first.post_only and (plan.quote_expires_utc is None or self.clock() >= plan.quote_expires_utc):
            return self._fail(ex, X.ORDER_REJECTED, "maker quote proof expired or missing", release=True)
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

        # L77 (2026-09-12): 28 of 30 taker first legs missed with the local socket book showing size
        # at the limit. One read of the venue's own book before the send: if it does not offer the
        # plan's size at the plan's limit, nothing is sent and the reservation goes back. No book
        # (the read failed) is not a verdict: the send goes out as before.
        # The two reads are independent, and they run CONCURRENTLY because the clearance is only good
        # for `clearance_ttl_ms` (500 ms) from its mint on the loop, before the worker hop. L77's read
        # alone measured 187.7 ms on the live cover 64d6925e; doing L85's after it would routinely
        # spend the window, the send would come back CLEARANCE_SPENT, and the grid would back the
        # whole game off as though the venue had rejected it -- the check meant to stop bad entries
        # would have stopped all of them. `confirm_budget_ms` records what was left of the window, so
        # this stays measured rather than argued.
        collateral_cap = None
        book = hedge_book = None
        if not plan.first.post_only and self.fresh_book is not None and self.mode.executes:
            def _read(leg, key):
                m = self.mono()
                try:
                    out = self.fresh_book(leg.venue, leg.market_id, leg.side)
                except Exception:  # noqa: BLE001 -- a failed read is not a verdict
                    out = None
                ex.stages[key] = round((self.mono() - m) * 1000.0, 2)
                return out

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                hedge_future = pool.submit(_read, plan.hedge, "b_confirm_ms")
                if plan.first.time_in_force in ("ioc", "fok"):
                    book = _read(plan.first, "a_confirm_ms")
                hedge_book = hedge_future.result()
            ex.stages["confirm_budget_ms"] = round((clearance.expires_mono - self.mono()) * 1000.0, 2)

        if book is not None:
            want = marginal_price(book, plan.first.contracts)
            top = book.asks[0].price if book.asks else None
            ex.protect["first_leg_confirm"] = {"limit": plan.first.limit_price, "marginal": want, "top": top,
                                               "contracts": plan.first.contracts}
            if top is not None and 0 < top < plan.first.limit_price:
                # L83: spend at most contracts x the venue's own ask, whatever the limit allows.
                collateral_cap = round(float(plan.first.contracts) * float(top), 2)
                ex.protect["first_leg_confirm"]["max_collateral_usd"] = collateral_cap
            if want is None or want > plan.first.limit_price + 1e-9:
                return self._fail(ex, X.BOOK_MOVED,
                                  f"first leg: {plan.first.venue} book offers {plan.first.contracts:g} at "
                                  f"{('%.4f' % want) if want is not None else 'no depth'} vs limit {plan.first.limit_price:.4f}; nothing sent",
                                  release=True)

        # L85 (2026-09-12): the same read for the leg we RELY on to get out. L77 confirmed only the
        # price about to be paid, so the lane could commit leg A against a hedge price minutes stale
        # and discover the gap with a position already open -- 64d6925e (ATP, 19:0xZ): planned PM
        # 0.54 / Kalshi 0.41, the Kalshi NO side was at 0.51 when the hedge fired 0.2 s later, the
        # protection layer paid it because a capped loss beats a naked leg, and the cover locked
        # -$2.17 of a $2.50 allowance. The hedge-capacity precheck that would have caught it
        # (`grid._hedge_capacity_ok`) is gated behind post_only, and the maker path is not live.
        #
        # The test is BREAK-EVEN, not the walked limit and not the budget. The walked limit is only
        # the ladder's first rung; the budget is the hurdle, and gating there would refuse covers
        # that still MAKE money -- MORIYA (98376aa2) hedged at 0.04 against a 0.0342 budget and a
        # 0.0442 break-even, a real profit below the hurdle. With no position open yet the only
        # thing worth refusing is a cover we can already see is a LOSS. Above break-even the layer
        # would be buying into the loss cap on purpose, which is what 64d6925e did.
        #
        # It is a VWAP against a VWAP break-even: `marginal_price` is the worst level the walk
        # touches, so comparing it here would refuse an average that is inside break-even. Short
        # depth for the authorized size is also a decline -- a hedge that cannot be filled whole is
        # the naked-residual failure (LAA @ WSH sat 38 min with no depth under the cap). A failed
        # read is not a verdict, exactly as in L77 above.
        if hedge_book is not None:
            paid_est = plan.first.limit_price
            vwap = vwap_for_size(hedge_book, plan.hedge.contracts)
            break_even = plan.hedge_break_even(paid_est)
            ex.protect["hedge_leg_confirm"] = {
                "limit": plan.hedge.limit_price, "vwap": vwap,
                "marginal": marginal_price(hedge_book, plan.hedge.contracts),
                "budget": plan.hedge_budget(paid_est), "break_even": break_even,
                "contracts": plan.hedge.contracts, "first_paid_assumed": paid_est,
                # Stamped so the layer can tell a reading from this entry apart from one left on the
                # row by an earlier entry (the guard's re-run loads it minutes later). Monotonic, so
                # the layer must reject a NEGATIVE age too: a stamp written before a reboot.
                "at_mono": round(self.mono(), 6)}
            if vwap is None or vwap > break_even + 1e-9:
                return self._fail(ex, X.BOOK_MOVED,
                                  f"hedge leg: {plan.hedge.venue} book covers {plan.hedge.contracts:g} at "
                                  f"{('%.4f' % vwap) if vwap is not None else 'no depth'} vs break-even "
                                  f"{break_even:.4f}; nothing sent",
                                  release=True)

        # LEG A: Polymarket, FAK (`ioc` in the internal protocol). Ambiguity here costs nothing;
        # that is why it goes first.
        req_a = self._request(plan, plan.first, plan.first.contracts, plan.first.limit_price, hedge=False,
                              execution_id=ex.execution_id)
        if collateral_cap is not None and not req_a.post_only and req_a.time_in_force in ("ioc", "fok"):
            req_a = replace(req_a, max_collateral_usd=collateral_cap)
        rest_deadline = None
        if req_a.post_only:
            rest_deadline = min(self.mono() + min(2.0, self.leg_a_settle_s),
                                self.mono() + max(0.0, plan.quote_expires_utc - self.clock()))
            clearance.authorize_maker_rest(rest_deadline, now_mono=self.mono())
        if req_a.post_only and hasattr(self.venues[plan.first.venue], "kill"):
            self.venues[plan.first.venue].kill = self.kill
        ex.first_client_id = req_a.client_order_id
        self._move(ex, X.LEG_A_SUBMITTED)
        self._stamp(ex, "a_submit_ms")
        ack = self.venues[plan.first.venue].submit(req_a, clearance)
        self._stamp(ex, "a_ack_ms")
        if req_a.post_only:
            ack = self._settle_maker_ack(plan.first.venue, ack, ex=ex, plan=plan,
                                         clearance=clearance, rest_deadline_mono=rest_deadline,
                                         maker_guard=maker_guard)
        else:
            ack = self._settle_ack(plan.first.venue, ack, deadline_mono=self.mono() + self.leg_a_settle_s, ex=ex, key="a")
        self._stamp(ex, "a_settled_ms")
        if ack.state is FillState.UNCONFIRMED:
            return self._fail(ex, X.UNKNOWN_PROVIDER_STATE, f"leg A unconfirmed: {ack.raw_status} {ack.detail}", release=False)
        if ack.state is FillState.REJECTED:
            return self._fail(ex, X.ORDER_REJECTED, f"leg A rejected: {ack.raw_status} {ack.detail}", release=True)
        if ack.state is FillState.UNFILLED:
            tif = "FAK" if plan.first.time_in_force == "ioc" else plan.first.time_in_force.upper()
            return self._fail(ex, X.ORDER_UNFILLED, f"leg A unfilled ({tif}): no position", release=True)
        ex.first_filled, ex.first_avg_price = ack.filled_contracts, ack.avg_price
        self._check_overfill(ex, req_a, ack)
        self._move_after_fill(ex, X.LEG_A_FILLED if ack.state is FillState.FILLED else X.LEG_A_PARTIAL,
                              detail=f"filled {ack.filled_contracts} @ {ack.avg_price}")
        if ack.state is FillState.PARTIAL:
            self._opp(ex, S.PARTIALLY_FILLED, self.clock())

        if ex.protect.get("maker_delta_unconfirmed"):
            return self._fail(ex, X.UNKNOWN_PROVIDER_STATE,
                              str(ex.protect["maker_delta_unconfirmed"]), release=False)

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
        # L65: the operator accepts only a sub-protection-dust price-improvement residual from a
        # separately pre-authorized $12/10 immediate PM wire.  The actual quantity stays intact.
        con = self.records.store.con
        table = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pm_bounded_taker_orders'").fetchone()
        bounded = con.execute(
            "SELECT max_accepted_excess FROM pm_bounded_taker_orders WHERE client_order_id=?",
            (req.client_order_id,)).fetchone() if table else None
        excess = ack.filled_contracts - req.contracts
        if (bounded is not None and ack.venue == "polymarket" and not req.post_only
                and excess < float(bounded[0]) - 1e-9):
            ex.protect["bounded_taker_residual"] = {
                "client_order_id": req.client_order_id, "contracts": excess,
                "policy": "L65:F20:sub_protection_dust",
            }
            return
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
                 side: str | None = None, execution_id: str = "", client_order_id: str | None = None) -> OrderRequest:
        # Never round a protective buy above the held quantity (10.166667 -> 10.16,
        # not 10.17), or a sell above the held tokens. Precision dust remains visible.
        quantity = float(Decimal(str(contracts)).quantize(Decimal("0.01"), rounding=ROUND_DOWN))
        return OrderRequest(leg.venue, leg.market_id, leg.outcome_id, side or leg.side, round(min(max(limit, 0.01), 0.99), 4),
                            quantity, leg.time_in_force, client_order_id or uuid.uuid4().hex, plan.opportunity_id,
                            hedge=hedge, tick=leg.tick, post_only=leg.post_only and not hedge,
                            entry_expires_utc=plan.quote_expires_utc if leg.post_only and not hedge else None,
                            execution_id=execution_id)

    @staticmethod
    def _newer(known, observed):
        return observed if observed is not None and observed.filled_contracts >= known.filled_contracts else known

    def _hedge_maker_high_water(self, plan, clearance, ex, known) -> None:
        """Protect a socket-confirmed maker delta after cancel dispatch, before slow REST finality."""
        auth = MakerRestAuthorization(
            authorization_id=str(getattr(getattr(clearance, "reservation", None), "reservation_id", "session")),
            maker_client_order_id=str(ex.first_client_id or "maker"),
            authorized_contracts=str(plan.hedge.contracts),
            deadline_mono=float(clearance.maker_rest_deadline_mono or self.mono()),
            hard_hedge_limit=str(plan.hedge.limit_price),
            max_hedge_book_age_s=5.0,
        )
        delta = MakerFillSession(auth, confirmed_fill_high_water=str(ex.first_filled),
                                 hedged_high_water=str(ex.hedge_filled)).observe_fill(
                                     str(known.filled_contracts)).plan_hedge_delta()
        quantity = float(delta.delta_contracts)
        if delta.overfill_contracts:
            ex.protect["maker_overfill_contracts"] = str(delta.overfill_contracts)
        if delta.unhedgeable_dust:
            ex.protect["maker_unhedgeable_dust"] = str(delta.unhedgeable_dust)
        ex.first_filled = max(ex.first_filled, float(known.filled_contracts))
        ex.first_avg_price = known.avg_price or ex.first_avg_price or plan.first.limit_price
        if quantity < 0.01:
            self._sync_after_fill(ex)
            return
        deadline = clearance.arm_hedge(self.mono())
        limit = plan.hedge_limit(ex.first_avg_price)
        target = format(Decimal(str(known.filled_contracts)).normalize(), "f")
        cid = uuid.uuid5(uuid.NAMESPACE_URL, f"janus:{ex.execution_id}:maker-hedge:{target}").hex
        req = self._request(plan, plan.hedge, quantity, limit, hedge=True,
                            execution_id=ex.execution_id, client_order_id=cid)
        ex.hedge_client_ids.append(req.client_order_id)
        # Persist ownership before the venue adapter journals/posts. A crash after the wire must
        # leave the guard an exact execution↔client-id join, never an orphan hedge it might buy again.
        self._sync_after_fill(ex)
        hb = self.venues[plan.hedge.venue].submit(req, clearance)
        hb = self._settle_ack(plan.hedge.venue, hb, deadline_mono=deadline, ex=ex, key="maker_delta")
        self._check_overfill(ex, req, hb)
        ex.protect.setdefault("maker_fill_deltas", []).append({
            "confirmed_high_water": float(known.filled_contracts), "requested": quantity,
            "state": hb.state.value, "filled": hb.filled_contracts, "avg": hb.avg_price,
        })
        if hb.state is FillState.UNCONFIRMED:
            ex.protect["maker_delta_unconfirmed"] = (
                f"maker fill hedge unconfirmed: {req.client_order_id} {hb.raw_status} {hb.detail}")
        elif hb.filled_contracts > 0:
            prev = ex.hedge_filled
            ex.hedge_filled += hb.filled_contracts
            ex.hedge_avg_price = (((ex.hedge_avg_price or 0.0) * prev
                                   + (hb.avg_price or 0.0) * hb.filled_contracts) / ex.hedge_filled)
        self._sync_after_fill(ex)

    def _settle_maker_ack(self, venue, ack, *, ex, plan=None, clearance=None,
                          rest_deadline_mono=None, maker_guard=None):
        """Wait briefly for maker liquidity, then cancel and reconcile; never replace.

        Known quantity is retained on cancel/GET failure and hedged even if the residual
        order is unresolved. That ambiguity latches entry and leaves the durable lock open.
        """
        if ack.state is FillState.REJECTED:
            return ack
        adapter = self.venues[venue]
        wait_until = min(self.mono() + min(2.0, self.leg_a_settle_s),
                         rest_deadline_mono if rest_deadline_mono is not None else self.mono())
        ex.stages["maker_rest_remaining_ms"] = max(0, (wait_until - self.mono()) * 1000)
        known = ack
        polls = 0
        # Only authenticated socket/durable high-water reads occur while resting. A blocking
        # venue GET cannot postpone cancel beyond the immutable deadline.
        while self.mono() < wait_until:
            observe = getattr(adapter, "observed", None)
            if observe is not None:
                try:
                    known = self._newer(known, observe(ack.client_order_id))
                except Exception:
                    pass
            if known.filled_contracts > 0:
                ex.stages["maker_fill_observed_ms"] = round((self.mono() - self._t0.get(ex.execution_id, self.mono())) * 1000, 2)
                break
            if maker_guard is not None:
                try:
                    remaining = max(0.0, float(getattr(plan, "quantity", 0.0)) - known.filled_contracts)
                    try:
                        reason = maker_guard(remaining, timeout_s=max(0.001, wait_until - self.mono()))
                    except TypeError as exc:
                        if "unexpected keyword argument 'timeout_s'" not in str(exc):
                            raise
                        reason = maker_guard(remaining)  # compatibility for pure/test guards
                except Exception as exc:  # noqa: BLE001 -- failed proof means cancel, never a resting order
                    reason = f"MAKER_GUARD_ERROR:{type(exc).__name__}"
                if reason:
                    ex.protect["maker_rest_block"] = reason
                    break
            self.sleep(min(self.poll_interval_s, max(0.0, wait_until - self.mono())))
        # The adapter's finality contract may deliberately require a stable terminal observation
        # window after the venue first reports CANCELED.  That evidence can appear near the end of
        # the ordinary response window.  Budget its declared grace plus one poll here; otherwise
        # the coordinator can latch milliseconds before already-seen terminal proof matures.
        terminal_grace = max(0.0, float(getattr(adapter, "terminal_proof_grace_s", 0.0)))
        deadline = self.mono() + self.leg_a_settle_s + terminal_grace + self.poll_interval_s
        try:
            cancel_only = getattr(adapter, "cancel_only", None)
            canceled = cancel_only(ack.client_order_id) if cancel_only is not None else adapter.cancel(ack.client_order_id)
            if canceled.filled_contracts >= known.filled_contracts:
                known = canceled
            if getattr(canceled, "final", False) and not canceled.open and canceled.filled_contracts >= known.filled_contracts:
                ex.stages["a_poll_count"] = polls
                return known
        except Exception:
            pass  # Known holdings still require protection if cancel cannot be proved.
        if known.filled_contracts > 0 and plan is not None and clearance is not None:
            self._hedge_maker_high_water(plan, clearance, ex, known)
        while self.mono() < deadline:
            if polls:
                self.sleep(min(self.poll_interval_s, max(0, deadline - self.mono())))
            polls += 1
            try:
                st = adapter.status(ack.client_order_id)
            except Exception:
                st = None
            if st is None:
                continue
            if st.filled_contracts >= known.filled_contracts:
                known = st
                if (st.filled_contracts > ex.first_filled and plan is not None and clearance is not None
                        and not ex.protect.get("maker_delta_unconfirmed")):
                    self._hedge_maker_high_water(plan, clearance, ex, known)
            if st.final and not st.open and st.filled_contracts >= known.filled_contracts:
                ex.stages["a_poll_count"] = polls
                return known
        detail = f"post-only cancel/late-fill lifecycle unresolved: {ack.client_order_id}"
        self._quantity_stop = detail
        if self.kill is not None and self.mode.risks_capital:
            try:
                self.kill.latch("live", detail)
            except Exception:
                raise_flag(self.records.store, "POST_ONLY_ROLE_VIOLATION", detail + "; kill latch failed", now=self.clock())
        ex.protect["post_only_unresolved"] = ack.client_order_id
        if known.filled_contracts > 0:
            return known  # Protect actual held quantity, without asserting order finality.
        return replace(known, state=FillState.UNCONFIRMED, detail=detail)

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

    def _storage_failure_after_fill(self, ex: Execution, exc: Exception) -> None:
        """A main execution-row failure must never suppress a known position's protective wire."""
        detail = f"execution persistence failed after confirmed fill: {type(exc).__name__}: {str(exc)[:120]}"
        ex.protect["post_fill_storage_error"] = detail
        self._quantity_stop = detail
        if self.mode.risks_capital and self.kill is not None:
            try:
                self.kill.latch("live", detail)
            except Exception:
                pass

    def _sync_after_fill(self, ex: Execution) -> bool:
        try:
            self._timed(ex, self.records.sync, ex, now=self.clock())
            return True
        except Exception as exc:  # noqa: BLE001 -- protection takes precedence over this audit write
            self._storage_failure_after_fill(ex, exc)
            return False

    def _move_after_fill(self, ex: Execution, to: X, *, detail: str = "") -> bool:
        try:
            self._move(ex, to, detail=detail)
            return True
        except Exception as exc:  # noqa: BLE001 -- keep the in-memory state and protect immediately
            old = ex.state
            ex.history.append((self.clock(), old, to, detail + "; persistence failed"))
            ex.state, ex.detail = to, detail
            self._storage_failure_after_fill(ex, exc)
            return False

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
