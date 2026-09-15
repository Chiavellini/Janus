#!/usr/bin/env python3
"""Bounded, read-only L141 production extractor.

The production database is deliberately not copied: executions are read from its rowid tail,
and sizing rows are fetched through the event-id index.  The script prints one compact JSON result
and never opens a write transaction.  It can be run on the box with ``python3 measure.py`` after
being shipped as a stdin heredoc by ``ops/box/run.sh``.
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
WINDOW_S = 86400.0
SIZING_GAP_S = 1.0


def qsummary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    xs = sorted(float(x) for x in values)
    def percentile(p: float) -> float:
        return xs[max(0, min(len(xs) - 1, math.ceil(p * len(xs)) - 1))]
    return {"n": len(xs), "p50": round(percentile(.50), 3),
            "p90": round(percentile(.90), 3), "max": round(xs[-1], 3),
            "mean": round(statistics.fmean(xs), 3)}


def js(value: Any, default: Any) -> Any:
    try:
        out = json.loads(value) if value else default
        return out
    except (TypeError, ValueError):
        return default


def walk(asks: list, contracts: float) -> tuple[float | None, float]:
    need, gross, depth = float(contracts), 0.0, 0.0
    for p, s in asks or []:
        p, s = float(p), float(s)
        depth += s
        if need <= 1e-9:
            break
        take = min(need, s)
        gross += take * p
        need -= take
    return ((gross / contracts) if need <= 1e-9 and contracts > 0 else None), depth


def stage_stats(rows: list[dict]) -> dict:
    all_values: dict[str, list[float]] = defaultdict(list)
    by_state: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        stages = js(r.get("stages_json"), {})
        if not isinstance(stages, dict) or stages.get("guard_rerun"):
            continue
        for k, v in stages.items():
            if isinstance(v, (int, float)):
                all_values[k].append(float(v))
                by_state[r["state"]][k].append(float(v))
    out = {k: qsummary(v) for k, v in sorted(all_values.items())}
    grouped = {st: {k: qsummary(v) for k, v in sorted(vals.items())}
               for st, vals in sorted(by_state.items())}
    # These are the adjacent, same-row differences required by NEXT.md.  Missing stages stay
    # missing; no median-of-medians arithmetic is used.
    segments = (("A_submit_to_ack", "a_submit_ms", "a_ack_ms"),
                ("A_ack_to_settled", "a_ack_ms", "a_settled_ms"),
                ("A_settled_to_overfill", "a_settled_ms", "a_overfill_ms"),
                ("A_overfill_to_recorded", "a_overfill_ms", "a_recorded_ms"),
                ("A_recorded_to_protect", "a_recorded_ms", "protect_entry_ms"),
                ("protect_to_first_attempt", "protect_entry_ms", "b_first_attempt_ms"),
                ("first_attempt_to_first_send", "b_first_attempt_ms", "b_submit_ms"),
                ("B_submit_to_ack", "b_submit_ms", "b_ack_ms"),
                ("B_ack_to_last_send", "b_ack_ms", "b_last_submit_ms"),
                ("B_last_send_to_last_ack", "b_last_submit_ms", "b_last_ack_ms"),
                ("B_last_ack_to_settled", "b_last_ack_ms", "b_settled_ms"),)
    seg: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        d = js(r.get("stages_json"), {})
        if not isinstance(d, dict) or d.get("guard_rerun"):
            continue
        for name, a, b in segments:
            if isinstance(d.get(a), (int, float)) and isinstance(d.get(b), (int, float)):
                # Reject impossible negative differences rather than hiding a rebased clock.
                delta = float(d[b]) - float(d[a])
                if delta >= -1e-6:
                    seg[name].append(max(0.0, delta))
    return {"all_states": out, "by_state": grouped,
            "differenced_segments": {k: qsummary(v) for k, v in sorted(seg.items())}}


def extract(db: str = DB, end_ts: float | None = None) -> dict:
    end = float(end_ts if end_ts is not None else time.time())
    start = end - WINDOW_S
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    # rowid is the only practical bounded access path: started_utc is not indexed.  A 2,000-row
    # tail is far wider than this registered funnel; assert that its oldest row precedes start.
    max_rowid = int(con.execute("SELECT max(rowid) FROM executions").fetchone()[0] or 0)
    tail = con.execute("SELECT rowid AS _rowid,* FROM executions WHERE rowid>=? ORDER BY rowid",
                       (max(1, max_rowid - 2000),)).fetchall()
    rows = [dict(r) for r in tail if r["started_utc"] is not None
            and start <= float(r["started_utc"]) <= end]
    prior = con.execute("SELECT rowid AS _rowid,started_utc FROM executions WHERE rowid<? ORDER BY rowid DESC LIMIT 1",
                        (min((r["_rowid"] for r in rows), default=max_rowid + 1),)).fetchone()
    if rows and prior is not None and prior["started_utc"] is not None and float(prior["started_utc"]) >= start:
        raise RuntimeError("bounded execution tail did not reach the window boundary")
    all_rows = [r for r in rows if r["execution_id"] != EXCLUDED_EXECUTION]
    excluded = [r for r in rows if r["execution_id"] == EXCLUDED_EXECUTION]
    states = Counter(r["state"] for r in all_rows)
    book_rows = [r for r in all_rows if r["state"] == "BOOK_MOVED"]

    first_book_age_by_state: dict[str, list[float]] = defaultdict(list)
    first_book_source_by_state: dict[str, Counter] = defaultdict(Counter)
    for r in all_rows:
        plan = js(r.get("plan_json"), {})
        first = plan.get("first") if isinstance(plan, dict) else None
        books = js(r.get("books_json"), {})
        if not isinstance(first, dict) or not isinstance(books, dict):
            continue
        for legs in books.values():
            for leg in legs if isinstance(legs, list) else []:
                if (leg.get("venue") == first.get("venue")
                        and leg.get("market_id") == first.get("market_id")
                        and leg.get("outcome_id") == first.get("outcome_id")):
                    first_book_source_by_state[r["state"]][str(leg.get("source") or "missing")] += 1
                    if leg.get("fetched_utc") is not None:
                        first_book_age_by_state[r["state"]].append(
                            (float(r["started_utc"]) - float(leg["fetched_utc"])) * 1000.0)

    # Full identity/accounting ledger: rowids and ids are retained so no attempt can disappear in
    # aggregation.  Hash-like compact identity is also useful in the verdict without copying JSON.
    ids = [{"rowid": int(r["_rowid"]), "execution_id": r["execution_id"],
            "event_id": r["event_id"], "opportunity_id": r["opportunity_id"],
            "league": r["league"], "quantity": r["quantity"], "state": r["state"],
            "started_utc": r["started_utc"]} for r in all_rows]

    by_event = Counter(r["event_id"] for r in book_rows)
    by_opp = Counter(r["opportunity_id"] for r in book_rows)
    repeats_event: dict[str, dict] = {}
    repeats_opp: dict[str, dict] = {}
    for label, counter, out in (("event", by_event, repeats_event), ("opportunity", by_opp, repeats_opp)):
        for key in sorted(counter):
            rs = sorted((r for r in book_rows if r[f"{label}_id"] == key), key=lambda r: r["started_utc"])
            gaps = [(float(b["started_utc"]) - float(a["started_utc"])) * 1000.0
                    for a, b in zip(rs, rs[1:])]
            out[key] = {"attempts": len(rs), "execution_ids": [r["execution_id"] for r in rs],
                        "inter_attempt_spacing_ms": qsummary(gaps)}

    confirm: list[dict] = []
    planned_frozen: list[float] = []
    frozen_age_ms: list[float] = []
    frozen_sources = Counter()
    confirm_marginals: list[float] = []
    confirm_lags: list[float] = []
    confirm_depth: list[float] = []
    price_delta: list[float] = []
    hedge_minus_break_even: list[float] = []
    decline_stage = Counter()
    missing = Counter()
    conversion_flags = Counter()
    for r in book_rows:
        plan = js(r.get("plan_json"), {})
        first = plan.get("first") if isinstance(plan, dict) else None
        books = js(r.get("books_json"), {})
        pj = js(r.get("protect_json"), {})
        fc = pj.get("first_leg_confirm") if isinstance(pj, dict) else None
        if not isinstance(first, dict):
            missing["plan.first"] += 1; continue
        q = float(first.get("contracts") or r.get("quantity") or 0)
        lim = first.get("limit_price")
        frozen_marginal = None
        for legs in books.values() if isinstance(books, dict) else []:
            for leg in legs if isinstance(legs, list) else []:
                if (leg.get("venue") == first.get("venue") and leg.get("market_id") == first.get("market_id")
                        and leg.get("outcome_id") == first.get("outcome_id")):
                    frozen_marginal, _ = walk(leg.get("asks"), q)
                    frozen_sources[str(leg.get("source") or "missing")] += 1
                    if leg.get("fetched_utc") is not None:
                        frozen_age_ms.append(
                            (float(r["started_utc"]) - float(leg["fetched_utc"])) * 1000.0)
        if frozen_marginal is not None:
            planned_frozen.append(float(frozen_marginal))
        else:
            missing["frozen_first_leg_book"] += 1
        if not isinstance(fc, dict):
            missing["first_leg_confirm"] += 1
            continue
        marginal = fc.get("marginal")
        if marginal is None:
            missing["confirm.marginal"] += 1
            continue
        marginal = float(marginal); confirm_marginals.append(marginal)
        if lim is not None:
            price_delta.append((marginal - float(lim)) * 100.0)
            conversion_flags["confirm_full_size_at_or_below_limit"] += int(marginal <= float(lim) + 1e-9)
        ladder = fc.get("ladder") if isinstance(fc.get("ladder"), list) else []
        depth_at_limit = sum(float(s) for p, s in ladder if float(p) <= float(lim) + 1e-9) if lim is not None else None
        if depth_at_limit is not None:
            confirm_depth.append(depth_at_limit)
            conversion_flags["confirm_ladder_depth_covers_q"] += int(depth_at_limit + 1e-9 >= q)
        first_ok = (lim is not None and marginal <= float(lim) + 1e-9
                    and depth_at_limit is not None and depth_at_limit + 1e-9 >= q)
        hc = pj.get("hedge_leg_confirm") if isinstance(pj, dict) else None
        if first_ok and isinstance(hc, dict) and hc.get("marginal") is not None:
            decline_stage["hedge_leg_above_break_even"] += 1
            if hc.get("break_even") is not None:
                hedge_minus_break_even.append(
                    (float(hc["marginal"]) - float(hc["break_even"])) * 100.0)
        elif first_ok:
            decline_stage["unclassified_after_first_leg_pass"] += 1
        else:
            decline_stage["first_leg_above_limit_or_short_depth"] += 1
        if fc.get("at_utc") is not None:
            lag = (float(fc["at_utc"]) - float(r["started_utc"])) * 1000.0
            confirm_lags.append(lag)
        confirm.append({"rowid": int(r["_rowid"]), "execution_id": r["execution_id"],
                        "limit": lim, "planned_marginal": frozen_marginal,
                        "rechecked_marginal": marginal, "rechecked_top": fc.get("top"),
                        "rechecked_depth_at_limit": depth_at_limit, "contracts": q,
                        "source": fc.get("source"), "fetched_utc": fc.get("fetched_utc"),
                        "at_utc": fc.get("at_utc")})

    # Related submitted orders are a tiny table; joining by exact execution_id prevents scalar
    # settlement contamination and distinguishes terminal zero from a missing provider answer.
    eids = [r["execution_id"] for r in all_rows]
    marks = ",".join("?" for _ in eids) or "NULL"
    orders = [dict(r) for r in con.execute("SELECT rowid AS _rowid,* FROM orders WHERE execution_id IN (" + marks + ")",
                                           eids).fetchall()]
    pm_orders = [o for o in orders if o["venue"] == "polymarket" and str(o.get("side") or "").startswith("buy_")]
    pm_filled = [o for o in pm_orders if float(o.get("filled_contracts") or 0) > 1e-9]
    # All current first legs are Polymarket; this is intentionally explicit in the result.
    fills_by_exec = {o["execution_id"]: float(o.get("filled_contracts") or 0) for o in pm_orders}

    # Pull sizing epochs only through the event-id index, then retain the exact selected opportunity
    # identities. A 1-second gap is the conservative contiguous-window boundary (the lane's
    # sizing loop is ~0.2 s); no window is inferred from repeated execution rows alone.
    events = sorted({r["event_id"] for r in all_rows})
    opps = {r["opportunity_id"] for r in all_rows}
    sizing: list[dict] = []
    for event in events:
        sizing.extend(dict(x) for x in con.execute(
            "SELECT rowid AS _rowid,* FROM sizing_decisions WHERE event_id=? AND seen_ts>=? AND seen_ts<=? ORDER BY seen_ts",
            (event, start, end)).fetchall())
    selected = [s for s in sizing if s.get("selected_opportunity_id") in opps]
    selected.sort(key=lambda x: (x["event_id"], x["selected_opportunity_id"], x["seen_ts"], x["_rowid"]))
    windows: list[dict] = []
    for key, grp in __import__("itertools").groupby(selected,
        key=lambda x: (x["event_id"], x["selected_opportunity_id"])):
        xs = list(grp); cur = [xs[0]]
        for x in xs[1:]:
            if float(x["seen_ts"]) - float(cur[-1]["seen_ts"]) <= SIZING_GAP_S:
                cur.append(x)
            else:
                windows.append({"event_id": key[0], "opportunity_id": key[1],
                       "start_utc": cur[0]["seen_ts"], "end_utc": cur[-1]["seen_ts"],
                                "duration_ms": round((cur[-1]["seen_ts"]-cur[0]["seen_ts"])*1000, 3),
                                "epochs": len(cur)})
                cur = [x]
        windows.append({"event_id": key[0], "opportunity_id": key[1],
                        "start_utc": cur[0]["seen_ts"], "end_utc": cur[-1]["seen_ts"],
                        "duration_ms": round((cur[-1]["seen_ts"]-cur[0]["seen_ts"])*1000, 3),
                        "epochs": len(cur)})

    # Assign executions to the nearest sizing epoch of the same opportunity, only for the
    # window-level conversion denominator. Unmatched rows remain explicit and cannot be credited.
    for w in windows:
        w["execution_ids"] = []
        w["pm_filled_execution_ids"] = []
    for r in all_rows:
        candidates = [w for w in windows if w["opportunity_id"] == r["opportunity_id"]]
        if not candidates:
            continue
        w = min(candidates, key=lambda x: min(abs(float(r["started_utc"])-float(x["start_utc"])),
                                               abs(float(r["started_utc"])-float(x["end_utc"]))))
        # Require nearest epoch window to be within 5 seconds to avoid arbitrary historical joins.
        distance = min(abs(float(r["started_utc"])-float(w["start_utc"])),
                       abs(float(r["started_utc"])-float(w["end_utc"])))
        if distance <= 5.0:
            w["execution_ids"].append(r["execution_id"])
            if fills_by_exec.get(r["execution_id"], 0.0) > 1e-9:
                w["pm_filled_execution_ids"].append(r["execution_id"])
    for w in windows:
        w["execution_count"] = len(w.pop("execution_ids"))
        w["pm_filled_count"] = len(w.pop("pm_filled_execution_ids"))
    active_windows = [w for w in windows if w["execution_count"]]
    active_filled_windows = [w for w in active_windows if w["pm_filled_count"]]

    con.close()
    return {
        "schema": "janus.l141.book_moved_execution_conversion.v1",
        "extraction": {"end_utc": end, "start_utc": start, "window_s": WINDOW_S,
                       "db": db, "execution_tail_max_rowid": max_rowid,
                       "tail_rows_read": len(tail), "tail_boundary_prior_row": dict(prior) if prior else None,
                       "sizing_gap_boundary_s": SIZING_GAP_S},
        "exclusion": {"execution_id": EXCLUDED_EXECUTION, "rows_excluded": len(excluded),
                      "states": Counter(r["state"] for r in excluded)},
        "accounting": {"all_window_rows": len(rows), "included_rows": len(all_rows),
                       "states": dict(sorted(states.items())), "book_moved_rows": len(book_rows),
                       "book_moved_rowids": [int(r["_rowid"]) for r in book_rows],
                       "identity_ledger": ids,
                       "first_book_age_ms_by_state": {k: qsummary(v) for k, v in sorted(first_book_age_by_state.items())},
                       "first_book_source_by_state": {k: dict(sorted(v.items())) for k, v in sorted(first_book_source_by_state.items())}},
        "book_moved": {"by_league": dict(sorted(Counter(r["league"] for r in book_rows).items())),
                       "unique_events": len(by_event), "unique_opportunities": len(by_opp),
                       "attempts_per_event": qsummary(list(by_event.values())),
                       "attempts_per_opportunity": qsummary(list(by_opp.values())),
                       "repeated_event_identities": repeats_event, "repeated_opportunity_identities": repeats_opp,
                       "confirm_rows": len(confirm), "missing_fields": dict(sorted(missing.items())),
                       "planned_frozen_marginal_c": qsummary([x * 100 for x in planned_frozen]),
                       "planned_frozen_source": dict(sorted(frozen_sources.items())),
                       "planned_frozen_age_ms": qsummary(frozen_age_ms),
                       "rechecked_marginal_c": qsummary([x * 100 for x in confirm_marginals]),
                       "rechecked_minus_limit_c": qsummary(price_delta),
                       "decision_to_confirm_ms": qsummary(confirm_lags),
                       "rechecked_depth_at_limit_contracts": qsummary(confirm_depth),
                       "decline_stage": dict(sorted(decline_stage.items())),
                       "hedge_marginal_minus_break_even_c": qsummary(hedge_minus_break_even),
                       "confirm_evidence": confirm,
                       "conversion_checks": dict(conversion_flags)},
        "stages": stage_stats(all_rows),
        "orders": {"rows": len(orders), "polymarket_first_leg_submitted": len(pm_orders),
                   "polymarket_first_leg_filled": len(pm_filled),
                   "polymarket_first_leg_fill_conversion": (len(pm_filled)/len(pm_orders) if pm_orders else None),
                   "by_state": {f"{k[0]}:{k[1]}": v for k, v in
                                sorted(Counter((o["venue"], o["state"]) for o in orders).items())},
                   "order_ids": [{"rowid": o["_rowid"], "execution_id": o["execution_id"],
                                  "venue": o["venue"], "state": o["state"], "filled_contracts": o["filled_contracts"]}
                                 for o in orders]},
        "sizing_epochs": {"events_queried": len(events), "rows_queried": len(sizing),
                           "selected_rows": len(selected), "contiguous_windows": len(windows),
                           "active_windows": len(active_windows), "active_windows_with_pm_fill": len(active_filled_windows),
                           "active_window_fill_conversion": (len(active_filled_windows) / len(active_windows)
                                                             if active_windows else None),
                           "window_duration_ms": qsummary([w["duration_ms"] for w in windows]),
                           "active_window_duration_ms": qsummary([w["duration_ms"] for w in active_windows]),
                           "windows": windows},
        "conversion_ceiling": {
            "frozen_book_was_executable_rows": len(planned_frozen),
            "confirmed_full_size_at_or_below_limit_rows": conversion_flags["confirm_full_size_at_or_below_limit"],
            "confirmed_ladder_depth_covers_q_rows": conversion_flags["confirm_ladder_depth_covers_q"],
            "latency_or_queue_correction_rows_supported": 0,
            "pre_send_confirmation_correction_rows_supported": 0,
            "order_lifecycle_correction_rows_supported": 0,
            "evidence_based_conversion_ceiling_fraction": 0.0,
            "one_third_supported": False,
            "one_third_assessment": "contradicted for this window: 90 BOOK_MOVED rows failed the fresh first-leg price/depth check; the five that passed it failed the fresh hedge break-even check; no named correction has a proved executable two-leg counterfactual under unchanged limits",
        },
    }


if __name__ == "__main__":
    end_arg = float(sys.argv[1]) if len(sys.argv) > 1 else None
    print(json.dumps(extract(end_ts=end_arg), sort_keys=True, separators=(",", ":")))
