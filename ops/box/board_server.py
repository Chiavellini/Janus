#!/usr/bin/env python3
"""The board: a read-only HTTP service on the box, loopback only, reached from the laptop through
an SSM port-forward (ops/box/board.sh). Nothing here writes; nothing here is reachable from the
internet (127.0.0.1, and the box's security group opens no port for it).

    GET /            the terminal page (ops/box/board.html)
    GET /board.json  the lane's one-second snapshot (grids/live_stream Supervisor.write_board)
    GET /pnl.json    bundles (executions with fills) and realized P&L windows from the journal,
                     recomputed at most every PNL_TTL_S seconds

Run as janus: JANUS_DATA_ROOT=/srv/janus python3 ops/box/board_server.py --port 8787
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PNL_TTL_S = 3.0
SINCE_ALL_TIME_UTC = 1789171200.0      # 2026-09-12T00:00:00Z: "all time" starts today (the operator, 2026-09-12)
FILLED_STATES = ("HEDGED", "SETTLED", "RECONCILED", "UNWOUND", "LEG_A_FILLED", "LEG_A_PARTIAL", "LEG_B_SUBMITTED",
                 "LEG_B_PARTIAL", "LEG_B_FILLED", "HEDGE_SLIPPAGE_EXCEEDED", "PARTIAL_FILL", "UNKNOWN_PROVIDER_STATE",
                 "HEDGE_UNAVAILABLE", "UNWIND_SUBMITTED")


def _ro(path: Path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    con.row_factory = sqlite3.Row
    return con


def _table(con, name: str) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def bundles(db: Path, *, now: float | None = None, since_s: float = 86400.0) -> dict:
    """One row per execution that filled anything (a bundle: the first leg, its hedge legs, the
    residual), never per order; plus the P&L windows and the attempt funnel."""
    now = time.time() if now is None else now
    con = _ro(db)
    try:
        has_ev, has_st = _table(con, "events"), _table(con, "execution_settlements")
        rows = []
        for e in con.execute("SELECT * FROM executions WHERE started_utc>? AND (first_filled>0 OR hedge_filled>0) ORDER BY started_utc DESC",
                             (now - since_s,)):
            ev = con.execute("SELECT short_name FROM events WHERE event_id=?", (e["event_id"],)).fetchone() if has_ev else None
            st = con.execute("SELECT kind,cover_usd,directional_usd,realized_usd,settled_ts FROM execution_settlements WHERE execution_id=?",
                             (e["execution_id"],)).fetchone() if has_st else None
            n_orders = con.execute("SELECT count(*), sum(state='FILLED' OR state='PARTIAL') FROM orders WHERE execution_id=?",
                                   (e["execution_id"],)).fetchone() if _table(con, "orders") else (None, None)
            stages = json.loads(e["stages_json"] or "{}")
            rows.append({
                "execution_id": e["execution_id"][:8], "name": (ev["short_name"] if ev else None) or e["event_id"], "league": e["league"],
                "started_utc": e["started_utc"], "state": e["state"], "requested": e["quantity"],
                "first": {"contracts": e["first_filled"], "price": e["first_avg_price"]},
                "hedge": {"contracts": e["hedge_filled"], "price": e["hedge_avg_price"]},
                "unhedged": e["unhedged"], "released": bool(e["released"]),
                "orders": n_orders[0], "fills": n_orders[1],
                "hedged_in_s": round((stages.get("b_settled_ms") or 0) / 1000.0, 1) if stages.get("b_settled_ms") else None,
                "settlement": dict(st) if st else None,
                "pnl_usd": (st["realized_usd"] if st else None),
                "cover_usd": (st["cover_usd"] if st else None),
                "kind": (st["kind"] if st else ("pending" if e["state"] in ("HEDGED", "SETTLED") else e["state"].lower())),
            })
        def window(since: float) -> dict:
            if not has_st:
                return {"realized_usd": 0.0, "cover_usd": 0.0, "settled": 0}
            r = con.execute("SELECT COALESCE(sum(realized_usd),0), COALESCE(sum(cover_usd),0), count(*) FROM execution_settlements WHERE settled_ts>?",
                            (since,)).fetchone()
            return {"realized_usd": round(r[0], 4), "cover_usd": round(r[1], 4), "settled": r[2]}
        attempts = con.execute("SELECT state, count(*) FROM executions WHERE started_utc>? GROUP BY state", (now - since_s,)).fetchall()
        by_state = {r[0]: r[1] for r in attempts}
        open_ = con.execute("SELECT count(*), COALESCE(sum(unhedged),0) FROM executions WHERE released=0").fetchone()
        return {"as_of": now, "since_s": since_s, "bundles": rows,
                "pnl_24h": window(now - since_s), "pnl_all_time": window(SINCE_ALL_TIME_UTC), "all_time_since_utc": SINCE_ALL_TIME_UTC,
                "funnel_24h": {"attempts": sum(by_state.values()), "by_state": by_state,
                               "first_leg_fills": sum(1 for r in rows), "covers": sum(1 for r in rows if (r["settlement"] or {}).get("kind") == "COVER")},
                "open": {"executions": open_[0], "unhedged_contracts": round(open_[1], 4)}}
    finally:
        con.close()


class Handler(BaseHTTPRequestHandler):
    board_path: Path = Path("/srv/janus/board/board.json")
    db_path: Path = Path("/srv/janus/tuples/tuples.sqlite")
    page: bytes = b""
    _pnl_cache: tuple[float, bytes] = (0.0, b"")

    def log_message(self, fmt, *args):      # quiet by default; journald sees errors only
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            return self._send(200, self.page, "text/html; charset=utf-8")
        if path == "/board.json":
            try:
                return self._send(200, self.board_path.read_bytes(), "application/json")
            except OSError:
                return self._send(503, b'{"error":"no board yet"}', "application/json")
        if path == "/pnl.json":
            ts, body = Handler._pnl_cache
            if time.time() - ts > PNL_TTL_S:
                try:
                    body = json.dumps(bundles(self.db_path), default=str).encode()
                except Exception as exc:  # noqa: BLE001
                    body = json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode()
                Handler._pnl_cache = (time.time(), body)
            return self._send(200, body, "application/json")
        return self._send(404, b"not found", "text/plain")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--bind", default="127.0.0.1")
    root = Path(os.environ.get("JANUS_DATA_ROOT") or "/srv/janus")
    ap.add_argument("--board", type=Path, default=root / "board" / "board.json")
    ap.add_argument("--db", type=Path, default=root / "tuples" / "tuples.sqlite")
    a = ap.parse_args()
    Handler.board_path, Handler.db_path = a.board, a.db
    Handler.page = (Path(__file__).resolve().parent / "board.html").read_bytes()
    srv = ThreadingHTTPServer((a.bind, a.port), Handler)
    print(f"board on http://{a.bind}:{a.port}  board={a.board} db={a.db}", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
