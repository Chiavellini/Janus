import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("itf_l42_measure", Path(__file__).with_name("measure.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def event(**changes):
    market = {"id": "m1", "sportsMarketType": "moneyline", "closed": True,
              "outcomes": '["Alice Player", "Bea Player"]', "outcomePrices": '["1", "0"]',
              "description": "Originally scheduled for September 1, 2026 at 2:00AM ET.",
              "gameStartTime": "2026-09-01T06:00:00Z"}
    market.update(changes)
    return {"id": "e1", "slug": "itf-alice-bea-2026-09-01", "closed": True,
            "title": "W15 Test: Alice Player vs Bea Player", "closedTime": "2026-09-01T09:00:00Z",
            "markets": [market]}


def test_uses_original_description_and_close_not_rewritten_game_start_or_end_date():
    e = event(gameStartTime="2026-09-15T06:00:01Z")
    e.update(closedTime="2026-09-15T06:00:01Z", endDate="2026-10-01T00:00:00Z")
    row = m.classify(e)
    assert row["delayed_gt14d"] and row["elapsed_seconds"] == 14 * 86400 + 1
    e["closedTime"] = "2026-09-15T06:00:00Z"
    assert not m.classify(e)["delayed_gt14d"]
    del e["closedTime"]
    assert m.classify(e)["reason"] == "AUTHORITATIVE_CLOSE_UNPARSEABLE"


def test_market_close_is_used_only_when_event_close_absent():
    e = event(closedTime="2026-09-01 09:00:00+00")
    del e["closedTime"]
    assert m.classify(e)["close_source"] == "market.closedTime"
    e["closedTime"] = "broken"
    assert m.classify(e)["reason"] == "AUTHORITATIVE_CLOSE_UNPARSEABLE"


def test_half_is_separate_and_nonterminal_prices_cannot_be_a_winner():
    row = m.classify(event(outcomePrices='["0.5", "0.5"]'))
    assert row["result"] == "HALF" and not row["delayed_gt14d"]
    assert m.classify(event(outcomePrices='["1", "0.2"]'))["reason"] == "TERMINAL_RESULT_UNPARSEABLE"


def test_exclusion_denominators_distinguish_structure_from_missing_evidence():
    rows = [m.classify(event()), m.classify(event(description="Scheduled at some time")),
            m.classify(event(outcomes='["Alice / Cara", "Bea / Dana"]'))]
    result = m.summarize(rows, complete=True)
    assert result["candidate_singles"] == 2 and result["parseability"] == 0.5
    assert result["registered_value"] is None and result["gates"] == "FAIL"


def test_no_year_or_ambiguous_dst_clock_is_rejected():
    with pytest.raises(ValueError):
        m.original_start("originally scheduled for September 1 at 2:00AM ET")
    with pytest.raises(ValueError):
        m.original_start("originally scheduled for November 1, 2026 at 1:30AM ET")


class Pages:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.offsets = []

    def get_json(self, url, params, use_cache):
        self.offsets.append(params["offset"])
        return next(self.pages)


def test_pagination_requires_empty_page_even_after_short_page(tmp_path):
    pages = Pages([[{"id": "1"}], [{"id": "2"}], []])
    assert [e["id"] for e in m.enumerate_events(pages, tmp_path, limit=200)] == ["1", "2"]
    assert pages.offsets == [0, 1, 2]


def test_duplicate_fails_instead_of_silently_deduplicating(tmp_path):
    pages = Pages([[{"id": "1"}], [{"id": "1"}], []])
    with pytest.raises(ValueError, match="DUPLICATED_ID"):
        list(m.enumerate_events(pages, tmp_path))


def test_small_sample_uses_preregistered_bound_and_incomplete_run_registers_nothing():
    rows = [m.classify(event())] * 42
    assert m.summarize(rows, complete=True)["registered_value"] == pytest.approx(3 / 42)
    assert m.summarize(rows, complete=False)["registered_value"] is None
