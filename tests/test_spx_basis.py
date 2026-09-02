#!/usr/bin/env python3
"""Hermetic L14 invariants — S&P settlement-reference basis. No network.

These lock the parts of the measurement that could silently produce a wrong "the references
agree" answer: the pre-registered inclusion filter, the within-event consistency STOP, the
relay-disagreement handling, the coverage gate, and the verdict rule at its exact boundary.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_SRC = ROOT / "research/exec/2026-08-19_spx-settlement-basis/measure_spx_basis.py"
_spec = importlib.util.spec_from_file_location("measure_spx_basis", _SRC)
mb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mb)


def _mkt(**kw):
    m = {"ticker": "KXINX-26AUG18H1600-T7691.9999", "event_ticker": "KXINX-26AUG18H1600",
         "series_ticker": "KXINX", "close_time": "2026-08-18T20:00:00Z",
         "expiration_value": "7691.76",
         "rules_primary": "If the end-of-day S&P 500 index value on Aug 18, 2026 is above 7691.9999"}
    m.update(kw)
    return m


def test_selftest_passes():
    mb.selftest()


def test_1600_et_filter_survives_the_dst_offset():
    """close_time is UTC; 16:00 ET is 20:00Z in summer and 21:00Z in winter. A naive UTC-hour
    filter would silently drop every winter expiry — a seasonal, invisible sample bias."""
    assert mb.closes_at_1600_et("2026-08-18T20:00:00Z")      # EDT
    assert mb.closes_at_1600_et("2026-01-15T21:00:00Z")      # EST
    assert not mb.closes_at_1600_et("2026-01-15T20:00:00Z")  # 15:00 ET, an hourly strike
    assert not mb.closes_at_1600_et("")


def test_rules_filter_requires_both_the_close_and_the_index():
    assert mb.rules_state_eod_sp500("the end-of-day S&P 500 index value on Aug 18, 2026")
    assert mb.rules_state_eod_sp500("the closing value of the S&P 500")
    # names the index but not the close -> an intraday strike, excluded
    assert not mb.rules_state_eod_sp500("the S&P 500 index value at 10:00 AM")
    # names a close but not this index -> a different market entirely
    assert not mb.rules_state_eod_sp500("the end-of-day Nasdaq-100 value")
    assert not mb.rules_state_eod_sp500(None)


def test_hourly_markets_are_bucketed_not_dropped():
    """Trap 2's shape: an excluded observation must be counted, never absent."""
    sel = mb.select_markets([_mkt(ticker="H", event_ticker="E2",
                                  close_time="2026-08-18T14:00:00Z")])
    assert len(sel["hourly"]) == 1 and sel["hourly"][0]["reason"] == "NOT_1600_ET"
    assert sel["included"] == []


def test_missing_expiration_value_is_a_reason_coded_rejection():
    sel = mb.select_markets([_mkt(expiration_value=None)])
    assert sel["rejected"][0]["reason"] == "NO_EXPIRATION_VALUE"


def test_within_event_disagreement_stops_rather_than_averages():
    """If two markets in one event disagree on expiration_value, our reading of the field is
    falsified. Averaging them would manufacture a settlement value that nobody published."""
    sel = mb.select_markets([_mkt(ticker="A"), _mkt(ticker="B", expiration_value="7691.77")])
    d = mb.dedupe_by_date(sel["included"])
    assert d["event_stops"] and d["date_stops"]
    assert "2026-08-18" not in d["values"]
    assert mb.verdict(mb.summarize([]), d)["verdict"] == mb.STOP_WITHIN_EVENT


def test_agreeing_markets_collapse_to_one_value_per_date():
    sel = mb.select_markets([_mkt(ticker="A"), _mkt(ticker="B")])
    d = mb.dedupe_by_date(sel["included"])
    assert d["values"] == {"2026-08-18": 7691.76} and not d["date_stops"]


def test_relay_disagreement_is_excluded_and_counted_not_averaged():
    k = {"2026-07-01": 7000.0}
    rows = mb.join_relays(k, {"2026-07-01": 7000.0}, {"2026-07-01": 7005.0})
    assert rows[0]["status"] == "RELAY_DISAGREE"
    assert rows[0]["official_close"] is None and rows[0]["diff"] is None
    s = mb.summarize(rows)
    assert s["n_relay_disagree"] == 1 and s["n_dates_headline"] == 0


def test_single_relay_is_reported_but_kept_out_of_the_headline():
    k = {"2026-07-01": 7000.0}
    rows = mb.join_relays(k, {"2026-07-01": 7000.0}, {})
    assert rows[0]["status"] == "SINGLE_RELAY"
    s = mb.summarize(rows)
    assert s["n_single_relay"] == 1 and s["n_dates_headline"] == 0


def _n_dates(n, offset=0.0):
    k = {f"2026-07-{i:02d}": 7000.0 + i for i in range(1, n + 1)}
    r = {d: v + offset for d, v in k.items()}
    return mb.join_relays(k, r, dict(r))


def test_coverage_gate_is_the_pre_registered_20():
    assert mb.verdict(mb.summarize(_n_dates(19)), {})["verdict"] == "INSUFFICIENT_COVERAGE"
    assert mb.verdict(mb.summarize(_n_dates(20)), {})["verdict"] == "REFERENCE_BASIS_MEASURED_ZERO"


def test_coverage_failure_quotes_no_distribution():
    v = mb.verdict(mb.summarize(_n_dates(5)), {})
    assert v["pair_status"] == "BLOCK"


def test_verdict_boundary_on_the_exact_fraction():
    """19/20 exact = 0.95 passes; 18/20 = 0.90 does not. The rule is not re-tuned after the fact."""
    rows = _n_dates(20)
    # a sub-cent difference still counts as equal; both sides publish 2dp, so the exact-.005
    # tie never occurs in the data and is deliberately not tested at that knife edge
    rows[0]["kalshi"] += 0.001
    s = mb.summarize(rows)
    assert s["frac_exactly_equal"] == 1.0

    rows = _n_dates(20)
    rows[0]["kalshi"] += 0.5
    rows[0]["diff"] = round(rows[0]["kalshi"] - rows[0]["official_close"], 6)
    s = mb.summarize(rows)
    assert s["frac_exactly_equal"] == 0.95 and s["max_abs"] > mb.MAX_ABS_ALLOWED
    # frac passes but max_abs fails -> BOTH conditions are required
    assert mb.verdict(s, {})["verdict"] == "REFERENCE_BASIS_MEASURED_NONZERO"


def test_a_measured_wedge_keeps_the_pair_blocked():
    v = mb.verdict(mb.summarize(_n_dates(25, offset=-1.5)), {})
    assert v["verdict"] == "REFERENCE_BASIS_MEASURED_NONZERO" and v["pair_status"] == "BLOCK"


def test_unreachable_relays_are_an_access_result_never_agreement():
    v = mb.verdict(mb.summarize(mb.join_relays({f"2026-07-{i:02d}": 7000.0
                                                for i in range(1, 26)}, {}, {})), {})
    assert v["verdict"] == "REFERENCE_SOURCE_UNAVAILABLE" and v["pair_status"] == "BLOCK"


def test_gates_match_the_registered_spec_text():
    """The constants in code must equal the immutable ones in spec.yaml."""
    spec = (ROOT / "research/exec/2026-08-19_spx-settlement-basis/spec.yaml").read_text()
    assert "min_settlement_dates: 20" in spec and mb.MIN_DATES == 20
    assert "frac_exactly_equal >= 0.95" in spec and mb.EXACT_FRAC_REQUIRED == 0.95
    assert "max_abs <= 0.01" in spec and mb.MAX_ABS_ALLOWED == 0.01


# ── L15 (per-series) ─────────────────────────────────────────────────────────

_L15 = ROOT / "research/exec/2026-08-19_spx-settlement-basis-per-series/measure.py"
_s15 = importlib.util.spec_from_file_location("measure_per_series", _L15)
ps = importlib.util.module_from_spec(_s15)
_s15.loader.exec_module(ps)


def test_per_series_selftest_passes():
    ps.selftest()


def test_series_are_never_pooled():
    """L14's STOP: two series publish different values for one date. Pooling them would average
    away the very quantity that stopped it."""
    inc = [{"ticker": "KXINX-A", "series_ticker": "KXINX", "settlement_date": "2026-07-07",
            "expiration_value": 7503.85, "event_ticker": "E1"},
           {"ticker": "KXINXU-A", "series_ticker": "KXINXU", "settlement_date": "2026-07-07",
            "expiration_value": 7503.74, "event_ticker": "E2"}]
    d = ps.dedupe_per_series(inc)
    assert not d["stops"]
    assert d["values"]["KXINX"]["2026-07-07"] != d["values"]["KXINXU"]["2026-07-07"]
    assert ps.series_wedge(d["values"])["max_abs"] == 0.11


def test_within_series_date_disagreement_still_stops():
    inc = [{"ticker": "A", "series_ticker": "KXINX", "settlement_date": "2026-07-07",
            "expiration_value": 7503.85, "event_ticker": "E1"},
           {"ticker": "B", "series_ticker": "KXINX", "settlement_date": "2026-07-07",
            "expiration_value": 7503.99, "event_ticker": "E1"}]
    d = ps.dedupe_per_series(inc)
    assert "KXINX|2026-07-07" in d["stops"]
    v = ps.verdict_for_series(ps.summarize([]), list(d["stops"]))
    assert v["verdict"] == "WITHIN_SERIES_DATE_DISAGREEMENT" and v["status"] == "BLOCK"


def test_an_html_body_raises_rather_than_reading_as_an_empty_series():
    """The defect L14 exposed: stooq answered 200 with a JS anti-bot page and the run reported
    'no observations'. A blocked source and a missing source must not look the same."""
    for parse in (ps.parse_fred, ps.parse_yahoo):
        try:
            parse("<html><body>are you a robot</body></html>")
        except ps.SourceUnparseable:
            continue
        raise AssertionError(f"{parse.__name__} accepted an HTML body")


def test_a_200_that_parses_to_nothing_also_raises():
    try:
        ps.parse_fred("observation_date,SP500\n2026-01-02,.\n")
    except ps.SourceUnparseable:
        return
    raise AssertionError("empty FRED series accepted")


def test_confidence_interval_actually_computes():
    """block_bootstrap_ci returns a DICT; unpacking it as a tuple silently degraded the CI to
    None. The spec names the CI as a reported statistic, so it must be present."""
    k = {f"2026-07-{i:02d}": 7000.0 + i for i in range(1, 26)}
    off = {d: v - 0.2 for d, v in k.items()}
    s = ps.summarize(ps.join_reference(k, off, dict(off)))
    assert s["ci95"] is not None and "ci95_error" not in s
    assert s["ci95"][0] <= s["median"] <= s["ci95"][1]
