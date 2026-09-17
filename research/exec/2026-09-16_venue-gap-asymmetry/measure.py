#!/usr/bin/env python3
"""L144: is L143's one-sided first-leg gap our own selection, or Polymarket's feed?

Read-only.  The discriminator is the Kalshi hedge leg, which is confirmed CONCURRENTLY with leg A on
the same clearance window (coordinator.py:205-215) off the same ``books_json`` snapshot.  Joint
selection on the pair predicts both legs one-sided adverse; a Polymarket-specific market-data defect
predicts Kalshi roughly symmetric.

``walk``, ``qsummary`` and ``spearman`` are carried over verbatim from L143's measure.py, where
``walk`` is pinned by test to ``nodes.execute.plan.marginal_price``.

Ships to the box as a stdin heredoc through ``ops/box/run.sh``.
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
EXCLUDED_EXECUTION = "17077a35da5b46bb92b62daf0d927ff7"
TAIL_ROWS = 4000
SCHEMA = "janus.l144.venue_gap_asymmetry.v1"

# Registered in spec.yaml before any extraction.  Do not move these.
KALSHI_FAVOURABLE_SYMMETRIC = 0.30
PM_FAVOURABLE_ONESIDED = 0.10
MEDIAN_BAND_C = 1.5
MIN_PAIRED_ROWS = 40
RHO_MARGINAL = 0.25
RHO_STRATUM = 0.15

# L143's retained result, for the mandatory reconciliation.
L143_PM_ADVERSE, L143_PM_ZERO, L143_PM_FAVOURABLE = 155, 46, 1


def js(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


def walk(asks: list, contracts: float) -> tuple[float | None, float]:
    """Cumulative-depth marginal price.  Identical to plan.marginal_price; pinned by test."""
    cum, depth, marginal = 0.0, 0.0, None
    for p, s in asks or []:
        p, s = float(p), float(s)
        depth += s
        cum += s
        if marginal is None and cum >= contracts - 1e-9:
            marginal = p
    return marginal, depth


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
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
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


def favourable_fraction(gaps: list[float]) -> float | None:
    return round(sum(1 for g in gaps if g < 0) / len(gaps), 4) if gaps else None


def sign_counts(gaps: list[float]) -> dict[str, int]:
    return {"adverse": sum(1 for g in gaps if g > 1e-9),
            "zero": sum(1 for g in gaps if abs(g) <= 1e-9),
            "favourable": sum(1 for g in gaps if g < -1e-9)}


def apparent_edge(first: dict, hedge: dict, plan: dict) -> dict[str, Any]:
    """The Candidate arithmetic the clearance actually screened on (grid.py:1149-1157).

    Reconstructed from the FROZEN plan_json only.  opportunities.net_profit / locked_return are
    overwritten by observe() on every later evaluation and are not the selection-time value.
    """
    try:
        contracts = float(first.get("contracts") or 0.0)
        first_cost = (float(first["vwap"]) if first.get("post_only") and first.get("vwap") is not None
                      else float(first["limit_price"]))
        planned_cost = (first_cost + float(hedge["vwap"])
                        + float(plan.get("fee") or 0.0)
                        + float(plan.get("settlement_buffer") or 0.0))
    except (KeyError, TypeError, ValueError):
        return {"planned_cost": None, "net_profit_usd": None, "locked_return": None}
    if contracts <= 0:
        return {"planned_cost": None, "net_profit_usd": None, "locked_return": None}
    profit = contracts * (1.0 - planned_cost)
    capital = contracts * planned_cost
    return {"planned_cost": round(planned_cost, 8),
            "net_profit_usd": round(profit, 8),
            "locked_return": (round(profit / capital, 8) if capital > 0 else None)}


def _leg_from_books(books: Any, leg: dict) -> dict | None:
    for legs in (books.values() if isinstance(books, dict) else []):
        for candidate in (legs if isinstance(legs, list) else []):
            if (candidate.get("venue") == leg.get("venue")
                    and candidate.get("market_id") == leg.get("market_id")
                    and candidate.get("outcome_id") == leg.get("outcome_id")):
                return candidate
    return None


def _tertiles(values: list[float]) -> tuple[float, float]:
    xs = sorted(values)
    return xs[len(xs) // 3], xs[(2 * len(xs)) // 3]


def stratified(rows: list[dict], gap_key: str, target: str, control: str) -> dict[str, Any]:
    """Marginal rho for `target`, plus rho within each tertile of `control`."""
    usable = [r for r in rows if r.get(target) is not None and r.get(control) is not None]
    out: dict[str, Any] = {"marginal": spearman([r[target] for r in usable],
                                                [r[gap_key] for r in usable])}
    if len(usable) < 9:
        out["strata"] = {"note": f"only {len(usable)} rows carry both predictors"}
        return out
    lo, hi = _tertiles([r[control] for r in usable])
    bands = {"low": [r for r in usable if r[control] <= lo],
             "mid": [r for r in usable if lo < r[control] <= hi],
             "high": [r for r in usable if r[control] > hi]}
    out["strata"] = {k: spearman([r[target] for r in v], [r[gap_key] for r in v])
                     for k, v in bands.items()}
    marg = out["marginal"].get("rho")
    holds = 0
    if marg is not None:
        for s in out["strata"].values():
            rho = s.get("rho") if isinstance(s, dict) else None
            if rho is not None and abs(rho) >= RHO_STRATUM and (rho > 0) == (marg > 0):
                holds += 1
    out["load_bearing"] = bool(marg is not None and abs(marg) >= RHO_MARGINAL and holds >= 2)
    out["strata_holding"] = holds
    return out


def extract(db: str = DB, end_ts: float | None = None) -> dict:
    end = float(end_ts if end_ts is not None else time.time())
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    max_rowid = int(con.execute("SELECT max(rowid) FROM executions").fetchone()[0] or 0)
    tail = [dict(r) for r in con.execute(
        "SELECT rowid AS _rowid,* FROM executions WHERE rowid>=? ORDER BY rowid",
        (max(1, max_rowid - TAIL_ROWS),))]
    rows = [r for r in tail if r["started_utc"] is not None and float(r["started_utc"]) <= end
            and r["execution_id"] != EXCLUDED_EXECUTION]

    missing = Counter()
    per_row: list[dict] = []
    pm_only_gaps: list[float] = []      # for the mandatory L143 reconciliation

    for r in rows:
        plan = js(r.get("plan_json"), {})
        first = plan.get("first") if isinstance(plan, dict) else None
        hedge = plan.get("hedge") if isinstance(plan, dict) else None
        if not isinstance(first, dict) or not isinstance(hedge, dict):
            missing["plan.first_or_hedge"] += 1
            continue
        q_first = float(first.get("contracts") or 0.0)
        q_hedge = float(hedge.get("contracts") or 0.0)
        if q_first <= 0 or q_hedge <= 0:
            missing["planned_contracts"] += 1
            continue

        books = js(r.get("books_json"), {})
        pm_leg = _leg_from_books(books, first)
        k_leg = _leg_from_books(books, hedge)
        pj = js(r.get("protect_json"), {})
        fc = pj.get("first_leg_confirm") if isinstance(pj, dict) else None
        hc = pj.get("hedge_leg_confirm") if isinstance(pj, dict) else None

        pm_frozen = walk(pm_leg.get("asks"), q_first)[0] if pm_leg else None
        pm_conf = (float(fc["marginal"]) if isinstance(fc, dict) and fc.get("marginal") is not None
                   else None)
        k_frozen = walk(k_leg.get("asks"), q_hedge)[0] if k_leg else None
        k_conf = (float(hc["marginal"]) if isinstance(hc, dict) and hc.get("marginal") is not None
                  else None)

        # Reconciliation set: exactly L143's population, regardless of the Kalshi side.
        if pm_frozen is not None and pm_conf is not None:
            pm_only_gaps.append((pm_conf - float(pm_frozen)) * 100.0)

        if pm_frozen is None or pm_conf is None:
            missing["polymarket_pair"] += 1
            continue
        if k_frozen is None:
            missing["kalshi_frozen_ladder"] += 1
            continue
        if k_conf is None:
            missing["kalshi_confirmation"] += 1
            continue

        started = float(r["started_utc"])
        pm_age = ((started - float(pm_leg["fetched_utc"])) * 1000.0
                  if pm_leg.get("fetched_utc") is not None else None)
        k_age = ((started - float(k_leg["fetched_utc"])) * 1000.0
                 if k_leg.get("fetched_utc") is not None else None)
        edge = apparent_edge(first, hedge, plan)

        per_row.append({
            "rowid": int(r["_rowid"]), "execution_id": r["execution_id"], "state": r["state"],
            "league": r.get("league"),
            "pm_contracts": q_first, "kalshi_contracts": q_hedge,
            "pm_frozen": float(pm_frozen), "pm_confirmed": pm_conf,
            "pm_gap_c": round((pm_conf - float(pm_frozen)) * 100.0, 6),
            "kalshi_frozen": float(k_frozen), "kalshi_confirmed": k_conf,
            "kalshi_gap_c": round((k_conf - float(k_frozen)) * 100.0, 6),
            "pm_book_age_ms": pm_age, "kalshi_book_age_ms": k_age,
            "apparent_locked_return": edge["locked_return"],
            "apparent_net_profit_usd": edge["net_profit_usd"],
            "pm_source": pm_leg.get("source"), "kalshi_source": k_leg.get("source"),
        })

    pm_gaps = [x["pm_gap_c"] for x in per_row]
    k_gaps = [x["kalshi_gap_c"] for x in per_row]
    by_state: dict[str, list[dict]] = defaultdict(list)
    for x in per_row:
        by_state[x["state"]].append(x)

    pm_only_signs = sign_counts(pm_only_gaps)
    reconciles = (pm_only_signs["adverse"] == L143_PM_ADVERSE
                  and pm_only_signs["zero"] == L143_PM_ZERO
                  and pm_only_signs["favourable"] == L143_PM_FAVOURABLE)

    pm_fav, k_fav = favourable_fraction(pm_gaps), favourable_fraction(k_gaps)
    pm_med = qsummary(pm_gaps).get("p50")
    k_med = qsummary(k_gaps).get("p50")

    verdict, reason = "MIXED_OR_INCONCLUSIVE", "no registered branch was satisfied"
    if len(per_row) < MIN_PAIRED_ROWS:
        reason = f"only {len(per_row)} paired rows (registered minimum {MIN_PAIRED_ROWS})"
    elif pm_fav is not None and k_fav is not None and pm_med is not None and k_med is not None:
        if (k_fav >= KALSHI_FAVOURABLE_SYMMETRIC and abs(k_med) <= MEDIAN_BAND_C
                and pm_fav < PM_FAVOURABLE_ONESIDED and pm_med >= MEDIAN_BAND_C):
            verdict, reason = "VENUE_SPECIFIC_POLYMARKET", (
                f"Kalshi favourable {k_fav} >= {KALSHI_FAVOURABLE_SYMMETRIC} with median "
                f"{k_med:+.2f}c inside +/-{MEDIAN_BAND_C}c, while Polymarket favourable {pm_fav} < "
                f"{PM_FAVOURABLE_ONESIDED} with median {pm_med:+.2f}c")
        elif k_fav < KALSHI_FAVOURABLE_SYMMETRIC and k_med >= MEDIAN_BAND_C:
            verdict, reason = "JOINT_SELECTION", (
                f"both legs one-sided adverse: Kalshi favourable {k_fav} < "
                f"{KALSHI_FAVOURABLE_SYMMETRIC}, median {k_med:+.2f}c >= {MEDIAN_BAND_C}c")

    return {
        "schema": SCHEMA,
        "extraction": {"db": db, "end_utc": end, "tail_rows_requested": TAIL_ROWS,
                       "tail_rows_read": len(tail), "max_rowid": max_rowid,
                       "excluded_execution": EXCLUDED_EXECUTION},
        "reconciliation_with_l143": {
            "polymarket_only_rows": len(pm_only_gaps), "sign_counts": pm_only_signs,
            "expected": {"adverse": L143_PM_ADVERSE, "zero": L143_PM_ZERO,
                         "favourable": L143_PM_FAVOURABLE},
            "reconciles": reconciles},
        "population": {"executions_in_scope": len(rows), "paired_rows": len(per_row),
                       "missing": dict(sorted(missing.items())),
                       "paired_by_state": {k: len(v) for k, v in sorted(by_state.items())}},
        "polymarket": {"signed_gap_c": qsummary(pm_gaps), "favourable_fraction": pm_fav,
                       "sign_counts": sign_counts(pm_gaps),
                       "book_age_ms": qsummary([x["pm_book_age_ms"] for x in per_row
                                                if x["pm_book_age_ms"] is not None]),
                       "source": dict(sorted(Counter(x["pm_source"] for x in per_row).items()))},
        "kalshi": {"signed_gap_c": qsummary(k_gaps), "favourable_fraction": k_fav,
                   "sign_counts": sign_counts(k_gaps),
                   "book_age_ms": qsummary([x["kalshi_book_age_ms"] for x in per_row
                                            if x["kalshi_book_age_ms"] is not None]),
                   "source": dict(sorted(Counter(x["kalshi_source"] for x in per_row).items()))},
        "by_state": {k: {"n": len(v),
                         "polymarket_gap_c": qsummary([x["pm_gap_c"] for x in v]),
                         "polymarket_favourable": favourable_fraction([x["pm_gap_c"] for x in v]),
                         "kalshi_gap_c": qsummary([x["kalshi_gap_c"] for x in v]),
                         "kalshi_favourable": favourable_fraction([x["kalshi_gap_c"] for x in v])}
                     for k, v in sorted(by_state.items())},
        "secondary_polymarket_only": {
            "gap_vs_apparent_edge": stratified(per_row, "pm_gap_c", "apparent_locked_return",
                                               "pm_book_age_ms"),
            "gap_vs_book_age": stratified(per_row, "pm_gap_c", "pm_book_age_ms",
                                          "apparent_locked_return"),
            "thresholds": {"marginal": RHO_MARGINAL, "stratum": RHO_STRATUM}},
        "verdict": verdict,
        "verdict_reason": reason,
        "registered_thresholds": {
            "kalshi_favourable_symmetric": KALSHI_FAVOURABLE_SYMMETRIC,
            "pm_favourable_onesided": PM_FAVOURABLE_ONESIDED,
            "median_band_c": MEDIAN_BAND_C, "min_paired_rows": MIN_PAIRED_ROWS},
        "rows": per_row,
    }


if __name__ == "__main__":
    end_arg = float(sys.argv[1]) if len(sys.argv) > 1 else None
    print(json.dumps(extract(end_ts=end_arg), sort_keys=True, separators=(",", ":")))
