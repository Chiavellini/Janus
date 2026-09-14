"""The launchpad: a read-only snapshot of the box rendered as one page. The extractor's SQL is
proven against a fixture built with the real DDLs; the renderer against a saved snapshot."""
from __future__ import annotations

import json
import time
from pathlib import Path

from nodes.discovery.discovery import EVENTS_DDL
from nodes.execute.records import EXECUTION_DDL
from nodes.execution.journal import JOURNAL_DDL
from nodes.reconcile.settle_executions import SETTLEMENTS_DDL
from nodes.risk.flags import FLAGS_DDL
from nodes.risk.ledger import LEDGER_DDL
from nodes.store_tuples.store import TupleStore
from ops import launchpad
from ops.box import launchpad_extract as lx

NOW = 1_800_000_000.0


def fixture(tmp_path: Path) -> Path:
    db = tmp_path / "t.sqlite"
    st = TupleStore(db, enforce_volume=False)
    for ddl in (EVENTS_DDL, EXECUTION_DDL, JOURNAL_DDL, SETTLEMENTS_DDL, FLAGS_DDL, LEDGER_DDL):
        st.ensure_ddl(ddl)
    c = st.con
    c.execute("INSERT INTO events(event_id,league,start_utc,short_name,phase,first_seen_ts,last_seen_ts) VALUES('pm:atp:1','atp',?,'A V B','in:co_listed',?,?)", (NOW, NOW, NOW))
    c.execute("INSERT INTO events(event_id,league,start_utc,short_name,phase,first_seen_ts,last_seen_ts) VALUES('espn:mlb:2','mlb',?,'NYY @ BOS','in:co_listed',?,?)", (NOW, NOW, NOW))
    # a settled COVER (two orders), a settled PARTIAL, an open HEDGED, an unfilled attempt, and one from 2 days ago
    rows = [
        ("e-cover", "pm:atp:1", "atp", "RECONCILED", NOW - 3600, 10.0, 10.0, 0.62, 10.0, 0.40, 0.0, 1, "c-a", '["c-b"]'),
        ("e-partial", "espn:mlb:2", "mlb", "RECONCILED", NOW - 7200, 25.0, 25.32, 0.78, 25.0, 0.22, 0.32, 1, "p-a", '["p-b1","p-b2"]'),
        ("e-open", "pm:atp:1", "atp", "HEDGED", NOW - 600, 10.0, 10.0, 0.55, 10.0, 0.47, 0.0, 0, "o-a", '["o-b"]'),
        ("e-miss", "espn:mlb:2", "mlb", "ORDER_UNFILLED", NOW - 300, 10.0, 0.0, None, 0.0, None, 0.0, 1, "m-a", "[]"),
        ("e-old", "pm:atp:1", "atp", "RECONCILED", NOW - 2 * 86400, 10.0, 10.0, 0.5, 10.0, 0.5, 0.0, 1, "x-a", "[]"),
    ]
    for exid, ev, lg, state, t, q, ff, fp, hf, hp, un, rel, fcid, hcids in rows:
        c.execute("INSERT INTO executions(execution_id,opportunity_id,event_id,league,mode,state,started_utc,last_utc,quantity,"
                  "first_client_id,hedge_client_ids,first_filled,first_avg_price,hedge_filled,hedge_avg_price,unhedged,reservation_id,released,"
                  "stages_json,protect_json) VALUES(?,?,?,?,'LIMITED_LIVE',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (exid, ev + ":opp", ev, lg, state, t, t + 5, q, fcid, hcids, ff, fp, hf, hp, un, "r-" + exid, rel,
                   '{"a_settled_ms": 900, "b_settled_ms": 2500}', '{"attempts": [{"kind": "hedge", "phase": "walked", "advance": "book_above_ceiling"}, {"kind": "hedge", "phase": "loss_cap"}]}'))
    for cid, exid, venue, side, px, n, state, filled, avg, opn in (
            ("c-a", "e-cover", "polymarket", "buy_yes", .62, 10, "FILLED", 10, .62, 0), ("c-b", "e-cover", "kalshi", "buy_yes", .40, 10, "FILLED", 10, .40, 0),
            ("p-a", "e-partial", "polymarket", "buy_yes", .79, 25, "FILLED", 25.32, .78, 0), ("p-b1", "e-partial", "kalshi", "buy_no", .17, 25, "UNFILLED", 0, None, 0),
            ("p-b2", "e-partial", "kalshi", "buy_no", .22, 25, "FILLED", 25, .22, 0), ("o-a", "e-open", "polymarket", "buy_yes", .55, 10, "FILLED", 10, .55, 0),
            ("o-b", "e-open", "kalshi", "buy_yes", .47, 10, "FILLED", 10, .47, 0), ("m-a", "e-miss", "polymarket", "buy_yes", .5, 10, "UNFILLED", 0, None, 0),
            ("live-1", "e-open", "polymarket", "buy_yes", .5, 10, "UNCONFIRMED", 0, None, 1)):
        c.execute("INSERT INTO orders(client_order_id,venue,mode,market_id,outcome_id,side,price,contracts,time_in_force,opportunity_id,state,"
                  "filled_contracts,avg_price,open,submitted_utc,last_utc,execution_id) VALUES(?,?,'LIMITED_LIVE','m','o',?,?,?,'ioc','opp',?,?,?,?,?,?,?)",
                  (cid, venue, side, px, n, state, filled, avg, opn, NOW - 1000, NOW - 999, exid))
    c.execute("INSERT INTO execution_settlements VALUES('e-cover','pm:atp:1:opp','pm:atp:1','atp','LIMITED_LIVE',?,'K','P',0.7798,1,'[]','COVER',10,0,0.7798,0)", (NOW - 1800,))
    c.execute("INSERT INTO execution_settlements VALUES('e-partial','espn:mlb:2:opp','espn:mlb:2','mlb','LIMITED_LIVE',?,'K','P',-0.447,1,'[]','PARTIAL',25,0.32,-0.5143,0.0672)", (NOW - 1700,))
    c.execute("INSERT INTO capital_reservations(reservation_id, event_id, league, per_venue_json, opportunity_id, created_utc, released_utc, release_reason) VALUES('r-e-open','pm:atp:1','atp','{\"kalshi\": 4.7, \"polymarket\": 5.5}','pm:atp:1:opp',?,NULL,NULL)", (NOW - 600,))
    c.execute("INSERT INTO capital_reservations(reservation_id, event_id, league, per_venue_json, opportunity_id, created_utc, released_utc, release_reason) VALUES('r-e-miss','espn:mlb:2','mlb','{\"kalshi\": 4.0, \"polymarket\": 5.0}','espn:mlb:2:opp',?,?,'ORDER_UNFILLED zero fill')", (NOW - 300, NOW - 290))
    c.execute("INSERT INTO lane_flags(seen_ts,flag,detail) VALUES(?,'PROTECT_FAILED','e-partial 0x1234567890abcdef unprotected')", (NOW - 7000,))
    for i in range(5):
        st.socket_health(venue="kalshi", stats={"connected": True, "frames": 100 * i, "age_s": 0.3, "loop_lag_s": 0.5 * i}, seen_ts=NOW - 300 + 60 * i)
    st.socket_health(venue="polymarket", stats={"connected": True, "frames": 9, "age_s": 0.4, "last_error": "drift 0xabcdefabcdef1234"}, seen_ts=NOW - 60)
    st.commit(); st.close()
    return db


def test_the_extractor_reads_trades_open_exposure_and_state_read_only(tmp_path: Path):
    db = fixture(tmp_path)
    root = tmp_path / "root"; (root / "kill").mkdir(parents=True)
    (root / "kill" / "arming_override.json").write_text(json.dumps({"mode": "LIMITED_LIVE", "runner_sha": "abc", "code_sha": "c", "limits_sha": "l",
                                                                     "caps": {"stake_usd": 30, "max_contracts": 25, "day_notional_usd": 500},
                                                                     "expires_utc": "2100-01-01T00:00:00Z", "written_utc": "2026-09-12T01:00:38", "signature": "SECRET"}))
    (root / "kill" / "live").write_text(json.dumps({"reason": "protect: 0x1234567890abcdef naked", "latched_utc": NOW - 100}))
    before = db.stat().st_mtime_ns
    snap = lx.collect(db, data_root=root, repo=tmp_path, now=NOW, system=False)
    assert db.stat().st_mtime_ns == before, "read-only"
    assert "signature" not in snap["override"] and snap["override"]["caps"]["max_contracts"] == 25 and snap["override"]["seconds_left"] > 0
    assert [k["name"] for k in snap["kills"]] == ["live"] and snap["kills"][0]["reason"].endswith("0x…abcdef naked")
    names = [t["short_name"] for t in snap["trades"]]
    assert names == ["NYY @ BOS", "A V B", "A V B", "NYY @ BOS"], "24 h window, newest first, event names joined"
    cover = next(t for t in snap["trades"] if t["execution_id"] == "e-cover")
    assert cover["settlement"]["kind"] == "COVER" and cover["settlement"]["realized_usd"] == 0.7798 and len(cover["orders"]) == 2
    assert next(t for t in snap["trades"] if t["execution_id"] == "e-miss")["orders"] == [], "a released zero fill carries no order detail"
    partial = next(t for t in snap["trades"] if t["execution_id"] == "e-partial")
    assert [o["client_order_id"] for o in partial["orders"]] == ["p-a", "p-b1", "p-b2"], "orders by client ids, in submit order"
    assert partial["advance"] and partial["hedge_attempts"] == 2 and partial["b_settled_ms"] == 2500
    f = snap["funnel"]
    assert (f["attempts"], f["first_leg_fills"], f["covers"], f["settled"]) == (4, 3, 1, 2)
    assert f["realized_usd"] == round(0.7798 - 0.447, 4) and f["cover_usd"] == round(0.7798 - 0.5143, 4)
    o = snap["open"]
    assert [e["execution_id"] for e in o["executions"]] == ["e-open"] and o["executions"][0]["pending_settlement"] and not o["executions"][0]["attention"]
    assert [x["client_order_id"] for x in o["orders"]] == ["live-1"]
    assert [r["reservation_id"] for r in o["reservations"]] == ["r-e-open"] and o["open_reservation_usd"] == 10.2
    assert o["day_committed_usd"] == 10.2, "the released zero-fill reservation does not count"
    assert o["day_cap_usd"] == 500 and o["today_realized_usd"] == round(0.7798 - 0.447, 4)
    assert snap["sockets"]["kalshi"]["loop_lag_s"] == 2.0 and snap["sockets"]["polymarket"]["last_error"].endswith("0x…ef1234")
    assert len(snap["lag_series"]) == 5 and snap["flags"][0]["flag"] == "PROTECT_FAILED" and "0x…abcdef" in snap["flags"][0]["detail"]


def test_the_page_renders_the_state_the_trades_and_the_badges(tmp_path: Path):
    db = fixture(tmp_path)
    root = tmp_path / "root"; (root / "kill").mkdir(parents=True)
    (root / "kill" / "arming_override.json").write_text(json.dumps({"mode": "LIMITED_LIVE", "runner_sha": "abc123456789", "caps": {"stake_usd": 30, "max_contracts": 25, "day_notional_usd": 500},
                                                                     "expires_utc": "2100-01-01T00:00:00Z", "written_utc": "x"}))
    snap = lx.collect(db, data_root=root, repo=tmp_path, now=NOW, system=False)
    snap["system"] = {"units": {"janus-live-stream": {"active": "active", "restarts": "0", "since": "t"}}, "disk": {"data": {"total": 200 * 2**30, "used": 50 * 2**30, "free": 150 * 2**30}},
                      "deployed_sha": "abc123456789", "host": "box", "uptime": "up 1 day", "load": [0.5], "mem_mb": {"MemAvailable": 1200}}
    html = launchpad.render(snap)
    assert "TRADING" in html and "KILL/" not in html and "$30 / 25 contracts / $500 a day" in html
    assert "A V B" in html and "NYY @ BOS" in html and "$+0.78" in html and "$-0.45" in html and "PARTIAL" in html and "L75" in html
    assert "nothing held" not in html and "live-1" not in html and "UNCONFIRMED open" in html
    assert "disk 25%" in html and "loop 2.0s" in html and "watchdog quiet" in html
    assert "<title>Janus Launchpad</title>" in html and "background:var(--bg)" in html
    snap["kills"] = [{"name": "live", "reason": "protect: naked", "latched_utc": NOW}]
    html2 = launchpad.render(snap)
    assert "HALTED" in html2 and "KILL/live" in html2
    page = launchpad.write(snap, tmp_path / "out")
    assert page.exists() and (tmp_path / "out" / "latest.json").exists()


def test_the_snapshot_is_found_between_the_sentinels_whatever_run_sh_prints_around_it():
    text = "status=Success\n" + lx.BEGIN + '\n{"as_of": 1, "trades": []}\n' + lx.END + "\n--- stderr\nDeprecationWarning: x\n"
    assert launchpad.parse_snapshot(text) == {"as_of": 1, "trades": []}
    import base64, zlib
    packed = base64.b64encode(zlib.compress(b'{"as_of": 2}')).decode()
    assert launchpad.parse_snapshot("x\n" + lx.BEGIN + "\n" + packed + "\n" + lx.END + "\ny") == {"as_of": 2}, "the box compresses; SSM keeps ~24 KB"
    try:
        launchpad.parse_snapshot("nothing here")
    except ValueError as exc:
        assert "no snapshot" in str(exc)
    else:
        raise AssertionError("missing sentinels must raise")
