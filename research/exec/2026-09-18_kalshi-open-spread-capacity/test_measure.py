"""Pins for L152. Pure functions and a synthetic end-to-end run; nothing here touches the network."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("l152_measure", Path(__file__).with_name("measure.py"))
m = importlib.util.module_from_spec(_spec)
sys.modules["l152_measure"] = m
_spec.loader.exec_module(m)


# ── the fee is the project's own pin ─────────────────────────────────────────────────────────────
def test_the_maker_fee_is_the_repos_kalshi_pin_not_a_new_number():
    from nodes.fees.models import KalshiQuadratic
    assert KalshiQuadratic.maker_coeff == 0.0175
    assert m.kalshi_maker_fee(0.5) == pytest.approx(0.0175 * 0.25)
    assert m.kalshi_maker_fee(0.1) == pytest.approx(0.0175 * 0.09)


# ── what counts as quotable ──────────────────────────────────────────────────────────────────────
def test_a_wide_spread_with_the_pm_mid_inside_is_quotable_and_nets_its_fee():
    # Kalshi 0.40/0.60 (20c), PM mid 0.50: one tick inside the nearer touch is 0.09, less the fee.
    e = m.quote_edge(0.40, 0.60, 0.49, 0.51, 0.10)
    assert e == pytest.approx(0.09 - 0.0175 * 0.25)


def test_a_spread_below_the_threshold_is_not_quotable():
    assert m.quote_edge(0.47, 0.52, 0.49, 0.51, 0.06) is None          # 5c < 6c
    assert m.quote_edge(0.46, 0.52, 0.49, 0.51, 0.06) is not None      # 6c counts


def test_a_pm_mid_outside_kalshis_touches_is_not_quotable():
    """The quote must IMPROVE both of Kalshi's touches around fair value, or it is not a market."""
    assert m.quote_edge(0.40, 0.60, 0.60, 0.70, 0.06) is None          # mid 0.65 above the ask
    assert m.quote_edge(0.40, 0.60, 0.59, 0.61, 0.06) is None          # mid AT the ask, not inside


def test_a_side_that_cannot_clear_its_fee_earns_nothing_rather_than_a_loss():
    """Mid sits one tick inside the bid: h = 0 after the tick, so the edge floors at zero."""
    assert m.quote_edge(0.40, 0.60, 0.40, 0.42, 0.06) == 0.0


def test_missing_prices_are_not_quotable():
    assert m.quote_edge(None, 0.60, 0.49, 0.51, 0.06) is None
    assert m.quote_edge(0.60, 0.40, 0.49, 0.51, 0.06) is None          # crossed book


# ── buckets, start time, matching ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("age,name", [(0, "0-5 min"), (299, "0-5 min"), (300, "5-30 min"),
                                      (7199, "30 min-2 h"), (7200, "2-6 h"), (21600, "6-24 h"),
                                      (86400, ">24 h"), (None, None)])
def test_every_age_lands_in_exactly_its_registered_bucket(age, name):
    assert m.bucket(age) == name


def test_the_game_start_is_read_from_the_ticker_in_eastern_time():
    # 26AUG231910 -> 2026-08-23 19:10 EDT = 23:10 UTC
    from datetime import datetime, timezone
    t = m.game_start_utc("KXMLBGAME-26AUG231910ATLMIL-MIL")
    assert datetime.fromtimestamp(t, timezone.utc) == datetime(2026, 8, 23, 23, 10, tzinfo=timezone.utc)
    assert m.game_start_utc("garbage") is None


def test_a_trade_matches_only_the_latest_sample_within_120_seconds():
    times = [100.0, 200.0, 300.0]
    assert m.latest_before(times, 250.0) == 1
    assert m.latest_before(times, 200.0) == 1          # at or before
    assert m.latest_before(times, 99.0) is None        # before any sample
    assert m.latest_before(times, 421.0) is None       # 121 s after the last one
    assert m.latest_before(times, 420.0) == 2


# ── the registered verdict ───────────────────────────────────────────────────────────────────────
def _ceil(v25_6, v25_10, v50_6, v50_10):
    return {(0.06, 0.10): 0, (0.10, 0.10): 0, (0.06, 0.25): v25_6, (0.10, 0.25): v25_10,
            (0.06, 0.50): v50_6, (0.10, 0.50): v50_10}


def test_the_verdict_boundaries_are_the_registered_ones():
    assert m.verdict(_ceil(50, 0, 100, 0), 500)[0] == "STRONG_LEAD"
    assert m.verdict(_ceil(49.99, 0, 99, 0), 500)[0] == "WEAK_LEAD"
    assert m.verdict(_ceil(10, 0, 14.99, 0), 500)[0] == "DEAD"
    assert m.verdict(_ceil(10, 0, 15, 0), 500)[0] == "WEAK_LEAD"      # 25% under 15, 50% reaches it
    assert m.verdict(_ceil(500, 500, 900, 900), 99)[0] == "DEAD", "too little flow trumps any ceiling"


def test_every_verdict_reason_says_ceiling_when_it_quotes_dollars():
    for c, vol in ((_ceil(60, 0, 90, 0), 500), (_ceil(20, 0, 30, 0), 500), (_ceil(1, 0, 2, 0), 500)):
        name, why = m.verdict(c, vol)
        assert "CEILING" in why, (name, why)


# ── end to end on a synthetic market ─────────────────────────────────────────────────────────────
def test_the_ceiling_is_edge_times_contracts_times_share_per_day():
    """One market, one day of samples every 60 s, Kalshi 0.40/0.60 with PM mid 0.50 throughout, and
    1,000 contracts trading. Edge = 0.09 - 0.004375 = 0.085625; at 25 % that is $21.40625 a day."""
    day = 86400.0
    samples = {"KXMLBGAME-26AUG231910ATLMIL-MIL":
               [(t, 0.40, 0.60, 0.49, 0.51, 1000.0 + t) for t in range(0, int(day) + 1, 60)]}
    trades = {"KXMLBGAME-26AUG231910ATLMIL-MIL":
              [{"ts": 30.0 + 60.0 * k, "count": 10.0, "yes_price": 0.5, "taker_side": "yes"} for k in range(100)]}
    out = m.measure(samples, trades, [])
    edge = 0.09 - 0.0175 * 0.25
    assert out["coverage"]["days"] == pytest.approx(1.0, abs=1e-6)
    assert out["contracts_per_day_traded_while_quotable"]["10c"] == pytest.approx(1000.0)
    assert out["CEILING_usd_per_day"]["10c@25%"] == pytest.approx(edge * 1000 * 0.25, rel=1e-4)
    assert out["CEILING_usd_per_day"]["10c@50%"] == pytest.approx(edge * 1000 * 0.50, rel=1e-4)
    assert out["required_filled_contracts_per_day_for_50usd"]["10c"] == pytest.approx(round(50 / edge), abs=1)
    assert out["verdict"] == "WEAK_LEAD"


def test_trades_outside_the_sampled_period_or_unmatched_are_never_counted():
    samples = {"KXMLBGAME-26AUG231910ATLMIL-MIL": [(1000.0, 0.40, 0.60, 0.49, 0.51, 500.0),
                                                   (2000.0, 0.40, 0.60, 0.49, 0.51, 1500.0)]}
    trades = {"KXMLBGAME-26AUG231910ATLMIL-MIL": [
        {"ts": 500.0, "count": 999.0, "yes_price": 0.5, "taker_side": "yes"},    # before the period
        {"ts": 1500.0, "count": 999.0, "yes_price": 0.5, "taker_side": "yes"},   # 500 s gap: unmatched
        {"ts": 1050.0, "count": 7.0, "yes_price": 0.5, "taker_side": "yes"}]}    # matched
    out = m.measure(samples, trades, [])
    assert out["coverage"]["trades_matched_to_a_sample_within_120s"] == 1
    total = sum(v["contracts_traded_while_quotable"]["10c"] for v in out["by_age_since_open"].values())
    assert total == pytest.approx(7.0)


def test_the_reader_is_read_only():
    src = Path(__file__).with_name("measure.py").read_text()
    assert src.count("mode=ro") >= 2
    for forbidden in ("INSERT", "UPDATE ", "DELETE ", "CREATE "):
        assert forbidden not in src


# ── L153: the robustness check ───────────────────────────────────────────────────────────────────
_rspec = importlib.util.spec_from_file_location("l153_robustness", Path(__file__).with_name("robustness.py"))
r = importlib.util.module_from_spec(_rspec)
sys.modules["l153_robustness"] = r
_rspec.loader.exec_module(r)


def test_a_trade_is_consistent_only_when_it_printed_at_the_touch_its_side_takes():
    assert r.consistent({"taker_side": "yes", "yes_price": 0.60}, 0.40, 0.60)        # lifted the ask
    assert r.consistent({"taker_side": "no", "yes_price": 0.40}, 0.40, 0.60)         # hit the bid
    assert r.consistent({"taker_side": "yes", "yes_price": 0.61}, 0.40, 0.60)        # within a tick
    assert not r.consistent({"taker_side": "yes", "yes_price": 0.50}, 0.40, 0.60)    # book had moved
    assert not r.consistent({"taker_side": "no", "yes_price": 0.60}, 0.40, 0.60)     # wrong touch
    assert not r.consistent({"taker_side": None, "yes_price": 0.60}, 0.40, 0.60)


def test_inconsistent_trades_are_removed_from_the_ceiling():
    day = 86400.0
    samples = {"KXMLBGAME-26AUG231910ATLMIL-MIL":
               [(t, 0.40, 0.60, 0.49, 0.51, 1000.0 + t) for t in range(0, int(day) + 1, 60)]}
    good = [{"ts": 30.0 + 60 * k, "count": 10.0, "yes_price": 0.60, "taker_side": "yes"} for k in range(50)]
    moved = [{"ts": 31.0 + 60 * k, "count": 10.0, "yes_price": 0.50, "taker_side": "yes"} for k in range(50)]
    out = r.run(samples, {"KXMLBGAME-26AUG231910ATLMIL-MIL": good + moved})["by_threshold"]["10c"]
    assert out["capturable_contracts_L152"] == 1000.0 and out["consistent_contracts"] == 500.0
    assert out["consistent_share"] == 0.5
    edge = 0.09 - 0.0175 * 0.25
    assert out["CEILING_usd_per_day_consistent"]["25%"] == pytest.approx(edge * 500 * 0.25, rel=1e-3)


def test_the_tight_window_keeps_only_trades_within_ten_seconds_of_their_sample():
    samples = {"KXMLBGAME-26AUG231910ATLMIL-MIL": [(1000.0, 0.40, 0.60, 0.49, 0.51, 500.0),
                                                   (2000.0, 0.40, 0.60, 0.49, 0.51, 1500.0)]}
    trades = [{"ts": 1005.0, "count": 4.0, "yes_price": 0.60, "taker_side": "yes"},
              {"ts": 1090.0, "count": 6.0, "yes_price": 0.60, "taker_side": "yes"}]
    out = r.run(samples, {"KXMLBGAME-26AUG231910ATLMIL-MIL": trades})["by_threshold"]["10c"]
    assert out["consistent_contracts"] == 10.0
    total_tight = out["CEILING_usd_per_day_consistent_within_10s"]["50%"]
    total_all = out["CEILING_usd_per_day_consistent"]["50%"]
    assert total_tight == pytest.approx(total_all * 4 / 10, rel=1e-3)
