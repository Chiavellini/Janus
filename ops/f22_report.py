#!/usr/bin/env python3
"""Read-only F22/L131 decision, outcome and dollar report.

The report joins the additive ``f22_decisions`` ledger to structured execution, order and
settlement rows.  It never parses human log text.  A missing link, unresolved provider answer,
missing fee, incomplete role proof or unreconciled settlement remains ``UNKNOWN``/``None`` and
therefore blocks the scored checkpoint.  The only zero-dollar values emitted without a settlement
row are explicit terminal no-position states (provider rejection or authoritative zero fill).

    python3 ops/f22_report.py --db /path/to/janus.sqlite --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

if "__file__" in globals():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kernel.paths import DB  # noqa: E402
from nodes.execute.entry_experiment import (  # noqa: E402
    F22_CAPS,
    OUTCOME_TAXONOMY,
    assignment_from_record,
)
from nodes.opportunity.thresholds import STRATEGY_VERSION  # noqa: E402


_TERMINAL = frozenset({
    "local_or_risk_refused_no_wire", "provider_rejected_no_position",
    "accepted_terminal_zero_fill", "accepted_partial_fill", "accepted_full_fill",
})
_ACCEPTED = frozenset({"accepted_terminal_zero_fill", "accepted_partial_fill", "accepted_full_fill"})
_BLOCKING = frozenset({"unknown_provider_state", "role_violation", "persistence_or_reconciliation_failure"})


def _has_table(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _json(value: Any, default: Any) -> Any:
    try:
        parsed = json.loads(value) if value else default
        return parsed
    except (TypeError, ValueError):
        return default


def _selected_candidate(decision: dict, quantity: float | None) -> dict | None:
    candidates = decision.get("candidates")
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("selected"):
            if quantity is None or abs(float(candidate.get("quantity", -1)) - quantity) <= 1e-9:
                return candidate
    return None


def _execution_rows(con: sqlite3.Connection) -> list[dict]:
    if not _has_table(con, "executions"):
        return []
    names = ("execution_id", "opportunity_id", "event_id", "league", "mode", "state", "quantity", "first_client_id",
             "hedge_client_ids", "first_filled",
             "hedge_filled", "first_avg_price", "hedge_avg_price", "unhedged", "released", "detail",
             "plan_json", "protect_json", "first_unwound", "hedge_unwound", "started_utc", "last_utc")
    return [dict(zip(names, row)) for row in con.execute(
        "SELECT execution_id,opportunity_id,event_id,league,mode,state,quantity,first_client_id,hedge_client_ids,first_filled,hedge_filled,"
        "first_avg_price,hedge_avg_price,unhedged,released,detail,plan_json,protect_json,first_unwound,"
        "hedge_unwound,started_utc,last_utc FROM executions").fetchall()]


def _plan(execution: dict | None) -> dict | None:
    value = _json(execution.get("plan_json"), {}) if execution else {}
    return value if isinstance(value, dict) else None


def _plan_identity(execution: dict | None) -> dict | None:
    plan = _plan(execution)
    sizing = plan.get("sizing") if isinstance(plan, dict) else None
    identity = sizing.get("entry_experiment") if isinstance(sizing, dict) else None
    return identity if isinstance(identity, dict) else None


def _identity_matches(identity: dict | None, row: dict) -> bool:
    if not isinstance(identity, dict):
        return False
    event = identity.get("event_id", identity.get("canonical_event_id"))
    if any(actual != row.get(expected) for actual, expected in (
            (event, "event_id"), (identity.get("forward_row_id"), "forward_row_id"),
            (identity.get("assignment_algorithm"), "assignment_algorithm"),
            (identity.get("digest"), "digest"), (identity.get("arm"), "arm"),
            (identity.get("sizing_input_hash"), "sizing_input_hash"),
            (identity.get("sizing_occurrence"), "sizing_occurrence"),
            (identity.get("sizing_book_epoch"), "sizing_book_epoch"))):
        return False
    caps = identity.get("caps")
    active_caps = identity.get("active_caps")
    try:
        normalized = {str(k): float(v) for k, v in dict(caps or {}).items()}
        normalized_active = {str(k): float(v) for k, v in dict(active_caps or {}).items()}
    except (TypeError, ValueError):
        return False
    return normalized == normalized_active == F22_CAPS


def _linked_execution(row: dict, executions: list[dict]) -> dict | None:
    """Join only an execution carrying the complete immutable F22 sizing identity."""
    def matches(execution: dict) -> bool:
        identity = _plan_identity(execution)
        return (
            execution.get("event_id") == row.get("event_id")
            and _identity_matches(identity, row)
        )
    if row.get("execution_id"):
        linked = [e for e in executions if e["execution_id"] == row["execution_id"]]
        matching = [e for e in executions if matches(e)]
        return linked[0] if len(linked) == 1 and len(matching) == 1 and matches(linked[0]) else None
    # A process crash can occur after the coordinator writes its row but before the loop writes the
    # analysis link.  The structured identity is an exact fallback, never an epoch-only guess.
    candidates = [e for e in executions if matches(e)]
    return candidates[0] if len(candidates) == 1 else None


def _sizing_join(con: sqlite3.Connection, row: dict) -> tuple[dict | None, str | None]:
    """Validate the F22 row against exactly one durable sizing decision."""
    if not _has_table(con, "sizing_decisions"):
        return None, "sizing_decisions table absent"
    matches = con.execute(
        "SELECT id,event_id,book_epoch,input_hash,occurrence,selected_opportunity_id,decision_json "
        "FROM sizing_decisions WHERE event_id=? AND input_hash=? AND occurrence=? AND book_epoch=?",
        (row.get("event_id"), row.get("sizing_input_hash"), row.get("sizing_occurrence"),
         row.get("sizing_book_epoch")),
    ).fetchall()
    if len(matches) != 1:
        return None, "sizing identity does not join exactly one row"
    names = ("id", "event_id", "book_epoch", "input_hash", "occurrence", "selected_opportunity_id", "decision_json")
    sizing = dict(zip(names, matches[0]))
    decision = _json(sizing.get("decision_json"), None)
    if not isinstance(decision, dict):
        return None, "sizing decision JSON is invalid"
    if sizing["selected_opportunity_id"] is None:
        return None, "sizing row has no selected opportunity"
    if not _has_table(con, "opportunities"):
        return None, "opportunities table absent"
    opportunity_rows = con.execute(
        "SELECT opportunity_id,event_id,league,strategy_version FROM opportunities WHERE opportunity_id=?",
        (sizing["selected_opportunity_id"],)).fetchall()
    if len(opportunity_rows) != 1:
        return None, "selected opportunity does not join exactly one row"
    opportunity = dict(zip(("opportunity_id", "event_id", "league", "strategy_version"), opportunity_rows[0]))
    if opportunity["event_id"] != row.get("event_id") or opportunity["strategy_version"] != STRATEGY_VERSION:
        return None, "selected opportunity identity/strategy mismatch"
    selected = [c for c in decision.get("candidates", [])
                if isinstance(c, dict) and c.get("selected") is True]
    try:
        quantity = float(row["selected_quantity"])
    except (TypeError, ValueError):
        return None, "selected quantity is invalid"
    if len(selected) != 1 or abs(float(selected[0].get("quantity")) - quantity) > 1e-9:
        return None, "selected quantity contradicts sizing decision"
    identity = decision.get("entry_experiment")
    if not _identity_matches(identity, row):
        return None, "sizing decision has no exact F22 identity"
    if decision != _json(row.get("decision_json"), None):
        return None, "F22 and sizing decision payloads differ"
    sizing["_opportunity"] = opportunity
    return sizing, None


def _orders(con: sqlite3.Connection, execution_id: str | None) -> list[dict]:
    if not execution_id or not _has_table(con, "orders"):
        return []
    names = ("client_order_id", "venue", "mode", "venue_order_id", "side", "contracts", "time_in_force", "state", "filled_contracts", "avg_price",
             "fee_usd", "open", "settlement_pending", "submitted_utc", "last_utc", "opportunity_id", "execution_id")
    return [dict(zip(names, row)) for row in con.execute(
        "SELECT client_order_id,venue,mode,venue_order_id,side,contracts,time_in_force,state,filled_contracts,avg_price,fee_usd,open,"
        "settlement_pending,submitted_utc,last_utc,opportunity_id,execution_id FROM orders WHERE execution_id=? ORDER BY submitted_utc",
        (execution_id,)).fetchall()]


def _settlement(con: sqlite3.Connection, execution_id: str | None) -> dict | None:
    if not execution_id or not _has_table(con, "execution_settlements"):
        return None
    names = ("execution_id", "opportunity_id", "event_id", "league", "mode", "realized_usd",
             "released", "kind", "hedged_contracts", "unhedged_contracts", "cover_usd",
             "directional_usd", "settled_ts")
    rows = con.execute(
        "SELECT execution_id,opportunity_id,event_id,league,mode,realized_usd,released,kind,"
        "hedged_contracts,unhedged_contracts,cover_usd,directional_usd,settled_ts "
        "FROM execution_settlements WHERE execution_id=?", (execution_id,)).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        return {"_duplicate": True}
    return dict(zip(names, rows[0]))


def _wire_status(row: dict, execution: dict, orders: list[dict]) -> str | None:
    """Validate the immutable first-leg contract recorded in executions.plan_json."""
    plan = _plan(execution)
    first = plan.get("first") if isinstance(plan, dict) else None
    hedge = plan.get("hedge") if isinstance(plan, dict) else None
    if not isinstance(first, dict) or not isinstance(hedge, dict):
        return "persistence_or_reconciliation_failure"
    if first.get("venue") != "polymarket" or hedge.get("venue") != "kalshi":
        return "persistence_or_reconciliation_failure"
    tif = str(first.get("time_in_force") or "").lower()
    post_only = bool(first.get("post_only"))
    try:
        selected = float(row.get("selected_quantity"))
        if (abs(float(execution.get("quantity")) - selected) > 1e-9
                or abs(float(first.get("contracts")) - selected) > 1e-9
                or abs(float(hedge.get("contracts")) - selected) > 1e-9):
            return "persistence_or_reconciliation_failure"
    except (TypeError, ValueError):
        return "persistence_or_reconciliation_failure"
    pm = next((o for o in orders if o.get("venue") == "polymarket"
               and str(o.get("side") or "").startswith("buy_")), None)
    if pm is not None and (str(pm.get("time_in_force") or "").lower() != tif
                           or pm.get("side") != first.get("side")):
        return "role_violation"
    hedge_tif = str(hedge.get("time_in_force") or "").lower()
    if (hedge_tif != "ioc" or bool(hedge.get("post_only"))
            or not str(hedge.get("side") or "").startswith("buy_")):
        return "role_violation"
    if any(str(o.get("time_in_force") or "").lower() != hedge_tif
           or o.get("side") != hedge.get("side") for o in orders if o.get("venue") == "kalshi"):
        return "role_violation"
    if row.get("arm") == "maker":
        return "role_violation" if not post_only or tif != "gtc" else None
    if row.get("arm") == "taker":
        return "role_violation" if post_only or tif not in {"ioc", "fok", "fak"} else None
    return "persistence_or_reconciliation_failure"


def _state_status(execution: dict, orders: list[dict]) -> str | None:
    """Reject impossible provider state/fill combinations before any PnL is scored."""
    if execution.get("released") != 1:
        return "persistence_or_reconciliation_failure"
    pm_orders = [o for o in orders if o.get("venue") == "polymarket"
                 and str(o.get("side") or "").startswith("buy_")]
    if len(pm_orders) != 1:
        return "persistence_or_reconciliation_failure"
    for order in orders:
        try:
            filled = float(order.get("filled_contracts") or 0.0)
            requested = float(order.get("contracts") or 0.0)
        except (TypeError, ValueError):
            return "persistence_or_reconciliation_failure"
        if filled < -1e-9 or requested <= 0.0 or filled > requested + 1e-9:
            return "persistence_or_reconciliation_failure"
        state = str(order.get("state") or "").upper()
        if bool(order.get("open")) or bool(order.get("settlement_pending")) or state in {"UNCONFIRMED", "UNKNOWN"}:
            return "unknown_provider_state"
        if state in {"REJECTED", "ORDER_REJECTED", "UNFILLED", "ORDER_UNFILLED"} and filled > 1e-9:
            return "persistence_or_reconciliation_failure"
        if order.get("fee_usd") is None:
            return "persistence_or_reconciliation_failure"
        if filled > 1e-9 and (order.get("avg_price") is None or order.get("fee_usd") is None):
            return "persistence_or_reconciliation_failure"
    if abs(float(execution.get("first_filled") or 0.0) - sum(
            float(o.get("filled_contracts") or 0.0) for o in orders
            if o.get("venue") == "polymarket" and str(o.get("side") or "").startswith("buy_"))) > 1e-9:
        return "persistence_or_reconciliation_failure"
    hedge_orders = [o for o in orders if o.get("venue") == "kalshi"
                    and str(o.get("side") or "").startswith("buy_")]
    if abs(float(execution.get("hedge_filled") or 0.0) - sum(
            float(o.get("filled_contracts") or 0.0) for o in hedge_orders)) > 1e-9:
        return "persistence_or_reconciliation_failure"
    first = pm_orders[0]
    first_state = str(first.get("state") or "").upper()
    first_filled = float(first.get("filled_contracts") or 0.0)
    execution_state = str(execution.get("state") or "").upper()
    if first_filled > 1e-9 and execution_state != "RECONCILED":
        return "persistence_or_reconciliation_failure"
    if first_filled <= 1e-9 and first_state in {"REJECTED", "ORDER_REJECTED"} and execution_state != "ORDER_REJECTED":
        return "persistence_or_reconciliation_failure"
    if first_filled <= 1e-9 and first_state in {"UNFILLED", "ORDER_UNFILLED", "CANCELED", "CANCELLED"} \
            and execution_state != "ORDER_UNFILLED":
        return "persistence_or_reconciliation_failure"
    return None


def _settlement_status(execution: dict, settlement: dict | None, orders: list[dict], filled: float) -> str | None:
    """Filled observations need complete, identity-matched settlement evidence."""
    if settlement is None:
        return "persistence_or_reconciliation_failure" if filled > 1e-9 else None
    if any(settlement.get(k) != execution.get(k) for k in ("execution_id", "opportunity_id", "event_id", "league", "mode")):
        return "persistence_or_reconciliation_failure"
    if settlement.get("released") != 1:
        return "unknown_provider_state"
    if filled <= 1e-9:
        return None
    required = ("realized_usd", "kind", "hedged_contracts", "unhedged_contracts", "cover_usd",
                "directional_usd", "settled_ts")
    if any(settlement.get(k) is None for k in required):
        return "persistence_or_reconciliation_failure"
    if (settlement.get("kind") != "COVER" or abs(float(settlement.get("unhedged_contracts") or 0.0)) > 1e-9
            or abs(float(settlement.get("directional_usd") or 0.0)) > 1e-9):
        return "persistence_or_reconciliation_failure"
    venues = {str(o.get("venue")) for o in orders}
    if len(orders) < 2 or not {"polymarket", "kalshi"}.issubset(venues) or any(
            o.get("fee_usd") is None for o in orders):
        return "persistence_or_reconciliation_failure"
    if abs(float(settlement["hedged_contracts"]) - float(execution.get("hedge_filled") or 0.0)) > 1e-9:
        return "persistence_or_reconciliation_failure"
    if abs(float(settlement["unhedged_contracts"]) - float(execution.get("unhedged") or 0.0)) > 1e-9:
        return "persistence_or_reconciliation_failure"
    return None


def _role_status(con: sqlite3.Connection, row: dict, execution: dict | None, orders: list[dict], filled: float) -> str | None:
    """Return a taxonomy override for contradictory/missing maker-role evidence."""
    if execution is None or not orders:
        return None
    pm = next((o for o in orders if o["venue"] == "polymarket" and str(o["side"]).startswith("buy")), None)
    if pm is None:
        return None
    maker = row.get("arm") == "maker"
    marker = None
    if _has_table(con, "pm_post_only_orders"):
        marker_row = con.execute(
            "SELECT terminal_proved,violated FROM pm_post_only_orders WHERE client_order_id=?",
            (pm["client_order_id"],)).fetchone()
        marker = dict(zip(("terminal_proved", "violated"), marker_row)) if marker_row else None
    if not maker:
        return "role_violation" if marker is not None else None
    if str(pm.get("time_in_force") or "").lower() != "gtc":
        return "role_violation"
    if marker is not None and marker["violated"]:
        return "role_violation"
    if filled <= 1e-9:
        if marker is None:
            return "persistence_or_reconciliation_failure"
        return None if marker["terminal_proved"] == 1 else "unknown_provider_state"
    if marker is None:
        return "persistence_or_reconciliation_failure"
    if marker["terminal_proved"] != 1:
        return "unknown_provider_state"
    if not _has_table(con, "venue_fills"):
        return "persistence_or_reconciliation_failure"
    roles = con.execute(
        "SELECT contracts,is_taker,final FROM venue_fills WHERE venue_order_id=?",
        (pm.get("venue_order_id"),),
    ).fetchall()
    if not roles:
        # The order can carry the provider's quantity but no authoritative role evidence.
        return "persistence_or_reconciliation_failure"
    if any(value[1] for value in roles):
        return "role_violation"
    if any(not value[2] for value in roles):
        return "unknown_provider_state"
    if abs(sum(float(value[0]) for value in roles) - filled) > 1e-9:
        return "persistence_or_reconciliation_failure"
    return None


def _classify(con: sqlite3.Connection, row: dict, execution: dict | None, orders: list[dict], settlement: dict | None) -> str:
    explicit = row.get("outcome")
    if explicit is not None and explicit not in OUTCOME_TAXONOMY:
        return "persistence_or_reconciliation_failure"
    if execution is None:
        if explicit == "local_or_risk_refused_no_wire":
            return explicit
        if explicit in {"unknown_provider_state", "role_violation", "persistence_or_reconciliation_failure"}:
            return explicit
        return "persistence_or_reconciliation_failure" if explicit else "unknown_provider_state"
    if (execution.get("event_id") != row.get("event_id") or execution.get("mode") != "LIMITED_LIVE"
            or row.get("_selected_opportunity_id") != execution.get("opportunity_id")):
        return "persistence_or_reconciliation_failure"
    opportunity = row.get("_opportunity") or {}
    if (opportunity.get("opportunity_id") != execution.get("opportunity_id")
            or opportunity.get("event_id") != execution.get("event_id")
            or opportunity.get("league") != execution.get("league")
            or opportunity.get("strategy_version") != STRATEGY_VERSION):
        return "persistence_or_reconciliation_failure"
    if explicit == "local_or_risk_refused_no_wire":
        no_wire_states = {"ORDER_REJECTED", "VENUE_DISCONNECTED", "BALANCE_CHANGED", "BOOK_MOVED", "MARKET_SUSPENDED"}
        raw_hedge_ids = execution.get("hedge_client_ids")
        hedge_ids = _json(raw_hedge_ids, None) if raw_hedge_ids else []
        if (not orders and settlement is None and not execution.get("first_client_id")
                and isinstance(hedge_ids, list) and not hedge_ids and execution.get("released") == 1
                and float(execution.get("first_filled") or 0.0) <= 1e-9
                and float(execution.get("hedge_filled") or 0.0) <= 1e-9
                and str(execution.get("state") or "") in no_wire_states):
            return explicit
        return "persistence_or_reconciliation_failure"
    if explicit in {"local_or_risk_refused_no_wire", "persistence_or_reconciliation_failure", "role_violation"}:
        # An execution contradicts a recorded no-wire disposition; a STOP is safer than selecting
        # either source after the fact.
        return "persistence_or_reconciliation_failure" if explicit == "local_or_risk_refused_no_wire" else explicit
    if not orders:
        return "persistence_or_reconciliation_failure"
    if settlement is not None and settlement.get("_duplicate"):
        return "persistence_or_reconciliation_failure"
    wire = _wire_status(row, execution, orders)
    if wire is not None:
        return wire
    client_ids = [o.get("client_order_id") for o in orders]
    if (any(not x for x in client_ids) or len(set(client_ids)) != len(client_ids)
            or any(o.get("mode") != "LIMITED_LIVE" for o in orders)
            or any(o.get("venue") not in {"polymarket", "kalshi"} for o in orders)):
        return "persistence_or_reconciliation_failure"
    pm_orders = [o for o in orders if o.get("venue") == "polymarket"
                 and str(o.get("side") or "").startswith("buy_")]
    if len(pm_orders) != 1 or pm_orders[0].get("client_order_id") != execution.get("first_client_id"):
        return "persistence_or_reconciliation_failure"
    try:
        hedge_ids = list(_json(execution.get("hedge_client_ids"), []))
    except TypeError:
        return "persistence_or_reconciliation_failure"
    kalshi_buy_ids = [o.get("client_order_id") for o in orders if o.get("venue") == "kalshi"
                      and str(o.get("side") or "").startswith("buy_")]
    if sorted(hedge_ids) != sorted(kalshi_buy_ids):
        return "persistence_or_reconciliation_failure"
    if any(not o.get("venue_order_id") for o in orders
           if str(o.get("state") or "").upper() not in {"REJECTED", "ORDER_REJECTED"}):
        return "persistence_or_reconciliation_failure"
    if any(o.get("execution_id") != execution.get("execution_id")
           or o.get("opportunity_id") != execution.get("opportunity_id")
           for o in orders):
        return "persistence_or_reconciliation_failure"
    if settlement is not None and any(settlement.get(k) != execution.get(k)
                                      for k in ("execution_id", "opportunity_id", "event_id", "league", "mode")):
        return "persistence_or_reconciliation_failure"
    state_status = _state_status(execution, orders)
    if state_status is not None:
        return state_status
    first = next((o for o in orders if o["venue"] == "polymarket" and str(o["side"]).startswith("buy")), None)
    if first is None:
        return "persistence_or_reconciliation_failure"
    requested = float(first.get("contracts") or execution.get("quantity") or 0.0)
    filled = float(first.get("filled_contracts") or 0.0)
    role = _role_status(con, row, execution, orders, filled)
    if role is not None:
        return role
    state = str(first.get("state") or "").upper()
    if bool(first.get("open")) or bool(first.get("settlement_pending")) or state in {"UNCONFIRMED", "UNKNOWN"}:
        return "unknown_provider_state"
    if state in {"REJECTED", "ORDER_REJECTED"} and filled <= 1e-9:
        return "provider_rejected_no_position"
    if state in {"UNFILLED", "ORDER_UNFILLED", "CANCELED", "CANCELLED"} and filled <= 1e-9:
        return "accepted_terminal_zero_fill"
    if filled <= 1e-9:
        return "unknown_provider_state"
    if requested <= 0.0 or filled > requested + 1e-9:
        return "persistence_or_reconciliation_failure"
    settlement_status = _settlement_status(execution, settlement, orders, filled)
    if settlement_status is not None:
        return settlement_status
    return "accepted_partial_fill" if filled + 1e-9 < requested else "accepted_full_fill"


def _fee_total(orders: list[dict]) -> float | None:
    if not orders or any(o.get("fee_usd") is None for o in orders):
        return None
    return round(sum(float(o["fee_usd"]) for o in orders), 8)


def _row_report(con: sqlite3.Connection, row: dict, executions: list[dict], sizing_error: str | None = None) -> dict:
    decision = _json(row.get("decision_json"), {})
    execution = _linked_execution(row, executions)
    if row.get("execution_id") and execution is None:
        sizing_error = sizing_error or "execution link is missing or identity does not match"
    orders = _orders(con, execution.get("execution_id") if execution else row.get("execution_id"))
    settlement = _settlement(con, execution.get("execution_id") if execution else row.get("execution_id"))
    quantity = float(row["selected_quantity"]) if row.get("selected_quantity") is not None else None
    candidate = _selected_candidate(decision, quantity)
    outcome = "persistence_or_reconciliation_failure" if sizing_error else _classify(con, row, execution, orders, settlement)
    proved_no_position = outcome in {"provider_rejected_no_position", "accepted_terminal_zero_fill"}
    explicit_no_wire = outcome == "local_or_risk_refused_no_wire"
    realized = (float(settlement["realized_usd"]) if outcome in _ACCEPTED and settlement
                and settlement.get("realized_usd") is not None and settlement.get("released") else
                0.0 if outcome in {"provider_rejected_no_position", "accepted_terminal_zero_fill",
                                   "local_or_risk_refused_no_wire"} else None)
    fees = _fee_total(orders) if execution else 0.0 if outcome == "local_or_risk_refused_no_wire" else None
    pm_orders = [o for o in orders if o["venue"] == "polymarket"]
    pm_fee = (None if any(o.get("fee_usd") is None for o in pm_orders) else
              round(sum(float(o["fee_usd"]) for o in pm_orders), 8)) if pm_orders else (
                  0.0 if outcome == "local_or_risk_refused_no_wire" else None)
    directional = (float(settlement["directional_usd"]) if settlement and settlement.get("directional_usd") is not None else
                   0.0 if proved_no_position or outcome == "local_or_risk_refused_no_wire" else None)
    protection = None
    if execution:
        if settlement and settlement.get("kind") == "UNWOUND":
            protection = realized
        elif execution.get("first_unwound") is not None and execution.get("hedge_unwound") is not None:
            protection = 0.0 if float(execution.get("first_unwound") or 0) == 0 and float(execution.get("hedge_unwound") or 0) == 0 else None
    elif outcome == "local_or_risk_refused_no_wire":
        protection = 0.0
    return {
        "id": row["id"], "forward_row_id": row["forward_row_id"],
        "assignment_algorithm": row["assignment_algorithm"], "event_id": row["event_id"],
        "arm": row["arm"], "digest": row["digest"], "sizing_input_hash": row["sizing_input_hash"],
        "sizing_occurrence": row["sizing_occurrence"], "sizing_book_epoch": row["sizing_book_epoch"],
        "selected_quantity": quantity, "sizing_decision": decision,
        "outcome": outcome, "outcome_detail": sizing_error or row.get("outcome_detail"),
        "persistence_or_reconciliation_failure": outcome == "persistence_or_reconciliation_failure",
        "execution_id": execution.get("execution_id") if execution else row.get("execution_id"),
        "planned_edge_usd": (float(candidate["profit_usd"]) if candidate and candidate.get("profit_usd") is not None else None),
        "pm_fee_usd": pm_fee, "combined_fee_usd": fees, "hedge_tail_usd": directional,
        "protection_loss_usd": protection, "settled_pnl_usd": realized,
        "created_utc": float(row["created_utc"]),
        "settled_utc": float(settlement["settled_ts"]) if settlement and settlement.get("settled_ts") is not None else None,
    }


def _sum_known(rows: list[dict], key: str) -> float | None:
    values = [r.get(key) for r in rows]
    return None if not values or any(v is None for v in values) else round(sum(float(v) for v in values), 8)


def _arm_summary(rows: list[dict]) -> dict:
    counts = {outcome: sum(r["outcome"] == outcome for r in rows) for outcome in OUTCOME_TAXONOMY}
    denominator = len(rows)
    pnl = [r["settled_pnl_usd"] for r in rows]
    accepted = [r for r in rows if r["outcome"] in _ACCEPTED]
    filled = [r for r in rows if r["outcome"] in {"accepted_partial_fill", "accepted_full_fill"}]
    observed = [r["settled_pnl_usd"] for r in accepted]
    lane_times = [t for r in rows for t in (r["created_utc"], r["settled_utc"]) if t is not None]
    lane_hours = round((max(lane_times) - min(lane_times)) / 3600.0, 8) if len(lane_times) > 1 and max(lane_times) > min(lane_times) else None
    complete = denominator > 0 and all(r["outcome"] in _TERMINAL and r["settled_pnl_usd"] is not None for r in rows)
    total_pnl = _sum_known(rows, "settled_pnl_usd")
    return {
        "eligible_decisions": denominator, "taxonomy": counts,
        "complete_reconciled": complete, "blocks_scored_checkpoint": not complete,
        "blocking_outcomes": {k: v for k, v in counts.items() if k in _BLOCKING and v},
        "planned_edge_usd": _sum_known(rows, "planned_edge_usd"),
        "pm_fee_usd": _sum_known(rows, "pm_fee_usd"), "combined_fee_usd": _sum_known(rows, "combined_fee_usd"),
        "hedge_tail_usd": _sum_known(rows, "hedge_tail_usd"), "protection_loss_usd": _sum_known(rows, "protection_loss_usd"),
        "settled_pnl_usd": total_pnl,
        "pnl_per_eligible_decision_usd": (round(total_pnl / denominator, 8) if complete and denominator else None),
        "accepted_orders": len(accepted),
        "pnl_per_accepted_order_usd": (round(sum(observed) / len(observed), 8) if accepted and all(x is not None for x in observed) else None),
        "filled_orders": len(filled),
        "pnl_per_fill_usd": (round(sum(r["settled_pnl_usd"] for r in filled) / len(filled), 8)
                             if filled and all(r["settled_pnl_usd"] is not None for r in filled) else None),
        "observed_lane_hours": lane_hours,
        "pnl_per_observed_lane_hour_usd": (round(total_pnl / lane_hours, 8) if complete and total_pnl is not None and lane_hours else None),
    }


def report(db: Path = DB, *, hours: float | None = None) -> dict:
    """Return JSON-ready F22 facts from a read-only SQLite connection."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        if not _has_table(con, "f22_decisions"):
            return {"row_id": "F22", "hours": hours, "decisions": [], "arms": {a: _arm_summary([]) for a in ("maker", "taker")},
                    "scored_checkpoint": False, "blocking_reason": "f22_decisions table absent"}
        since = None if hours is None else __import__("time").time() - float(hours) * 3600.0
        query = "SELECT id,event_id,forward_row_id,assignment_algorithm,digest,arm,sizing_input_hash,sizing_occurrence,sizing_book_epoch,selected_quantity,decision_json,outcome,outcome_detail,execution_id,created_utc,updated_utc FROM f22_decisions"
        params: tuple = ()
        if since is not None:
            query += " WHERE created_utc>?"
            params = (since,)
        query += " ORDER BY created_utc,id"
        names = ("id", "event_id", "forward_row_id", "assignment_algorithm", "digest", "arm", "sizing_input_hash",
                 "sizing_occurrence", "sizing_book_epoch", "selected_quantity", "decision_json", "outcome", "outcome_detail",
                 "execution_id", "created_utc", "updated_utc")
        rows = []
        sizing_errors: dict[int, str | None] = {}
        for values in con.execute(query, params).fetchall():
            row = dict(zip(names, values))
            if row["selected_quantity"] is None:  # common sizing refusal is not an eligible F22 observation
                continue
            try:
                assignment_from_record({"forward_row_id": row["forward_row_id"], "assignment_algorithm": row["assignment_algorithm"],
                                        "canonical_event_id": row["event_id"], "digest": row["digest"], "arm": row["arm"]})
            except (TypeError, ValueError):
                row["outcome"] = "persistence_or_reconciliation_failure"
            sizing, sizing_error = _sizing_join(con, row)
            row["_selected_opportunity_id"] = sizing.get("selected_opportunity_id") if sizing else None
            row["_opportunity"] = sizing.get("_opportunity") if sizing else None
            sizing_errors[row["id"]] = sizing_error
            rows.append(row)
        executions = _execution_rows(con)
        facts = [_row_report(con, row, executions, sizing_errors.get(row["id"])) for row in rows]
        execution_ids = [r["execution_id"] for r in facts if r.get("execution_id")]
        duplicate_ids = {eid for eid in execution_ids if execution_ids.count(eid) > 1}
        for fact in facts:
            if fact.get("execution_id") in duplicate_ids:
                fact["outcome"] = "persistence_or_reconciliation_failure"
                fact["persistence_or_reconciliation_failure"] = True
                fact["outcome_detail"] = "execution linked by more than one F22 decision"
        arms = {arm: _arm_summary([r for r in facts if r["arm"] == arm]) for arm in ("maker", "taker")}
        complete = bool(facts) and all(r["outcome"] in _TERMINAL and r["settled_pnl_usd"] is not None for r in facts)
        return {"row_id": "F22", "hours": hours, "decisions": facts, "arms": arms,
                "scored_checkpoint": complete,
                "blocking_reason": None if complete else "unknown, role, persistence, or unreconciled outcome present"}
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--hours", type=float, default=None, help="restrict by decision age; default is all retained F22 rows")
    ap.add_argument("--json", action="store_true", help="emit JSON (the default)")
    args = ap.parse_args()
    print(json.dumps(report(args.db, hours=args.hours), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
