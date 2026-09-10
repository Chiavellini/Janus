from decimal import Decimal

from nodes.redeem_polymarket.redeem import (
    Position, Redeemer, RedemptionStore, Submission, Transaction, eligible_positions,
)

CID = "0x" + "ab" * 32
OTHER = "0x" + "cd" * 32


class Fake:
    def __init__(self, positions):
        self.current = positions
        self.submits = []
        self.recovered = None
        self.tx = Transaction("PENDING", "tx1")
    def positions(self): return list(self.current)
    def submit(self, condition_id, *, metadata):
        self.submits.append((condition_id, metadata))
        return Submission("tx1")
    def transaction(self, transaction_id): return self.tx
    def recover(self, *, metadata): return self.recovered
    def close(self): pass


def test_eligibility_ignores_losing_remnants_and_malformed_rows():
    rows = [
        Position(CID, "10", "10", True),
        Position(OTHER, "8", "0", True),
        Position("bad", "9", "9", True),
        Position(CID.upper().replace("0X", "0x"), "0.5", "0.5", True),
        Position("0x" + "ef" * 32, "1", "1", False),
    ]
    assert eligible_positions(rows) == {CID: Decimal("10.5")}


def test_submit_is_prepared_then_idempotent(tmp_path):
    fake = Fake([Position(CID, "10", "10", True)])
    store = RedemptionStore(tmp_path / "r.sqlite")
    counts = Redeemer(fake, store, clock=lambda: 1000.0).run_once()
    assert counts["submitted"] == 1 and len(fake.submits) == 1
    assert store.row(CID)["state"] == "SUBMITTED"
    Redeemer(fake, store, clock=lambda: 1001.0).run_once()
    assert len(fake.submits) == 1


def test_prepared_crash_recovers_exact_transaction_without_resubmit(tmp_path):
    fake = Fake([Position(CID, "10", "10", True)])
    store = RedemptionStore(tmp_path / "r.sqlite")
    store.prepare(CID, Decimal("10"), now=1000.0)
    fake.recovered = Submission("recovered", "0xhash")
    fake.tx = Transaction("CONFIRMED", "recovered", "0xhash")
    counts = Redeemer(fake, store, clock=lambda: 1001.0).run_once()
    assert not fake.submits and counts["confirmed"] == 1
    assert store.row(CID)["state"] == "CONFIRMED_PENDING"


def test_confirmed_needs_fresh_position_disappearance_then_completes(tmp_path):
    fake = Fake([Position(CID, "10", "10", True)])
    store = RedemptionStore(tmp_path / "r.sqlite")
    store.prepare(CID, Decimal("10"), now=1000.0)
    store.move(CID, "SUBMITTED", now=1000.1, transaction_id="tx1")
    fake.tx = Transaction("CONFIRMED", "tx1", "0xhash")
    Redeemer(fake, store, clock=lambda: 1001.0).run_once()
    assert store.row(CID)["state"] == "CONFIRMED_PENDING"
    fake.current = []
    counts = Redeemer(fake, store, clock=lambda: 1002.0).run_once()
    assert counts["complete"] == 1 and store.row(CID)["state"] == "COMPLETE"


def test_failed_transaction_is_terminal_and_not_retried(tmp_path):
    fake = Fake([Position(CID, "10", "10", True)])
    store = RedemptionStore(tmp_path / "r.sqlite")
    store.prepare(CID, Decimal("10"), now=1000.0)
    store.move(CID, "SUBMITTED", now=1000.1, transaction_id="tx1")
    fake.tx = Transaction("FAILED", "tx1", detail="reverted")
    counts = Redeemer(fake, store, clock=lambda: 1001.0).run_once()
    assert counts["failed"] == 1 and store.row(CID)["state"] == "FAILED"
    again = Redeemer(fake, store, clock=lambda: 1002.0).run_once()
    assert again["failed"] == 1
    assert not fake.submits


def test_unrecoverable_prepared_wire_is_unknown_and_never_resubmitted(tmp_path):
    fake = Fake([Position(CID, "10", "10", True)])
    store = RedemptionStore(tmp_path / "r.sqlite")
    store.prepare(CID, Decimal("10"), now=1000.0)
    counts = Redeemer(fake, store, clock=lambda: 1001.0).run_once()
    assert counts["unknown"] == 1 and counts["pending"] == 1
    assert not fake.submits and store.row(CID)["state"] == "PREPARED"
