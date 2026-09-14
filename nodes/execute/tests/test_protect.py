"""The hedge protection layer (2026-09-08), one rule per test, on paper venues."""
from __future__ import annotations

from dataclasses import replace

import pytest

from kernel.schema import Book, ExecutionState as X, FillState, Quote
from nodes.execute.protect import (hedge_ceilings, loss_allowance, next_hedge_limit, projected_pnl_usd, tick_floor,
                                   remaining_loss_usd, unwind_floor)
from nodes.execute.records import Execution
from nodes.execute.tests.test_coordinator import T, bk, clearance_for, harness, offers, plan_for
from nodes.risk.limits import ProtectLimits


def book2(bids, asks):
    return Book(bids=tuple(Quote(p, s) for p, s in bids), asks=tuple(Quote(p, s) for p, s in asks), fetched_utc=T)


def hedge_book_that_moves(vs, hedge_venue, at_entry):
    """A `fresh_book` that answers L85's pre-send hedge read with `at_entry` and every later read
    with the venue's own book.

    L85 declines an entry whose hedge is already above break-even, so a layer test that wants a
    position facing a hedge it cannot afford has to move the book the way the venue does: priced
    and admitted at one level, walked away from in the 0.2-1 s before the hedge fires. The ladder
    and the unwind still see the venue's book, so what those tests pin is unchanged.
    """
    seen = []

    def fresh(venue, market, side):
        if venue == hedge_venue and not seen:
            seen.append(True)
            return at_entry
        return vs[venue].orderbook(market, side)
    return fresh


def test_the_arithmetic():
    lim = ProtectLimits()
    assert loss_allowance(lim, 1.0, 10.0) == 0.10 and loss_allowance(lim, 0.30, 10.0) == pytest.approx(0.03)
    assert loss_allowance(lim, 1.0, 100.0) == 0.01 and loss_allowance(lim, 0.0, 5.0) == 0.0 and loss_allowance(lim, 1.0, 0.0) == 0.0
    offs = offers()
    p, _ = plan_for(offs)
    c = hedge_ceilings(p, 0.45, 0.01)
    assert c.walked == tick_floor(p.hedge_limit(0.45), p.hedge.tick)
    assert c.budget == tick_floor(p.hedge_budget(0.45), p.hedge.tick)
    assert c.break_even == pytest.approx(p.hedge_break_even(0.45)) and c.loss_cap == pytest.approx(round(c.break_even + 0.01, 2), abs=0.0101)
    assert c.walked < c.budget < c.break_even < c.loss_cap
    # the next limit: one tick up, or the fresh book's marginal price, never past the ceiling
    assert next_hedge_limit(0.44, 0.01, None, 10, 0.50) == 0.50, "no fresh book: the ceiling at once (an IOC limit is a cap)"
    assert next_hedge_limit(0.44, 0.01, book2([], [(0.47, 5), (0.48, 20)]), 10, 0.50) == 0.48
    assert next_hedge_limit(0.44, 0.01, book2([], [(0.60, 50)]), 10, 0.50) == 0.50
    assert next_hedge_limit(0.50, 0.01, None, 10, 0.50) is None
    assert next_hedge_limit(0.32, 0.01, None, 10, 0.3272) is None, "a continuous budget is floored to the valid buy tick"
    # the unwind floor: sell at no worse than entry + one side's fee - L
    assert unwind_floor(0.57, 0.01, 0.10, 0.01) == 0.48 and unwind_floor(0.57, 0.01, 0.0, 0.01) == 0.58
    ex = Execution("e", "o", "ev", "mlb", "PAPER_EXECUTION", 10.0, T, first_filled=10.0, first_avg_price=0.57,
                   first_unwound=10.0, first_unwind_avg=0.55)
    assert projected_pnl_usd(ex, p) == pytest.approx(10 * (0.55 - 0.57 - p.fee_per_contract / 2))
    assert remaining_loss_usd(ex, p, lim) == pytest.approx(max(0.0, lim.max_protect_loss_usd - 10 * (0.02 + p.fee_per_contract / 2)))


def test_a_book_one_tick_above_the_walked_limit_fills_on_the_chase_inside_the_budget(tmp_path):
    co, vs, store, clk, _ = harness(tmp_path)
    offs = offers()
    p, _ = plan_for(offs)
    vs["polymarket"].books = {"P_H": offs["home"][0].book}
    vs["kalshi"].books = {"K_A": bk([(0.46, 5000)])}                  # two ticks above 0.44, under the budget
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.HEDGED and ex.hedge_avg_price == pytest.approx(0.46)
    assert "ABOVE_BUDGET" not in ex.detail and "ABOVE_BREAK_EVEN" not in ex.detail
    phases = [a["phase"] for a in ex.protect["attempts"]]
    assert phases[-1] == "budget" and phases.count("walked") == 3


def test_a_fresh_book_jumps_the_limit_to_its_marginal_price(tmp_path):
    co, vs, store, clk, _ = harness(tmp_path)
    offs = offers()
    p, _ = plan_for(offs)
    vs["polymarket"].books = {"P_H": offs["home"][0].book}
    vs["kalshi"].books = {"K_A": bk([(0.47, 5000)])}
    co.fresh_book = lambda venue, market, side: vs[venue].orderbook(market, side)
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.HEDGED
    chase = [a for a in ex.protect["attempts"] if a["phase"] != "walked"]
    assert len(chase) == 1 and chase[0]["limit"] == 0.47, "one chase attempt straight at the book, not three ticks"


def test_an_off_tick_budget_is_floored_and_the_valid_loss_cap_phase_still_hedges(tmp_path):
    """Exact regression for F12 ARI-KC: 32.72c is an economic ceiling, not a valid Kalshi
    price.  The budget retry stays at 32c and the next phase may take 33c inside the unchanged
    loss allowance; no invalid-price rejection can strand the first leg."""
    co, vs, _, _, _ = harness(tmp_path)
    p0, _ = plan_for(offers(), q=10.0)
    p = replace(p0,
                quantity=10.0,
                first=replace(p0.first, limit_price=0.63, vwap=0.63, contracts=10.0),
                hedge=replace(p0.hedge, limit_price=0.32, vwap=0.32, contracts=10.0, tick=0.01),
                max_cost_per_contract=0.9900990099009901,
                fee_per_contract=0.026895,
                settlement_buffer_per_contract=0.00600012)
    vs["polymarket"].books = {"P_H": bk([(0.63, 10)])}
    vs["kalshi"].books = {"K_A": bk([(0.33, 10)])}
    co.fresh_book = lambda venue, market, side: vs[venue].orderbook(market, side)
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.HEDGED and ex.hedge_avg_price == pytest.approx(0.33)
    hedge_attempts = [a for a in ex.protect["attempts"] if a["kind"] == "hedge"]
    assert {a["limit"] for a in hedge_attempts} <= {0.32, 0.33}
    assert hedge_attempts[-1]["phase"] == "loss_cap" and hedge_attempts[-1]["state"] == "FILLED"


def test_cap_reached_with_the_unwind_on_sells_leg_a_back_inside_the_cap(tmp_path):
    co, vs, store, clk, opps = harness(tmp_path)
    # the harness trades 100 contracts; the pilot's $1 cap is 1c a contract there, so the cap is
    # scaled to the fixture (10c a contract, the pilot's per-contract figure at its 10-contract size)
    co.limits = ProtectLimits(unwind_enabled=True, max_protect_loss_usd=10.0)
    offs = offers()
    p, _ = plan_for(offs)
    pm_book = book2([(0.44, 5000), (0.43, 5000)], [(0.44, 5000)])     # bids one tick under what leg A paid (0.45)
    vs["polymarket"].books = {"P_H": pm_book, ("P_H", "sell_yes"): pm_book}
    vs["kalshi"].books = {"K_A": bk([(0.70, 5000)])}                  # the hedge is never had
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.UNWOUND and ex.released and ex.first_unwound == 100.0 and ex.first_unwind_avg == pytest.approx(0.44)
    assert not ex.holds_anything and ex.unhedged == 0.0
    row = store.con.execute("SELECT kind, realized_usd, released FROM execution_settlements WHERE execution_id=?", (ex.execution_id,)).fetchone()
    assert row[0] == "UNWOUND" and row[2] == 1 and -10.0 - 1e-6 <= row[1] < 0, "a small locked loss, inside the cap"
    floors = [a["floor"] for a in ex.protect["attempts"] if a["kind"] == "unwind"]
    assert floors and floors[0] <= 0.44, "the floor the cap allows admits the 0.44 bid"
    kinds = [a["kind"] for a in ex.protect["attempts"]]
    assert "unwind" in kinds and kinds.index("unwind") > kinds.index("hedge")
    st = store.con.execute("SELECT state, released FROM executions WHERE execution_id=?", (ex.execution_id,)).fetchone()
    assert st == ("UNWOUND", 1)


def test_a_database_failure_after_an_unwind_fill_cannot_abort_the_terminal_protection_path(tmp_path):
    co, vs, store, clk, _ = harness(tmp_path)
    co.limits = ProtectLimits(unwind_enabled=True, max_protect_loss_usd=10.0)
    offs = offers()
    p, _ = plan_for(offs)
    pm_book = book2([(0.44, 5000)], [(0.44, 5000)])
    vs["polymarket"].books = {"P_H": pm_book, ("P_H", "sell_yes"): pm_book}
    vs["kalshi"].books = {"K_A": bk([(0.70, 5000)])}
    real_sync = co.records.sync
    failed = []

    def fail_once_after_unwind(ex, **kw):
        if ex.first_unwound > 0 and not failed:
            failed.append(ex.execution_id)
            raise OSError("terminal unwind sync unavailable")
        return real_sync(ex, **kw)

    co.records.sync = fail_once_after_unwind
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert failed == [ex.execution_id]
    assert ex.state is X.UNWOUND and ex.released and not ex.holds_anything
    assert "OSError" in ex.protect["post_fill_storage_error"]
    assert "OSError" in co._quantity_stop


def test_bids_below_the_floor_are_waited_for_and_an_unsold_position_is_held_and_paged(tmp_path):
    co, vs, store, clk, _ = harness(tmp_path)
    co.limits = ProtectLimits(unwind_enabled=True)
    paged = []
    co.on_unprotected = lambda ex, text: paged.append(text)
    offs = offers()
    p, _ = plan_for(offs)
    pm_book = book2([(0.20, 5000)], [(0.44, 5000)])                  # bids far below any floor the cap allows
    vs["polymarket"].books = {"P_H": pm_book, ("P_H", "sell_yes"): pm_book}
    vs["kalshi"].books = {"K_A": bk([(0.70, 5000)])}
    # Admitted at the planned hedge price; the hedge side is 0.70 by the time the layer gets there.
    co.fresh_book = hedge_book_that_moves(vs, "kalshi", bk([(p.hedge.limit_price, 5000)]))
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.HEDGE_SLIPPAGE_EXCEEDED and not ex.released and ex.unhedged == 100.0 and ex.first_unwound == 0.0
    assert any(a["kind"] == "unwind_wait" for a in ex.protect["attempts"]), "the floor held; no sale below it"
    assert store.con.execute("SELECT COUNT(*) FROM orders WHERE side='sell_yes'").fetchone()[0] == 0
    assert paged and "UNPROTECTED" in paged[0]


def test_a_terminal_database_failure_cannot_suppress_the_unprotected_page(tmp_path):
    co, vs, store, clk, _ = harness(tmp_path)
    co.limits = ProtectLimits(unwind_enabled=False)
    paged = []
    co.on_unprotected = lambda ex, text: paged.append(text)
    offs = offers()
    p, _ = plan_for(offs)
    vs["polymarket"].books = {"P_H": offs["home"][0].book}
    vs["kalshi"].books = {"K_A": bk([(0.70, 5000)])}
    real_move = co.records.move

    def fail_terminal_move(ex, to, **kw):
        if to is X.HEDGE_SLIPPAGE_EXCEEDED:
            raise OSError("terminal execution row unavailable")
        return real_move(ex, to, **kw)

    co.records.move = fail_terminal_move
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.HEDGE_SLIPPAGE_EXCEEDED and not ex.released
    assert paged and "UNPROTECTED" in paged[0]
    assert "OSError" in ex.protect["post_fill_storage_error"]
    assert "OSError" in co._quantity_stop


def test_an_unconfirmed_hedge_is_unknown_provider_state_and_paged_never_resubmitted(tmp_path):
    from types import SimpleNamespace
    from kernel.execution_protocol import Ack, OrderState
    co, vs, store, clk, _ = harness(tmp_path)
    paged = []
    co.on_unprotected = lambda ex, text: paged.append(text)
    offs = offers()
    p, _ = plan_for(offs)
    vs["polymarket"].books = {"P_H": offs["home"][0].book}
    real_k = vs["kalshi"]
    submits = []

    class Ambiguous:
        venue, mode, journal, books = "kalshi", real_k.mode, real_k.journal, {}
        def submit(self, req, clearance):
            submits.append(req.client_order_id)
            real_k.journal.pending(req, mode=real_k.mode.value, now=T)
            return Ack("kalshi", req.client_order_id, None, FillState.UNCONFIRMED, 0.0, None, None, "TRANSPORT", T)
        def status(self, cid):
            return OrderState("kalshi", cid, None, FillState.UNCONFIRMED, 0.0, None, None, "NOT_FOUND", T)
        def cancel(self, cid): raise AssertionError("never")
    vs["kalshi"] = Ambiguous()
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.UNKNOWN_PROVIDER_STATE and not ex.released and len(submits) == 1
    assert paged and "hedge unconfirmed" in paged[0]


def test_a_rejected_hedge_goes_straight_to_the_unwind(tmp_path):
    from kernel.execution_protocol import Ack
    co, vs, store, clk, _ = harness(tmp_path)
    co.limits = ProtectLimits(unwind_enabled=True)
    offs = offers()
    p, _ = plan_for(offs)
    pm_book = book2([(0.45, 5000)], [(0.44, 5000)])
    vs["polymarket"].books = {"P_H": pm_book, ("P_H", "sell_yes"): pm_book}
    real_k = vs["kalshi"]

    class Refusing:
        venue, mode, journal, books = "kalshi", real_k.mode, real_k.journal, {}
        n = 0
        def submit(self, req, clearance):
            self.n += 1
            real_k.journal.pending(req, mode=real_k.mode.value, now=T)
            return Ack("kalshi", req.client_order_id, None, FillState.REJECTED, 0.0, None, None, "market_closed", T, detail="closed")
        def status(self, cid): raise AssertionError("never")
        def cancel(self, cid): raise AssertionError("never")
    vs["kalshi"] = Refusing()
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert vs["kalshi"].n == 1, "a refusal is not chased"
    assert ex.state is X.UNWOUND and ex.first_unwound == 100.0 and "hedge rejected" in ex.detail


def test_unwind_off_holds_and_pages_and_dust_is_a_cover(tmp_path):
    co, vs, store, clk, _ = harness(tmp_path)
    paged = []
    co.on_unprotected = lambda ex, text: paged.append(text)
    co.limits = ProtectLimits(unwind_enabled=False, protect_dust_contracts=1.0)
    offs = offers()
    p, _ = plan_for(offs)
    vs["polymarket"].books = {"P_H": offs["home"][0].book}
    vs["kalshi"].books = {"K_A": bk([(0.44, 99.5), (0.90, 5000)])}   # half a contract short: dust
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.HEDGED and ex.unhedged == pytest.approx(0.5) and not paged, "a remainder under the venue minimum is recorded, not chased"


def _rerun(tmp_path, *, at_mono, first_filled=100.0, marginal=0.46):
    """A guard re-run on a row carrying an L85 entry reading: the hedge book has moved to 0.46, and
    `hedge_leg_confirm` says so. Returns the hedge attempts the layer made."""
    from kernel.schema import Mode
    from nodes.risk.clearance import clear_protect
    from nodes.risk.kill import KillSwitches
    from nodes.risk.limits import load_limits
    co, vs, store, clk, opps = harness(tmp_path)
    offs = offers()
    p, _ = plan_for(offs)
    vs["kalshi"].books = {"K_A": bk([(marginal, 5000)])}
    ex = Execution("rerun01", p.opportunity_id, p.event_id, "mlb", "PAPER_EXECUTION", 100.0, T,
                   first_filled=first_filled, first_avg_price=0.45, state=X.UNKNOWN_PROVIDER_STATE)
    ex.protect["hedge_leg_confirm"] = {"marginal": marginal, "at_mono": at_mono,
                                       "contracts": p.hedge.contracts, "vwap": marginal}
    co.records.start(ex, plan={"first": p.first.__dict__, "hedge": p.hedge.__dict__,
                               "max_cost": p.max_cost_per_contract, "fee": p.fee_per_contract}, books={})
    co.records.sync(ex, now=T)
    out = co.protect_existing(co.records.load("rerun01"), co.records.plan_of("rerun01"),
                              clear_protect(opportunity_id=p.opportunity_id, event_id=p.event_id,
                                            venues=("kalshi", "polymarket"), mode=Mode.PAPER_EXECUTION,
                                            limits=load_limits(),
                                            kill=KillSwitches(tmp_path / "kill", enforce_volume=False),
                                            now_mono=100.0))
    return [a for a in out.protect["attempts"] if a["kind"] == "hedge"]


def test_a_reading_stamped_before_a_reboot_never_skips_a_walked_send(tmp_path):
    """`at_mono` is a monotonic stamp persisted into protect_json. After a reboot monotonic restarts
    near zero, so a stamp from before it is in the FUTURE and the age is negative -- which an upper
    bound alone would accept. maker.py:258 rejects a negative book age for the same reason."""
    hedge = _rerun(tmp_path, at_mono=1e9)          # written "before the reboot": age is negative
    assert hedge and hedge[0]["state"] != "SKIPPED", "a negative age is not freshness"
    assert hedge[0]["phase"] == "walked"


def test_a_reading_from_this_entry_does_skip_the_walked_send(tmp_path):
    """The control for the two rejections above: a fresh, full-size reading still skips."""
    hedge = _rerun(tmp_path / "b", at_mono=100.0)  # the clearance's now_mono; age 0
    assert hedge and hedge[0]["state"] == "SKIPPED" and hedge[0]["skip"] == "entry_book_above_walked"


def test_a_partial_first_leg_never_skips_on_a_reading_taken_for_the_full_size(tmp_path):
    """The entry read walked the book for the FULL planned hedge size. A padded FAK partially
    filling is the expected case (plan.py), and the book may cover what is left at the walked price
    even though it could not cover the whole plan -- so that reading does not describe this send."""
    hedge = _rerun(tmp_path, at_mono=100.0, first_filled=40.0)
    assert hedge and hedge[0]["state"] != "SKIPPED", "the reading was for 100, this send is for 40"


def test_a_hedge_fill_with_no_reported_average_is_booked_at_the_limit_not_at_zero(tmp_path):
    """L91: the Kalshi adapter can report filled > 0 with `avg_price` None (no
    `average_fill_price`) or 0.0 (a missing cost field). Booking that at zero makes
    `projected_pnl_usd` show a large fictitious profit, so `remaining_loss_usd` hands back the FULL
    per-execution allowance however much the chase has already lost, and the loss-cap phase
    re-authorises a fresh ceiling on the rest. The IOC limit is the worst the attempt could have
    paid, so it is the honest fallback."""
    from kernel.execution_protocol import Ack
    co, vs, store, clk, _ = harness(tmp_path)
    offs = offers()
    p, _ = plan_for(offs)
    vs["polymarket"].books = {"P_H": offs["home"][0].book}
    real_k = vs["kalshi"]

    class NoAverage:
        venue, mode, journal, books = "kalshi", real_k.mode, real_k.journal, {}

        def submit(self, req, clearance):
            real_k.journal.pending(req, mode=real_k.mode.value, now=T)
            return Ack(self.venue, req.client_order_id, "k1", FillState.FILLED,
                       req.contracts, None, 0.0, "filled", T, detail="no average reported")

        def status(self, cid):
            raise AssertionError("a FILLED ack is terminal; nothing should poll")

    vs["kalshi"] = NoAverage()
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.HEDGED and ex.hedge_filled == 100.0
    assert ex.hedge_avg_price == pytest.approx(p.hedge_limit(ex.first_avg_price)), "the limit, not 0.0"
    assert ex.hedge_avg_price > 0.0


def test_the_guard_s_rerun_protects_from_the_row(tmp_path):
    """The execution the guard corrected (leg A filled, nothing hedged) is loaded from its row and
    protected under a clear_protect clearance: the hedge is sent, the record moves to HEDGED."""
    from kernel.schema import Mode
    from nodes.risk.clearance import clear_protect
    from nodes.risk.kill import KillSwitches
    from nodes.risk.limits import load_limits
    co, vs, store, clk, opps = harness(tmp_path)
    offs = offers()
    p, _ = plan_for(offs)
    vs["kalshi"].books = {"K_A": bk([(0.44, 5000)])}
    ex = Execution("rerun01", p.opportunity_id, p.event_id, "mlb", "PAPER_EXECUTION", 100.0, T, first_filled=100.0,
                   first_avg_price=0.45, state=X.UNKNOWN_PROVIDER_STATE)
    co.records.start(ex, plan={"first": p.first.__dict__, "hedge": p.hedge.__dict__, "max_cost": p.max_cost_per_contract, "fee": p.fee_per_contract}, books={})
    co.records.sync(ex, now=T)
    plan = co.records.plan_of("rerun01")
    c = clear_protect(opportunity_id=p.opportunity_id, event_id=p.event_id, venues=("kalshi", "polymarket"), mode=Mode.PAPER_EXECUTION,
                      limits=load_limits(), kill=KillSwitches(tmp_path / "kill", enforce_volume=False), now_mono=100.0)
    out = co.protect_existing(co.records.load("rerun01"), plan, c)
    assert out.state is X.HEDGED and out.hedge_filled == 100.0 and out.stages["guard_rerun"] == 1
    assert store.con.execute("SELECT state, hedge_filled FROM executions WHERE execution_id='rerun01'").fetchone() == ("HEDGED", 100.0)


def _sekulic_like(p0):
    """The 73688bf3 plan: PM 0.801 first, Kalshi walked 0.16, budget 0.1622 (floors to 0.16),
    break-even 0.1722, loss cap 0.27 at 10 contracts under the $1 allowance."""
    return replace(p0, quantity=10.0,
                   first=replace(p0.first, limit_price=0.802, vwap=0.801, contracts=10.0),
                   hedge=replace(p0.hedge, limit_price=0.16, vwap=0.16, contracts=10.0, tick=0.01),
                   max_cost_per_contract=0.99, fee_per_contract=0.01738, settlement_buffer_per_contract=0.009437)


def test_a_zero_fill_at_a_walked_price_the_book_has_left_advances_the_phase_after_one_send(tmp_path):
    """L75: with a fresh book whose marginal price is above the walked ceiling, the walked phase
    hands over after its first zero fill instead of re-sending the same price three times."""
    co, vs, store, clk, _ = harness(tmp_path)
    offs = offers()
    p, _ = plan_for(offs)
    vs["polymarket"].books = {"P_H": offs["home"][0].book}
    vs["kalshi"].books = {"K_A": bk([(0.46, 5000)])}
    # At entry the hedge was there at the planned price, so L85 does not skip; it moves to 0.46
    # while leg A is acking, which is the zero fill L75 is about.
    co.fresh_book = hedge_book_that_moves(vs, "kalshi", bk([(p.hedge.limit_price, 5000)]))
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.HEDGED and ex.hedge_avg_price == pytest.approx(0.46)
    hedge = [a for a in ex.protect["attempts"] if a["kind"] == "hedge"]
    assert [a["phase"] for a in hedge] == ["walked", "budget"], "one walked send, then the chase"
    assert hedge[0]["state"] == "UNFILLED" and hedge[0]["advance"] == "book_above_ceiling" and hedge[0]["book_marginal"] == 0.46
    assert hedge[1]["state"] == "FILLED" and hedge[1]["limit"] == 0.46


def test_a_walked_send_the_entry_read_already_says_will_miss_is_not_sent_at_all(tmp_path):
    """L85: the entry check walked this book for this size a moment ago. If it was already above the
    walked ceiling, the layer does not spend a submit and a poll interval learning that again --
    L75's lesson without L75's send. One send, and the hedge leaves sooner."""
    co, vs, store, _, _ = harness(tmp_path)
    p0, _ = plan_for(offers(), q=10.0)
    p = replace(p0, quantity=10.0,
                first=replace(p0.first, limit_price=0.94, vwap=0.93, contracts=10.0),
                hedge=replace(p0.hedge, limit_price=0.03, vwap=0.03, contracts=10.0, tick=0.01),
                max_cost_per_contract=0.99, fee_per_contract=0.005295, settlement_buffer_per_contract=0.01046315)
    assert p.hedge_break_even(0.94) > 0.04, "0.04 is admissible at entry; only the walked rung is not"
    vs["polymarket"].books = {"P_H": bk([(0.93, 10)])}
    vs["kalshi"].books = {"K_A": bk([(0.04, 5000)])}
    co.fresh_book = lambda venue, market, side: vs[venue].orderbook(market, side)
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.HEDGED and ex.hedge_avg_price == pytest.approx(0.04)
    hedge = [a for a in ex.protect["attempts"] if a["kind"] == "hedge"]
    assert [(a["phase"], a["state"]) for a in hedge] == [("walked", "SKIPPED"), ("budget", "FILLED")]
    assert hedge[0]["skip"] == "entry_book_above_walked" and hedge[0]["book_marginal_at_entry"] == 0.04
    assert store.con.execute("SELECT COUNT(*) FROM orders WHERE venue='kalshi'").fetchone()[0] == 1, "one hedge order"


def test_a_stale_entry_reading_never_skips_a_walked_send(tmp_path):
    """The guard's re-run loads a row whose `hedge_leg_confirm` can be minutes old. Past
    `entry_book_trust_s` the layer reads its own book, as it did before L85."""
    co, vs, store, clk, _ = harness(tmp_path)
    co.limits = ProtectLimits(entry_book_trust_s=0.0)
    p0, _ = plan_for(offers(), q=10.0)
    p = replace(p0, quantity=10.0,
                first=replace(p0.first, limit_price=0.94, vwap=0.93, contracts=10.0),
                hedge=replace(p0.hedge, limit_price=0.03, vwap=0.03, contracts=10.0, tick=0.01),
                max_cost_per_contract=0.99, fee_per_contract=0.005295, settlement_buffer_per_contract=0.01046315)
    vs["polymarket"].books = {"P_H": bk([(0.93, 10)])}
    vs["kalshi"].books = {"K_A": bk([(0.04, 5000)])}
    co.fresh_book = lambda venue, market, side: vs[venue].orderbook(market, side)
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.HEDGED
    hedge = [a for a in ex.protect["attempts"] if a["kind"] == "hedge"]
    assert [(a["phase"], a["state"]) for a in hedge] == [("walked", "UNFILLED"), ("budget", "FILLED")]


def test_the_sekulic_schedule_reaches_the_loss_cap_phase_in_two_sends_not_six(tmp_path):
    """SEKULIC (73688bf3): budget ceiling == walked price (0.16), book at 0.19 under the 0.27 loss
    cap. Live: six sends, filled at +3.8 s. With L75: the walked zero fill advances, the budget
    phase skips its blind retry because the book is above 0.16, the loss-cap phase fills at 0.19."""
    co, vs, _, _, _ = harness(tmp_path)
    p0, _ = plan_for(offers(), q=10.0)
    p = _sekulic_like(p0)
    vs["polymarket"].books = {"P_H": bk([(0.801, 10)])}
    vs["kalshi"].books = {"K_A": bk([(0.19, 5000)])}
    # Admitted at the 0.16 it was priced at; the NO side is 0.19 by the time the hedge fires.
    co.fresh_book = hedge_book_that_moves(vs, "kalshi", bk([(0.16, 5000)]))
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.HEDGED and ex.hedge_avg_price == pytest.approx(0.19)
    hedge = [a for a in ex.protect["attempts"] if a["kind"] == "hedge"]
    assert [(a["phase"], a["limit"], a["state"]) for a in hedge] == [("walked", 0.16, "UNFILLED"), ("loss_cap", 0.19, "FILLED")]
    assert hedge[0]["advance"] == "book_above_ceiling" and hedge[0]["left"] == "walked"
    assert hedge[0]["skipped_phase"] == "budget" and hedge[0]["skipped_ceiling"] == 0.16 and hedge[0]["book_marginal_at_skip"] == 0.19
    assert hedge[-1]["ceiling"] == pytest.approx(0.27, abs=0.0101)


def test_the_moriya_schedule_reaches_the_budget_tick_in_two_sends_not_five(tmp_path):
    """MORIYA (98376aa2): walked 0.03, book at 0.04, budget ceiling floors to 0.04."""
    co, vs, _, _, _ = harness(tmp_path)
    p0, _ = plan_for(offers(), q=10.0)
    p = replace(p0, quantity=10.0,
                first=replace(p0.first, limit_price=0.94, vwap=0.93, contracts=10.0),
                hedge=replace(p0.hedge, limit_price=0.03, vwap=0.03, contracts=10.0, tick=0.01),
                max_cost_per_contract=0.99, fee_per_contract=0.005295, settlement_buffer_per_contract=0.01046315)
    vs["polymarket"].books = {"P_H": bk([(0.93, 10)])}
    vs["kalshi"].books = {"K_A": bk([(0.04, 5000)])}
    # Admitted with the hedge at the planned 0.03; it is 0.04 by the time the layer sends.
    co.fresh_book = hedge_book_that_moves(vs, "kalshi", bk([(0.03, 5000)]))
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    assert ex.state is X.HEDGED and ex.hedge_avg_price == pytest.approx(0.04)
    hedge = [a for a in ex.protect["attempts"] if a["kind"] == "hedge"]
    assert [(a["phase"], a["limit"], a["state"]) for a in hedge] == [("walked", 0.03, "UNFILLED"), ("budget", 0.04, "FILLED")]


def test_without_a_fresh_book_the_walked_phase_still_sends_three_times(tmp_path):
    """L75's guard: no book, no advance. The sequence is the 2026-09-08 one."""
    co, vs, _, _, _ = harness(tmp_path)
    p0, _ = plan_for(offers(), q=10.0)
    p = _sekulic_like(p0)
    vs["polymarket"].books = {"P_H": bk([(0.801, 10)])}
    vs["kalshi"].books = {"K_A": bk([(0.19, 5000)])}
    co.fresh_book = None
    ex = co.execute(p, clearance_for(tmp_path, now_mono=100.0))
    hedge = [a for a in ex.protect["attempts"] if a["kind"] == "hedge"]
    assert [a["phase"] for a in hedge][:3] == ["walked"] * 3 and not any("advance" in a for a in hedge)
    assert ex.state is X.HEDGED and ex.hedge_avg_price == pytest.approx(0.19)


def test_the_hedge_submit_ceiling_survives_the_guard_s_re_runs(tmp_path):
    """L105 (2026-09-14): nothing bounded the hedge submits an EXECUTION may make.

    `attempts`, `phase1` and `phase_attempts` are locals of `protect()`; `clear_protect` mints a
    fresh clearance with a fresh `max_protect_submits` on every hand-over; and `_scan_naked` hands a
    naked row over on every guard pass forever. One execution fired **511 orders for 12,775
    contracts to hedge 25**. The bound has to be durable, so it is counted from `hedge_client_ids`,
    which is persisted with the row and reloaded with it.
    """
    from nodes.execute.tests.test_quantity_caps import setup
    from nodes.risk.clearance import clear_protect
    from nodes.risk.kill import KillSwitches
    from nodes.risk.limits import load_limits
    from kernel.schema import Mode

    # Leg A fills; every hedge attempt comes back filled ZERO, which is the runaway's real shape --
    # a rejection would have set `rejected` and stopped after one.
    co, ex, _pm, _k, _kill, _store, plan = setup(tmp_path, 10, hedge_fills=[0] * 5000)
    assert ex.hedge_filled == 0 and ex.unhedged == 10
    first_call = len(ex.hedge_client_ids)
    assert first_call > 0, "the first call must actually send, or this proves nothing"

    limits, kills = load_limits(), KillSwitches(tmp_path / "kill", enforce_volume=False)
    for i in range(40):                      # the guard's hand-over, over and over
        c = clear_protect(opportunity_id="o1", event_id="espn:mlb:1", venues=("kalshi", "polymarket"),
                          mode=Mode.LIMITED_LIVE, limits=limits, kill=kills, now_mono=200.0 + i)
        assert not hasattr(c, "code"), c     # clear_protect ignores kill/live, by design
        co.protect_existing(ex, plan, c)

    cap = limits.protect.max_protect_submits_total
    assert len(ex.hedge_client_ids) == cap, f"{len(ex.hedge_client_ids)} submits against a cap of {cap}"
    assert ex.protect["submit_ceiling"]["contracts"] == 600.0
    assert "PROTECT_SUBMIT_CEILING" in ex.detail
    # L100's lesson: a ceiling of ours is not a venue rejection, and the row must not say it is.
    assert "hedge rejected" not in ex.detail, ex.detail
    assert "stopped before a hedge" in ex.detail, ex.detail


def test_a_position_naked_past_the_total_window_stops_being_re_run(tmp_path):
    """The second durable bound: a naked position does not become more hedgeable by being retried
    for an hour, and the submit ceiling alone cannot stop a re-run that sends nothing."""
    from dataclasses import replace as _replace
    from nodes.execute.tests.test_quantity_caps import setup
    from nodes.risk.clearance import clear_protect
    from nodes.risk.kill import KillSwitches
    from nodes.risk.limits import load_limits
    from kernel.schema import Mode

    co, ex, _pm, _k, _kill, _store, plan = setup(tmp_path, 10, hedge_fills=[0] * 5000)
    co.limits = _replace(co.limits, max_protect_submits_total=0, protect_total_window_s=60.0)
    assert ex.protect["first_naked_utc"], "the position's age is stamped when it first goes naked"

    limits, kills = load_limits(), KillSwitches(tmp_path / "kill", enforce_volume=False)
    co.clock = lambda: ex.protect["first_naked_utc"] + 61.0      # one second past the window
    c = clear_protect(opportunity_id="o1", event_id="espn:mlb:1", venues=("kalshi", "polymarket"),
                      mode=Mode.LIMITED_LIVE, limits=limits, kill=kills, now_mono=300.0)
    before = len(ex.hedge_client_ids)
    co.protect_existing(ex, plan, c)
    assert len(ex.hedge_client_ids) == before, "past the window, not one further order goes out"
    assert "PROTECT_WINDOW_EXHAUSTED" in ex.detail, ex.detail

