#!/usr/bin/env python3
"""The offline walk must be the SAME arithmetic the lane prices its hedge with, or the number is
not comparable to `hedge_slippage_c` and the whole measurement is decorative."""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from kernel.schema import Book, Quote
from measure import walk_vwap
from nodes.execute.plan import vwap_for_size


def test_the_offline_walk_equals_the_lanes_vwap_on_random_ladders():
    rnd = random.Random(20260914)
    for _ in range(400):
        levels = sorted((round(rnd.uniform(0.01, 0.99), 2), round(rnd.uniform(0.1, 50), 4))
                        for _ in range(rnd.randint(1, 8)))
        book = Book(asks=tuple(Quote(p, s) for p, s in levels), fetched_utc=0.0)
        for q in (5.0, 10.0, 25.0, 100.0):
            assert walk_vwap(levels, q) == vwap_for_size(book, q), (levels, q)


def test_short_depth_is_none_in_both_and_is_not_a_zero():
    """`walk_ladder` demands a full fill. A hedge that cannot be filled whole is a WORSE outcome
    than an expensive one -- the naked-residual failure -- so it must never silently become 0.0."""
    levels = [(0.40, 3.0)]
    book = Book(asks=(Quote(0.40, 3.0),), fetched_utc=0.0)
    assert walk_vwap(levels, 10.0) is None and vwap_for_size(book, 10.0) is None
    assert walk_vwap(levels, 3.0) == vwap_for_size(book, 3.0) == 0.4


def test_the_no_leg_is_read_off_the_no_projection():
    """`_leg_side`: a Kalshi outcome ending ':NO' is a buy_no, so the hedge is priced from the NO
    ladder. Reading the YES side there measures the wrong instrument entirely."""
    from measure import actionable_moments  # noqa: F401  (import-time check only)
    import json, sqlite3, tempfile
    db = Path(tempfile.mkdtemp()) / "t.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE stream_evaluations(seen_ts REAL, game_id TEXT, league TEXT, "
                "quantity REAL, status TEXT, cost REAL, gross REAL, fees REAL, return_locked REAL, "
                "required_ask_sum REAL, cents_from_actionable REAL, blocked_by TEXT, "
                "triggered_by TEXT, latency_ms REAL, legs_json TEXT)")
    import time as _t
    t0 = _t.mktime(_t.strptime("2026-09-13 12:00:00", "%Y-%m-%d %H:%M:%S")) - _t.timezone
    for legs in ([{"venue": "kalshi", "outcome": "KXATP-ABC:NO", "vwap": 0.44},
                  {"venue": "polymarket", "outcome": "tok", "vwap": 0.55}],
                 [{"venue": "kalshi", "outcome": "KXATP-DEF", "vwap": 0.31},
                  {"venue": "polymarket", "outcome": "tok2", "vwap": 0.68}]):
        con.execute("INSERT INTO stream_evaluations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (t0, "g", "atp", 10.0, "PROFITABLE_UNEXECUTED", 0.99, 1.0, 0.01, 0.01,
                     0.99, 1.0, None, "k", 1.0, json.dumps(legs)))
    con.commit(); con.close()
    got = actionable_moments(db, "2026-09-13")
    sides = {m[1]: m[2] for m in got}
    assert sides == {"KXATP-ABC": "no", "KXATP-DEF": "yes"}, got
    assert all(m[3] == 10.0 and m[5] == "atp" for m in got)
