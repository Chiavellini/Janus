#!/usr/bin/env python3
"""Settle exactly the one held L136 cover while the live lane remains stopped.

This is deliberately a small operator helper, not a general settlement command.  It has a
read-only proof/fetch half and a single mutation call through ``settle_executions``.  The kill is
never removed or rewritten.  The caller (the stopped-lane shell route) proves the unit has zero
``MainPID`` and ``ControlPID`` immediately before invoking this command.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

# Production invokes this helper by absolute path from a stopped-lane shell route.  Resolve the
# checkout from the helper itself before importing repository packages; the caller's cwd and
# PYTHONPATH are intentionally not part of that contract.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kernel.fetch import Client
from nodes.opportunity.opportunity import OpportunityStore
from nodes.reconcile.settle_executions import apply_settlements, fetch_results, pending
from nodes.risk.ledger import ExposureLedger
from nodes.store_tuples.store import TupleStore
from ops.box.clear_guard_failure_latch import _empty_admission, _post_only_violation_history


# These values are registered in research/exec/2026-09-15_stopped-lane-settlement-convergence.
# Do not make them command-line configurable beyond requiring the complete value: a different
# cover is a different experiment and must get a different pre-registration.
# The release SHA is supplied by the stopped-lane release route.  It must be complete and must
# equal the checkout at invocation time; it is intentionally not pinned to this helper's source
# commit because the deployed release necessarily contains this helper after installation.
EXPECTED_KILL_SHA256 = "dcc4c761ee8fb5f903475e0400b54a0ef57db8246cd7d378d4846cf181c96d83"
EXECUTION_ID = "17077a35da5b46bb92b62daf0d927ff7"
RESERVATION_ID = "b292be2ab30449a3a9f53a3387c1aa17"
EVENT_ID = "pm:atp:1013694"
OPPORTUNITY_ID = "pm:atp:1013694:moneyline:v1-taker-taker-moneyline:25"
PM_SLUG = "atp-sharipo-ivashka-2026-09-14"
MODE = "LIMITED_LIVE"
QUANTITY = 25.0
FIRST_CLIENT_ID = "9651448ba6764525bb4b38550019074c"
HEDGE_CLIENT_ID = "d69958b6cff34cddbd7d8dc857d8bc17"
FIRST_VENUE = "polymarket"
HEDGE_VENUE = "kalshi"
FIRST_MARKET_ID = "72712501754602888946143744674184738877763886494495477038669466143320274090551"
HEDGE_MARKET_ID = "KXATPCHALLENGERMATCH-26SEP15SHAIVA-SHA"
OTHER_KALSHI_MARKET_ID = "KXATPCHALLENGERMATCH-26SEP15SHAIVA-IVA"
OTHER_PM_MARKET_ID = "10097664483560929455470564637222416470629306049683205339459055770653505215527"
EXPECTED_OUTCOMES = {
    "atp:ilya-ivashka": {"kalshi": OTHER_KALSHI_MARKET_ID, "polymarket": FIRST_MARKET_ID},
    "atp:marat-sharipov": {"kalshi": HEDGE_MARKET_ID, "polymarket": OTHER_PM_MARKET_ID},
}
FIRST_PRICE = 0.51
HEDGE_PRICE = 0.44
FIRST_FEE = 0.31237
HEDGE_FEE = 0.4312
RESERVED_USD = {"polymarket": 13.06237, "kalshi": 11.4312}
_FULL_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FULL_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_EPS = 1e-9


class SettlementBlocked(RuntimeError):
    """An exact safety or post-write proof failed."""


class SettlementWaiting(RuntimeError):
    """A venue has not yet returned a final result; no database write was attempted."""


class _DeferredCommitConnection:
    """Forward SQLite operations while holding nested commits for one final commit."""

    def __init__(self, con: sqlite3.Connection):
        self._con = con

    def commit(self) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._con, name)


class _AtomicSettlementStore:
    """Narrow store facade for already-proved production schemas.

    The ordinary continuously-running path durably releases a reservation before later state
    writes.  This stopped-lane one-shot instead holds those nested commits until its complete
    post-state is proved, so a later write failure rolls the whole convergence back.
    """

    def __init__(self, store: TupleStore):
        self.raw_con = store.con
        self.con = _DeferredCommitConnection(self.raw_con)

    def ensure_ddl(self, _ddl: str) -> None:
        # _require_schema proves the needed schema first. executescript would implicitly commit.
        return None


def _same(a: object, b: float, *, tol: float = _EPS) -> bool:
    try:
        return math.isfinite(float(a)) and abs(float(a) - b) <= tol
    except (TypeError, ValueError):
        return False


def _full(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise SettlementBlocked(f"{label} must be the complete lowercase digest")
    return value


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _regular_bytes(path: Path, label: str) -> bytes:
    """Read a regular non-symlink file, binding the opened inode for this read."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise SettlementBlocked(f"{label} is not a regular non-symlink file") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise SettlementBlocked(f"{label} is not a regular file")
        with os.fdopen(fd, "rb") as stream:
            return stream.read()
    except Exception:
        # fdopen owns fd on success; this is only needed for failures before fdopen.
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def check_release_and_kill(*, repo: Path, release_sha: str, kill_path: Path,
                           expected_kill_sha: str) -> bytes:
    """Require the registered full checkout and exact retained-kill bytes."""
    _full(release_sha, _FULL_GIT_SHA, "release SHA")
    try:
        got = subprocess.run(("git", "-C", str(repo), "rev-parse", "--verify", "HEAD"),
                             check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise SettlementBlocked("cannot verify deployed checkout") from exc
    if got != release_sha:
        raise SettlementBlocked("deployed checkout SHA does not equal requested release SHA")
    _full(expected_kill_sha, _FULL_SHA256, "kill SHA256")
    if expected_kill_sha != EXPECTED_KILL_SHA256:
        raise SettlementBlocked("kill SHA256 is not the registered retained kill")
    raw = _regular_bytes(kill_path, "live kill")
    if _sha(raw) != expected_kill_sha:
        raise SettlementBlocked("live kill changed (full SHA256 mismatch)")
    return raw


def assert_stopped_unit(*, state: str, main_pid: object, control_pid: object) -> None:
    """Validate evidence supplied by a stopped-lane caller (no systemd call is made here)."""
    if state not in {"inactive", "failed"}:
        raise SettlementBlocked(f"live unit is not stopped: state={state!r}")
    if str(main_pid) != "0" or str(control_pid) != "0":
        raise SettlementBlocked("stopped unit does not prove MainPID=0 and ControlPID=0")


def _live_unit_state() -> tuple[str, str, str]:
    """Read the service state directly; never trust a caller's stale Boolean."""
    try:
        state = subprocess.run(
            ("systemctl", "is-active", "janus-live-stream"), check=False,
            capture_output=True, text=True,
        ).stdout.strip()
        main_pid = subprocess.run(
            ("systemctl", "show", "janus-live-stream", "--property=MainPID", "--value"),
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        control_pid = subprocess.run(
            ("systemctl", "show", "janus-live-stream", "--property=ControlPID", "--value"),
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise SettlementBlocked("cannot prove live unit is stopped") from exc
    if not main_pid or not control_pid:
        raise SettlementBlocked("systemd returned an incomplete PID proof")
    return state, main_pid, control_pid


def _prove_stopped(unit_reader: Callable[[], tuple[str, str, str]]) -> None:
    state, main_pid, control_pid = unit_reader()
    if state != "inactive":
        raise SettlementBlocked(f"live unit is not stopped: state={state!r}")
    assert_stopped_unit(state=state, main_pid=main_pid, control_pid=control_pid)


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def _require_schema(con: sqlite3.Connection) -> None:
    required = {
        "events", "opportunities", "executions", "orders", "capital_reservations",
        "execution_settlements", "execution_venue_results", "execution_transitions",
    }
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = sorted(required - tables)
    if missing:
        raise SettlementBlocked("expected safety table missing: " + ",".join(missing))
    needed = {
        "executions": {"execution_id", "opportunity_id", "event_id", "mode", "state", "quantity",
                       "first_client_id", "hedge_client_ids", "first_filled", "first_avg_price",
                       "hedge_filled", "hedge_avg_price", "unhedged", "reservation_id", "released"},
        "orders": {"client_order_id", "venue", "mode", "market_id", "outcome_id", "side", "price",
                   "contracts", "time_in_force", "opportunity_id", "state", "filled_contracts",
                   "avg_price", "fee_usd", "open", "settlement_pending"},
        "capital_reservations": {"reservation_id", "event_id", "per_venue_json", "opportunity_id", "released_utc"},
        "events": {"event_id", "spec_json"},
        "opportunities": {"opportunity_id", "event_id", "league", "strategy_version", "status",
                          "first_seen_ts", "last_seen_ts", "quantity", "gross", "fees",
                          "settlement_buffer", "slippage_buffer", "fixed_cost", "net_profit",
                          "locked_return", "n_max", "n_star", "limit_reason", "slippage_modelled",
                          "blocked_by", "legs_json"},
        "execution_settlements": {"execution_id", "released", "kind", "hedged_contracts",
                                   "unhedged_contracts", "directional_usd", "cover_usd",
                                   "realized_usd", "kalshi_winner", "polymarket_winner", "legs_json"},
        "execution_venue_results": {"execution_id", "venue", "winner", "observed_ts"},
    }
    for table, names in needed.items():
        absent = sorted(names - _columns(con, table))
        if absent:
            raise SettlementBlocked(f"expected columns missing from {table}: {','.join(absent)}")


def _rowdict(cur: sqlite3.Cursor, row: tuple | sqlite3.Row) -> dict[str, Any]:
    return dict(zip((d[0] for d in cur.description), row))


def _json_list(raw: object, label: str) -> list:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError) as exc:
        raise SettlementBlocked(f"{label} is not valid JSON") from exc
    if not isinstance(value, list):
        raise SettlementBlocked(f"{label} is not a list")
    return value


def _exact_rows(con: sqlite3.Connection, *, settled: bool = False) -> tuple[dict, dict, list[dict]]:
    """Read and bind the complete registered execution, reservation and its two orders."""
    open_executions = con.execute("SELECT execution_id FROM executions WHERE released IS NOT 1").fetchall()
    open_reservations = con.execute(
        "SELECT reservation_id FROM capital_reservations WHERE released_utc IS NULL").fetchall()
    if settled:
        if open_executions or open_reservations:
            raise SettlementBlocked("money remains unreleased after exact settlement")
    else:
        if len(open_executions) != 1 or open_executions[0][0] != EXECUTION_ID:
            raise SettlementBlocked("unreleased executions are not exactly the registered execution")
        if len(open_reservations) != 1 or open_reservations[0][0] != RESERVATION_ID:
            raise SettlementBlocked("unreleased reservations are not exactly the registered reservation")
    cur = con.execute("SELECT * FROM executions WHERE execution_id=?", (EXECUTION_ID,))
    row = cur.fetchone()
    if row is None:
        raise SettlementBlocked("registered execution is absent")
    execution = _rowdict(cur, row)
    exact = {
        "execution_id": EXECUTION_ID, "opportunity_id": OPPORTUNITY_ID, "event_id": EVENT_ID,
        "mode": MODE, "state": "RECONCILED" if settled else "HEDGED", "quantity": QUANTITY,
        "first_client_id": FIRST_CLIENT_ID,
        "first_filled": QUANTITY, "first_avg_price": FIRST_PRICE, "hedge_filled": QUANTITY,
        "hedge_avg_price": HEDGE_PRICE, "unhedged": 0.0, "reservation_id": RESERVATION_ID,
        "released": 1 if settled else 0,
    }
    for key, expected in exact.items():
        actual = execution.get(key)
        if isinstance(expected, float):
            ok = _same(actual, expected)
        else:
            ok = actual == expected
        if not ok:
            raise SettlementBlocked(f"execution {key} is not the registered value")
    hedge_ids = _json_list(execution.get("hedge_client_ids"), "hedge_client_ids")
    if hedge_ids != [HEDGE_CLIENT_ID]:
        raise SettlementBlocked("hedge order ownership is not exact")
    for key in ("first_unwound", "hedge_unwound"):
        if key in execution and not _same(execution[key], 0.0):
            raise SettlementBlocked(f"execution {key} is nonzero")
    if "unwind_client_ids" in execution and _json_list(execution["unwind_client_ids"], "unwind_client_ids"):
        raise SettlementBlocked("registered execution has an unwind order")

    cur = con.execute("SELECT * FROM capital_reservations WHERE reservation_id=?", (RESERVATION_ID,))
    row = cur.fetchone()
    if row is None:
        raise SettlementBlocked("registered reservation is absent")
    reservation = _rowdict(cur, row)
    if (reservation.get("event_id"), reservation.get("opportunity_id")) != (EVENT_ID, OPPORTUNITY_ID):
        raise SettlementBlocked("reservation identity does not match execution")
    if settled != (reservation.get("released_utc") is not None):
        raise SettlementBlocked("reservation release state is not the registered phase")
    try:
        amounts = json.loads(reservation.get("per_venue_json") or "")
    except (TypeError, ValueError) as exc:
        raise SettlementBlocked("reservation economics are not valid JSON") from exc
    if not isinstance(amounts, dict) or set(amounts) != set(RESERVED_USD) \
            or any(not _same(amounts[v], RESERVED_USD[v]) for v in RESERVED_USD):
        raise SettlementBlocked("reservation economics changed")

    client_ids = [FIRST_CLIENT_ID, HEDGE_CLIENT_ID]
    marks = ",".join("?" for _ in client_ids)
    cur = con.execute(f"SELECT * FROM orders WHERE client_order_id IN ({marks})", client_ids)
    orders = [_rowdict(cur, r) for r in cur.fetchall()]
    if len(orders) != 2 or {r.get("client_order_id") for r in orders} != set(client_ids):
        raise SettlementBlocked("owned orders are not exactly the two registered orders")
    if "execution_id" in _columns(con, "orders"):
        extras = con.execute("SELECT client_order_id FROM orders WHERE execution_id=?", (EXECUTION_ID,)).fetchall()
        if {r[0] for r in extras} != set(client_ids):
            raise SettlementBlocked("execution owns an extra or missing order")
    expected_orders = {
        FIRST_CLIENT_ID: (FIRST_VENUE, FIRST_PRICE, FIRST_FEE),
        HEDGE_CLIENT_ID: (HEDGE_VENUE, HEDGE_PRICE, HEDGE_FEE),
    }
    for order in orders:
        cid = order["client_order_id"]
        venue, price, fee = expected_orders[cid]
        # The outcome IDs are bound to the event's registered outcome map below.  In particular,
        # do not let an opportunity retry borrow a same-venue order merely because its price is
        # equal.  IOC + buy_yes are the exact registered taker roles for both legs.
        checks = (
            order.get("venue") == venue, order.get("mode") == MODE,
            order.get("opportunity_id") == OPPORTUNITY_ID, order.get("state") == "FILLED",
            _same(order.get("contracts"), QUANTITY), _same(order.get("price"), price),
            _same(order.get("filled_contracts"), QUANTITY), _same(order.get("avg_price"), price),
            _same(order.get("fee_usd"), fee), order.get("open") == 0,
            order.get("settlement_pending") == 0, order.get("side") == "buy_yes",
            order.get("time_in_force") == "ioc",
        )
        if not all(checks):
            raise SettlementBlocked(f"order {cid} identity/economics/finality changed")
    settlements = con.execute(
        "SELECT execution_id FROM execution_settlements WHERE execution_id=?", (EXECUTION_ID,)
    ).fetchall()
    if not settled and settlements:
        raise SettlementBlocked("registered execution already has a settlement row")
    return execution, reservation, orders


def l133_predicates(con: sqlite3.Connection) -> dict[str, Any]:
    """Expose the corrected admission/history predicates for the subsequent L133 proof."""
    admission_rows = con.execute(
        "SELECT slot,client_order_id,claimed_utc FROM pm_post_only_admission ORDER BY slot"
    ).fetchall()
    return {
        "admission_empty": _empty_admission(admission_rows),
        "unresolved_post_only_violations": _post_only_violation_history(con),
    }


def _ro(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise SettlementBlocked("database is missing")
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30)


def _fetch_item(con: sqlite3.Connection) -> tuple[dict, dict, dict, list[dict]]:
    execution, reservation, orders = _exact_rows(con)
    # ``pending`` is intentionally the canonical selection path.  It reads the event's registered
    # outcome map and refuses to manufacture an item for a non-holding state.
    items = pending(SimpleNamespace(con=con))
    if len(items) != 1 or items[0]["execution_id"] != EXECUTION_ID:
        raise SettlementBlocked("pending() did not return exactly the registered held cover")
    item = items[0]
    if item.get("opportunity_id") != OPPORTUNITY_ID or item.get("reservation_id") != RESERVATION_ID \
            or item.get("event_id") != EVENT_ID or item.get("mode") != MODE or item.get("pm_slug") != PM_SLUG:
        raise SettlementBlocked("pending item identity changed")
    outcomes = item.get("outcomes")
    if outcomes != EXPECTED_OUTCOMES:
        raise SettlementBlocked("registered complementary event outcome map changed")
    valid_k = {str(v["kalshi"]) for v in outcomes.values()}
    valid_p = {str(v["polymarket"]) for v in outcomes.values()}
    for order in orders:
        if order["venue"] == HEDGE_VENUE:
            if str(order.get("market_id")) != HEDGE_MARKET_ID or HEDGE_MARKET_ID not in valid_k:
                raise SettlementBlocked("Kalshi market identity is not registered for the event")
            if str(order.get("outcome_id")) != HEDGE_MARKET_ID:
                raise SettlementBlocked("Kalshi outcome identity is not registered for the event")
        elif order["venue"] == FIRST_VENUE:
            if (str(order.get("market_id")) != FIRST_MARKET_ID
                    or str(order.get("outcome_id")) != FIRST_MARKET_ID
                    or FIRST_MARKET_ID not in valid_p):
                raise SettlementBlocked("Polymarket market/outcome identity is not registered for the event")
        else:
            raise SettlementBlocked("owned order has an unexpected venue")
    return execution, reservation, item, orders


def _validate_winners(item: dict, winners: dict[str, dict]) -> dict[str, str]:
    record = winners.get(EXECUTION_ID)
    if not isinstance(record, dict):
        raise SettlementBlocked("fetch_results returned no result for the registered execution")
    if any(key.endswith("_error") for key in record):
        raise SettlementBlocked("provider result carried an error")
    if record.get("kalshi") is None or record.get("polymarket") is None:
        raise SettlementWaiting("one or both venue outcomes are not final")
    valid_k = {str(v["kalshi"]) for v in item["outcomes"].values()}
    valid_p = {str(v["polymarket"]) for v in item["outcomes"].values()}
    kalshi, polymarket = str(record["kalshi"]), str(record["polymarket"])
    if kalshi not in valid_k or polymarket not in valid_p:
        raise SettlementBlocked("provider winner is not one of the registered event outcomes")
    return {"kalshi": kalshi, "polymarket": polymarket}


def _settled_proof(con: sqlite3.Connection, winners: dict[str, str]) -> dict[str, Any]:
    """Prove the complete exact post-state on either the uncommitted or read-only connection."""
    _require_schema(con)
    execution, reservation, orders = _exact_rows(con, settled=True)
    opportunity = con.execute(
        "SELECT event_id,status FROM opportunities WHERE opportunity_id=?", (OPPORTUNITY_ID,)
    ).fetchone()
    if opportunity != (EVENT_ID, "RECONCILED"):
        raise SettlementBlocked("registered opportunity is not RECONCILED")
    cur = con.execute("SELECT * FROM execution_settlements WHERE execution_id=?", (EXECUTION_ID,))
    rows = [_rowdict(cur, r) for r in cur.fetchall()]
    if len(rows) != 1:
        raise SettlementBlocked("registered execution does not have exactly one settlement")
    settlement = rows[0]
    if (settlement.get("released"), settlement.get("kind"), settlement.get("kalshi_winner"),
            settlement.get("polymarket_winner")) != (1, "COVER", winners["kalshi"], winners["polymarket"]):
        raise SettlementBlocked("released settlement is not the exact COVER result")
    if not (_same(settlement.get("hedged_contracts"), QUANTITY)
            and _same(settlement.get("unhedged_contracts"), 0.0)
            and _same(settlement.get("directional_usd"), 0.0)):
        raise SettlementBlocked("settlement is not exactly 25 hedged and zero directional")
    legs = _json_list(settlement.get("legs_json"), "settlement legs")
    if len(legs) != 2 or {str(leg.get("client_order_id")) for leg in legs} != {
            FIRST_CLIENT_ID, HEDGE_CLIENT_ID}:
        raise SettlementBlocked("settlement includes an order outside the exact cover")
    owned = {order["client_order_id"]: order for order in orders}
    for leg in legs:
        order = owned.get(str(leg.get("client_order_id")))
        if order is None or any((
                leg.get("venue") != order.get("venue"),
                leg.get("outcome_id") != order.get("outcome_id"),
                leg.get("side") != order.get("side"),
                not _same(leg.get("contracts"), float(order.get("filled_contracts"))),
                not _same(leg.get("price"), float(order.get("avg_price"))),
                not _same(leg.get("fee_usd"), float(order.get("fee_usd"))),
                leg.get("state") != "FILLED", leg.get("final") is not True,
        )):
            raise SettlementBlocked("settlement leg does not match its exact owned order")
    return {"execution": execution, "reservation": reservation, "settlement": settlement}


def _final_proof(db_path: Path, winners: dict[str, str], *, kill_path: Path,
                 expected_kill_sha: str) -> dict[str, Any]:
    raw = _regular_bytes(kill_path, "live kill")
    if _sha(raw) != expected_kill_sha:
        raise SettlementBlocked("live kill changed during settlement")
    con = _ro(db_path)
    try:
        return _settled_proof(con, winners)
    finally:
        con.close()


def settle_exact(*, db_path: Path, kill_path: Path, expected_kill_sha: str,
                 release_sha: str, repo: Path = Path("."), client: object | None = None,
                 fetcher: Callable = fetch_results, applier: Callable = apply_settlements,
                 store_factory: Callable | None = None, stopped_unit_proof: bool = True,
                 unit_reader: Callable[[], tuple[str, str, str]] = _live_unit_state,
                 now: float | None = None, log: Callable[[str], None] = lambda _line: None) -> dict[str, Any]:
    """Settle/release only L136's cover; return ``WAITING`` without any write while open."""
    if not stopped_unit_proof:
        raise SettlementBlocked("stopped-unit proof was not supplied by the caller")
    _prove_stopped(unit_reader)
    check_release_and_kill(repo=repo, release_sha=release_sha, kill_path=kill_path,
                           expected_kill_sha=expected_kill_sha)
    ro = _ro(db_path)
    try:
        _require_schema(ro)
        # A retry after a successful state commit must be idempotent.  Validate the existing exact
        # settlement after closing this read connection; never fetch a provider result again and
        # never ask apply_settlements to write a second row.
        existing = ro.execute(
            "SELECT kalshi_winner,polymarket_winner,released,kind FROM execution_settlements "
            "WHERE execution_id=?", (EXECUTION_ID,)
        ).fetchall()
        if existing:
            if len(existing) != 1 or existing[0][2] != 1 or existing[0][3] != "COVER" \
                    or not existing[0][0] or not existing[0][1]:
                raise SettlementBlocked("existing registered settlement is not an exact released COVER")
            retry_winners = {"kalshi": str(existing[0][0]), "polymarket": str(existing[0][1])}
            ro.close()
            proof = _final_proof(db_path, retry_winners, kill_path=kill_path,
                                 expected_kill_sha=expected_kill_sha)
            return {"status": "SETTLED", "execution_id": EXECUTION_ID, "reservation_id": RESERVATION_ID,
                    "winners": retry_winners, "proof": proof, "retry": True}
        _, _, item, _ = _fetch_item(ro)
        # The corrected predicates are read as part of the same stopped-lane proof.  They do not
        # authorize mutation, but make the result available to the following L133 static proof.
        predicates = l133_predicates(ro)
        if not predicates["admission_empty"] or predicates["unresolved_post_only_violations"]:
            raise SettlementBlocked("corrected L133 admission/history predicate is not quiet")
        winners_payload = fetcher(
            [item], client or Client("l136-settle", rate=2, burst=2, cache_dir=None)
        )
        winners = _validate_winners(item, winners_payload)
    finally:
        ro.close()
    # Re-check the retained kill and the complete exact identity after network I/O and immediately
    # before the sole existing state mutation.  No write occurs before this point.
    check_release_and_kill(repo=repo, release_sha=release_sha, kill_path=kill_path,
                           expected_kill_sha=expected_kill_sha)
    _prove_stopped(unit_reader)
    factory = store_factory or (lambda path: TupleStore(path, isolation_level="IMMEDIATE", timeout_s=120.0))
    base_store = factory(db_path)
    try:
        _require_schema(base_store.con)
        base_store.con.execute("BEGIN IMMEDIATE")
        store = _AtomicSettlementStore(base_store)
        _, _, item, _ = _fetch_item(store.con)
        winners = _validate_winners(item, {EXECUTION_ID: winners})
        _prove_stopped(unit_reader)
        ledger = ExposureLedger(store)
        opportunities = OpportunityStore(store)
        result = applier(store, ledger, None, opportunities, [item], {EXECUTION_ID: winners},
                         now=now, log=log)
        if result != {"settled": 1, "waiting": 0, "unreleasable": 0}:
            raise SettlementBlocked(f"settlement path did not release exactly one cover: {result}")
        _prove_stopped(unit_reader)
        check_release_and_kill(repo=repo, release_sha=release_sha, kill_path=kill_path,
                               expected_kill_sha=expected_kill_sha)
        _settled_proof(store.con, winners)
        base_store.con.commit()
    except Exception:
        try:
            base_store.con.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            base_store.con.close()
        except Exception:
            pass
    proof = _final_proof(db_path, winners, kill_path=kill_path, expected_kill_sha=expected_kill_sha)
    return {"status": "SETTLED", "execution_id": EXECUTION_ID, "reservation_id": RESERVATION_ID,
            "winners": winners, "proof": proof}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--kill", type=Path, required=True)
    ap.add_argument("--expected-kill-sha", required=True)
    ap.add_argument("--release-sha", required=True)
    ap.add_argument("--repo", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        # The invoking stopped-lane shell has just asserted inactive + MainPID=0 + ControlPID=0.
        result = settle_exact(db_path=args.db, kill_path=args.kill, expected_kill_sha=args.expected_kill_sha,
                              release_sha=args.release_sha, repo=args.repo, stopped_unit_proof=True)
        print(f"L136_SETTLE_COMPLETE execution={result['execution_id']} reservation={result['reservation_id']}")
        return 0
    except SettlementWaiting as exc:
        print(f"L136_SETTLE_WAIT: {exc}")
        return 3
    except (SettlementBlocked, RuntimeError, OSError, sqlite3.Error, ValueError) as exc:
        print(f"L136_SETTLE_BLOCKED: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
