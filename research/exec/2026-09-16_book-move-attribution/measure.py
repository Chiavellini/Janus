#!/usr/bin/env python3
"""L143: is the pre-wire first-leg decline latency or adverse selection?

Read-only.  Bounded by the executions rowid tail, exactly as L141, and it never opens a write
transaction.  The methodological difference from L141 is the population: this walks EVERY execution
carrying both a frozen plan ladder and a fresh confirmation ladder, not only the BOOK_MOVED rows.
Conditioning on the decline selects the unfavourable tail and cannot tell a shifted distribution
apart from the tail of a centred one, which is the whole question.

Ships to the box as a stdin heredoc through ``ops/box/run.sh``.  Prints one JSON object whose
``schema`` matches what it actually emits.
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
SCHEMA = "janus.l143.book_move_attribution.v1"

# Registered in spec.yaml before any extraction.  Do not move these.
CENTRED_BAND_C = 1.5
FAVOURABLE_LO, FAVOURABLE_HI = 0.40, 0.60
RHO_LATENCY = 0.20


def js(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


def walk(asks: list, contracts: float) -> tuple[float | None, float]:
    """Cumulative-depth marginal price.  Arithmetically identical to plan.marginal_price, and
    pinned to it by test_measure.py rather than asserted here."""
    cum, depth, marginal = 0.0, 0.0, None
    for p, s in asks or []:
        p, s = float(p), float(s)
        depth += s
        cum += s
        if marginal is None and cum >= contracts - 1e-9:
            marginal = p
    return marginal, depth


def depth_at_or_below(ladder: list, price: float) -> float:
    return sum(float(s) for p, s in ladder or [] if float(p) <= float(price) + 1e-9)


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
    """Tie-corrected Spearman via Pearson on ranks.  No scipy on the box."""
    if len(xs) != len(ys) or len(xs) < 3:
        return {"n": len(xs), "rho": None}
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx <= 0 or dy <= 0:
        return {"n": len(xs), "rho": None, "note": "zero rank variance"}
    rho = num / (dx * dy)
    # Fisher z, adequate for n >= 10 and only ever reported alongside n.
    ci = None
    if len(xs) > 3 and abs(rho) < 1.0:
        z = 0.5 * math.log((1 + rho) / (1 - rho))
        se = 1.0 / math.sqrt(len(xs) - 3)
        lo, hi = math.tanh(z - 1.96 * se), math.tanh(z + 1.96 * se)
        ci = [round(lo, 4), round(hi, 4)]
    return {"n": len(xs), "rho": round(rho, 4), "ci95": ci}


def extract(db: str = DB, end_ts: float | None = None, window_s: float | None = None) -> dict:
    end = float(end_ts if end_ts is not None else time.time())
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    max_rowid = int(con.execute("SELECT max(rowid) FROM executions").fetchone()[0] or 0)
    tail = [dict(r) for r in con.execute(
        "SELECT rowid AS _rowid,* FROM executions WHERE rowid>=? ORDER BY rowid",
        (max(1, max_rowid - TAIL_ROWS),))]
    rows = [r for r in tail if r["started_utc"] is not None and float(r["started_utc"]) <= end]
    if window_s is not None:
        rows = [r for r in rows if float(r["started_utc"]) >= end - float(window_s)]
    rows = [r for r in rows if r["execution_id"] != EXCLUDED_EXECUTION]

    missing = Counter()
    per_row: list[dict] = []
    book_age_ms: list[float] = []

    for r in rows:
        plan = js(r.get("plan_json"), {})
        first = plan.get("first") if isinstance(plan, dict) else None
        if not isinstance(first, dict):
            missing["plan.first"] += 1
            continue
        q = float(first.get("contracts") or r.get("quantity") or 0)
        if q <= 0:
            missing["planned_contracts"] += 1
            continue
        lim = first.get("limit_price")

        books = js(r.get("books_json"), {})
        frozen_marginal = frozen_depth = frozen_fetched = None
        frozen_source = None
        for legs in (books.values() if isinstance(books, dict) else []):
            for leg in (legs if isinstance(legs, list) else []):
                if (leg.get("venue") == first.get("venue")
                        and leg.get("market_id") == first.get("market_id")
                        and leg.get("outcome_id") == first.get("outcome_id")):
                    frozen_marginal, frozen_depth = walk(leg.get("asks"), q)
                    frozen_source = str(leg.get("source") or "missing")
                    frozen_fetched = leg.get("fetched_utc")
        if frozen_marginal is None:
            missing["frozen_first_leg_book"] += 1
            continue

        pj = js(r.get("protect_json"), {})
        fc = pj.get("first_leg_confirm") if isinstance(pj, dict) else None
        if not isinstance(fc, dict) or fc.get("marginal") is None:
            missing["first_leg_confirm"] += 1
            continue
        confirmed = float(fc["marginal"])
        ladder = fc.get("ladder") if isinstance(fc.get("ladder"), list) else []

        # Signed gap, positive = worse for the BUY we were about to send.
        gap_c = (confirmed - float(frozen_marginal)) * 100.0

        # Elapsed: frozen frame capture -> confirmation completion.  Adjacent stamps on ONE row.
        elapsed_ms = None
        if frozen_fetched is not None and fc.get("at_utc") is not None:
            elapsed_ms = (float(fc["at_utc"]) - float(frozen_fetched)) * 1000.0
        if frozen_fetched is not None and r.get("started_utc") is not None:
            age = (float(r["started_utc"]) - float(frozen_fetched)) * 1000.0
            book_age_ms.append(age)

        # Phantom-depth test: is the ORIGINAL planned price still present, but thin?
        depth_at_frozen = depth_at_or_below(ladder, float(frozen_marginal))
        price_held = any(abs(float(p) - float(frozen_marginal)) <= 1e-9 for p, _ in ladder)

        sent = fc.get("sent") if isinstance(fc.get("sent"), dict) else None
        post = pj.get("first_leg_post") if isinstance(pj, dict) else None
        consumed = None
        if isinstance(sent, dict) and isinstance(post, dict) and sent.get("price") is not None:
            before = depth_at_or_below(ladder, float(sent["price"]))
            after_ladder = post.get("ladder") if isinstance(post.get("ladder"), list) else None
            if after_ladder is not None:
                after = depth_at_or_below(after_ladder, float(sent["price"]))
                need = float(sent.get("contracts") or 0)
                if before + 1e-9 >= need > 0:
                    consumed = "CONSUMED" if after <= 1e-9 else (
                        "STILL_THERE" if after + 1e-9 >= need else "PARTIAL")
                else:
                    consumed = "SHORT_BEFORE_SEND"

        per_row.append({
            "rowid": int(r["_rowid"]), "execution_id": r["execution_id"], "state": r["state"],
            "league": r.get("league"), "contracts": q, "limit": lim,
            "frozen_marginal": float(frozen_marginal), "frozen_depth": frozen_depth,
            "frozen_source": frozen_source, "confirmed_marginal": confirmed,
            "gap_c": round(gap_c, 6), "elapsed_ms": elapsed_ms,
            "confirmed_depth_at_frozen_price": depth_at_frozen,
            "frozen_price_still_present": price_held,
            "phantom": bool(price_held and depth_at_frozen + 1e-9 < q),
            "consumed_class": consumed,
        })

    def gaps(rs): return [x["gap_c"] for x in rs]

    def favourable_fraction(rs):
        g = gaps(rs)
        return (round(sum(1 for x in g if x < 0) / len(g), 4)) if g else None

    by_state: dict[str, list[dict]] = defaultdict(list)
    for x in per_row:
        by_state[x["state"]].append(x)

    timed = [x for x in per_row if x["elapsed_ms"] is not None]
    rho_abs = spearman([x["elapsed_ms"] for x in timed], [abs(x["gap_c"]) for x in timed])
    rho_signed = spearman([x["elapsed_ms"] for x in timed], [x["gap_c"] for x in timed])

    all_gap = qsummary(gaps(per_row))
    fav_all = favourable_fraction(per_row)
    declines = by_state.get("BOOK_MOVED", [])
    phantom_declines = sum(1 for x in declines if x["phantom"])

    # Verdict strictly by the registered decision_rule.  No branch is widened here.
    verdict = "MIXED_OR_INCONCLUSIVE"
    reason = "no registered branch was satisfied"
    if all_gap.get("n", 0) >= 20 and fav_all is not None and rho_abs.get("rho") is not None:
        med, rho = all_gap["p50"], rho_abs["rho"]
        centred = abs(med) <= CENTRED_BAND_C and FAVOURABLE_LO <= fav_all <= FAVOURABLE_HI
        against = med >= CENTRED_BAND_C and fav_all < FAVOURABLE_LO
        if centred and rho >= RHO_LATENCY:
            verdict, reason = "LATENCY_DOMINATES", (
                f"all-rows median {med:+.2f}c within +/-{CENTRED_BAND_C}c, favourable fraction "
                f"{fav_all}, |gap| rises with elapsed time rho={rho}")
        elif against and rho < RHO_LATENCY:
            verdict, reason = "ADVERSE_SELECTION_DOMINATES", (
                f"all-rows median {med:+.2f}c against, favourable fraction {fav_all} < "
                f"{FAVOURABLE_LO}, no elapsed-time scaling rho={rho}")
        elif declines and phantom_declines > len(declines) / 2:
            verdict, reason = "PHANTOM_DEPTH_DOMINATES", (
                f"{phantom_declines}/{len(declines)} declines held the planned price with depth "
                f"below planned size")
    elif all_gap.get("n", 0) < 20:
        reason = f"only {all_gap.get('n', 0)} rows carried both ladders"

    return {
        "schema": SCHEMA,
        "extraction": {"db": db, "end_utc": end, "window_s": window_s,
                       "tail_rows_requested": TAIL_ROWS, "tail_rows_read": len(tail),
                       "max_rowid": max_rowid, "excluded_execution": EXCLUDED_EXECUTION},
        "population": {"executions_in_scope": len(rows),
                       "rows_with_both_ladders": len(per_row),
                       "missing": dict(sorted(missing.items())),
                       "states_in_scope": dict(sorted(Counter(r["state"] for r in rows).items())),
                       "states_with_both_ladders": {k: len(v) for k, v in sorted(by_state.items())}},
        "all_rows_signed_gap_c": all_gap,
        "all_rows_favourable_fraction": fav_all,
        "gap_by_state_c": {k: qsummary(gaps(v)) for k, v in sorted(by_state.items())},
        "favourable_fraction_by_state": {k: favourable_fraction(v) for k, v in sorted(by_state.items())},
        "elapsed_vs_abs_gap": rho_abs,
        "elapsed_vs_signed_gap": rho_signed,
        "elapsed_ms": qsummary([x["elapsed_ms"] for x in timed]),
        "frozen_book_age_ms": qsummary(book_age_ms),
        "phantom_depth": {"declines": len(declines), "declines_phantom": phantom_declines,
                          "all_rows_phantom": sum(1 for x in per_row if x["phantom"])},
        "consumed_taxonomy": dict(sorted(Counter(
            x["consumed_class"] for x in per_row if x["consumed_class"]).items())),
        "frozen_source": dict(sorted(Counter(x["frozen_source"] for x in per_row).items())),
        "verdict": verdict,
        "verdict_reason": reason,
        "registered_thresholds": {"centred_band_c": CENTRED_BAND_C,
                                  "favourable_band": [FAVOURABLE_LO, FAVOURABLE_HI],
                                  "rho_latency": RHO_LATENCY},
        "rows": per_row,
    }


if __name__ == "__main__":
    end_arg = float(sys.argv[1]) if len(sys.argv) > 1 else None
    win_arg = float(sys.argv[2]) if len(sys.argv) > 2 else None
    print(json.dumps(extract(end_ts=end_arg, window_s=win_arg), sort_keys=True, separators=(",", ":")))
