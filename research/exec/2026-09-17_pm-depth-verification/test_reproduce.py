"""L146 pins.

Each test asserts the behaviour the deployed code was OBSERVED to exhibit. They are written so that a
future fix to the Polymarket depth-verification defect breaks them visibly -- which is the point: a
fix should be accompanied by flipping these assertions, not by deleting them.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from nodes.stream_polymarket.reconcile import due
from nodes.stream_polymarket.stream import PolymarketStream

_spec = importlib.util.spec_from_file_location("l146_reproduce", Path(__file__).with_name("reproduce.py"))
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)


# ── the controls come first: if these fail, nothing else may be concluded ─────────────────────
def test_c1_the_same_lost_update_at_the_touch_is_caught():
    c1 = rp.c1_touch_level_is_caught()
    assert c1["caught"] is True
    assert c1["drift_counted"] == 1 and c1["last_fault"] == "HASH_MISMATCH"
    assert c1["resnapshot_requested"] is True


def test_c2_a_kalshi_sequence_gap_is_caught():
    c2 = rp.c2_kalshi_sequence_gap_is_caught()
    assert c2["caught"] is True
    assert c2["handle_returned"] == "gap" and c2["last_fault"] == "SEQ_GAP"


# ── the defect ──────────────────────────────────────────────────────────────────────────────
def test_r1_a_phantom_level_below_the_touch_survives_sixty_verified_updates():
    r1 = rp.r1_phantom_depth_survives_verification()
    assert r1["phantom_level_present"] and not r1["venue_truth_has_level"]
    assert r1["agreement_checks"] == 60 and r1["drift_counted"] == 0
    assert r1["any_fault"] is False, "the book was reported healthy throughout"
    assert r1["ever_due_for_rest"] is False, "the REST backstop never selected it"
    assert r1["verified_utc_advanced_to"] == rp.T + 60, "every agreeing update re-verified it"


def test_r2_the_size_at_the_touch_is_never_compared():
    r2 = rp.r2_touch_size_unchecked()
    assert r2["touch_size_local"] != r2["touch_size_venue"]
    assert r2["stale_book_agrees"] is True and r2["true_book_agrees"] is True
    assert r2["stream_drift_counted"] == 0 and r2["replica_touch_size_after"] == 8.0
    assert r2["replica_fault"] is None


def test_r3_a_rest_correction_is_undone_by_the_next_update():
    r3 = rp.r3_rest_correction_overwritten()
    assert r3["due_before_reconcile"] is True
    after = r3["after_reconcile"]
    assert after["asks_equal_truth"] and after["source"] == "rest" and after["rest_drift"] == 1
    assert after["stream_ladder_still_has_phantom"], "REST never reached ps.books"
    back = r3["after_one_update"]
    assert back["phantom_level_present"] and back["source"] == "ws" and back["fault"] is None
    assert r3["correction_survived"] is False


def test_agreeing_traffic_is_the_only_thing_that_keeps_the_book_out_of_reconciliation():
    """Isolates the cause. Same book, same 20 seconds; the only difference is the traffic."""
    def after_20s(traffic: bool) -> bool:
        s, r = PolymarketStream(), rp._replica()
        s.register(rp.A, r)
        s.handle(rp.BOOK_DEEP, now=rp.T)
        for i in range(1, 21):
            s.handle(rp.change(0.18, 4, "BUY", bb=0.19, ba=0.20) if traffic else "PONG",
                     now=rp.T + i)
        return rp.A in due(s.regs, rp.T + 20)

    assert after_20s(traffic=False) is True, "a quiet book is reconciled"
    assert after_20s(traffic=True) is False, "an equally stale but active book is not"


def test_the_phantom_level_makes_the_book_look_cheaper_for_a_buyer():
    """Direction only. The magnitude depends on the constructed ladders and is not an estimate."""
    econ = rp.r1_phantom_depth_survives_verification()["economics"]
    assert econ["illustrative_only"] is True
    assert econ["truth_minus_stale_c"] > 0, "the stale book understates what 25 contracts cost"


def test_the_registered_outcome_is_defect_reproduced():
    out = rp.run()
    assert out["defective"] == {"R1": True, "R2": True, "R3": True}
    assert out["verdict"] == "DEFECT_REPRODUCED"
    assert out["schema"] == "janus.l146.pm_depth_verification.v1"


# ── the outcome rule itself ─────────────────────────────────────────────────────────────────
def _obs():
    return (rp.r1_phantom_depth_survives_verification(), rp.r2_touch_size_unchecked(),
            rp.r3_rest_correction_overwritten(), rp.c1_touch_level_is_caught(),
            rp.c2_kalshi_sequence_gap_is_caught())


def test_a_failing_control_invalidates_the_harness_whatever_r1_to_r3_say():
    r1, r2, r3, c1, c2 = _obs()
    assert rp.verdict(r1, r2, r3, {**c1, "caught": False}, c2)[0] == "HARNESS_INVALID"
    assert rp.verdict(r1, r2, r3, c1, {**c2, "caught": False})[0] == "HARNESS_INVALID"


def test_a_mixed_result_is_partial_and_an_all_clear_result_is_refuted():
    r1, r2, r3, c1, c2 = _obs()
    healthy_r1 = {**r1, "any_fault": True}
    assert rp.verdict(healthy_r1, r2, r3, c1, c2)[0] == "PARTIAL"
    healthy_r2 = {**r2, "stale_book_agrees": False}
    healthy_r3 = {**r3, "correction_survived": True}
    assert rp.verdict(healthy_r1, healthy_r2, healthy_r3, c1, c2)[0] == "DEFECT_REFUTED"
