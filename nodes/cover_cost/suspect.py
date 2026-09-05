#!/usr/bin/env python3
"""L40: a SUSPECT label for a profitable print that can be FALSE.

L36 labels a PROFITABLE_UNEXECUTED row SUSPECT when a stale-family fault on the SAME GAME sits
within +-60 s of it, any replica, any quantity, before or after. Under the 200 ms coalescing window
and the 15 s heartbeat a quiet book's replica reports stale-family blocks almost continuously, so
that clause fired on 276 of 277 clean-window prints (2026-09-05): a monitor that always fires.
L36's criteria are immutable, so this is a NEW descriptive row with a rule that asks the sharper
question -- was a book THIS print was priced from untrustworthy just BEFORE it was priced?

  SUSPECT_V2 iff any of:
    flapping      -- the print sits inside a socket flap window (L36's definition, unchanged);
    end           -- the print is in the last 600 s of the game (closing books; L36's phase);
    stale_before  -- a stale-family fault on a replica (venue, outcome) that one of the print's
                     legs was priced from, in the 60 s BEFORE the print (inclusive), never after.
                     A Kalshi ":NO" leg on ticker T maps to T's outcome (the NO book is the same
                     ticker's message stream folded); a Polymarket NO token maps to its YES twin's.

Reads no outcome, claims no edge. Ledger L40 owns the definitions; this module only computes them.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from statistics import median, pstdev

from nodes.cover_cost.distribution import END_WINDOW_S, STALE_FAMILY, in_windows, load_games, phase_of

BEFORE_S = 60.0


def _fault_replica(blocked_by: str | None) -> tuple[str, str] | None:
    """`venue:outcome:FAULT` -> (venue, outcome) when FAULT is stale-family; else None."""
    if not blocked_by:
        return None
    parts = blocked_by.split(":")
    if len(parts) < 3 or parts[-1] not in STALE_FAMILY:
        return None
    return parts[0], ":".join(parts[1:-1])


def leg_replicas(legs: list[dict], outcomes: dict) -> set[tuple[str, str]]:
    """The (venue, outcome key) replicas a print's legs were priced from, via the event's outcomes
    map {outcome_key: {kalshi: ticker, polymarket: token, polymarket_no: token}}."""
    by_market: dict[tuple[str, str], str] = {}
    for key, v in (outcomes or {}).items():
        for venue in ("kalshi", "polymarket"):
            if v.get(venue):
                by_market[(venue, str(v[venue]))] = key
        if v.get("polymarket_no"):
            by_market[("polymarket", str(v["polymarket_no"]))] = key
    out: set[tuple[str, str]] = set()
    for leg in legs or []:
        venue, mid = leg.get("venue"), str(leg.get("outcome") or "")
        if mid.endswith(":NO"):
            mid = mid[:-3]
        key = by_market.get((venue, mid))
        if key is not None:
            out.add((venue, key))
    return out


def load(con: sqlite3.Connection, *, since: float, until: float) -> dict:
    prints = [{"seen_ts": float(r[0]), "game_id": r[1], "league": r[2], "quantity": float(r[3]), "cost": r[4],
               "return_locked": r[5], "legs": json.loads(r[6]) if r[6] else []}
              for r in con.execute("SELECT seen_ts, game_id, league, quantity, cost, return_locked, legs_json FROM stream_evaluations "
                                   "WHERE status='PROFITABLE_UNEXECUTED' AND seen_ts >= ? AND seen_ts < ? ORDER BY seen_ts", (since, until))]
    faults: dict[tuple[str, str, str], list[float]] = defaultdict(list)          # (game, venue, outcome) -> fault times
    for ts, gid, bb in con.execute("SELECT seen_ts, game_id, blocked_by FROM stream_evaluations WHERE status LIKE 'BLOCKED%' "
                                   "AND blocked_by IS NOT NULL AND seen_ts >= ? AND seen_ts < ?", (since - BEFORE_S, until)):
        rep = _fault_replica(bb)
        if rep is not None:
            faults[(gid, rep[0], rep[1])].append(float(ts))
    outcomes = {eid: (json.loads(sj).get("outcomes") or {}) for eid, sj in con.execute("SELECT event_id, spec_json FROM events WHERE spec_json IS NOT NULL")}
    last_ts: dict[str, float] = defaultdict(float)
    for gid, ts in con.execute("SELECT game_id, MAX(seen_ts) FROM stream_evaluations WHERE seen_ts >= ? AND seen_ts < ? GROUP BY game_id", (since, until)):
        last_ts[gid] = float(ts)
    return {"prints": prints, "faults": faults, "outcomes": outcomes, "games": load_games(con), "last_ts": last_ts}


def label(data: dict, flaps: list[tuple[float, float]]) -> dict:
    prints, faults, outcomes, games, last_ts = data["prints"], data["faults"], data["outcomes"], data["games"], data["last_ts"]
    for k in faults:
        faults[k].sort()
    out = []
    for p in prints:
        reps = leg_replicas(p["legs"], outcomes.get(p["game_id"], {}))
        stale_before = any(p["seen_ts"] - BEFORE_S <= t <= p["seen_ts"]
                           for (v, o) in reps for t in faults.get((p["game_id"], v, o), ()))
        phase = phase_of(p["seen_ts"], games.get(p["game_id"]), last_ts.get(p["game_id"], p["seen_ts"]))
        flapping = in_windows(p["seen_ts"], flaps)
        out.append({**p, "legs": len(p["legs"]), "replicas": len(reps), "phase": phase, "flapping": flapping,
                    "stale_before_60s": stale_before, "unmapped_legs": len(p["legs"]) - len(reps) if p["legs"] else 0,
                    "suspect_v2": bool(flapping or phase == "end" or stale_before or not reps)})
    clean = [p for p in out if not p["suspect_v2"]]
    by = defaultdict(lambda: {"prints": 0, "clean": 0, "returns": []})
    for p in out:
        for key in ((p["league"],), (p["league"], f"{p['quantity']:g}"), (p["league"], p["phase"])):
            c = by["|".join(key)]
            c["prints"] += 1
            if not p["suspect_v2"]:
                c["clean"] += 1
                c["returns"].append(float(p["return_locked"] or 0.0))
    cells = {k: {"prints": v["prints"], "clean": v["clean"],
                 "clean_median_return": round(median(v["returns"]), 5) if v["returns"] else None,
                 "clean_sigma_return": round(pstdev(v["returns"]), 5) if len(v["returns"]) > 1 else None}
             for k, v in sorted(by.items())}
    why = {"flapping": sum(p["flapping"] for p in out), "end": sum(p["phase"] == "end" for p in out),
           "stale_before_60s": sum(p["stale_before_60s"] for p in out), "no_mapped_replica": sum(not p["replicas"] for p in out)}
    return {"prints": len(out), "clean": len(clean), "suspect": len(out) - len(clean), "why": why, "cells": cells,
            "clean_rows": [{k: v for k, v in p.items() if k != "legs"} for p in clean], "rows": out}
