#!/usr/bin/env python3
"""The hedge protection layer: once the first leg is filled, the position is never left naked by
choice (2026-09-08).

The rule until now was one IOC at the level the pricer walked, three attempts, three seconds,
then a holding failure: "chasing is HEDGE_SLIPPAGE_EXCEEDED by definition". Sound for paper,
wrong for money: a cover that misses the hurdle by two cents is a small loss, a naked leg is a
coin flip on the whole stake (01:39Z: leg A filled, the hedge never went out, nothing would ever
have hedged it). The layer, inside ONE protect window (`[protect] hedge_protect_window_s`) armed
the instant leg A is known:

  phase 1  the walked limit, as before (max_hedge_submits inside max_hedge_latency_ms);
  phase 2  the CHASE to the BUDGET: a fresh book when the venue gives one, the limit raised to
           the book's marginal price (at least one tick), never above `plan.hedge_budget` --
           still a cover at the hurdle;
  phase 3  the chase on to the LOSS CAP: the price at which the pair locks in exactly the
           allowance (`max_protect_loss_usd` per execution, `max_protect_loss_per_contract_usd`
           per contract, the tighter binds; profit already locked never funds more loss);
  phase 4  the UNWIND (`unwind_enabled`): the naked side sold back, IOC at a floor that keeps the
           loss inside the same allowance (bids below the floor are waited for, never chased);
           an over-hedge sells the surplus on the hedge venue the same way.

What the phases never do: resubmit over an UNCONFIRMED answer (a venue that may hold an order is
UNKNOWN_PROVIDER_STATE, and the operator is paged), chase a venue that REJECTED (a refusal is not
a price problem: straight to the unwind), or exceed the window or `max_protect_submits`. A
position that is still naked at the end is a holding failure AND `on_unprotected` (the lane
latches kill/live and pages): fail closed, the operator's decision.

Every attempt is appended to `Execution.protect["attempts"]` (persisted as protect_json) so each
protective order can be reconciled against the venue by hand.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from kernel.schema import ExecutionState as X, FillState, OpportunityStatus as S
from nodes.execute.plan import marginal_price
from nodes.risk.limits import ProtectLimits


# ── the arithmetic (pure) ─────────────────────────────────────────────────────

def tick_floor(x: float, tick: float) -> float:
    return round(math.floor(x / tick + 1e-9) * tick, 4)


def tick_ceil(x: float, tick: float) -> float:
    return round(math.ceil(x / tick - 1e-9) * tick, 4)


def clamp(p: float) -> float:
    return min(0.99, max(0.01, p))


def loss_allowance(limits: ProtectLimits, remaining_usd: float, qty: float) -> float:
    """The loss per contract the layer may still lock in on `qty` contracts: the per-contract cap
    or what is left of the per-execution cap spread over them, whichever is tighter."""
    if qty <= 1e-9:
        return 0.0
    return max(0.0, min(limits.max_protect_loss_per_contract_usd, remaining_usd / qty))


@dataclass(frozen=True)
class Ceilings:
    walked: float        # the level the pricer walked, less leg A's overpay (plan.hedge_limit)
    budget: float        # the average the hedge may pay for the cover to clear the hurdle
    break_even: float    # 1 - paid - fee: the pair returns exactly nothing
    loss_cap: float      # break_even + L: the pair locks in exactly the allowance


def hedge_ceilings(plan, paid: float, L: float) -> Ceilings:
    tick = plan.hedge.tick or 0.01
    be = round(1.0 - paid - plan.fee_per_contract, 4)
    return Ceilings(walked=plan.hedge_limit(paid), budget=plan.hedge_budget(paid), break_even=be,
                    loss_cap=clamp(tick_floor(be + L, tick)))


def next_hedge_limit(prev: float, tick: float, book, qty: float, ceiling: float) -> float | None:
    """The next IOC limit, never above `ceiling`; None when `prev` already sits at the ceiling. An
    IOC limit is a cap, not a price paid (it fills at the resting levels up to it), so without a
    fresh book the next limit IS the ceiling: one order that takes whatever sits under it, instead
    of a tick-by-tick crawl that spends the submit budget. With a fresh book, the book's marginal
    price for `qty` (at least one tick up), capped."""
    if prev >= ceiling - 1e-9:
        return None
    if book is None:
        return round(ceiling, 4)
    want = marginal_price(book, qty)
    nxt = max(prev + tick, want if want is not None else ceiling)
    return round(min(nxt, ceiling), 4)


def unwind_floor(entry: float, fee_per_contract: float, L: float, tick: float) -> float:
    """The lowest sell price that keeps the loss on a contract bought at `entry` inside L."""
    return clamp(tick_ceil(entry + fee_per_contract - L, tick))


def best_bid(book) -> float | None:
    return book.bids[0].price if (book is not None and book.bids) else None


def projected_pnl_usd(ex, plan) -> float:
    """What the execution has locked in so far, per what is filled: the pairs at the hurdle's
    arithmetic, each unwound contract at its sell less its buy less one side's fee. The naked
    remainder counts nothing (its outcome is unknown, which is the point of protecting it)."""
    paid = ex.first_avg_price or plan.first.limit_price
    hedge_avg = ex.hedge_avg_price or 0.0
    fee = plan.fee_per_contract
    pairs = min(ex.net_first, ex.net_hedge)
    pnl = pairs * (1.0 - paid - hedge_avg - fee)
    if ex.first_unwound > 1e-9 and ex.first_unwind_avg is not None:
        pnl += ex.first_unwound * (ex.first_unwind_avg - paid - fee / 2.0)
    if ex.hedge_unwound > 1e-9 and ex.hedge_unwind_avg is not None:
        pnl += ex.hedge_unwound * (ex.hedge_unwind_avg - hedge_avg - fee / 2.0)
    return round(pnl, 6)


def remaining_loss_usd(ex, plan, limits: ProtectLimits) -> float:
    """The per-execution cap less the loss already locked in. Profit never funds more loss."""
    return max(0.0, limits.max_protect_loss_usd - max(0.0, -projected_pnl_usd(ex, plan)))


# ── the routine ───────────────────────────────────────────────────────────────

def protect(co, ex, plan, clearance, *, limits: ProtectLimits | None = None, fresh_book=None, on_unprotected=None):
    """Hedge, chase, unwind, or fail closed. `co` is the Coordinator (its records, venues, clocks
    and stage helpers are reused); returns the Execution in its end state."""
    lim = limits or ProtectLimits()
    venues, hedge = co.venues, plan.hedge
    paid = ex.first_avg_price or plan.first.limit_price
    tick = hedge.tick or 0.01
    dust = lim.protect_dust_contracts
    now = co.mono()
    # ONE window, the clearance's, armed now that the position exists.
    deadline = clearance.arm_hedge(now) if hasattr(clearance, "arm_hedge") else now + co.hedge_deadline_s
    t_hedge = now + co.hedge_deadline_s
    t_unwind = deadline - lim.unwind_reserve_s if lim.unwind_enabled else deadline
    ex.protect.setdefault("attempts", [])
    ex.protect.update({"loss_cap_usd": lim.max_protect_loss_usd, "window_s": round(deadline - now, 3),
                       "unwind_enabled": lim.unwind_enabled})
    budget = plan.hedge_budget(paid)
    limit = max(plan.hedge_limit(paid), 0.01)
    attempts = phase1 = 0
    rejected = None
    #: Submits kept for the unwind so the chase can never starve it (phases 2-3 get the rest).
    chase_cap = lim.max_protect_submits - (3 if lim.unwind_enabled else 0)

    def log(**kw):
        ex.protect["attempts"].append({"t": round(co.mono() - now, 3), **kw})

    def fail_unprotected(state, text):
        co._stamp(ex, "done_ms")
        co._fail(ex, state, text, release=False)
        if on_unprotected is not None:
            try:
                on_unprotected(ex, text)
            except Exception as exc:  # noqa: BLE001 -- the page must not hide the record
                print(f"  [protect] on_unprotected failed: {type(exc).__name__}: {exc}", flush=True)
        return ex

    # ── phases 1-3: the hedge, then the chase ────────────────────────────
    for phase in ("walked", "budget", "loss_cap"):
        phase_attempts = 0
        while ex.unhedged > dust and attempts < chase_cap and rejected is None:
            t = co.mono()
            if phase == "walked":
                if t >= t_hedge or phase1 >= clearance.max_hedge_submits:
                    break
                ceiling = limit
            else:
                if t >= t_unwind:
                    break
                L = loss_allowance(lim, remaining_loss_usd(ex, plan, lim), ex.unhedged)
                c = hedge_ceilings(plan, paid, L)
                ceiling = max(limit, c.budget) if phase == "budget" else max(limit, c.loss_cap)
                book = fresh_book(hedge.venue, hedge.market_id, hedge.side) if fresh_book is not None else None
                nxt = next_hedge_limit(limit, tick, book, ex.unhedged, ceiling)
                if nxt is None:
                    # at this phase's ceiling already: one more try there (the book may have refilled
                    # in the resubmit wait), then the next phase, or the unwind
                    if phase_attempts >= 2 or limit < ceiling - 1e-9:
                        break
                    nxt = round(ceiling, 4)
                limit = nxt
            phase_attempts += 1
            attempts += 1
            phase1 += int(phase == "walked")
            req = co._request(plan, hedge, ex.unhedged, max(limit, 0.01), hedge=True)
            ex.hedge_client_ids.append(req.client_order_id)
            co._move(ex, X.LEG_B_SUBMITTED, detail=f"attempt {attempts} limit {limit:.4f} budget {budget:.4f}"
                                                   + ("" if phase == "walked" else f" phase {phase} ceiling {ceiling:.4f}"))
            co._stamp(ex, "b_submit_ms")
            hb = venues[hedge.venue].submit(req, clearance)
            co._stamp(ex, "b_ack_ms")
            hb = co._settle_ack(hedge.venue, hb, deadline_mono=deadline, ex=ex, key="b")
            co._stamp(ex, "b_settled_ms")
            ex.stages["b_attempts"] = attempts
            log(kind="hedge", phase=phase, limit=limit, ceiling=round(ceiling, 4), qty=round(ex.unhedged, 4),
                state=hb.state.value, filled=hb.filled_contracts, avg=hb.avg_price)
            if hb.state is FillState.UNCONFIRMED:
                return fail_unprotected(X.UNKNOWN_PROVIDER_STATE, f"hedge unconfirmed: {hb.detail}")
            if hb.state is FillState.REJECTED:
                rejected = f"{hb.raw_status} {hb.detail}"
                break
            if hb.filled_contracts > 0:
                prev = ex.hedge_filled
                ex.hedge_filled += hb.filled_contracts
                ex.hedge_avg_price = ((prev * (ex.hedge_avg_price or 0.0)) + hb.filled_contracts * (hb.avg_price or 0.0)) / ex.hedge_filled
                co._move(ex, X.LEG_B_FILLED if ex.unhedged <= dust else X.LEG_B_PARTIAL,
                         detail=f"hedge filled {hb.filled_contracts} @ {hb.avg_price}")
            elif hb.state is FillState.UNFILLED:
                co._timed(ex, co.records.sync, ex, now=co.clock())
                co.sleep(co.poll_interval_s if phase == "walked" else lim.protect_resubmit_ms / 1000.0)
        if ex.unhedged <= dust or rejected is not None:
            break

    if ex.unhedged <= dust and ex.overhedged <= dust:
        return _hedged(co, ex, plan, paid, budget)

    # ── phase 4: the unwind ───────────────────────────────────────────────
    if lim.unwind_enabled:
        while (ex.unhedged > dust or ex.overhedged > dust) and co.mono() < deadline and attempts < lim.max_protect_submits:
            if ex.unhedged > dust:
                leg, qty, entry, which = plan.first, ex.unhedged, paid, "first"
            else:
                leg, qty, entry, which = hedge, ex.overhedged, (ex.hedge_avg_price or hedge.limit_price), "hedge"
            side = "sell_yes" if leg.side == "buy_yes" else "sell_no"
            L = loss_allowance(lim, remaining_loss_usd(ex, plan, lim), qty)
            floor = unwind_floor(entry, plan.fee_per_contract / 2.0, L, leg.tick or 0.01)
            book = fresh_book(leg.venue, leg.market_id, side) if fresh_book is not None else None
            bb = best_bid(book)
            if bb is not None and bb < floor - 1e-9:
                log(kind="unwind_wait", leg=which, floor=floor, best_bid=bb, qty=round(qty, 4))
                co.sleep(lim.protect_resubmit_ms / 1000.0)
                continue                                      # the book is below the floor: wait, never chase down
            attempts += 1
            req = co._request(plan, leg, qty, floor, hedge=True, side=side)
            ex.unwind_client_ids.append(req.client_order_id)
            co._move(ex, X.UNWIND_SUBMITTED, detail=f"sell {qty:g} {which} floor {floor:.4f} L={L:.4f} attempt {attempts}")
            co._stamp(ex, "u_submit_ms")
            ack = venues[leg.venue].submit(req, clearance)
            hb = co._settle_ack(leg.venue, ack, deadline_mono=deadline, ex=ex, key="u")
            co._stamp(ex, "u_settled_ms")
            log(kind="unwind", leg=which, floor=floor, best_bid=bb, qty=round(qty, 4), state=hb.state.value,
                filled=hb.filled_contracts, avg=hb.avg_price)
            if hb.state is FillState.UNCONFIRMED:
                return fail_unprotected(X.UNKNOWN_PROVIDER_STATE, f"unwind unconfirmed: {hb.detail}")
            if hb.filled_contracts > 0:
                if which == "first":
                    prev = ex.first_unwound
                    ex.first_unwound += hb.filled_contracts
                    ex.first_unwind_avg = ((prev * (ex.first_unwind_avg or 0.0)) + hb.filled_contracts * (hb.avg_price or 0.0)) / ex.first_unwound
                else:
                    prev = ex.hedge_unwound
                    ex.hedge_unwound += hb.filled_contracts
                    ex.hedge_unwind_avg = ((prev * (ex.hedge_unwind_avg or 0.0)) + hb.filled_contracts * (hb.avg_price or 0.0)) / ex.hedge_unwound
                co._timed(ex, co.records.sync, ex, now=co.clock())
            else:
                co.sleep(lim.protect_resubmit_ms / 1000.0)

    if ex.unhedged <= dust and ex.overhedged <= dust:
        if not ex.holds_anything:
            realized = projected_pnl_usd(ex, plan)
            co._stamp(ex, "done_ms")
            co._timed(ex, co.records.write_unwind_settlement, ex, realized_usd=realized, legs=list(ex.protect["attempts"]), now=co.clock())
            ex.released = True
            co._move(ex, X.UNWOUND, detail=f"UNWOUND: {ex.first_unwound:g} first @ {ex.first_unwind_avg} "
                                           f"{ex.hedge_unwound:g} hedge @ {ex.hedge_unwind_avg}; realized {realized:+.4f} USD"
                                           + (f"; hedge rejected: {rejected}" if rejected else ""))
            co._opp(ex, S.FAILED_HEDGE, co.clock())
            co._opp(ex, S.SETTLED, co.clock())
            return ex
        return _hedged(co, ex, plan, paid, budget, protected=True)

    left = f"{ex.unhedged:g} unhedged" if ex.unhedged > dust else f"{ex.overhedged:g} over-hedged"
    if rejected is not None and ex.hedge_filled <= 0:
        reason, why = X.HEDGE_UNAVAILABLE, f"hedge rejected: {rejected}"
    elif ex.hedge_filled <= 0:
        reason, why = X.HEDGE_SLIPPAGE_EXCEEDED, "no hedge inside the loss cap"
    else:
        reason, why = X.PARTIAL_FILL, "hedged in part, the rest not inside the loss cap"
    text = f"UNPROTECTED: {left} after {attempts} attempts; {why}" + ("" if lim.unwind_enabled else "; unwind disabled")
    return fail_unprotected(reason, text)


def _hedged(co, ex, plan, paid: float, budget: float, *, protected: bool = False):
    be = round(1.0 - paid - plan.fee_per_contract, 4)
    avg = ex.hedge_avg_price or 0.0
    label = ""
    if avg > be + 1e-9:
        label = f" ABOVE_BREAK_EVEN {be:.4f}: a locked loss inside the cap, still a cover"
    elif avg > budget + 1e-9:
        label = f" ABOVE_BUDGET {budget:.4f}: below the hurdle, still a cover"
    detail = f"{ex.hedge_filled} hedged @ {ex.hedge_avg_price}" + label
    if protected:
        detail = (f"PROTECTED: {min(ex.net_first, ex.net_hedge):g} pairs kept, {ex.first_unwound:g} first sold @ {ex.first_unwind_avg}, "
                  f"{ex.hedge_unwound:g} hedge sold @ {ex.hedge_unwind_avg}; " + detail)
        realized = projected_pnl_usd(ex, plan)
        co._timed(ex, co.records.write_unwind_settlement, ex, realized_usd=realized, legs=list(ex.protect["attempts"]), now=co.clock())
    co._stamp(ex, "done_ms")
    co._move(ex, X.HEDGED, detail=detail)
    co._opp(ex, S.HEDGED, co.clock())
    return ex
