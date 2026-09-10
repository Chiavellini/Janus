"""L54 coordinator waits/cancels a single maker order, then protects actual quantity."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from kernel.execution_protocol import Ack, OrderState
from kernel.schema import FillState, Mode
from nodes.execute.plan import maker_plan_from_cover
from nodes.execute.tests.test_coordinator import harness, offers, plan_for
from nodes.execute.records import Execution
from nodes.risk.kill import KillSwitches


def test_maker_plan_quotes_below_ask_without_reinterpreting_old_plans():
    offs = offers()
    historical, cov = plan_for(offs, q=10)
    plan = maker_plan_from_cover(opportunity_id="o1", event_id="e1", league="mlb", cov=cov, offers=offs)
    assert historical.first.time_in_force == "ioc" and not historical.first.post_only
    assert plan.first.post_only and plan.first.time_in_force == "gtc" and plan.first.limit_price == .43
    assert plan.first.contracts == historical.first.contracts == plan.hedge.contracts
    assert plan.fee_per_contract == historical.fee_per_contract


def test_terminal_proof_can_mature_just_after_ordinary_settle_window(tmp_path):
    co, _, _, clock, _ = harness(tmp_path)
    co.mode = Mode.LIMITED_LIVE
    co.kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    co.leg_a_settle_s = .3
    co.poll_interval_s = .1

    pending = lambda: OrderState("polymarket", "cid", "order", FillState.UNCONFIRMED,
                                 0, None, None, "post_only_pending", clock.now(), open=False, final=False)

    class Maker:
        terminal_proof_grace_s = .2
        def cancel_only(self, _cid):
            return pending()
        def status(self, _cid):
            # Old deadline: 100.3. The adapter's stable-terminal proof matures at 100.5.
            if clock.mono() < 100.5 - 1e-9:
                return pending()
            return OrderState("polymarket", "cid", "order", FillState.UNFILLED,
                              0, None, None, "post_only_terminal", clock.now(), open=False, final=True)

    co.venues = {"polymarket": Maker()}
    ex = Execution("ex", "o", "e", "mlb", co.mode.value, 10, clock.now())
    ack = Ack("polymarket", "cid", "order", FillState.UNCONFIRMED, 0, None, None,
              "live", clock.now(), open=True)
    result = co._settle_maker_ack("polymarket", ack, ex=ex, rest_deadline_mono=clock.mono())
    assert result.state is FillState.UNFILLED
    assert clock.mono() == pytest.approx(100.5)
    assert not co.kill.active(live=True)


def test_genuinely_unresolved_maker_still_latches_after_terminal_grace(tmp_path):
    co, _, _, clock, _ = harness(tmp_path)
    co.mode = Mode.LIMITED_LIVE
    co.kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    co.leg_a_settle_s = .3
    co.poll_interval_s = .1
    pending = OrderState("polymarket", "cid", "order", FillState.UNCONFIRMED,
                         0, None, None, "post_only_pending", clock.now(), open=True, final=False)
    maker = SimpleNamespace(terminal_proof_grace_s=.2, cancel_only=lambda _cid: pending,
                            status=lambda _cid: pending)
    co.venues = {"polymarket": maker}
    ex = Execution("ex", "o", "e", "mlb", co.mode.value, 10, clock.now())
    result = co._settle_maker_ack("polymarket", pending, ex=ex, rest_deadline_mono=clock.mono())
    assert result.state is FillState.UNCONFIRMED
    assert co.kill.active(live=True) and ex.protect["post_only_unresolved"] == "cid"


@pytest.mark.parametrize("late", [6, 10])
def test_cancel_race_returns_actual_cumulative_fill_within_original_cap(tmp_path, late):
    co, _, _, clock, _ = harness(tmp_path)
    co.mode = Mode.LIMITED_LIVE
    co.kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    calls = []
    def status(cid):
        q = late if calls else 6
        return OrderState("polymarket", cid, "order", FillState.FILLED if q == 10 else FillState.PARTIAL,
                          q, .43, 0, "matched", clock.now(), open=not bool(calls), final=bool(calls))
    def cancel(cid):
        calls.append(cid)
        return status(cid)
    co.venues = {"polymarket": SimpleNamespace(status=status, cancel=cancel)}
    ex = Execution("ex", "o", "e", "mlb", co.mode.value, 10, clock.now())
    start = Ack("polymarket", "cid", "order", FillState.UNCONFIRMED, 0, None, None, "live", clock.now(), open=True)
    result = co._settle_maker_ack("polymarket", start, ex=ex)
    assert result.filled_contracts == late and calls == ["cid"] and not co.kill.active(live=True)


def test_cancel_failure_keeps_partial_fill_for_hedge_and_latches_entry(tmp_path):
    co, _, _, clock, _ = harness(tmp_path)
    co.mode = Mode.LIMITED_LIVE
    co.kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    co.leg_a_settle_s = .3
    st = OrderState("polymarket", "cid", "order", FillState.PARTIAL, 6, .43, 0, "live", clock.now(), open=True)
    co.venues = {"polymarket": SimpleNamespace(status=lambda cid: st,
                    cancel=lambda cid: (_ for _ in ()).throw(TimeoutError("cancel lost")))}
    ex = Execution("ex", "o", "e", "mlb", co.mode.value, 10, clock.now())
    result = co._settle_maker_ack("polymarket", st, ex=ex)
    assert result.filled_contracts == 6 and result.open and co.kill.active(live=True)
    assert co._quantity_stop and ex.protect["post_only_unresolved"] == "cid"


@pytest.mark.parametrize("fill_at_cancel", [0, 6, 10])
def test_expiry_cancels_before_another_poll_and_protects_racing_fill(tmp_path, fill_at_cancel):
    from kernel.schema import ExecutionState as X
    from nodes.execute.tests.test_quantity_caps import ScriptedVenue
    from nodes.execution.testing import clearance_for
    co, _, _, clock, _ = harness(tmp_path)
    co.mode = Mode.LIMITED_LIVE
    co.kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    calls = []
    class Maker(ScriptedVenue):
        def submit(self, request, clearance):
            assert clearance.consume(clock.mono())
            self.requests.append(request)
            self.answer = Ack("polymarket", request.client_order_id, "v", FillState.FILLED,
                              fill_at_cancel, request.price, 0, "matched", clock.now())
            answer = self.answer
            assert request.post_only and request.time_in_force == "gtc"
            return replace(answer, state=FillState.UNCONFIRMED, filled_contracts=0, open=True)
        def status(self, cid):
            if not calls:
                assert clock.mono() < 100.05, "cancel is issued at the proof deadline before another read"
                return OrderState(**replace(self.answer, state=FillState.UNCONFIRMED, filled_contracts=0, open=True).__dict__)
            state = FillState.FILLED if fill_at_cancel == 10 else FillState.PARTIAL if fill_at_cancel else FillState.UNFILLED
            return OrderState(**replace(self.answer, state=state, filled_contracts=fill_at_cancel, open=False).__dict__, final=True)
        def cancel(self, cid):
            calls.append(clock.mono())
            return self.status(cid)
    pm = Maker("polymarket", clock, [fill_at_cancel])
    hedge = ScriptedVenue("kalshi", clock, [])
    co.venues = {"polymarket": pm, "kalshi": hedge}
    offs = offers()
    _, cov = plan_for(offs, q=10)
    plan = maker_plan_from_cover(opportunity_id="o1", event_id="e", league="mlb", cov=cov, offers=offs)
    plan = replace(plan, quote_expires_utc=clock.now() + .05)
    ex = co.execute(plan, clearance_for(tmp_path, mode=Mode.LIMITED_LIVE, now_mono=clock.mono()))
    assert calls == pytest.approx([100.05]), (ex.state, repr(getattr(ex, "machine_error", None)), ex.protect)
    assert len(pm.requests) == 1 and ex.first_filled == fill_at_cancel
    if fill_at_cancel:
        assert ex.state is X.HEDGED and hedge.requests[0].contracts == fill_at_cancel
        assert hedge.requests[0].price <= plan.hedge_budget(.43)
    else:
        assert ex.state is X.ORDER_UNFILLED and not hedge.requests and ex.released


def test_slow_status_cannot_delay_deadline_cancel_dispatch(tmp_path):
    co, _, _, clock, _ = harness(tmp_path)
    calls = []
    def status(cid):
        calls.append(("status", clock.mono()))
        clock.sleep(5)
        return OrderState("polymarket", cid, "order", FillState.UNFILLED, 0, None, None,
                          "canceled", clock.now(), final=True)
    def cancel(cid):
        calls.append(("cancel", clock.mono()))
        return status(cid)
    co.venues = {"polymarket": SimpleNamespace(status=status, cancel=cancel)}
    ex = Execution("ex", "o", "e", "mlb", co.mode.value, 10, clock.now())
    ack = Ack("polymarket", "cid", "order", FillState.UNCONFIRMED, 0, None, None, "live", clock.now(), open=True)
    co._settle_maker_ack("polymarket", ack, ex=ex, rest_deadline_mono=100.05)
    assert calls[0] == ("cancel", pytest.approx(100.05))


def test_rest_guard_failure_cancels_immediately_before_deadline(tmp_path):
    co, _, _, clock, _ = harness(tmp_path)
    calls = []
    final = OrderState("polymarket", "cid", "order", FillState.UNFILLED, 0, None, 0,
                       "canceled", clock.now(), open=False, final=True)
    co.venues = {"polymarket": SimpleNamespace(
        observed=lambda _cid: OrderState("polymarket", "cid", "order", FillState.UNCONFIRMED,
                                          0, None, None, "live", clock.now(), open=True),
        cancel=lambda _cid: calls.append(clock.mono()) or final,
    )}
    ex = Execution("ex", "o", "e", "mlb", co.mode.value, 10, clock.now())
    start = Ack("polymarket", "cid", "order", FillState.UNCONFIRMED, 0, None, None,
                "live", clock.now(), open=True)
    result = co._settle_maker_ack("polymarket", start, ex=ex,
                                  rest_deadline_mono=102.0,
                                  maker_guard=lambda _remaining: "HEDGE_DEPTH_INSUFFICIENT")
    assert calls == [100.0] and result.state is FillState.UNFILLED
    assert ex.protect["maker_rest_block"] == "HEDGE_DEPTH_INSUFFICIENT"


def test_rest_guard_exception_is_a_cancel_reason_not_an_escape(tmp_path):
    co, _, _, clock, _ = harness(tmp_path)
    calls = []
    final = OrderState("polymarket", "cid", "order", FillState.UNFILLED, 0, None, 0,
                       "canceled", clock.now(), open=False, final=True)
    co.venues = {"polymarket": SimpleNamespace(
        observed=lambda _cid: None,
        cancel=lambda _cid: calls.append(clock.mono()) or final,
    )}
    ex = Execution("ex", "o", "e", "mlb", co.mode.value, 10, clock.now())
    start = Ack("polymarket", "cid", "order", FillState.UNCONFIRMED, 0, None, None,
                "live", clock.now(), open=True)
    result = co._settle_maker_ack(
        "polymarket", start, ex=ex, rest_deadline_mono=102.0,
        maker_guard=lambda _remaining, **_kw: (_ for _ in ()).throw(RuntimeError("loop failed")),
    )
    assert calls == [100.0] and result.state is FillState.UNFILLED
    assert ex.protect["maker_rest_block"] == "MAKER_GUARD_ERROR:RuntimeError"


def test_socket_high_water_two_then_five_hedges_two_then_only_three(tmp_path):
    from nodes.execute.tests.test_quantity_caps import ScriptedVenue
    from nodes.execution.testing import clearance_for
    co, _, _, clock, _ = harness(tmp_path)
    co.mode = Mode.LIMITED_LIVE
    co.kill = KillSwitches(tmp_path / "kill", enforce_volume=False)

    class Maker:
        def __init__(self):
            self.statuses = [
                OrderState("polymarket", "cid", "order", FillState.PARTIAL, 2, .43, 0,
                           "socket", clock.now(), open=True, final=False),
                OrderState("polymarket", "cid", "order", FillState.PARTIAL, 5, .43, 0,
                           "canceled", clock.now(), open=False, final=True),
            ]
        def observed(self, _cid):
            return self.statuses[0]
        def cancel_only(self, _cid):
            return self.statuses[0]
        def status(self, _cid):
            return self.statuses.pop(0)

    hedge = ScriptedVenue("kalshi", clock, [2, 3])
    co.venues = {"polymarket": Maker(), "kalshi": hedge}
    offs = offers()
    _, cov = plan_for(offs, q=10)
    plan = maker_plan_from_cover(opportunity_id="o1", event_id="e", league="mlb", cov=cov, offers=offs)
    clearance = clearance_for(tmp_path, mode=Mode.LIMITED_LIVE, now_mono=clock.mono())
    clearance.authorize_maker_rest(102.0, now_mono=clock.mono())
    assert clearance.consume(clock.mono())
    ex = Execution("ex", "o1", "e", "mlb", co.mode.value, 10, clock.now(), first_client_id="cid")
    co._t0[ex.execution_id] = clock.mono()
    start = Ack("polymarket", "cid", "order", FillState.UNCONFIRMED, 0, None, None,
                "live", clock.now(), open=True)
    result = co._settle_maker_ack("polymarket", start, ex=ex, plan=plan,
                                  clearance=clearance, rest_deadline_mono=102.0)
    assert result.filled_contracts == 5
    assert [request.contracts for request in hedge.requests] == [2, 3]
    assert ex.hedge_filled == 5 and ex.unhedged == 0


def test_unknown_delta_hedge_stops_later_maker_high_water_from_resubmitting(tmp_path):
    from nodes.execution.testing import clearance_for
    co, _, _, clock, _ = harness(tmp_path)
    co.mode = Mode.LIMITED_LIVE
    co.kill = KillSwitches(tmp_path / "kill", enforce_volume=False)

    two = OrderState("polymarket", "cid", "order", FillState.PARTIAL, 2, .43, 0,
                     "socket", clock.now(), open=True, final=False)
    five = OrderState("polymarket", "cid", "order", FillState.PARTIAL, 5, .43, 0,
                      "canceled", clock.now(), open=False, final=True)
    maker = SimpleNamespace(observed=lambda _cid: two, cancel_only=lambda _cid: two,
                            status=lambda _cid: five)

    class UnknownHedge:
        venue = "kalshi"
        def __init__(self): self.requests = []
        def submit(self, req, clearance):
            assert clearance.consume(clock.mono(), hedge=True)
            self.requests.append(req)
            return Ack("kalshi", req.client_order_id, "k", FillState.UNCONFIRMED, 0,
                       None, None, "transport", clock.now())
        def status(self, cid):
            return OrderState("kalshi", cid, "k", FillState.UNCONFIRMED, 0, None, None,
                              "transport", clock.now(), final=False)

    hedge = UnknownHedge()
    co.venues = {"polymarket": maker, "kalshi": hedge}
    offs = offers()
    _, cov = plan_for(offs, q=10)
    plan = maker_plan_from_cover(opportunity_id="o1", event_id="e", league="mlb", cov=cov, offers=offs)
    clearance = clearance_for(tmp_path, mode=Mode.LIMITED_LIVE, now_mono=clock.mono())
    clearance.protect_window_s = .1
    clearance.authorize_maker_rest(102.0, now_mono=clock.mono())
    assert clearance.consume(clock.mono())
    ex = Execution("ex", "o1", "e", "mlb", co.mode.value, 10, clock.now(), first_client_id="cid")
    co._t0[ex.execution_id] = clock.mono()
    result = co._settle_maker_ack(
        "polymarket", Ack("polymarket", "cid", "order", FillState.UNCONFIRMED, 0,
                           None, None, "live", clock.now(), open=True),
        ex=ex, plan=plan, clearance=clearance, rest_deadline_mono=102.0,
    )
    assert result.filled_contracts == 5
    assert len(hedge.requests) == 1 and hedge.requests[0].contracts == 2
    assert "maker fill hedge unconfirmed" in ex.protect["maker_delta_unconfirmed"]


def test_delta_hedge_execution_ownership_is_durable_before_wire(tmp_path):
    import json
    from nodes.execution.testing import clearance_for
    co, _, _, clock, _ = harness(tmp_path)
    co.mode = Mode.LIMITED_LIVE
    offs = offers()
    _, cov = plan_for(offs, q=10)
    plan = maker_plan_from_cover(opportunity_id="o1", event_id="e", league="mlb", cov=cov, offers=offs)
    clearance = clearance_for(tmp_path, mode=Mode.LIMITED_LIVE, now_mono=clock.mono())
    clearance.authorize_maker_rest(102.0, now_mono=clock.mono())
    assert clearance.consume(clock.mono())
    ex = Execution("durable", "o1", "e", "mlb", co.mode.value, 10, clock.now(), first_client_id="cid")
    co.records.start(ex, plan={"first": plan.first.__dict__, "hedge": plan.hedge.__dict__,
                               "max_cost": plan.max_cost_per_contract, "fee": plan.fee_per_contract}, books={})

    class AssertOwned:
        venue = "kalshi"
        def submit(self, req, token):
            owned = json.loads(co.records.row("durable")["hedge_client_ids"])
            assert req.client_order_id in owned
            assert token.consume(clock.mono(), hedge=True)
            return Ack("kalshi", req.client_order_id, "k", FillState.FILLED, req.contracts,
                       req.price, 0, "filled", clock.now())

    co.venues = {"kalshi": AssertOwned()}
    known = OrderState("polymarket", "cid", "p", FillState.PARTIAL, 2, .43, 0,
                       "socket", clock.now(), open=True, final=False)
    co._hedge_maker_high_water(plan, clearance, ex, known)
    assert ex.hedge_filled == 2


def test_execution_row_sync_failure_after_maker_fill_does_not_suppress_delta_hedge(tmp_path, monkeypatch):
    from nodes.execute.tests.test_quantity_caps import ScriptedVenue
    from nodes.execution.testing import clearance_for
    co, _, _, clock, _ = harness(tmp_path)
    co.mode = Mode.LIMITED_LIVE
    co.kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    offs = offers()
    _, cov = plan_for(offs, q=10)
    plan = maker_plan_from_cover(opportunity_id="o1", event_id="e", league="mlb", cov=cov, offers=offs)
    clearance = clearance_for(tmp_path, mode=Mode.LIMITED_LIVE, now_mono=clock.mono())
    clearance.authorize_maker_rest(102.0, now_mono=clock.mono())
    assert clearance.consume(clock.mono())
    ex = Execution("durable-fail", "o1", "e", "mlb", co.mode.value, 10, clock.now(), first_client_id="cid")
    co.records.start(ex, plan={"first": plan.first.__dict__, "hedge": plan.hedge.__dict__,
                               "max_cost": plan.max_cost_per_contract, "fee": plan.fee_per_contract}, books={})
    real_sync, failed = co.records.sync, {"once": False}
    def fail_once(*args, **kwargs):
        if not failed["once"]:
            failed["once"] = True
            raise OSError("execution db unavailable")
        return real_sync(*args, **kwargs)
    monkeypatch.setattr(co.records, "sync", fail_once)
    hedge = ScriptedVenue("kalshi", clock, [2])
    co.venues = {"kalshi": hedge}
    known = OrderState("polymarket", "cid", "p", FillState.PARTIAL, 2, .43, 0,
                       "socket", clock.now(), open=True, final=False)
    co._hedge_maker_high_water(plan, clearance, ex, known)
    assert hedge.requests[0].contracts == 2 and hedge.requests[0].execution_id == ex.execution_id
    assert ex.hedge_filled == 2 and "OSError" in ex.protect["post_fill_storage_error"]
    assert co.kill.active(live=True)


def test_execution_move_failure_after_known_first_fill_still_sends_hedge(tmp_path, monkeypatch):
    from nodes.execute.tests.test_quantity_caps import ScriptedVenue
    from nodes.execution.testing import clearance_for
    co, _, _, clock, _ = harness(tmp_path)
    co.mode = Mode.LIMITED_LIVE
    co.kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    pm, hedge = ScriptedVenue("polymarket", clock, [10]), ScriptedVenue("kalshi", clock, [10])
    co.venues = {"polymarket": pm, "kalshi": hedge}
    plan, _ = plan_for(offers(), q=10)
    real_move = co.records.move
    def move(ex, to, **kwargs):
        if to.name == "LEG_A_FILLED":
            raise OSError("execution transition unavailable")
        return real_move(ex, to, **kwargs)
    monkeypatch.setattr(co.records, "move", move)
    result = co.execute(plan, clearance_for(tmp_path, mode=Mode.LIMITED_LIVE, now_mono=clock.mono()))
    assert hedge.requests and hedge.requests[0].contracts == 10
    assert result.hedge_filled == 10 and co.kill.active(live=True)


@pytest.mark.parametrize("quantity", [6, 10])
def test_post_wire_status_disk_failure_still_sends_actual_protective_hedge(tmp_path, monkeypatch, quantity):
    from kernel.schema import ExecutionState as X
    from nodes.exec_polymarket.tests.test_post_only_lifecycle import setup
    from nodes.execute.tests.test_quantity_caps import ScriptedVenue
    from nodes.execution.testing import clearance_for
    co, _, _, clock, _ = harness(tmp_path)
    co.mode = Mode.LIMITED_LIVE
    pm, journal, transport = setup(tmp_path / "pm")
    pm.clock, pm.mono = clock.now, clock.mono
    co.kill = pm.kill
    co.leg_a_settle_s = .3
    def posted(prepared):
        transport.payload.update(size_matched=str(quantity), status="MATCHED")
        monkeypatch.setattr(journal, "record", lambda *a, **kw: (_ for _ in ()).throw(OSError("post-wire disk")))
        return {"success": True, "orderID": "signed-hash"}
    transport.post_prepared_post_only = posted
    hedge = ScriptedVenue("kalshi", clock, [], kill=pm.kill)
    co.venues = {"polymarket": pm, "kalshi": hedge}
    offs = offers()
    _, cov = plan_for(offs, q=10)
    plan = maker_plan_from_cover(opportunity_id="o1", event_id="e", league="mlb", cov=cov, offers=offs)
    result = co.execute(plan, clearance_for(tmp_path, mode=co.mode, now_mono=clock.mono()))
    assert result.first_filled == quantity, (result.state, getattr(result, "machine_error", None))
    assert hedge.requests[0].contracts == quantity and result.state is X.HEDGED
    assert pm.persistence_error and pm.kill.active(live=True)
    assert journal.store.con.execute("SELECT client_order_id FROM pm_post_only_admission").fetchone()[0]
