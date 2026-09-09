"""L53 overfill alarms and strictly downward protective quantity conversion."""
from dataclasses import replace

import pytest

from kernel.execution_protocol import Ack, OrderState
from kernel.schema import ExecutionState as X, FillState, Mode
from nodes.execute.coordinator import Coordinator
from nodes.execute.guard import GuardSnapshot
from nodes.execute.records import ExecutionRecords
from nodes.execute.tests.test_coordinator import Clock, offers, plan_for
from nodes.execute.tests.test_guard import T0, _gea_row, _world
from nodes.execution.testing import clearance_for
from nodes.risk.kill import KillSwitches
from nodes.risk.limits import ProtectLimits
from nodes.store_tuples.store import TupleStore


class ScriptedVenue:
    def __init__(self, venue, clock, fills, *, pending=False, kill=None):
        self.venue, self.clock, self.fills = venue, clock, list(fills)
        self.pending, self.kill, self.requests = pending, kill, []

    def submit(self, req, clearance):
        assert clearance.consume(self.clock.mono(), hedge=req.hedge)
        self.requests.append(req)
        if self.kill is not None:
            assert self.kill.active(live=True), "overfill must latch before protective hedge"
        qty = self.fills.pop(0) if self.fills else req.contracts
        self.answer = Ack(self.venue, req.client_order_id, "v", FillState.FILLED,
                          qty, req.price, 0, "matched", self.clock.now())
        if self.pending:
            return replace(self.answer, state=FillState.UNCONFIRMED, filled_contracts=0)
        return self.answer

    def status(self, cid):
        return OrderState(**self.answer.__dict__, final=True)


def setup(tmp_path, filled, *, pending=False, hedge_fills=(), dust=1.0):
    clk = Clock()
    kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    pm = ScriptedVenue("polymarket", clk, [filled], pending=pending)
    k = ScriptedVenue("kalshi", clk, hedge_fills, kill=kill if filled > 10 else None)
    store = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    co = Coordinator({"polymarket": pm, "kalshi": k}, ExecutionRecords(store), Mode.LIMITED_LIVE,
                     kill=kill, clock=clk.now, mono=clk.mono, sleep=clk.sleep,
                     limits=replace(ProtectLimits(), protect_dust_contracts=dust))
    plan, _ = plan_for(offers(), q=10)
    ex = co.execute(plan, clearance_for(tmp_path, mode=Mode.LIMITED_LIVE, now_mono=100.0))
    return co, ex, pm, k, kill, store, plan


@pytest.mark.parametrize("pending", [False, True])
def test_f15_overfill_latches_before_hedge_and_preserves_actual_quantity(tmp_path, pending):
    co, ex, pm, k, kill, store, plan = setup(tmp_path, 10.166667, pending=pending)
    assert ex.first_filled == 10.166667 and ex.hedge_filled == 10
    assert ex.unhedged == pytest.approx(.166667) and ex.overhedged == 0
    assert k.requests[0].contracts == 10
    assert kill.active(live=True) == ["live"]
    assert ex.protect["quantity_violations"][0]["filled"] == 10.166667
    assert store.con.execute("SELECT flag FROM lane_flags").fetchone()[0] == "ORDER_OVERFILL"
    second = co.execute(plan, clearance_for(tmp_path / "next", mode=Mode.LIMITED_LIVE, now_mono=100.0))
    assert second.state is X.ORDER_REJECTED and len(pm.requests) == 1


def test_fractional_protection_floors_and_never_rounds_above_held_shares(tmp_path):
    _, ex, _, k, _, _, _ = setup(tmp_path, 9.999999)
    assert k.requests[0].contracts == 9.99 and ex.overhedged == 0
    assert ex.unhedged == pytest.approx(.009999)


def test_multiple_hedge_fills_do_not_expand_aggregate_authorized_cap(tmp_path):
    _, ex, _, k, kill, _, _ = setup(tmp_path, 12.166667, hedge_fills=[6, 4])
    assert [r.contracts for r in k.requests] == [10, 4]
    assert ex.hedge_filled == 10 and ex.first_filled == 12.166667
    assert ex.unhedged == pytest.approx(2.166667) and not ex.released
    assert ex.state is not X.HEDGED and kill.active(live=True)
    assert ex.protect["quantity_cap_residual"] == pytest.approx(2.166667)


def test_late_authoritative_overfill_below_protection_dust_still_latches(tmp_path):
    kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    _, journal, records, guard = _world(tmp_path, venues={}, kill=kill)
    _gea_row(journal, records)
    journal.record(Ack("polymarket", "a1", "late", FillState.FILLED, 10.166667, .36, 0,
                       "trade_feed", T0 + 250), kind="status")
    report = guard.apply(GuardSnapshot(now=T0 + 300))
    assert kill.active(live=True) == ["live"]
    assert any(s.startswith("ORDER_OVERFILL") for s in report.findings)
    assert journal.get("a1")["filled_contracts"] == 10.166667
    assert not any(s.startswith("ORDER_OVERFILL") for s in guard.apply(GuardSnapshot(now=T0 + 301)).findings)


def test_in_process_overfill_stop_survives_a_failed_kill_write(tmp_path):
    co, ex, pm, _, _, _, plan = setup(tmp_path, 9.999999)
    class BrokenKill:
        def active(self, **kwargs): return []
        def latch(self, *args): raise OSError("unavailable kill volume")
    co.kill = BrokenKill()
    request = pm.requests[0]
    co._check_overfill(ex, request, Ack("polymarket", request.client_order_id, "v", FillState.FILLED,
                                       10.166667, .36, 0, "matched", 1000))
    assert "OSError" in ex.protect["overfill_latch_error"]
    next_ex = co.execute(plan, clearance_for(tmp_path / "next", mode=Mode.LIMITED_LIVE, now_mono=100.0))
    assert next_ex.state is X.ORDER_REJECTED and len(pm.requests) == 1


def test_guard_retries_a_failed_overfill_kill_write(tmp_path):
    class RetryKill:
        calls = 0
        def latch(self, *args):
            self.calls += 1
            if self.calls == 1:
                raise OSError("temporary volume failure")
    kill = RetryKill()
    _, journal, records, guard = _world(tmp_path, venues={}, kill=kill)
    _gea_row(journal, records)
    journal.record(Ack("polymarket", "a1", "late", FillState.FILLED, 10.166667, .36, 0,
                       "trade_feed", T0 + 250), kind="status")
    assert any("kill latch failed" in s for s in guard.apply(GuardSnapshot(now=T0 + 300)).findings)
    # The post-sync scan may retry in the same pass; once it succeeds, later scans are quiet.
    guard.apply(GuardSnapshot(now=T0 + 301))
    assert kill.calls == 2
