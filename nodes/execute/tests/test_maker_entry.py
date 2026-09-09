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
        assert ex.state is X.ORDER_REJECTED and not hedge.requests and ex.released


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
