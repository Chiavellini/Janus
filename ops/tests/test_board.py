"""The board: the lane's one-second snapshot, the bundles/P&L query, and the loopback service."""
from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from ops.box import board_server
from ops.tests.test_launchpad import NOW, fixture


def test_the_lane_writes_a_board_with_every_poller_s_books(tmp_path: Path):
    from grids.live_stream.tests.test_grid_callbacks import _supervisor, sync_all, T
    sup, s = _supervisor(tmp_path)
    s.tier, s.start_utc, s.league = "live", T - 600, "mlb"
    sync_all(s.poller, kh=0.44, ka=0.99, ph=0.99, pa=0.44)
    sup._on_update("g1")("K_H", T)
    sup.board_path = tmp_path / "board" / "board.json"
    sup.write_board(now=T + 1)
    b = json.loads(sup.board_path.read_text())
    assert b["as_of"] == T + 1 and b["games"] and sup.board_written == 1
    g = b["games"][0]
    assert g["name"] == "SF @ PIT" and g["tier"] == "live" and g["league"] == "mlb" and g["start_utc"] == T - 600
    assert set(g["outcomes"]) == {"home", "away"}
    home = g["outcomes"]["home"]
    assert home["kalshi"]["ask"] == 0.44 and home["polymarket"]["ask"] == 0.99 and home["kalshi"]["state"] == "SYNCED"
    assert g["status"] and g["cost"] is not None and g["evaluations"] >= 1
    # a second write is atomic (no .tmp left) and counts
    sup.write_board(now=T + 2)
    assert sup.board_written == 2 and not (tmp_path / "board" / "board.tmp").exists()


def test_bundles_are_one_row_per_filled_execution_with_windows_and_funnel(tmp_path: Path):
    db = fixture(tmp_path)
    p = board_server.bundles(db, now=NOW)
    names = [(b["name"], b["kind"], b["pnl_usd"]) for b in p["bundles"]]
    assert names == [("A V B", "pending", None), ("A V B", "COVER", 0.7798), ("NYY @ BOS", "PARTIAL", -0.447)], "newest first, only fills, no per-order rows"
    partial = p["bundles"][2]
    assert partial["orders"] == 3 and partial["fills"] == 2 and partial["first"]["contracts"] == 25.32 and partial["hedge"]["price"] == 0.22
    assert p["pnl_24h"]["settled"] == 2 and p["pnl_24h"]["realized_usd"] == round(0.7798 - 0.447, 4)
    assert p["funnel_24h"]["attempts"] == 4 and p["funnel_24h"]["first_leg_fills"] == 3 and p["funnel_24h"]["covers"] == 1
    assert p["open"] == {"executions": 1, "unhedged_contracts": 0.0}
    assert p["all_time_since_utc"] == board_server.SINCE_ALL_TIME_UTC


def _get(path: str) -> tuple[int, bytes]:
    """Drive the handler without a socket (the suite forbids connecting out, loopback included)."""
    import io
    h = board_server.Handler.__new__(board_server.Handler)
    h.path, h.wfile, out = path, io.BytesIO(), {}
    h.send_response = lambda code: out.__setitem__("code", code)
    h.send_header = lambda k, v: None
    h.end_headers = lambda: None
    h.do_GET()
    return out["code"], h.wfile.getvalue()


def test_the_service_serves_the_page_the_board_and_the_pnl(tmp_path: Path, monkeypatch):
    db = fixture(tmp_path)
    monkeypatch.setattr(board_server.time, "time", lambda: NOW)         # the fixture's clock, not the wall's
    board = tmp_path / "board.json"
    board.write_text(json.dumps({"as_of": NOW, "mode": "LIMITED_LIVE", "games": []}))
    board_server.Handler.board_path, board_server.Handler.db_path = board, db
    board_server.Handler.page = (Path(board_server.__file__).parent / "board.html").read_bytes()
    board_server.Handler._pnl_cache = (0.0, b"")
    code, page = _get("/")
    assert code == 200 and b"<title>Janus Board</title>" in page and b"board.json" in page and b"pnl.json" in page
    code, body = _get("/board.json")
    assert code == 200 and json.loads(body)["mode"] == "LIMITED_LIVE"
    code, body = _get("/pnl.json?x=1")
    assert code == 200 and len(json.loads(body)["bundles"]) == 3
    assert _get("/nope")[0] == 404
    board.unlink()
    assert _get("/board.json")[0] == 503
