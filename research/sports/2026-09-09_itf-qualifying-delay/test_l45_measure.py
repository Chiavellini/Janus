import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("l45_measure", Path(__file__).with_name("measure.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def event(*, qualifying):
    stage = "Qualifying" if qualifying else "Main Draw"
    return {"id": "1", "slug": "itf-a-b-2026-08-01", "closed": True,
            "closedTime": "2026-08-01T12:00:00Z",
            "markets": [{"sportsMarketType": "moneyline", "outcomes": '["Alice", "Bea"]',
                         "outcomePrices": '["1", "0"]', "closed": True,
                         "description": f"In the W15 Test, {stage}, originally scheduled for August 1, 2026 at 2:00AM ET."}]}


def test_qualifying_and_main_draw_populations_do_not_overlap():
    for qualifying in (False, True):
        main = m.l44.classify(event(qualifying=qualifying), source_closed=True)
        qual = m.l44.classify(event(qualifying=qualifying), source_closed=True, qualifying_population=True)
        assert main["denominator"] != qual["denominator"]
        assert qual["denominator"] is qualifying


def test_qualifying_missing_timestamp_is_adverse_and_not_transferred_from_main_draw():
    e = event(qualifying=True)
    e["closedTime"] = ""
    e["markets"][0]["closedTime"] = "2026-08-01T12:00:00Z"
    row = m.l44.classify(e, source_closed=True, qualifying_population=True)
    assert row["adverse"] and not row["parseable"]
    assert m.l44.summarize([row], complete=True)["registered_value"] is None


def test_incomplete_qualifying_archive_cannot_fetch_or_pass(tmp_path):
    with pytest.raises(ValueError, match="NETWORK_FORBIDDEN"):
        list(m.l44.enumerate_events(m.OfflineOnly(), tmp_path, closed=True))


def test_immature_qualifiers_still_count_against_required_field_parseability():
    good = m.l44.classify(event(qualifying=True), source_closed=True, qualifying_population=True)
    e = event(qualifying=True)
    e["markets"][0]["description"] = "Qualifying, originally scheduled for September 8, 2026 at 2:00AM ET."
    e["closedTime"] = None
    bad = m.l44.classify(e, source_closed=True, qualifying_population=True)
    results = m.l44.summarize([good] + [bad] * 99, complete=True)
    assert results["parseability"] == 0.01 and results["mature_n"] == 1
    assert results["registered_value"] is None
