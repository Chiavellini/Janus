import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("l44_measure", Path(__file__).with_name("measure.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def event(*, closed=True, prices='["1", "0"]', description=None):
    return {"id": "e1", "slug": "itf-alice-bea-2026-08-01", "closed": closed,
            "closedTime": "2026-08-01T12:00:00Z" if closed else None,
            "markets": [{"sportsMarketType": "moneyline", "outcomes": '["Alice", "Bea"]',
                         "outcomePrices": prices, "closed": closed, "description": description or
                         "Originally scheduled for August 1, 2026 at 2:00AM ET."}]}


def test_open_and_half_are_included_as_adverse_even_without_winner():
    rows = [m.classify(event(closed=False), source_closed=False),
            m.classify(event(prices='["0.5", "0.5"]'), source_closed=True),
            m.classify(event(), source_closed=True)]
    result = m.summarize(rows, complete=True)
    assert result["mature_n"] == 3 and result["adverse"] == 2
    assert result["mature_reasons"] == {"MATURE_STILL_OPEN": 1, "HALF": 1, "WINNER_WITHIN_14D": 1}


def test_immature_winner_and_open_event_both_leave_denominator():
    for closed in (False, True):
        row = m.classify(event(closed=closed, description="Originally scheduled for September 8, 2026 at 2:00AM ET."), source_closed=closed)
        assert row["reason"] == "IMMATURE_AT_SNAPSHOT" and not row["denominator"]


def test_immature_bad_terminal_fields_still_fail_the_all_singles_parseability_gate():
    good = m.classify(event(), source_closed=True)
    bad_event = event(prices='["0.4", "0.6"]', description="Originally scheduled for September 8, 2026 at 2:00AM ET.")
    bad_event["closedTime"] = None
    bad = m.classify(bad_event, source_closed=True)
    assert not bad["denominator"] and not bad["parseable"]
    result = m.summarize([good] + [bad] * 99, complete=True)
    assert result["mature_n"] == 1 and result["parseability"] == 0.01
    assert result["gates"] == "FAIL" and result["registered_value"] is None
    assert result["unparseable_events"] == 99
    assert result["unparseable"] == {"AUTHORITATIVE_CLOSE_UNPARSEABLE": 99, "TERMINAL_RESULT_UNPARSEABLE": 99}


def test_authoritative_close_gate_uses_actual_payload_state_even_in_open_catalog():
    bad_event = event()
    bad_event["closedTime"] = None
    closed_payload = m.classify(bad_event, source_closed=False)
    opened = m.classify(event(closed=False), source_closed=False)
    result = m.summarize([closed_payload] + [opened] * 99, complete=True)
    assert result["parseability"] == 0.99 and result["actual_closed_candidates"] == 1
    assert result["gate_failures"] == ["AUTHORITATIVE_CLOSE_UNAVAILABLE"]


def test_all_open_population_fails_total_authoritative_close_absence():
    opened = m.classify(event(closed=False), source_closed=False)
    result = m.summarize([opened], complete=True)
    assert result["mature_n"] == 1 and result["adverse"] == 1
    assert result["parseability"] == 1.0 and result["actual_closed_candidates"] == 0
    assert result["gate_failures"] == ["AUTHORITATIVE_CLOSE_UNAVAILABLE"]
    assert result["registered_value"] is None


def test_missing_source_is_adverse_and_counts_against_parseability():
    bad = m.classify(event(description="No original time"), source_closed=True)
    assert bad["adverse"] and bad["denominator"] and not bad["parseable"]
    rows = [m.classify(event(), source_closed=True)] * 99 + [bad]
    result = m.summarize(rows, complete=True)
    assert result["parseability"] == 0.99 and result["adverse"] == 1 and result["gates"] == "PASS"
    assert result["registered_value"] > 0.01


def test_large_sample_never_registers_zero():
    rows = [m.classify(event(), source_closed=True)] * 1000
    assert m.summarize(rows, complete=True)["registered_value"] == pytest.approx(0.003)


@pytest.mark.parametrize("invalid", [None, "", "broken", "2026-08-01T12:00:00"])
def test_present_invalid_event_close_never_falls_back_to_valid_market_close(invalid):
    e = event()
    e["closedTime"] = invalid
    e["markets"][0]["closedTime"] = "2026-08-01T12:00:00Z"
    row = m.classify(e, source_closed=True)
    assert row["reason"] == "AUTHORITATIVE_CLOSE_UNPARSEABLE"
    assert row["adverse"] and row["denominator"] and not row["parseable"]
    del e["closedTime"]
    assert m.classify(e, source_closed=True)["reason"] == "WINNER_WITHIN_14D"


def test_catalog_payload_state_changes_remain_adverse_and_do_not_invent_close_parse_errors():
    opened = m.classify(event(closed=False), source_closed=True)
    assert opened["reason"] == "MATURE_STILL_OPEN" and opened["parseable"] and opened["catalog_state_mismatch"]
    closed = m.classify(event(closed=True), source_closed=False)
    assert closed["adverse"] and closed["reason"] == "CATALOG_STATE_MISMATCH"
    m.merge_transition(closed, opened)
    assert closed["adverse"] and closed["denominator"] and closed["reason"] == "CLOSED_OPEN_STATE_TRANSITION"


def test_transition_preserves_immature_exclusion():
    e = event(description="Originally scheduled for September 8, 2026 at 2:00AM ET.")
    row = m.classify(e, source_closed=True)
    m.merge_transition(row, m.classify(e, source_closed=False))
    assert row["reason"] == "IMMATURE_AT_SNAPSHOT" and not row["denominator"]


class Pages:
    def __init__(self, values):
        self.values = iter(values)
        self.params = []

    def get_json(self, url, params, use_cache):
        self.params.append(params)
        return next(self.values)


def test_cursor_is_passed_verbatim_and_short_page_does_not_end_crawl(tmp_path):
    cl = Pages([{"events": [{"id": "1"}], "next_cursor": "opaque=="},
                {"events": [{"id": "2"}], "next_cursor": "next"}, {"events": []}])
    assert len(list(m.enumerate_events(cl, tmp_path, closed=True))) == 2
    assert cl.params[1]["after_cursor"] == "opaque==" and "offset" not in cl.params[1]
    # Resumption verifies every saved request/hash and consumes no new network response.
    offline = Pages([])
    assert len(list(m.enumerate_events(offline, tmp_path, closed=True))) == 2
    assert not offline.params


def test_cursor_loop_and_duplicate_are_failures(tmp_path):
    cl = Pages([{"events": [{"id": "1"}], "next_cursor": "x"},
                {"events": [{"id": "2"}], "next_cursor": "x"}])
    with pytest.raises(ValueError, match="CURSOR_LOOP"):
        list(m.enumerate_events(cl, tmp_path, closed=True))
    cl = Pages([{"events": [{"id": "1"}, {"id": "1"}]}])
    with pytest.raises(ValueError, match="DUPLICATED_ID"):
        list(m.enumerate_events(cl, tmp_path, closed=False))


def test_json_null_event_id_fails_instead_of_becoming_a_string(tmp_path):
    cl = Pages([{"events": [{"id": None}], "next_cursor": None}])
    with pytest.raises(ValueError, match="MISSING_OR_DUPLICATED_ID"):
        list(m.enumerate_events(cl, tmp_path, closed=True))
