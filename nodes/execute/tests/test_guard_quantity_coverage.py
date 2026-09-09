"""L53 review: partial cash/fill coverage cannot erase an authoritative overfill."""
from dataclasses import replace
import json

import pytest

from kernel.execution_protocol import Ack, FillRecord
from kernel.schema import FillState
from nodes.execute.guard import GuardSnapshot
from nodes.execute.tests.test_guard import TOK, T0, _gea_row, _world
from nodes.risk.kill import KillSwitches


def world(tmp_path):
    kill = KillSwitches(tmp_path / "kill", enforce_volume=False)
    store, journal, records, guard = _world(tmp_path, venues={}, kill=kill)
    _gea_row(journal, records)
    journal.record(Ack("polymarket", "a1", "f15-order", FillState.FILLED, 10.166667,
                       .36, .11626, "matched", T0 + 150), kind="status",
                   raw={"id": "f15-order", "original_size": "10", "size_matched": "10.166667"})
    partial = FillRecord("polymarket", "f15-order", "partial-cash", 6, .35, .06825, True,
                         T0 + 151, True, market_id=TOK, side="buy_yes")
    journal.record_fill(partial)
    return store, journal, records, guard, kill, partial


def test_authoritative_overfill_latches_before_partial_fifo_sync(tmp_path, monkeypatch):
    store, journal, records, guard, kill, partial = world(tmp_path)
    sync = guard._sync_order_from_fills
    calls = []
    def checked_sync(row):
        assert kill.active(live=True) == ["live"], "must latch before any FIFO mutation"
        assert row["filled_contracts"] == 10.166667
        calls.append(row["client_order_id"])
        return sync(row)
    monkeypatch.setattr(guard, "_sync_order_from_fills", checked_sync)
    rep = guard.apply(GuardSnapshot(now=T0 + 300, fills=[partial]))
    row = journal.get("a1")
    assert calls == ["a1"]
    assert row["filled_contracts"] == 10.166667 and row["contracts"] == 10
    assert row["avg_price"] == .36 and row["fee_usd"] == .11626
    assert row["state"] == "FILLED" and row["settlement_pending"] == 1
    assert records.load("789ad9b2").first_filled == 10.166667
    assert any(s.startswith("ORDER_OVERFILL") for s in rep.findings)
    assert store.con.execute("SELECT COUNT(*) FROM lane_flags WHERE flag='ORDER_OVERFILL'").fetchone()[0] == 1
    guard.apply(GuardSnapshot(now=T0 + 301, fills=[partial]))
    assert journal.get("a1")["filled_contracts"] == 10.166667


def test_late_full_fifo_updates_cash_only_after_all_fill_cash_is_final(tmp_path):
    _, journal, records, guard, kill, partial = world(tmp_path)
    guard.apply(GuardSnapshot(now=T0 + 300, fills=[partial]))
    remaining = FillRecord("polymarket", "f15-order", "remaining-cash", 4.166667,
                           .3599999712000023, .04801, True, T0 + 152, False,
                           market_id=TOK, side="buy_yes")
    journal.record_fill(remaining)
    guard.apply(GuardSnapshot(now=T0 + 301, fills=[remaining]))
    assert journal.get("a1")["filled_contracts"] == 10.166667
    assert journal.get("a1")["settlement_pending"] == 1
    journal.record_fill(replace(remaining, final=True))
    guard.apply(GuardSnapshot(now=T0 + 302, fills=[replace(remaining, final=True)]))
    row = journal.get("a1")
    assert row["filled_contracts"] == 10.166667 and row["settlement_pending"] == 0
    assert row["avg_price"] == pytest.approx(3.60 / 10.166667)
    assert row["fee_usd"] == pytest.approx(.11626)
    assert records.load("789ad9b2").first_avg_price == pytest.approx(3.60 / 10.166667)
    assert kill.active(live=True) == ["live"], "cash completion never clears the overfill stop"


def test_zero_or_reduced_fifo_is_not_an_implicit_reversal(tmp_path):
    _, journal, _, guard, _, partial = world(tmp_path)
    # A previously seen trade changing quantity or becoming provisional does not
    # certify an order-level reversal. No table deletion or negative-fill inference.
    journal.record_fill(replace(partial, contracts=0, final=False))
    guard.apply(GuardSnapshot(now=T0 + 300, fills=[replace(partial, contracts=0, final=False)]))
    row = journal.get("a1")
    assert row["filled_contracts"] == 10.166667 and row["settlement_pending"] == 1
    assert "explicit reversal required" in row["detail"]


def test_explicit_audited_reversal_can_reduce_quantity_without_clearing_historical_alarm(tmp_path):
    store, journal, records, guard, kill, partial = world(tmp_path)
    guard.apply(GuardSnapshot(now=T0 + 300, fills=[partial]))
    # The guard does not infer or manufacture this event. Model a separate,
    # venue-authoritative reversal already accepted by the reconciliation operator.
    reversal = {"venue_order_id": "f15-order", "event_id": "venue-reversal-1",
                "previous_contracts": "10.166667", "remaining_contracts": "6",
                "reversed_contracts": "4.166667", "status": "REVERSED"}
    journal.record(Ack("polymarket", "a1", "f15-order", FillState.PARTIAL, 6, .35, .06825,
                       "venue_reversal", T0 + 301), kind="venue_reversal", raw=reversal)
    guard.apply(GuardSnapshot(now=T0 + 302, fills=[partial]))
    assert journal.get("a1")["filled_contracts"] == 6
    assert journal.get("a1")["settlement_pending"] == 0
    assert records.load("789ad9b2").first_filled == 6
    events = store.con.execute("SELECT kind,raw_json FROM order_events WHERE client_order_id='a1'").fetchall()
    assert any(kind == "status" and json.loads(raw)["size_matched"] == "10.166667" for kind, raw in events if raw)
    assert any(kind == "venue_reversal" and json.loads(raw) == reversal for kind, raw in events if raw)
    assert kill.active(live=True) == ["live"]
