#!/usr/bin/env python3
"""First-seen starts are immutable, resolution is three-state, and the pass never stops on one failure."""
from __future__ import annotations

from nodes.discovery.census import GameEvent
from nodes.store_tuples.store import TupleStore
from nodes.watch_settle.settle import delay_rows, polymarket_outcome, record_watch, resolve_pending

T = 1_800_000_000.0


def ev(slug, start, parts=("A", "B")):
    return GameEvent("polymarket", "tennis", slug, "2027-01-15", start, list(parts), [], 1, True, None, None, None, ["tok"])


def test_the_first_seen_start_is_immutable_and_the_live_start_refreshes(tmp_path):
    st = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    assert record_watch(st, [ev("wta-a-b-2027-01-15", T + 3600)], now=T) == 1
    record_watch(st, [ev("wta-a-b-2027-01-15", T + 3600 + 86400 * 8)], now=T + 100)   # the venue moved it a week
    row = st.con.execute("SELECT first_seen_ts, start_utc, start_utc_last, last_seen_ts, league_hint FROM watch_events").fetchone()
    assert row == (T, T + 3600, T + 3600 + 86400 * 8, T + 100, "wta")


def test_outcomes_are_three_state():
    assert polymarket_outcome({"closed": True, "outcomes": '["A","B"]', "outcomePrices": '["1","0"]'}) == "A"
    assert polymarket_outcome({"closed": True, "outcomes": '["A","B"]', "outcomePrices": '["0.5","0.5"]'}) == "HALF"
    assert polymarket_outcome({"closed": False, "outcomes": '["A","B"]', "outcomePrices": '["0.7","0.3"]'}) is None
    assert polymarket_outcome(None) is None


def test_resolve_marks_winners_and_halves_leaves_open_ones_and_survives_a_failed_fetch(tmp_path):
    st = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    record_watch(st, [ev("wta-a-b-2027-01-15", T - 7200), ev("atp-c-d-2027-01-15", T - 7200),
                      ev("atp-e-f-2027-01-15", T - 7200), ev("atp-g-h-2027-01-15", T - 7200), ev("atp-late-2027-01-15", T - 60)], now=T - 7200)

    def fetch(slug, cl):
        if slug.startswith("wta-a-b"):
            return {"markets": [{"slug": slug, "sportsMarketType": "moneyline", "closed": True, "outcomes": '["A","B"]', "outcomePrices": '["0","1"]'}]}
        if slug.startswith("atp-c-d"):
            return {"markets": [{"slug": slug, "sportsMarketType": "moneyline", "closed": True, "outcomes": '["C","D"]', "outcomePrices": '["0.5","0.5"]'}]}
        if slug.startswith("atp-e-f"):
            return {"markets": [{"slug": slug, "sportsMarketType": "moneyline", "closed": False}]}
        raise RuntimeError("HTTP 503")

    out = resolve_pending(st, None, now=T, fetch=fetch)
    assert out == {"checked": 4, "resolved": 1, "half": 1, "open": 1, "errors": 1}, out
    rows = {r[0]: r for r in st.con.execute("SELECT event_id, result, resolved_seen_ts, resolve_note FROM watch_events")}
    assert rows["wta-a-b-2027-01-15"][1:3] == ("B", T) and rows["atp-c-d-2027-01-15"][1] == "HALF"
    assert rows["atp-e-f-2027-01-15"][1] is None and rows["atp-e-f-2027-01-15"][3] == "not resolved"
    assert rows["atp-g-h-2027-01-15"][3].startswith("fetch failed") and rows["atp-late-2027-01-15"][2] is None, "too young to ask"
    assert {r[0] for r in delay_rows(st)} == {"wta-a-b-2027-01-15", "atp-c-d-2027-01-15"}
    assert resolve_pending(st, None, now=T + 1, fetch=fetch)["checked"] == 2, "resolved rows are not asked again"
