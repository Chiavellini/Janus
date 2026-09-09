from __future__ import annotations

import json

from nodes.discovery.discovery import EVENTS_DDL
from nodes.store_tuples.store import TupleStore
from ops.coverage_report import coverage_alerts, report


def test_a_game_ever_co_listed_is_not_a_gap_after_one_venue_settles(tmp_path):
    now = 2_000_000_000.0
    db = tmp_path / "lane.sqlite"
    st = TupleStore(db, enforce_volume=False)
    st.ensure_ddl(EVENTS_DDL)
    st.con.execute(
        "INSERT INTO events(event_id,league,start_utc,participants,short_name,phase,kalshi_event,pm_slug,"
        "first_seen_ts,last_seen_ts,block_reason) VALUES('e','mlb',?,'[]','NYY @ BOS','post',"
        "'KXMLBGAME-NYYBOS','mlb-nyy-bos',?,?, 'UNPAIRED:kalshi=missing,polymarket=found')",
        (now - 600, now - 3600, now),
    )
    st.con.execute("INSERT INTO event_transitions(seen_ts,event_id,phase,block_reason) VALUES(?,?,?,NULL)",
                   (now - 1800, "e", "in:co_listed"))
    st.con.commit(); st.close()
    census = tmp_path / "census.json"
    census.write_text(json.dumps({"co_listed_pairs_48h": [{
        "kalshi_event": "KXMLBGAME-NYYBOS", "pm_event": "mlb-nyy-bos", "kalshi_series": "KXMLBGAME",
        "date": "2033-05-18", "start_utc": now - 600, "participants": ["Yankees", "Red Sox"],
    }]}))
    assert coverage_alerts(db, census, now=now) == []


def test_unregistered_loose_joins_are_deduplicated_research_only_and_never_alert(tmp_path):
    now = 2_000_000_000.0
    db = tmp_path / "lane.sqlite"
    st = TupleStore(db, enforce_volume=False)
    st.ensure_ddl(EVENTS_DDL)
    st.close()
    census = tmp_path / "census.json"
    census.write_text(json.dumps({"run_utc": "2033-05-18T00:00:00+00:00", "co_listed_pairs_48h": [
        {"kalshi_event": "KXCS2GAME-A", "pm_event": "cs2-a", "kalshi_series": "KXCS2GAME",
         "pm_sport": "cs2", "start_utc": now + 60, "participants": ["A", "B"]},
        {"kalshi_event": "KXCS2GAME-B", "pm_event": "cs2-b", "kalshi_series": "KXCS2GAME",
         "pm_sport": "cs2", "start_utc": now + 120, "participants": ["C", "D"]},
        {"kalshi_event": "KXKBOGAME-FAR", "pm_event": "kbo-far", "kalshi_series": "KXKBOGAME",
         "pm_sport": "kbo", "start_utc": now + 10 * 3600, "participants": ["E", "F"]},
        {"kalshi_event": "KXCS2GAME-A", "pm_event": "cs2-a", "kalshi_series": "KXCS2GAME",
         "pm_sport": "cs2", "start_utc": now + 60, "participants": ["A", "B"]},
        {"kalshi_event": "", "pm_event": "missing-id", "kalshi_series": "KXCS2GAME",
         "pm_sport": "cs2", "start_utc": now + 60, "participants": ["A", "B"]},
    ]}))
    got = report(db, census, now=now)
    assert got["rows"] == []
    candidates = got["unverified_coverage_candidates_48h"]
    assert len(candidates) == 3
    assert {row["status"] for row in candidates} == {"UNVERIFIED_COVERAGE_CANDIDATE"}
    assert all(row["operational"] is False and row["basis"] == "LOOSE_PARTICIPANT_DATE_JOIN"
               for row in candidates)
    assert got["unverified_candidate_summary"] == {
        "candidate_rows": 3,
        "discarded_malformed_or_duplicate_rows": 2,
        "mapping_candidates": [
            {"kalshi_series": "KXCS2GAME", "pm_sport": "cs2", "candidate_rows": 2},
            {"kalshi_series": "KXKBOGAME", "pm_sport": "kbo", "candidate_rows": 1},
        ],
    }
    assert coverage_alerts(db, census, now=now) == [], "research candidates never page operations"
