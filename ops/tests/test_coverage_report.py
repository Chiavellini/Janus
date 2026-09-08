from __future__ import annotations

import json

from nodes.discovery.discovery import EVENTS_DDL
from nodes.store_tuples.store import TupleStore
from ops.coverage_report import coverage_alerts


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
