#!/usr/bin/env python3
"""First-seen kickoffs are immutable; a moved match counts once it is terminal; no token, no run."""
from __future__ import annotations

import pytest

from nodes.store_tuples.store import TupleStore
from nodes.watch_fd.snapshot import fetch_matches, rates, record

T = 1_800_000_000.0


def _m(mid, kick, status, **kw):
    return {"id": mid, "utcDate": kick, "status": status, "matchday": 3, "season": {"startDate": "2026-08-15"},
            "homeTeam": {"name": "Lyon"}, "awayTeam": {"name": "Lens"}, "lastUpdated": "2026-09-05T00:00:00Z", **kw}


def test_first_seen_kickoff_is_immutable_and_a_moved_terminal_match_counts(tmp_path):
    st = TupleStore(tmp_path / "t.sqlite", enforce_volume=False)
    day1 = [_m(1, "2026-09-12T19:00:00Z", "SCHEDULED"), _m(2, "2026-09-12T15:00:00Z", "TIMED"), _m(3, "2026-09-13T15:00:00Z", "TIMED")]
    assert record(st, "FL1", day1, now=T) == 3
    # the venue moves match 1 by three days and rewrites utcDate in place; match 3 is cancelled; match 2 finishes on time
    day2 = [_m(1, "2026-09-15T19:00:00Z", "FINISHED"), _m(2, "2026-09-12T15:00:00Z", "FINISHED"), _m(3, "2026-09-13T15:00:00Z", "CANCELLED")]
    record(st, "FL1", day2, now=T + 86400 * 4)
    row = st.con.execute("SELECT utc_date_first, utc_date_last, status_first, status_last FROM fd_matches WHERE match_id=1").fetchone()
    assert row[1] - row[0] == pytest.approx(3 * 86400) and row[2] == "SCHEDULED" and row[3] == "FINISHED"
    r = rates(st)["fl1"]
    assert r == {"matches": 3, "terminal": 3, "moved_gt48h": 1, "cancelled": 1,
                 "postponed_gt48h_rate": pytest.approx(1 / 3), "cancelled_rate": pytest.approx(1 / 3)}
    # an open match is not a denominator
    record(st, "FL1", [_m(4, "2026-09-20T15:00:00Z", "TIMED")], now=T + 86400 * 4)
    assert rates(st)["fl1"]["terminal"] == 3 and rates(st)["fl1"]["matches"] == 4


def test_no_token_no_run():
    class NoNet:
        def get_json(self, *a, **k):
            raise AssertionError("must not be called")
    with pytest.raises(ValueError):
        fetch_matches("PL", NoNet(), token="")
