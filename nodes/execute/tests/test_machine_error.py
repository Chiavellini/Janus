from types import SimpleNamespace

from kernel.schema import ExecutionState as X, Mode
from nodes.execute.coordinator import Coordinator
from nodes.execute.plan import LegPlan, Plan
from nodes.execute.records import ExecutionRecords
from kernel.execution_protocol import Ack, FillState
from nodes.store_tuples.store import TupleStore


class Venue:
    def __init__(self, raise_on_submit: bool):
        self.raise_on_submit = raise_on_submit
        self.submits = 0

    def submit(self, req, clearance):
        self.submits += 1
        if self.raise_on_submit:
            raise RuntimeError("database is locked")           # the journal write after the POST, 2026-09-08 01:17Z
        return Ack(req.venue, req.client_order_id, "v1", FillState.FILLED, req.contracts, req.price, 0.0, "matched", 1000.0)

    def status(self, cid):
        raise AssertionError("not polled")

    def cancel(self, cid):
        raise AssertionError("not cancelled")


def _plan():
    first = LegPlan("polymarket", "m1", "tok", "buy_yes", 0.36, 10.0, "ioc")
    hedge = LegPlan("kalshi", "m2", "K", "buy_no", 0.60, 10.0, "ioc")
    return Plan("opp1", "ev1", "atp", 10.0, first, hedge, max_cost_per_contract=0.97, fee_per_contract=0.01, strategy_version="v1")


def _clearance():
    return SimpleNamespace(opportunity_id="opp1", reservation=SimpleNamespace(reservation_id="r1"), max_hedge_submits=1,
                           valid=lambda *_: True, arm_hedge=lambda now: now + 3.0)


def test_a_machine_error_after_leg_a_was_submitted_is_recorded_as_unknown_provider_state(tmp_path, capsys):
    """The row must never stay LEG_A_SUBMITTED with nothing on it: the machine records the error
    as the failure it is (holding the reservation, alarmed by the watchdog) and returns."""
    st = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    co = Coordinator({"polymarket": Venue(True), "kalshi": Venue(False)}, ExecutionRecords(st), Mode.LIMITED_LIVE)
    ex = co.execute(_plan(), _clearance())
    assert ex.state is X.UNKNOWN_PROVIDER_STATE and not ex.released
    assert "machine error after LEG_A_SUBMITTED: RuntimeError: database is locked" in ex.detail
    assert isinstance(ex.machine_error, RuntimeError)
    row = st.con.execute("SELECT state, released FROM executions WHERE execution_id=?", (ex.execution_id,)).fetchone()
    assert row == ("UNKNOWN_PROVIDER_STATE", 0)
    tr = [r[0] for r in st.con.execute("SELECT to_state FROM execution_transitions WHERE execution_id=? ORDER BY id", (ex.execution_id,))]
    assert tr[-2:] == ["LEG_A_SUBMITTED", "UNKNOWN_PROVIDER_STATE"]


def test_a_machine_error_before_any_order_is_a_released_rejection(tmp_path):
    st = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    co = Coordinator({"polymarket": Venue(False), "kalshi": Venue(False)}, ExecutionRecords(st), Mode.LIMITED_LIVE,
                     kill=SimpleNamespace(active=lambda **k: (_ for _ in ()).throw(OSError("kill root unreadable"))))
    ex = co.execute(_plan(), _clearance())
    assert ex.state is X.ORDER_REJECTED and ex.released
    assert "machine error after VALIDATED" in ex.detail or "machine error after DETECTED" in ex.detail
