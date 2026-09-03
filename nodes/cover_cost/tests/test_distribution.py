#!/usr/bin/env python3
"""Dwell weighting, phase cuts, reason tails, flap windows and the paper n, on synthetic rows."""
from __future__ import annotations

import sqlite3

from nodes.cover_cost.distribution import (Row, distribute, in_windows, load_flap_windows, load_rows,
                                           paper_n, phase_of, reason_of)

T = 1_000_000.0


def r(t, status, *, q=5.0, cost=None, cfa=None, blocked=None, rl=None, gid="g", league="mlb"):
    return Row(T + t, gid, league, q, status, cost, rl, cfa, blocked)


def test_rows_are_weighted_by_dwell_not_counted():
    rows = [r(0, "NO_EDGE", cost=1.02, cfa=2.0), r(10, "NO_EDGE", cost=1.02, cfa=2.0),
            r(20, "BLOCKED_STALE", blocked="polymarket:x:HASH_MISMATCH")]
    games = {"g": {"start": T - 3600, "post": None}}
    out = distribute(rows, games, [], dwell_cap_s=60.0)
    cell = out["cells"]["mlb|5|end|clean"]           # no post transition: the last row stands for the end
    assert cell["rows"] == 3 and cell["dwell_s"] == 10 + 10 + 60
    assert cell["status_share"]["NO_EDGE"] == 0.25 and cell["status_share"]["BLOCKED_STALE"] == 0.75
    assert cell["blocked_reason_share"] == {"polymarket:HASH_MISMATCH": 0.75}
    assert cell["priced_share"] == 0.25 and cell["near_actionable_share"] == 0.0
    assert cell["cost_p50"] == 1.02 and cell["cost_min"] == 1.02


def test_phases_cut_on_start_and_the_post_transition():
    g = {"start": T + 100, "post": T + 2000}
    assert phase_of(T + 50, g, T + 3000) == "pre"
    assert phase_of(T + 500, g, T + 3000) == "in"
    assert phase_of(T + 1500, g, T + 3000) == "end"
    assert phase_of(T + 2500, g, T + 3000) == "post"
    assert phase_of(T + 2900, None, T + 3000) == "end", "no game record: the last row is the end"
    assert phase_of(T + 100, None, T + 3000) == "in"


def test_reason_tails_are_kept_raw():
    assert reason_of("polymarket:mlb:pittsburgh-pirates:STALE") == "polymarket:STALE"
    assert reason_of("kalshi:x:SOMETHING_NEW") == "kalshi:SOMETHING_NEW", "an unknown fault stays visible"
    assert reason_of("insufficient_depth") == "insufficient_depth"
    assert reason_of(None) == "(none)"


def test_flap_windows_come_from_socket_health_and_the_declared_loop():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE socket_health(seen_ts REAL, venue TEXT, connected INTEGER, errors INTEGER)")
    con.executemany("INSERT INTO socket_health VALUES(?,?,?,?)",
                    [(T, "kalshi", 1, 0), (T + 60, "kalshi", 1, 0), (T + 120, "kalshi", 0, 0), (T + 180, "kalshi", 1, 3), (T + 240, "kalshi", 1, 3)])
    w = load_flap_windows(con, declared=[(T + 900, T + 1000)])
    assert w == [(T + 60, T + 120), (T + 120, T + 180), (T + 900, T + 1000)]
    assert in_windows(T + 90, w) and not in_windows(T + 30, w) and in_windows(T + 950, w)


def test_profitable_rows_are_audited_against_stale_neighbours_and_the_n_is_declared_when_thin():
    rows = [r(0, "PROFITABLE_UNEXECUTED", cost=0.93, cfa=-7.0, rl=0.07),
            r(30, "BLOCKED_STALE", blocked="polymarket:x:STALE"),
            r(5000, "PROFITABLE_UNEXECUTED", cost=0.98, cfa=-2.0, rl=0.02, gid="h"),
            r(5100, "NO_EDGE", cost=1.01, cfa=1.0, gid="h")]
    games = {"g": {"start": T - 100, "post": T + 9000}, "h": {"start": T - 100, "post": T + 9000}}
    out = distribute(rows, games, [(T - 10, T + 100)])
    p = out["profitable"]
    assert p[0]["stale_within_60s"] and p[0]["flapping"] and p[0]["phase"] == "in"
    assert not p[1]["stale_within_60s"] and not p[1]["flapping"]
    assert out["n_for_paper"]["basis"] == "declared" and out["n_for_paper"]["n"] == 30
    many = [{"phase": "in", "flapping": False, "return_locked": 0.01 + 0.002 * (i % 5)} for i in range(20)]
    n = paper_n(many)
    assert n["basis"] == "power" and n["n"] >= 30 and n["in_play_clean_actionable_rows"] == 20


def test_the_old_vocabulary_is_excluded_and_counted():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE stream_evaluations(seen_ts REAL, game_id TEXT, league TEXT, quantity REAL, status TEXT, cost REAL, "
                "return_locked REAL, cents_from_actionable REAL, blocked_by TEXT)")
    con.executemany("INSERT INTO stream_evaluations VALUES(?,?,?,?,?,?,?,?,?)",
                    [(T, "g", "mlb", 5.0, "ACTIONABLE", 0.99, 0.01, -1.0, None),
                     (T + 1, "g", "mlb", 5.0, "kalshi:mlb:x:STALE", None, None, None, None),
                     (T + 2, "g", "mlb", 5.0, "NO_EDGE", 1.02, -0.02, 2.0, None),
                     (T - 100, "g", "mlb", 5.0, "NO_EDGE", 1.02, -0.02, 2.0, None)])
    rows, excluded = load_rows(con, since=T)
    assert [x.status for x in rows] == ["NO_EDGE"] and excluded == 2
