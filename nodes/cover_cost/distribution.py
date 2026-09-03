#!/usr/bin/env python3
"""The recorded cover-cost distribution: what the streaming lane priced, per league, quantity and
game phase, with every blocked reason kept distinct and the flapping minutes kept apart.

The rows are `stream_evaluations` (nodes/store_tuples): a MATERIAL-CHANGE series, written on a
status change, a 0.1c move in cost, or a 15 s heartbeat. They are not samples. So every row is
weighted by its DWELL -- the seconds until the next row of the same (game, quantity), capped --
and the raw row count is reported beside every weighted figure.

Reads no outcome, claims no edge. Ledger L36 owns the definitions; this module only computes them.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from statistics import median, pstdev
from typing import Iterable, Mapping, Sequence

from kernel.schema import OpportunityStatus

#: Statuses the streaming lane writes. Anything else in the table is an older vocabulary (the REST
#: lane's) and is EXCLUDED by definition, counted once, never folded in.
VOCAB = frozenset(s.value for s in OpportunityStatus)
#: Replica faults that mean "a book was not trustworthy at that instant" (nodes/book_replica).
STALE_FAMILY = ("STALE", "HASH_MISMATCH", "HEARTBEAT_LOST", "UNVERIFIED_TOO_LONG", "NOT_SYNCED", "SEQ_GAP", "CROSSED_BOOK")
DWELL_CAP_S = 60.0          # a row never holds longer than this (the heartbeat is 15 s)
END_WINDOW_S = 600.0        # the last ten minutes before the game's end
NEAR_ACTIONABLE_CENTS = 1.0
QUANTITIES = (5.0, 25.0, 100.0)


@dataclass(frozen=True)
class Row:
    seen_ts: float
    game_id: str
    league: str
    quantity: float
    status: str
    cost: float | None
    return_locked: float | None
    cents_from_actionable: float | None
    blocked_by: str | None


@dataclass
class Cell:
    rows: int = 0
    dwell_s: float = 0.0
    by_status: dict[str, float] = field(default_factory=lambda: defaultdict(float))       # dwell
    by_reason: dict[str, float] = field(default_factory=lambda: defaultdict(float))       # dwell, blocked rows only
    priced_dwell_s: float = 0.0
    near_dwell_s: float = 0.0           # priced and within NEAR_ACTIONABLE_CENTS
    profitable_dwell_s: float = 0.0
    costs: list[tuple[float, float]] = field(default_factory=list)                        # (cost, dwell)

    def summary(self) -> dict:
        d = self.dwell_s or 1.0
        return {"rows": self.rows, "dwell_s": round(self.dwell_s, 1),
                "status_share": {k: round(v / d, 4) for k, v in sorted(self.by_status.items())},
                "blocked_reason_share": {k: round(v / d, 4) for k, v in sorted(self.by_reason.items())},
                "priced_share": round(self.priced_dwell_s / d, 4),
                "near_actionable_share": round(self.near_dwell_s / d, 4),
                "profitable_share": round(self.profitable_dwell_s / d, 4),
                "cost_p50": _wq(self.costs, 0.5), "cost_p90": _wq(self.costs, 0.9),
                "cost_min": round(min(c for c, _ in self.costs), 4) if self.costs else None}


def _wq(pairs: Sequence[tuple[float, float]], q: float) -> float | None:
    """Dwell-weighted quantile of cost."""
    if not pairs:
        return None
    s = sorted(pairs)
    total = sum(w for _, w in s)
    acc = 0.0
    for c, w in s:
        acc += w
        if acc >= q * total:
            return round(c, 4)
    return round(s[-1][0], 4)


def reason_of(blocked_by: str | None) -> str:
    """`venue:outcome:FAULT` -> `venue:FAULT`; a cover reject reason stays as it is. The tail is
    kept raw so an unrecognised fault cannot hide behind the status it was mapped to."""
    if not blocked_by:
        return "(none)"
    parts = blocked_by.split(":")
    if len(parts) >= 3:
        return f"{parts[0]}:{parts[-1]}"
    return blocked_by


def load_rows(con: sqlite3.Connection, *, since: float, until: float | None = None) -> tuple[list[Row], int]:
    """Rows in the lane's vocabulary, and the count of rows outside it (excluded)."""
    q = "SELECT seen_ts, game_id, league, quantity, status, cost, return_locked, cents_from_actionable, blocked_by " \
        "FROM stream_evaluations WHERE seen_ts >= ?" + (" AND seen_ts < ?" if until else "") + " ORDER BY seen_ts"
    args = (since, until) if until else (since,)
    rows, excluded = [], 0
    for r in con.execute(q, args):
        if r[4] not in VOCAB:
            excluded += 1
            continue
        rows.append(Row(float(r[0]), r[1], r[2], float(r[3]), r[4], r[5], r[6], r[7], r[8]))
    return rows, excluded


def load_games(con: sqlite3.Connection) -> dict[str, dict]:
    """start and end per game. End = the first `post` transition; None when the slate reaped the
    game before ESPN said post (then the game's last row stands in, see phase_of)."""
    games: dict[str, dict] = {}
    for eid, start in con.execute("SELECT event_id, start_utc FROM events"):
        games[eid] = {"start": float(start) if start is not None else None, "post": None}
    for eid, ts in con.execute("SELECT event_id, MIN(seen_ts) FROM event_transitions WHERE phase LIKE 'post%' GROUP BY event_id"):
        games.setdefault(eid, {"start": None, "post": None})["post"] = float(ts)
    return games


def load_flap_windows(con: sqlite3.Connection, *, declared: Iterable[tuple[float, float]] = ()) -> list[tuple[float, float]]:
    """Intervals in which a venue socket was flapping: between two consecutive socket_health rows of
    a venue where the later row is disconnected or its error count rose, plus the declared
    windows (the 2026-09-03 loop pre-dates the reconnect counter)."""
    out = list(declared)
    prev: dict[str, tuple[float, int]] = {}
    for ts, venue, connected, errors in con.execute("SELECT seen_ts, venue, connected, errors FROM socket_health ORDER BY seen_ts"):
        e = int(errors or 0)
        if venue in prev:
            pts, pe = prev[venue]
            if not connected or e > pe:
                out.append((pts, float(ts)))
        prev[venue] = (float(ts), e)
    return sorted(out)


def in_windows(t: float, windows: Sequence[tuple[float, float]]) -> bool:
    return any(a <= t <= b for a, b in windows)


def phase_of(t: float, game: Mapping | None, last_row_ts: float) -> str:
    """pre | in | end | post. `end` is the last END_WINDOW_S before the game's end, where the end is
    the post transition when one was recorded and the game's last evaluation row otherwise."""
    start = (game or {}).get("start")
    post = (game or {}).get("post")
    end_ts = post if post is not None else last_row_ts
    if start is not None and t < start:
        return "pre"
    if post is not None and t > post:
        return "post"
    if t >= end_ts - END_WINDOW_S:
        return "end"
    return "in"


def distribute(rows: Sequence[Row], games: Mapping[str, dict], flaps: Sequence[tuple[float, float]],
               *, dwell_cap_s: float = DWELL_CAP_S) -> dict:
    """Cells keyed (league, quantity, phase, flapping) plus the profitable-row audit and the n."""
    by_key: dict[tuple[str, float], list[Row]] = defaultdict(list)
    for r in rows:
        by_key[(r.game_id, r.quantity)].append(r)
    last_ts: dict[str, float] = defaultdict(float)
    for r in rows:
        last_ts[r.game_id] = max(last_ts[r.game_id], r.seen_ts)
    cells: dict[tuple, Cell] = defaultdict(Cell)
    profitable: list[dict] = []
    stale_ts: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r.blocked_by and any(f in r.blocked_by for f in STALE_FAMILY):
            stale_ts[r.game_id].append(r.seen_ts)
    for (gid, q), series in by_key.items():
        series.sort(key=lambda x: x.seen_ts)
        for i, r in enumerate(series):
            nxt = series[i + 1].seen_ts if i + 1 < len(series) else r.seen_ts + dwell_cap_s
            dwell = max(0.0, min(dwell_cap_s, nxt - r.seen_ts))
            phase = phase_of(r.seen_ts, games.get(gid), last_ts[gid])
            flapping = in_windows(r.seen_ts, flaps)
            c = cells[(r.league, q, phase, flapping)]
            c.rows += 1
            c.dwell_s += dwell
            c.by_status[r.status] += dwell
            if r.status.startswith("BLOCKED"):
                c.by_reason[reason_of(r.blocked_by)] += dwell
            if r.cost is not None:
                c.priced_dwell_s += dwell
                c.costs.append((float(r.cost), dwell))
                if r.cents_from_actionable is not None and float(r.cents_from_actionable) <= NEAR_ACTIONABLE_CENTS:
                    c.near_dwell_s += dwell
            if r.status == OpportunityStatus.PROFITABLE_UNEXECUTED.value:
                c.profitable_dwell_s += dwell
                near_stale = any(abs(t - r.seen_ts) <= 60.0 for t in stale_ts[gid])
                profitable.append({"seen_ts": r.seen_ts, "game_id": gid, "league": r.league, "quantity": q,
                                   "phase": phase, "flapping": flapping, "cost": r.cost,
                                   "return_locked": r.return_locked, "stale_within_60s": near_stale})
    out = {"cells": {f"{k[0]}|{k[1]:g}|{k[2]}|{'flap' if k[3] else 'clean'}": v.summary() for k, v in sorted(cells.items())},
           "profitable": sorted(profitable, key=lambda d: d["seen_ts"]),
           "n_for_paper": paper_n(profitable)}
    return out


def paper_n(profitable: Sequence[Mapping]) -> dict:
    """GATE step 7: n for the forward paper row, from the in-play, non-flapping actionable rows'
    locked return. n = max(30, ceil((1.96 * sigma / 0.005)^2)); with fewer than 5 such rows sigma is
    undefined and n = 30 by declaration, said so."""
    import math
    clean = [float(p["return_locked"]) for p in profitable
             if p["phase"] == "in" and not p["flapping"] and p["return_locked"] is not None]
    if len(clean) < 5:
        return {"n": 30, "basis": "declared", "in_play_clean_actionable_rows": len(clean),
                "note": "fewer than 5 in-play, non-flapping actionable rows: sigma undefined, n = 30 by declaration"}
    sigma = pstdev(clean)
    n = max(30, math.ceil((1.96 * sigma / 0.005) ** 2))
    return {"n": n, "basis": "power", "in_play_clean_actionable_rows": len(clean),
            "sigma_locked_return": round(sigma, 5), "median_locked_return": round(median(clean), 5)}
