#!/usr/bin/env python3
"""Hermetic L21/L22 invariants — KXWTI ladder coherence and forward capture. No network."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_L21 = ROOT / "research/exec/2026-08-20_wti-ladder-coherence/measure.py"
_s = importlib.util.spec_from_file_location("l21_meas", _L21)
l21 = importlib.util.module_from_spec(_s)
_s.loader.exec_module(l21)

from collectors.collect_wti_ladder import (  # noqa: E402
    GAP_REASONS, Store, cycle, next_slot, rule_kind_of, selftest as collector_selftest,
)


def _mk(t, k, b, a, rules="the daily settlement price for WTI crude oil(October 2026 contract)"):
    return {"ticker": t, "strike_type": "greater", "floor_strike": k,
            "yes_bid_dollars": str(b), "yes_ask_dollars": str(a),
            "no_bid_dollars": str(round(1 - a, 4)), "no_ask_dollars": str(round(1 - b, 4)),
            "yes_bid_size_fp": "5", "yes_ask_size_fp": "5", "open_interest_fp": "1",
            "volume_fp": "1", "event_ticker": "E", "rules_primary": rules}


def test_l21_and_collector_selftests():
    l21.selftest()
    collector_selftest()


def test_a_mid_only_violation_is_never_counted_as_executable():
    """The phase-1 error that manufactured a 47c edge: scoring coherence at mid."""
    rungs = l21.build_ladder([_mk("A", 80.0, 0.40, 0.60), _mk("B", 81.0, 0.45, 0.65)])["rungs"]
    na = l21.no_arb(rungs, adjacent_only=True)
    assert na["executable_violations"] == []
    assert na["n_mid_only"] == 1
    assert l21.monotonicity(rungs)["mid"]["n_violations"] == 1


def test_sub_tick_edge_is_noise_not_a_violation():
    """A 1c tick puts +/-0.5c on each quote, so a sub-cent gross edge cannot be real."""
    rungs = l21.build_ladder([_mk("A", 80.0, 0.50, 0.520), _mk("B", 81.0, 0.525, 0.55)])["rungs"]
    na = l21.no_arb(rungs, adjacent_only=True)
    assert na["executable_violations"] == [] and len(na["within_tick_noise"]) == 1


def test_a_genuine_violation_is_reported_gross_and_fee_net():
    rungs = l21.build_ladder([_mk("A", 80.0, 0.40, 0.42), _mk("B", 81.0, 0.60, 0.62)])["rungs"]
    v = l21.no_arb(rungs, adjacent_only=True)["executable_violations"]
    assert len(v) == 1 and v[0]["gross"] == 0.18 and v[0]["fee_net_flat2c"] == 0.14


def test_out_of_range_price_raises_rather_than_clipping():
    """Trap 7: Kalshi returns decimal-dollar strings; a unit error must be loud."""
    try:
        l21.build_ladder([_mk("X", 80.0, 1.5, 1.6)])
    except ValueError:
        return
    raise AssertionError("price outside [0,1] was accepted")


def test_truncated_ladder_refuses_to_quote_an_implied_mean():
    narrow = l21.build_ladder([_mk("A", 80.0, 0.5, 0.6), _mk("B", 90.0, 0.4, 0.5)])["rungs"]
    assert l21.implied_mean(narrow, "mid")["status"] == "TRUNCATION_MATERIAL"


def test_front_month_events_are_tagged_and_never_given_a_named_month():
    """L21 measured that far-dated KXWTI settles on the FRONT-MONTH price -- a time-varying
    reference L20's CL-equivalence does not cover. Pooling it with named months is the error."""
    front = "the front-month settle price for a barrel of West Texas Intermediate oil"
    kind, month = rule_kind_of([_mk("A", 80, .9, .92, front)])
    assert kind == "front_month" and month is None
    kind, month = rule_kind_of([_mk("A", 80, .9, .92)])
    assert kind == "named_month" and month == "OCT 26"


def test_cl_delivery_month_maps_expiry_to_delivery():
    """CL Oct-26 stops trading ~2026-09-22, so delivery is the month AFTER expiration."""
    assert l21.cl_delivery_month("20260922") == "OCT 26"
    assert l21.cl_delivery_month("20261221") == "JAN 27"
    assert l21.cl_delivery_month("nonsense") is None


def test_every_slot_writes_exactly_one_row_even_when_the_source_fails():
    """Phase A lost two days to absences that looked like silence. A gap must be a ROW."""
    import tempfile

    class Boom:
        def paginate_cursor(self, *a, **k):
            raise RuntimeError("kalshi down")

    with tempfile.TemporaryDirectory() as d:
        st = Store(Path(d) / "t.sqlite", enforce_root=False)
        r = cycle(st, Boom(), 500.0)
        assert r["reason"] == "KALSHI_ERROR"
        rows = st.con.execute("SELECT ok, reason FROM snapshots WHERE slot_ts=500.0").fetchall()
        assert rows == [(0, "KALSHI_ERROR")]


def test_unregistered_gap_reason_and_identifier_text_are_both_refused():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        st = Store(Path(d) / "t.sqlite", enforce_root=False)
        for bad in ("MADE_UP", "oops"):
            try:
                st.snapshot(slot_ts=1.0, ok=False, reason=bad)
                raise AssertionError(f"gap reason {bad} accepted")
            except ValueError:
                pass
        assert "FRONT_MONTH_RULE" in GAP_REASONS
        try:
            st.health("c", "s", "acctId=U1234567")
            raise AssertionError("identifier text persisted")
        except ValueError:
            pass


def test_store_refuses_the_root_disk():
    try:
        Store(Path("/tmp/nope.sqlite"))
    except ValueError:
        return
    raise AssertionError("L22 data was allowed off /Volumes/Kilos")


def test_slot_grid_is_aligned():
    assert next_slot(1000.0, 300.0) == 1200.0
    assert next_slot(1200.0, 300.0) == 1500.0


# ── L23 commodity term-structure classifier ─────────────────────────────────

_L23 = ROOT / "research/exec/2026-08-20_commodity-term-structure/measure.py"
_s23 = importlib.util.spec_from_file_location("l23_meas", _L23)
l23 = importlib.util.module_from_spec(_s23)
_s23.loader.exec_module(l23)


def test_l23_selftest():
    l23.selftest()


def test_a_named_source_always_beats_the_unnamed_candlestick_fallback():
    """KXNATGASD and KXGOLDD use the SAME candlestick construct; only one names Pyth. If the
    fallback ever outranked a named source, that real distinction would vanish."""
    assert l23.classify_reference("1-minute candlestick for natural gas", "per Pyth") == "PYTH_INDEX"
    assert l23.classify_reference("the close price of the 1-minute candlestick for gold",
                                  "rounded to 2 decimal places") == "CANDLESTICK_UNNAMED_SOURCE"


def test_dormant_series_do_not_poison_a_group_verdict():
    """46 series have no markets. Counting them as UNPARSEABLE flipped four groups to
    INSUFFICIENT_RULES on the first pass."""
    g = l23.group_verdict([{"reference_class": "PYTH_INDEX"},
                           {"reference_class": "NO_MARKETS_TO_SAMPLE"}])
    assert g["verdict"] == "COMPARABLE" and g["n_dormant_cadences"] == 1
    assert l23.group_verdict([{"reference_class": "NO_MARKETS_TO_SAMPLE"}])["verdict"] == "NO_LIVE_MARKETS"


def test_mixed_references_block_the_calendar_spread():
    g = l23.group_verdict([{"reference_class": "NAMED_MONTH_FUTURES"},
                           {"reference_class": "PYTH_INDEX"}])
    assert g["verdict"] == "CROSS_CADENCE_BLOCK"


def test_metadata_conflict_catches_a_source_naming_another_commodity():
    """Observed live: KXWHEATMON advertises 'Trading Economics - Corn'."""
    assert l23.metadata_conflict("Trading Economics - Corn", "THIRD_PARTY_QUOTE", "Wheat Monthly")
    assert not l23.metadata_conflict("Trading Economics - Corn", "THIRD_PARTY_QUOTE", "Corn Monthly")


def test_contract_roll_is_detected():
    """A rolling reference is a different economic object from a spot print."""
    assert l23.has_contract_roll("x", "rolling forward to the next contract 5 business days before")
    assert l23.has_contract_roll("settled on the nearest listed contract month")
    assert not l23.has_contract_roll("the close price of the 1-minute candlestick")
