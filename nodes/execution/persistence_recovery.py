"""Exact closure of a persistence alarm after every economic record is independently final.

This does not repair or infer cash.  It only appends an exact flag-resolution marker after the
normal guard has already reconstructed and settled the complete execution from authoritative
venue fills.  The live kill is deliberately outside this module.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

from kernel.schema import Mode
from nodes.risk.flags import flag_snapshot, resolve_exact_flags, unresolved_flag_rows


FLAG = "ORDER_PERSISTENCE_FAILED"
_DETAIL = re.compile(
    r"^ORDER_PERSISTENCE_FAILED: (?P<cid>[0-9a-f]{32}): OperationalError: database is locked"
    r"(?:; independent kill failed: PermissionError: \[Errno 13\] Permission denied: "
    r"'/srv/janus/kill/live')?$"
)


def _rows(con, query: str, params=()) -> list[dict]:
    cursor = con.execute(query, params)
    names = [col[0] for col in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _decimal(value) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("missing or boolean numeric evidence")
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("invalid numeric evidence") from exc
    if not out.is_finite():
        raise ValueError("nonfinite numeric evidence")
    return out


def _same(left, right, *, tolerance=Decimal("0.000000001")) -> bool:
    return abs(_decimal(left) - _decimal(right)) <= tolerance


def _owned_ids(execution: dict) -> list[str]:
    owned = [execution["first_client_id"]] if execution.get("first_client_id") else []
    for field in ("hedge_client_ids", "unwind_client_ids"):
        values = json.loads(execution.get(field) or "[]")
        if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
            raise ValueError("invalid execution order identity")
        owned.extend(values)
    if not owned or len(owned) != len(set(owned)):
        raise ValueError("missing or duplicate execution order identity")
    return owned


def client_id_from_detail(detail: str) -> str:
    match = _DETAIL.fullmatch(detail or "")
    if match is None:
        raise ValueError("persistence detail is not the exact recoverable database-lock grammar")
    return match.group("cid")


def recovered_incident_snapshot(con, client_order_id: str) -> dict:
    """Prove one fully durable, cash-final and released execution containing ``client_order_id``."""
    selected = _rows(con, "SELECT * FROM orders WHERE client_order_id=?", (client_order_id,))
    if len(selected) != 1 or not selected[0].get("execution_id"):
        raise ValueError("exact persisted order or execution owner is absent")
    order = selected[0]
    try:
        sends_real = Mode(order["mode"]).sends_real_orders
    except (ValueError, KeyError) as exc:
        raise ValueError("order mode is not a known real-order mode") from exc
    if not sends_real or not order.get("venue_order_id"):
        raise ValueError("incident order is not an identified real order")

    executions = _rows(con, "SELECT * FROM executions WHERE execution_id=?", (order["execution_id"],))
    if len(executions) != 1:
        raise ValueError("unique owning execution is absent")
    execution = executions[0]
    if execution.get("state") != "RECONCILED" or execution.get("released") != 1:
        raise ValueError("owning execution is not RECONCILED and released")
    if execution.get("opportunity_id") != order.get("opportunity_id") or execution.get("mode") != order.get("mode"):
        raise ValueError("order/execution identity mismatch")
    owned = _owned_ids(execution)
    if client_order_id not in owned:
        raise ValueError("incident order is absent from execution ownership")
    marks = ",".join("?" for _ in owned)
    orders = _rows(con, f"SELECT * FROM orders WHERE client_order_id IN ({marks}) ORDER BY client_order_id", owned)
    if len(orders) != len(owned) or {row["client_order_id"] for row in orders} != set(owned):
        raise ValueError("complete owned order set is absent")
    reverse = {row["client_order_id"] for row in _rows(
        con, "SELECT client_order_id FROM orders WHERE execution_id=?", (execution["execution_id"],))}
    if reverse != set(owned):
        raise ValueError("journal execution ownership is not exact")

    fifo_proof = []
    bounded_proof = []
    for owned_order in orders:
        if (owned_order.get("execution_id") != execution["execution_id"]
                or owned_order.get("opportunity_id") != execution["opportunity_id"]
                or owned_order.get("mode") != execution["mode"]):
            raise ValueError("owned order identity mismatch")
        if (owned_order.get("open") != 0 or owned_order.get("settlement_pending") != 0
                or owned_order.get("state") == "UNCONFIRMED" or not owned_order.get("venue_order_id")):
            raise ValueError("owned order is open, unknown, unidentified or cash-pending")
        requested = _decimal(owned_order["contracts"])
        filled = _decimal(owned_order["filled_contracts"])
        if requested <= 0 or filled < 0:
            raise ValueError("owned order quantity is invalid")
        fills = _rows(con, "SELECT * FROM venue_fills WHERE venue_order_id=? ORDER BY fill_id",
                      (owned_order["venue_order_id"],))
        if filled > 0:
            if not fills or any(row.get("final") != 1 or row.get("venue") != owned_order["venue"] for row in fills):
                raise ValueError("positive order lacks final authoritative FIFO")
            quantity = sum((_decimal(row["contracts"]) for row in fills), Decimal(0))
            cash = sum((_decimal(row["contracts"]) * _decimal(row["price"]) for row in fills), Decimal(0))
            fees = sum((_decimal(row["fee_usd"]) for row in fills), Decimal(0))
            if not _same(quantity, filled) or not _same(cash / quantity, owned_order["avg_price"]):
                raise ValueError("authoritative FIFO quantity or average differs from order")
            if not _same(fees, owned_order["fee_usd"]):
                raise ValueError("authoritative FIFO fee differs from order")
            fifo_proof.append({"client_order_id": owned_order["client_order_id"],
                               "fill_ids": [row["fill_id"] for row in fills],
                               "quantity": str(quantity), "cash": str(cash), "fees": str(fees)})
        elif fills:
            raise ValueError("zero-filled order has an unexpected FIFO")

        if filled > requested:
            if owned_order["venue"] != "polymarket":
                raise ValueError("non-Polymarket overfill has no bounded authorization")
            bounds = _rows(con, "SELECT * FROM pm_bounded_taker_orders WHERE client_order_id=?",
                           (owned_order["client_order_id"],))
            if len(bounds) != 1:
                raise ValueError("Polymarket overfill lacks exact bounded-taker authorization")
            bound = bounds[0]
            if (not _same(bound["requested_contracts"], requested)
                    or requested > _decimal(bound["max_requested_contracts"])
                    or filled - requested >= _decimal(bound["max_accepted_excess"]) - Decimal("0.000000001")
                    or filled * _decimal(owned_order["avg_price"]) + _decimal(owned_order["fee_usd"])
                    > _decimal(bound["max_collateral_usd"])
                    or not _same(bound["authorized_utc"], owned_order["submitted_utc"], tolerance=Decimal("0.000001"))):
                raise ValueError("Polymarket overfill exceeds or contradicts bounded-taker authorization")
            bounded_proof.append(bound)

    settlements = _rows(con, "SELECT * FROM execution_settlements WHERE execution_id=?",
                        (execution["execution_id"],))
    if len(settlements) != 1 or settlements[0].get("released") != 1:
        raise ValueError("unique released settlement is absent")
    settlement = settlements[0]
    if any(settlement.get(field) != execution.get(field)
           for field in ("execution_id", "opportunity_id", "event_id", "league", "mode")):
        raise ValueError("settlement/execution identity mismatch")
    legs = json.loads(settlement.get("legs_json") or "[]")
    if (not isinstance(legs, list) or len(legs) != len(orders)
            or {leg.get("client_order_id") for leg in legs} != set(owned)):
        raise ValueError("settlement does not cover the complete order set")
    by_client = {row["client_order_id"]: row for row in orders}
    for leg in legs:
        linked = by_client[leg["client_order_id"]]
        if leg.get("final") is not True:
            raise ValueError("settlement contains a non-final leg")
        for field in ("venue", "client_order_id", "outcome_id", "side", "state"):
            if leg.get(field) != linked.get(field):
                raise ValueError("settlement leg identity differs from order")
        for target, source in (("contracts", "filled_contracts"), ("price", "avg_price"), ("fee_usd", "fee_usd")):
            expected = linked[source]
            if expected is None and linked["filled_contracts"] == 0 and source in {"avg_price", "fee_usd"}:
                expected = 0
            if not _same(leg.get(target), expected):
                raise ValueError("settlement leg amount differs from order")

    reservations = _rows(con, "SELECT * FROM capital_reservations WHERE reservation_id=?",
                         (execution.get("reservation_id"),))
    if len(reservations) != 1 or reservations[0].get("released_utc") is None:
        raise ValueError("matching released capital reservation is absent")
    reservation = reservations[0]
    if any(reservation.get(field) != execution.get(field)
           for field in ("event_id", "league", "opportunity_id")):
        raise ValueError("reservation/execution identity mismatch")
    return {"client_order_id": client_order_id, "execution_id": execution["execution_id"],
            "owned_client_order_ids": owned, "fifo": fifo_proof, "bounded": bounded_proof,
            "settled_ts": settlement["settled_ts"], "released_utc": reservation["released_utc"]}


def resolve_recovered_persistence(store, *, now: float, verify_pass) -> bool:
    """Resolve every current exact incident together, after repeating all proof under the lock."""
    if not unresolved_flag_rows(store.con, FLAG):
        return False
    evidence: list[dict] = []
    acknowledged: list[dict] = []

    def verify() -> bool:
        if not verify_pass():
            return False
        current_evidence = []
        current_acknowledged = []
        for row in unresolved_flag_rows(store.con, FLAG):
            cid = client_id_from_detail(row[3] or "")
            current_evidence.append(recovered_incident_snapshot(store.con, cid))
            current_acknowledged.append(flag_snapshot(row))
        if not current_evidence or (evidence and current_evidence != evidence):
            return False
        acknowledged.clear()
        acknowledged.extend(current_acknowledged)
        return True

    try:
        if not verify():
            return False
        evidence.extend(recovered_incident_snapshot(
            store.con, client_id_from_detail(row[3] or ""))
            for row in unresolved_flag_rows(store.con, FLAG))
        return resolve_exact_flags(
            store, FLAG, acknowledged,
            "Fresh complete two-venue guard; exact terminal FIFO, execution, settlement, and reservation proof",
            now=now, verify=verify)
    except (ValueError, TypeError, KeyError, IndexError, ArithmeticError, json.JSONDecodeError):
        return False
