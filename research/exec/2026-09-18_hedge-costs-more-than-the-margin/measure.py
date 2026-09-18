#!/usr/bin/env python3
"""L151: realised hedge slippage against the margin the lane requires. READ-ONLY.

    python3 measure.py [/path/to/tuples.sqlite]

Population is every Kalshi hedge ORDER in LIMITED_LIVE, not the settled covers: a hedge that never
filled is the same failure as one that filled expensively, and counting only covers hides it.

Slippage is `avg_price - plan_json["hedge"]["vwap"]`, in cents. That plan vwap is the fee-exclusive
VWAP of walking the Kalshi ask ladder for the full hedge size, as the ladder stood when the cover was
priced (nodes/execute/plan.py:305-310, nodes/cover/cover.py:130-139) -- so this compares what the
hedge was CHARGED at entry with what it actually COST, which is exactly the quantity entry does not
price today: `slippage_for` is read only by `frontier()` and gates no order
(nodes/cover/capacity.py:49-50).

The comparison is against the hurdles that bind: EXECUTION_MIN_LOCKED_RETURN = 0.005 and
EXECUTION_MIN_NET_PROFIT_USD = 0.05 (nodes/opportunity/thresholds.py, mirrored in limits.toml).
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import sys

DB = "/srv/janus/tuples/tuples.sqlite"
SCHEMA = "janus.l151.hedge_vs_margin.v1"
#: nodes/opportunity/thresholds.py, mirrored authoritatively in nodes/risk/limits.toml:57-58.
MIN_LOCKED_RETURN = 0.005
MIN_NET_PROFIT_USD = 0.05


def pct(xs: list[float], p: float) -> float | None:
    """Percentile by nearest rank on a sorted copy; None for an empty sample."""
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))]


def hedge_vwap(plan_json: str | None) -> float | None:
    """What the plan charged the hedge, or None when the row carries no usable plan."""
    try:
        hedge = (json.loads(plan_json or "{}") or {}).get("hedge")
    except ValueError:
        return None
    if not isinstance(hedge, dict):
        return None
    try:
        v = float(hedge.get("vwap") or 0.0)
    except (TypeError, ValueError):
        return None
    return v or None


def collect(con: sqlite3.Connection) -> dict:
    rows = con.execute("""
        SELECT e.league, o.contracts, o.filled_contracts, o.avg_price, o.fee_usd,
               e.plan_json, o.state, o.execution_id
        FROM orders o JOIN executions e ON e.execution_id = o.execution_id
        WHERE o.venue = 'kalshi' AND o.mode = 'LIMITED_LIVE'""").fetchall()
    leagues: dict[str, dict] = {}
    no_plan = 0
    for league, want, got, avg, fee, plan, state, xid in rows:
        lg = league or "(none)"
        d = leagues.setdefault(lg, {"orders": 0, "filled": 0, "zero_fill": 0, "slippage_c": [],
                                    "fill_ratio": [], "fee_per_contract": [], "executions": set()})
        d["orders"] += 1
        d["executions"].add(xid)
        if not got:
            d["zero_fill"] += 1
            continue
        d["filled"] += 1
        if want:
            d["fill_ratio"].append(got / want)
        if fee:
            d["fee_per_contract"].append(fee / got)
        planned = hedge_vwap(plan)
        if planned is None or avg is None:
            no_plan += 1
            continue
        d["slippage_c"].append((float(avg) - planned) * 100.0)

    out = {}
    for lg, d in leagues.items():
        s = d["slippage_c"]
        out[lg] = {
            "hedge_orders": d["orders"], "executions": len(d["executions"]),
            "filled_orders": d["filled"], "zero_fill_orders": d["zero_fill"],
            "slippage_sample": len(s),
            "slippage_c_median": round(statistics.median(s), 3) if s else None,
            "slippage_c_p90": round(pct(s, 0.9), 3) if s else None,
            "slippage_c_worst": round(max(s), 3) if s else None,
            "mean_fill_ratio": round(statistics.mean(d["fill_ratio"]), 4) if d["fill_ratio"] else None,
            "fee_per_contract_median": (round(statistics.median(d["fee_per_contract"]), 5)
                                        if d["fee_per_contract"] else None),
        }
    return {"by_league": out, "orders_without_a_usable_plan_vwap": no_plan}


def verdict(pooled: list[float]) -> tuple[str, str]:
    """The registered rule, decided on the POOLED sample and stated with its size."""
    if len(pooled) < 10:
        return "TOO_FEW_FILLS", f"only {len(pooled)} filled hedge orders carry a plan vwap"
    med = statistics.median(pooled)
    # The margin the lane requires, in cents per contract, at its own floor: a locked return of
    # 0.5 % on a contract that pays $1 is half a cent. The $0.05 net-profit floor is per COVER, so on
    # a 25-contract cover it is 0.2c per contract -- smaller still. Half a cent is the generous read.
    margin_c = MIN_LOCKED_RETURN * 100.0
    if med > margin_c:
        return ("SLIPPAGE_EXCEEDS_MARGIN",
                f"median realised hedge slippage {med:+.2f}c per contract against a required margin "
                f"of {margin_c:.2f}c: the hedge costs {med / margin_c:.1f}x what entry demands")
    return ("MARGIN_EXCEEDS_SLIPPAGE",
            f"median realised hedge slippage {med:+.2f}c is inside the {margin_c:.2f}c margin")


def run(db: str = DB) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        data = collect(con)
    finally:
        con.close()
    # The pooled sample is re-read from the rows, never rebuilt from rounded per-league medians.
    pooled: list[float] = []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        for league, got, avg, plan in con.execute("""
                SELECT e.league, o.filled_contracts, o.avg_price, e.plan_json
                FROM orders o JOIN executions e ON e.execution_id = o.execution_id
                WHERE o.venue = 'kalshi' AND o.mode = 'LIMITED_LIVE' AND o.filled_contracts > 0"""):
            planned = hedge_vwap(plan)
            if planned is not None and avg is not None:
                pooled.append((float(avg) - planned) * 100.0)
    finally:
        con.close()
    name, why = verdict(pooled)
    return {
        "schema": SCHEMA,
        "thresholds": {"min_locked_return": MIN_LOCKED_RETURN,
                       "min_net_profit_usd": MIN_NET_PROFIT_USD,
                       "required_margin_c_per_contract": MIN_LOCKED_RETURN * 100.0},
        "pooled": {
            "sample": len(pooled),
            "median_c": round(statistics.median(pooled), 3) if pooled else None,
            "p90_c": round(pct(pooled, 0.9), 3) if pooled else None,
            "worst_c": round(max(pooled), 3) if pooled else None,
            "adverse": sum(1 for x in pooled if x > 0),
        },
        **data,
        "verdict": name,
        "verdict_reason": why,
        "note": ("Slippage is realised: the fill average minus the plan's own hedge VWAP. Entry "
                 "charges the hedge that VWAP and nothing more (plan.py:346-349), and slippage_for "
                 "gates no order (capacity.py:49-50), so this difference is paid out of the margin."),
    }


if __name__ == "__main__":
    print(json.dumps(run(sys.argv[1] if len(sys.argv) > 1 else DB), indent=2, sort_keys=True))
