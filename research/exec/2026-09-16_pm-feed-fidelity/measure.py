#!/usr/bin/env python3
"""L145: is the Polymarket websocket book unfaithful on markets the lane never selected?

Read-only.  Runs on the box from ``/opt/janus`` so every REST ladder is parsed by the deployed,
reviewed ``pm_book`` / ``kalshi_book`` (both byte-identical between 59dd5ae and the tree that
registered this row).

One bounded pass:
  1. read recent priced ``stream_evaluations`` rows and collect their plain (non-``:NO``) legs;
  2. fetch each distinct leg's REST book once, alternating venues so a deadline cannot starve one;
  3. after the sweep, pair each REST read with the ``stream_evaluations`` row NEAREST in time for
     the same game and quantity, and compare the VWAP each implies at that quantity.

Nothing here mutates lane state.  No replica, no ``Reconciler``, no ``fresh_book``, no socket.
"""
from __future__ import annotations

import json
import math
import sqlite3
import statistics
import sys
import time
from collections import Counter, defaultdict
from typing import Any

DB = "/srv/janus/tuples/tuples.sqlite"
SCHEMA = "janus.l145.pm_feed_fidelity.v1"

# Registered in spec.yaml before any extraction.  Do not move these.
FRESH_S = 3.0
SENSITIVITY_FRESH_S = (1.0, 5.0)
MOVE_EPS_C = 0.05
FAV_OPTIMISTIC = 0.25
FAV_SYMMETRIC_LO, FAV_SYMMETRIC_HI = 0.35, 0.65
MEDIAN_OPTIMISTIC_C = 1.0
MIN_MOVED_PAIRS = 30

# Operational bounds.  ops/box/run.sh gives ~300 s; leave room for the pairing pass.
LOOKBACK_S = 120.0
FETCH_DEADLINE_S = 170.0
MAX_LEGS_PER_VENUE = 220
PM_RATE, PM_BURST = 2.0, 4.0        # half the lane reconciler's bucket: PM queues, never rejects
K_RATE, K_BURST = 4.0, 8.0
KALSHI_DEPTH = 20


def walk_vwap(asks, contracts: float) -> float | None:
    """Average price to buy `contracts` off an ask ladder, or None when depth is short.

    Identical arithmetic to `nodes.execute.plan.vwap_for_size` (walk_ladder + round 6); pinned by
    test_measure.py.  Carried from L116's measure.py.
    """
    need, gross = float(contracts), 0.0
    for p, s in asks:
        if need <= 1e-9:
            break
        take = min(need, float(s))
        gross += take * float(p)
        need -= take
    return round(gross / contracts, 6) if need <= 1e-9 and contracts > 0 else None


def plain_legs(legs_json: str | None) -> list[tuple[str, str, float]]:
    """(venue, market_id, vwap) for priced legs that are NOT a ':NO' projection.

    outcome_id == market_id for a plain leg (poller.py:297-298).  A ':NO' leg's book is the
    complementary token/projection and is deliberately excluded rather than mapped.
    """
    try:
        legs = json.loads(legs_json) if legs_json else []
    except (TypeError, ValueError):
        return []
    out = []
    for leg in legs if isinstance(legs, list) else []:
        if not isinstance(leg, dict) or "control" in leg:
            continue
        venue, outcome, vwap = leg.get("venue"), str(leg.get("outcome") or ""), leg.get("vwap")
        if venue not in ("polymarket", "kalshi") or not outcome or vwap is None:
            continue
        if outcome.endswith(":NO"):
            continue
        out.append((venue, outcome, float(vwap)))
    return out


def no_legs_in(legs_json: str | None) -> int:
    try:
        legs = json.loads(legs_json) if legs_json else []
    except (TypeError, ValueError):
        return 0
    return sum(1 for leg in (legs if isinstance(legs, list) else [])
               if isinstance(leg, dict) and str(leg.get("outcome") or "").endswith(":NO"))


def qsummary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    xs = sorted(float(x) for x in values)

    def pct(p: float) -> float:
        return xs[max(0, min(len(xs) - 1, math.ceil(p * len(xs)) - 1))]

    return {"n": len(xs), "p10": round(pct(.10), 4), "p50": round(pct(.50), 4),
            "p90": round(pct(.90), 4), "min": round(xs[0], 4), "max": round(xs[-1], 4),
            "mean": round(statistics.fmean(xs), 4)}


def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> dict[str, Any]:
    if len(xs) != len(ys) or len(xs) < 4:
        return {"n": len(xs), "rho": None}
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx <= 0 or dy <= 0:
        return {"n": len(xs), "rho": None, "note": "zero rank variance"}
    return {"n": len(xs), "rho": round(num / (dx * dy), 4)}


def symmetry(gaps: list[float]) -> dict[str, Any]:
    """Favourable fraction GIVEN A MOVE.  The L144 denominator correction, applied on purpose."""
    moved = [g for g in gaps if abs(g) > MOVE_EPS_C]
    fav = sum(1 for g in moved if g < 0)
    return {"pairs": len(gaps), "moved": len(moved), "favourable": fav,
            "adverse": len(moved) - fav, "unchanged": len(gaps) - len(moved),
            "favourable_given_move": (round(fav / len(moved), 4) if moved else None),
            "moved_gap_c": qsummary(moved), "all_gap_c": qsummary(gaps)}


def classify(pm: dict, k: dict) -> tuple[str, str]:
    """Strictly the registered decision_rule.  No branch is widened here."""
    pm_f, k_f = pm.get("favourable_given_move"), k.get("favourable_given_move")
    pm_med = pm.get("moved_gap_c", {}).get("p50")
    k_med = k.get("moved_gap_c", {}).get("p50")
    if pm.get("moved", 0) < MIN_MOVED_PAIRS or k.get("moved", 0) < MIN_MOVED_PAIRS:
        return "MIXED_OR_INCONCLUSIVE", (
            f"moved pairs PM={pm.get('moved', 0)} Kalshi={k.get('moved', 0)}; registered minimum "
            f"{MIN_MOVED_PAIRS} per venue")
    if pm_f is None or k_f is None or pm_med is None or k_med is None:
        return "MIXED_OR_INCONCLUSIVE", "a required statistic is undefined"
    if (FAV_SYMMETRIC_LO <= pm_f <= FAV_SYMMETRIC_HI
            and FAV_SYMMETRIC_LO <= k_f <= FAV_SYMMETRIC_HI):
        return "NEITHER_OPTIMISTIC", (
            f"both symmetric given a move: PM {pm_f}, Kalshi {k_f} within "
            f"[{FAV_SYMMETRIC_LO}, {FAV_SYMMETRIC_HI}]")
    if (pm_f < FAV_OPTIMISTIC and pm_med >= MEDIAN_OPTIMISTIC_C
            and k_f < FAV_OPTIMISTIC and k_med >= MEDIAN_OPTIMISTIC_C):
        return "BOTH_OPTIMISTIC", (
            f"both one-sided: PM {pm_f} median {pm_med:+.2f}c, Kalshi {k_f} median {k_med:+.2f}c")
    if pm_f < FAV_OPTIMISTIC and pm_med >= MEDIAN_OPTIMISTIC_C and k_f >= FAV_SYMMETRIC_LO:
        return "PM_FEED_OPTIMISTIC", (
            f"PM favourable-given-move {pm_f} < {FAV_OPTIMISTIC} with moved median {pm_med:+.2f}c, "
            f"while Kalshi {k_f} >= {FAV_SYMMETRIC_LO}")
    return "MIXED_OR_INCONCLUSIVE", "no registered branch was satisfied"


def nearest_row(con, game_id: str, quantity: float, t: float) -> tuple | None:
    """The stream_evaluations row for (game, quantity) nearest `t`, before or after."""
    best = None
    for sql in ("SELECT seen_ts, status, legs_json FROM stream_evaluations "
                "WHERE game_id=? AND quantity=? AND seen_ts<=? ORDER BY seen_ts DESC LIMIT 1",
                "SELECT seen_ts, status, legs_json FROM stream_evaluations "
                "WHERE game_id=? AND quantity=? AND seen_ts>? ORDER BY seen_ts ASC LIMIT 1"):
        r = con.execute(sql, (game_id, quantity, t)).fetchone()
        if r is not None and (best is None or abs(r[0] - t) < abs(best[0] - t)):
            best = r
    return best


def run(db: str = DB) -> dict:
    from kernel.fetch import Client
    from nodes.venue_kalshi.books import KALSHI_BASE, kalshi_book
    from nodes.venue_polymarket.books import PM_CLOB, pm_book

    t_start = time.time()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

    # ── 1. what to sample: every priced (game, quantity) seen recently ─────────────────────
    targets: dict[tuple[str, str], set[tuple[str, float]]] = defaultdict(set)
    game_league: dict[str, str] = {}
    no_legs_seen = 0
    for game_id, league, q, legs_json in con.execute(
            "SELECT game_id, league, quantity, legs_json FROM stream_evaluations "
            "WHERE seen_ts>=? AND legs_json IS NOT NULL AND legs_json!='[]'",
            (t_start - LOOKBACK_S,)):
        game_league[game_id] = league
        no_legs_seen += no_legs_in(legs_json)
        for venue, market_id, _ in plain_legs(legs_json):
            targets[(venue, market_id)].add((game_id, float(q)))

    pm_ids = sorted(m for v, m in targets if v == "polymarket")[:MAX_LEGS_PER_VENUE]
    k_ids = sorted(m for v, m in targets if v == "kalshi")[:MAX_LEGS_PER_VENUE]
    capped = {"polymarket": max(0, sum(1 for v, _ in targets if v == "polymarket") - len(pm_ids)),
              "kalshi": max(0, sum(1 for v, _ in targets if v == "kalshi") - len(k_ids))}

    # ── 2. one REST read per leg, alternating venues so a deadline cannot starve one ───────
    pm_cl = Client("l145-polymarket", rate=PM_RATE, burst=PM_BURST, cache_dir=None)
    k_cl = Client("l145-kalshi", rate=K_RATE, burst=K_BURST, cache_dir=None)
    rest: dict[tuple[str, str], tuple[float, list]] = {}
    errors = Counter()
    order: list[tuple[str, str]] = []
    for i in range(max(len(pm_ids), len(k_ids))):
        if i < len(pm_ids):
            order.append(("polymarket", pm_ids[i]))
        if i < len(k_ids):
            order.append(("kalshi", k_ids[i]))
    deadline_hit, fetched = False, Counter()
    for venue, market_id in order:
        if time.time() - t_start > FETCH_DEADLINE_S:
            deadline_hit = True
            break
        try:
            if venue == "polymarket":
                payload = pm_cl.get_json(f"{PM_CLOB}/book", params={"token_id": market_id},
                                         use_cache=False)
                now = time.time()
                book = pm_book(payload, now)
            else:
                payload = k_cl.get_json(f"{KALSHI_BASE}/markets/{market_id}/orderbook",
                                        params={"depth": KALSHI_DEPTH}, use_cache=False)
                now = time.time()
                book = kalshi_book(payload, "yes", now, depth_requested=KALSHI_DEPTH)
            rest[(venue, market_id)] = (now, [(q.price, q.size) for q in book.asks])
            fetched[venue] += 1
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            errors[f"{venue}:{type(exc).__name__}"] += 1
    fetch_elapsed = time.time() - t_start

    # ── 3. pair each REST read with the NEAREST ws evaluation for the same game/quantity ───
    pairs: list[dict] = []
    fate = Counter()
    for (venue, market_id), (rest_t, asks) in rest.items():
        for game_id, q in targets[(venue, market_id)]:
            row = nearest_row(con, game_id, q, rest_t)
            if row is None:
                fate["no_ws_row"] += 1
                continue
            seen_ts, status, legs_json = row
            ws_vwap = next((v for vv, m, v in plain_legs(legs_json)
                            if vv == venue and m == market_id), None)
            if ws_vwap is None:
                fate["leg_absent_in_nearest_row"] += 1
                continue
            rest_vwap = walk_vwap(asks, q)
            if rest_vwap is None:
                fate["depth_short"] += 1
                continue
            sep = rest_t - float(seen_ts)
            pairs.append({"venue": venue, "market_id": market_id, "game_id": game_id,
                          "league": game_league.get(game_id), "quantity": q, "status": status,
                          "ws_vwap": ws_vwap, "rest_vwap": rest_vwap,
                          "gap_c": round((rest_vwap - ws_vwap) * 100.0, 6),
                          "separation_s": round(sep, 4)})
            fate["paired"] += 1
    con.close()

    def fresh(window: float, venue: str) -> list[dict]:
        return [p for p in pairs if p["venue"] == venue and abs(p["separation_s"]) <= window]

    pm = symmetry([p["gap_c"] for p in fresh(FRESH_S, "polymarket")])
    k = symmetry([p["gap_c"] for p in fresh(FRESH_S, "kalshi")])
    verdict, reason = classify(pm, k)

    by_status: dict[str, dict] = {}
    for status in sorted({p["status"] for p in pairs}):
        by_status[status] = {
            v: symmetry([p["gap_c"] for p in fresh(FRESH_S, v) if p["status"] == status])
            for v in ("polymarket", "kalshi")}
    by_quantity: dict[str, dict] = {}
    for qq in sorted({p["quantity"] for p in pairs}):
        by_quantity[f"{qq:g}"] = {
            v: symmetry([p["gap_c"] for p in fresh(FRESH_S, v) if p["quantity"] == qq])
            for v in ("polymarket", "kalshi")}
    sensitivity = {f"{w:g}s": {v: symmetry([p["gap_c"] for p in fresh(w, v)])
                               for v in ("polymarket", "kalshi")}
                   for w in SENSITIVITY_FRESH_S}
    sep_rho = {v: spearman([abs(p["separation_s"]) for p in fresh(FRESH_S, v)],
                           [p["gap_c"] for p in fresh(FRESH_S, v)])
               for v in ("polymarket", "kalshi")}

    return {
        "schema": SCHEMA,
        "extraction": {"db": db, "started_utc": t_start, "fetch_elapsed_s": round(fetch_elapsed, 2),
                       "total_elapsed_s": round(time.time() - t_start, 2),
                       "lookback_s": LOOKBACK_S, "fetch_deadline_s": FETCH_DEADLINE_S,
                       "deadline_hit": deadline_hit,
                       "rates": {"polymarket": [PM_RATE, PM_BURST], "kalshi": [K_RATE, K_BURST]},
                       "kalshi_depth_requested": KALSHI_DEPTH},
        "accounting": {"distinct_legs": {"polymarket": sum(1 for v, _ in targets if v == "polymarket"),
                                         "kalshi": sum(1 for v, _ in targets if v == "kalshi")},
                       "capped_by_max_legs": capped,
                       "no_legs_excluded": no_legs_seen,
                       "fetched": dict(fetched), "fetch_errors": dict(errors),
                       "pair_fate": dict(fate),
                       "pairs_total": len(pairs),
                       "pairs_fresh": {v: len(fresh(FRESH_S, v)) for v in ("polymarket", "kalshi")}},
        "polymarket": pm,
        "kalshi": k,
        "verdict": verdict,
        "verdict_reason": reason,
        "by_status": by_status,
        "by_quantity": by_quantity,
        "sensitivity_description_only": sensitivity,
        "gap_vs_separation": sep_rho,
        "registered_thresholds": {"fresh_s": FRESH_S, "move_eps_c": MOVE_EPS_C,
                                  "fav_optimistic": FAV_OPTIMISTIC,
                                  "fav_symmetric": [FAV_SYMMETRIC_LO, FAV_SYMMETRIC_HI],
                                  "median_optimistic_c": MEDIAN_OPTIMISTIC_C,
                                  "min_moved_pairs": MIN_MOVED_PAIRS},
        "pairs": pairs,
    }


if __name__ == "__main__":
    print(json.dumps(run(sys.argv[1] if len(sys.argv) > 1 else DB),
                     sort_keys=True, separators=(",", ":")))
