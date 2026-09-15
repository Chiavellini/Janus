"""Pure, versioned entry-arm assignment and forward outcome vocabulary.

The assignment is deliberately independent of books, time, sizing, or order shape.  It is
performed once for the canonical event and carried into every durable decision made for that
event.  Keeping this module free of venue/grid imports makes the randomization replayable without
starting a live lane.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


F22_ROW_ID = "F22"
ASSIGNMENT_ALGORITHM = "janus:f22:entry-arm:v1"
F22_SPEC_PATH = "research/sports/2026-09-15_limited-live-f22-maker-vs-taker/spec.yaml"
F22_OPERATOR_STATEMENT = "proceed with the experiment; consider todays goal (reach 20 usd profit)"
F22_CAPS = {"stake_usd": 30.0, "max_contracts": 25.0, "day_notional_usd": 500.0}
F23_ROW_ID = "F23"
F23_ASSIGNMENT_ALGORITHM = "janus:f23:entry-arm:v1"
F23_SPEC_PATH = "research/sports/2026-09-15_limited-live-f23-maker-vs-taker/spec.yaml"
F23_OPERATOR_STATEMENT = "we want to be able to prove we can or cannot reach the goal with the system as is and fix whatever is necessary to reach it."
F23_CAPS = dict(F22_CAPS)
_PREFIX = ASSIGNMENT_ALGORITHM.encode("utf-8") + b"\0"
ARMS = frozenset({"maker", "taker"})

# This is the persisted, analysis-facing vocabulary.  It intentionally does not collapse a
# no-wire refusal, an authoritative zero fill, and an unresolved provider answer.
OUTCOME_TAXONOMY = (
    "local_or_risk_refused_no_wire",
    "provider_rejected_no_position",
    "accepted_terminal_zero_fill",
    "accepted_partial_fill",
    "accepted_full_fill",
    "unknown_provider_state",
    "role_violation",
    "persistence_or_reconciliation_failure",
)

# This is an analysis ledger, not an execution authority.  It is written only after the existing
# sizing decision is durable and is keyed by that decision's immutable book epoch.  In particular,
# it must never be used to manufacture an order or to turn a missing execution into a zero-dollar
# observation.
F22_DECISIONS_DDL = """
CREATE TABLE IF NOT EXISTS f22_decisions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL,
  forward_row_id TEXT NOT NULL,
  assignment_algorithm TEXT NOT NULL,
  digest TEXT NOT NULL,
  arm TEXT NOT NULL,
  sizing_input_hash TEXT NOT NULL,
  sizing_occurrence INTEGER NOT NULL,
  sizing_book_epoch TEXT NOT NULL,
  selected_quantity REAL,
  decision_json TEXT NOT NULL,
  outcome TEXT,
  outcome_detail TEXT,
  execution_id TEXT,
  created_utc REAL NOT NULL,
  updated_utc REAL NOT NULL,
  UNIQUE(event_id, sizing_book_epoch)
);
CREATE INDEX IF NOT EXISTS f22_decisions_event ON f22_decisions(event_id, created_utc);
CREATE INDEX IF NOT EXISTS f22_decisions_execution ON f22_decisions(execution_id);
"""

# F23 is a fresh cohort.  It deliberately has a separate table so F22's STOP rows cannot be
# repaired, relabelled, or pooled into the new estimate.
F23_DECISIONS_DDL = F22_DECISIONS_DDL.replace("f22_decisions", "f23_decisions").replace(
    "f22_decisions_event", "f23_decisions_event").replace("f22_decisions_execution", "f23_decisions_execution")


def ensure_f22_decisions(store) -> None:
    """Create the additive F22 analysis table on the caller's existing store connection."""
    store.ensure_ddl(F22_DECISIONS_DDL)


def ensure_f23_decisions(store) -> None:
    store.ensure_ddl(F23_DECISIONS_DDL)


def f22_spec_sha(root: Path | str) -> str:
    """Digest the immutable preregistration that the operator's override must pin."""
    return hashlib.sha256((Path(root) / F22_SPEC_PATH).read_bytes()).hexdigest()


def f22_activation(*, root: Path | str, state: Mapping[str, object]) -> tuple[bool, str]:
    """Validate the signed override's exact F22 authority, including its preregistration.

    A normal LIMITED_LIVE override intentionally returns false: without this explicit payload the
    historical taker entry remains active and no event is assigned to an experiment arm.
    """
    exp = state.get("experiment")
    if not isinstance(exp, Mapping):
        return False, "override has no F22 experiment authority"
    if state.get("mode") != "LIMITED_LIVE":
        return False, "override does not authorize F22's LIMITED_LIVE mode"
    try:
        spec_sha = f22_spec_sha(root)
    except OSError as exc:
        return False, f"registered F22 spec unreadable: {type(exc).__name__}"
    expected = {
        "row_id": F22_ROW_ID,
        "spec_path": F22_SPEC_PATH,
        "spec_sha256": spec_sha,
        "assignment_algorithm": ASSIGNMENT_ALGORITHM,
    }
    for key, value in expected.items():
        if exp.get(key) != value:
            return False, f"override experiment {key} mismatch"
    if state.get("operator_statement") != F22_OPERATOR_STATEMENT:
        return False, "override operator statement does not exactly authorize F22"
    try:
        caps = {str(k): float(v) for k, v in dict(state.get("caps") or {}).items()}
    except (TypeError, ValueError):
        return False, "override experiment caps are unreadable"
    if caps != F22_CAPS:
        return False, f"override experiment caps differ from registered F22 caps: {caps}"
    return True, "F22 authority matches preregistration"


def _activation(*, root: Path | str, state: Mapping[str, object], row_id: str,
                spec_path: str, algorithm: str, statement: str, caps: Mapping[str, float]) -> tuple[bool, str]:
    exp = state.get("experiment")
    if not isinstance(exp, Mapping):
        return False, f"override has no {row_id} experiment authority"
    if state.get("mode") != "LIMITED_LIVE":
        return False, f"override does not authorize {row_id}'s LIMITED_LIVE mode"
    try:
        spec_sha = hashlib.sha256((Path(root) / spec_path).read_bytes()).hexdigest()
    except OSError as exc:
        return False, f"registered {row_id} spec unreadable: {type(exc).__name__}"
    for key, value in {"row_id": row_id, "spec_path": spec_path,
                       "spec_sha256": spec_sha, "assignment_algorithm": algorithm}.items():
        if exp.get(key) != value:
            return False, f"override experiment {key} mismatch"
    if state.get("operator_statement") != statement:
        return False, f"override operator statement does not exactly authorize {row_id}"
    try:
        actual_caps = {str(k): float(v) for k, v in dict(state.get("caps") or {}).items()}
    except (TypeError, ValueError):
        return False, "override experiment caps are unreadable"
    if actual_caps != dict(caps):
        return False, f"override experiment caps differ from registered {row_id} caps: {actual_caps}"
    return True, f"{row_id} authority matches preregistration"


def f23_activation(*, root: Path | str, state: Mapping[str, object]) -> tuple[bool, str]:
    return _activation(root=root, state=state, row_id=F23_ROW_ID, spec_path=F23_SPEC_PATH,
                       algorithm=F23_ASSIGNMENT_ALGORITHM, statement=F23_OPERATOR_STATEMENT,
                       caps=F23_CAPS)


def first_three_fills_reconciled(store, *, row_id: str = F22_ROW_ID,
                                 exclude_event_id: str | None = None,
                                 exclude_book_epoch: str | None = None) -> tuple[bool, str]:
    """Gate a fourth F22 admission until its first three actual fills are fully reconciled.

    The check is deliberately against durable structured rows only.  Zero fills do not consume
    this checkpoint, and a missing table/column or contradictory identity blocks rather than being
    interpreted as a successful reconciliation.
    """
    try:
        table = "f23_decisions" if row_id == F23_ROW_ID else "f22_decisions"
        names = {r[0] for r in store.con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            f"('{table}','executions','execution_settlements','orders','pm_post_only_orders','venue_fills')").fetchall()}
        label = row_id
        if table not in names or "executions" not in names:
            # A live sizing row is inserted immediately before the provider door. During that
            # narrow just-created window the caller supplies its immutable book epoch; absence of
            # the additive table cannot be mistaken for prior lineage. Direct report/checkpoint
            # callers without that exclusion still fail closed on a missing lineage table.
            if exclude_book_epoch is not None:
                return True, f"current {label} decision is not yet visible to the checkpoint"
            return False, f"{label} reconciliation lineage table is absent"
        f_columns = {r[1] for r in store.con.execute(f"PRAGMA table_info({table})").fetchall()}
        execution_columns = {r[1] for r in store.con.execute("PRAGMA table_info(executions)").fetchall()}
        epoch_expr = "f.sizing_book_epoch" if "sizing_book_epoch" in f_columns else "NULL"
        outcome_expr = "f.outcome" if "outcome" in f_columns else "NULL"
        started_expr = "e.started_utc" if "started_utc" in execution_columns else "f.id"
        duplicate = store.con.execute(
            f"SELECT f.execution_id,COUNT(*) FROM {table} f JOIN executions e ON e.execution_id=f.execution_id "
            "WHERE f.forward_row_id=? AND f.selected_quantity IS NOT NULL AND e.first_filled>1e-9 "
            "GROUP BY f.execution_id HAVING COUNT(*)<>1 LIMIT 1", (row_id,)).fetchone()
        if duplicate is not None:
            return False, f"{label} fill {duplicate[0]} is linked by {duplicate[1]} decisions"
        rows = store.con.execute(
            "SELECT f.id,f.event_id,f.assignment_algorithm,f.digest,f.arm,f.selected_quantity,"
            f"{epoch_expr},{outcome_expr},f.execution_id,e.execution_id,e.opportunity_id,e.event_id,e.league,e.mode,"
            "e.state,e.released,e.first_filled,e.quantity "
            f"FROM {table} f LEFT JOIN executions e ON e.execution_id=f.execution_id "
            "WHERE f.forward_row_id=? AND f.selected_quantity IS NOT NULL "
            f"ORDER BY {started_expr},f.id", (row_id,)).fetchall()
        rows = [r for r in rows if not (
            (exclude_book_epoch is not None and r[6] == exclude_book_epoch)
            or (exclude_book_epoch is None and exclude_event_id is not None and r[1] == exclude_event_id))]
        # A prior selected decision without a durable execution link is missing lineage, not a
        # no-fill. The just-created current row is explicitly excluded by the caller so it cannot
        # self-block before the provider wire response exists.
        for r in rows:
            if (not r[8] or r[9] is None) and r[7] != "local_or_risk_refused_no_wire":
                return False, f"prior {label} decision has missing execution lineage"
        rows = [r for r in rows if float(r[16] or 0.0) > 1e-9]
        if len(rows) < 3:
            return True, f"{len(rows)} of first three {label} fills observed"
        # The gate is a one-time warm-up checkpoint: it protects admission of fill four, not
        # turnover forever. Continue checking lineage on every selected row above, but only the
        # chronological first three filled rows must be fully settled before later fills proceed.
        rows = rows[:3]
        if "execution_settlements" not in names:
            return False, f"three {label} fills observed but settlement ledger is absent"
        for row in rows:
            _, f_event, algorithm, digest, arm, selected, epoch, outcome, exid, linked_exid, opp, event, league, mode, state, released, first_filled, quantity = row
            try:
                assignment_from_record({"forward_row_id": row_id, "assignment_algorithm": algorithm,
                                        "event_id": f_event, "digest": digest, "arm": arm})
            except (TypeError, ValueError):
                return False, f"first-three fill {exid} has contradictory {label} assignment"
            if f_event != event or linked_exid != exid or mode != "LIMITED_LIVE" or abs(float(selected) - float(quantity)) > 1e-9:
                return False, f"first-three fill {exid} decision/execution identity mismatch"
            if not released or state != "RECONCILED" or float(first_filled or 0.0) <= 0:
                return False, f"first-three fill {exid} is not released RECONCILED"
            settled = store.con.execute(
                "SELECT opportunity_id,event_id,league,mode,released,kind,hedged_contracts,"
                "unhedged_contracts,realized_usd,cover_usd,directional_usd "
                "FROM execution_settlements WHERE execution_id=?", (exid,)).fetchall()
            if len(settled) != 1:
                return False, f"first-three fill {exid} has {len(settled)} settlement rows"
            s = settled[0]
            if tuple(s[:4]) != (opp, event, league, mode) or not s[4] or s[5] != "COVER":
                return False, f"first-three fill {exid} settlement identity/terminality mismatch"
            if (s[6] is None or float(s[6]) <= 0 or s[7] is None or abs(float(s[7])) > 1e-9
                    or any(x is None for x in s[8:11]) or abs(float(s[10])) > 1e-9):
                return False, f"first-three fill {exid} settlement economics incomplete"
            if "orders" in names:
                orders = store.con.execute(
                    "SELECT client_order_id,venue,fee_usd,state,open,settlement_pending FROM orders WHERE execution_id=?",
                    (exid,)).fetchall()
                if len(orders) < 2 or any(o[2] is None or o[4] or o[5] for o in orders):
                    return False, f"first-three fill {exid} fee/order completeness is missing"
                pm = [o for o in orders if o[1] == "polymarket"]
                ks = [o for o in orders if o[1] == "kalshi"]
                if len(pm) != 1 or not ks:
                    return False, f"first-three fill {exid} venue-role completeness is missing"
                if arm == "maker":
                    marker = store.con.execute(
                        "SELECT terminal_proved,violated FROM pm_post_only_orders WHERE client_order_id=?",
                        (pm[0][0],)).fetchone() if "pm_post_only_orders" in names else None
                    if marker != (1, 0):
                        return False, f"first-three fill {exid} maker role proof is incomplete"
                    fills = store.con.execute(
                        "SELECT is_taker,final FROM venue_fills WHERE venue_order_id=(SELECT venue_order_id FROM orders WHERE client_order_id=?)",
                        (pm[0][0],)).fetchall() if "venue_fills" in names else []
                    if not fills or any(bool(f[0]) or not bool(f[1]) for f in fills):
                        return False, f"first-three fill {exid} maker fill-role evidence is incomplete"
                elif "pm_post_only_orders" in names and store.con.execute(
                        "SELECT 1 FROM pm_post_only_orders WHERE client_order_id=?", (pm[0][0],)).fetchone():
                    return False, f"first-three fill {exid} taker role conflicts with maker evidence"
        return True, f"first three {label} fills are authoritatively reconciled"
    except Exception as exc:  # noqa: BLE001 -- malformed evidence is a block, never a pass
        return False, f"{label} reconciliation proof unreadable: {type(exc).__name__}: {exc}"


def _record_decision(store, *, assignment: Mapping[str, object], decision: Mapping[str, object],
                     selected_quantity: float | None, now: float | None, row_id: str) -> bool:
    """Persist one selected/common-sizing decision after its sizing row is durable.

    A missing or malformed lineage is rejected rather than repaired.  ``outcome`` starts NULL:
    report code treats that as unresolved until either an explicit pre-wire disposition or the
    structured execution/settlement records prove the terminal result.
    """
    (ensure_f23_decisions if row_id == F23_ROW_ID else ensure_f22_decisions)(store)
    restored = assignment_from_record(assignment)
    ih = assignment.get("sizing_input_hash")
    occurrence = assignment.get("sizing_occurrence")
    epoch = assignment.get("sizing_book_epoch")
    if not isinstance(ih, str) or not ih or not isinstance(epoch, str) or not epoch or occurrence is None:
        raise ValueError("incomplete F22 sizing lineage")
    t = time.time() if now is None else float(now)
    cur = store.con.execute(
        f"INSERT OR IGNORE INTO {'f23_decisions' if row_id == F23_ROW_ID else 'f22_decisions'}(event_id,forward_row_id,assignment_algorithm,digest,arm,"
        "sizing_input_hash,sizing_occurrence,sizing_book_epoch,selected_quantity,decision_json,created_utc,updated_utc) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (restored.event_id, restored.forward_row_id, restored.algorithm, restored.digest, restored.arm,
         ih, int(occurrence), epoch, selected_quantity,
         json.dumps(dict(decision), sort_keys=True, separators=(",", ":")), t, t),
    )
    return cur.rowcount == 1


def record_f22_decision(store, *, assignment: Mapping[str, object], decision: Mapping[str, object],
                        selected_quantity: float | None, now: float | None = None) -> bool:
    return _record_decision(store, assignment=assignment, decision=decision,
                            selected_quantity=selected_quantity, now=now, row_id=F22_ROW_ID)


def record_f23_decision(store, *, assignment: Mapping[str, object], decision: Mapping[str, object],
                        selected_quantity: float | None, now: float | None = None) -> bool:
    return _record_decision(store, assignment=assignment, decision=decision,
                            selected_quantity=selected_quantity, now=now, row_id=F23_ROW_ID)


def update_f22_decision(store, *, event_id: str, sizing_book_epoch: str,
                        outcome: str | None = None, detail: str | None = None,
                        execution_id: str | None = None, now: float | None = None) -> bool:
    """Append no new interpretation; update only the structured disposition/link for one key.

    Callers may set an outcome once.  A contradictory second disposition is a persistence error,
    not permission to overwrite the first fact.
    """
    if outcome is not None and outcome not in OUTCOME_TAXONOMY:
        raise ValueError(f"unsupported F22 outcome: {outcome}")
    ensure_f22_decisions(store)
    row = store.con.execute(
        "SELECT outcome, outcome_detail, execution_id FROM f22_decisions WHERE event_id=? AND sizing_book_epoch=?",
        (event_id, sizing_book_epoch)).fetchone()
    if row is None:
        raise ValueError("F22 decision lineage not found")
    if row[0] is not None and outcome is not None and row[0] != outcome:
        raise ValueError("contradictory F22 outcome")
    if row[1] is not None and detail is not None and row[1] != detail:
        raise ValueError("contradictory F22 outcome detail")
    if row[2] is not None and execution_id is not None and row[2] != execution_id:
        raise ValueError("contradictory F22 execution link")
    t = time.time() if now is None else float(now)
    changed = store.con.execute(
        "UPDATE f22_decisions SET outcome=COALESCE(outcome,?), outcome_detail=COALESCE(outcome_detail,?), "
        "execution_id=COALESCE(execution_id,?), updated_utc=? WHERE event_id=? AND sizing_book_epoch=?",
        (outcome, detail, execution_id, t, event_id, sizing_book_epoch)).rowcount
    return changed == 1


def update_f23_decision(store, *, event_id: str, sizing_book_epoch: str,
                        outcome: str | None = None, detail: str | None = None,
                        execution_id: str | None = None, now: float | None = None) -> bool:
    if outcome is not None and outcome not in OUTCOME_TAXONOMY:
        raise ValueError(f"unsupported F23 outcome: {outcome}")
    ensure_f23_decisions(store)
    row = store.con.execute(
        "SELECT outcome, outcome_detail, execution_id FROM f23_decisions WHERE event_id=? AND sizing_book_epoch=?",
        (event_id, sizing_book_epoch)).fetchone()
    if row is None:
        raise ValueError("F23 decision lineage not found")
    if row[0] is not None and outcome is not None and row[0] != outcome:
        raise ValueError("contradictory F23 outcome")
    if row[1] is not None and detail is not None and row[1] != detail:
        raise ValueError("contradictory F23 outcome detail")
    if row[2] is not None and execution_id is not None and row[2] != execution_id:
        raise ValueError("contradictory F23 execution link")
    t = time.time() if now is None else float(now)
    changed = store.con.execute(
        "UPDATE f23_decisions SET outcome=COALESCE(outcome,?), outcome_detail=COALESCE(outcome_detail,?), "
        "execution_id=COALESCE(execution_id,?), updated_utc=? WHERE event_id=? AND sizing_book_epoch=?",
        (outcome, detail, execution_id, t, event_id, sizing_book_epoch)).rowcount
    return changed == 1


@dataclass(frozen=True)
class EntryArmAssignment:
    """The immutable identity for one canonical event and one registered cohort."""

    event_id: str
    digest: str
    arm: str
    algorithm: str = ASSIGNMENT_ALGORITHM
    forward_row_id: str = F22_ROW_ID

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str):
            raise TypeError("event_id must be a string")
        expected = {ASSIGNMENT_ALGORITHM: F22_ROW_ID, F23_ASSIGNMENT_ALGORITHM: F23_ROW_ID}
        if self.algorithm not in expected:
            raise ValueError(f"unsupported assignment algorithm: {self.algorithm}")
        if self.forward_row_id != expected[self.algorithm]:
            raise ValueError("assignment row and algorithm disagree")
        if self.arm not in ARMS:
            raise ValueError(f"unsupported entry arm: {self.arm}")
        if len(self.digest) != 64 or any(c not in "0123456789abcdef" for c in self.digest):
            raise ValueError("digest must be a lowercase SHA-256 hex string")

    def as_record(self, caps: Mapping[str, object] | None = None) -> dict:
        """Return stable JSON-friendly lineage, including the caps active at sizing time."""
        active_caps = {str(k): float(v) for k, v in (caps or {}).items()}
        # Both the explicit names in L131 and the concise names used by existing audit readers are
        # retained.  They are the same values; neither is inferred from order shape later.
        return {
            "forward_row_id": self.forward_row_id,
            "row_id": self.forward_row_id,
            "assignment_algorithm": self.algorithm,
            "algorithm": self.algorithm,
            "canonical_event_id": self.event_id,
            "event_id": self.event_id,
            "digest": self.digest,
            "arm": self.arm,
            "active_caps": active_caps,
            "caps": dict(active_caps),
        }


def assign_entry_arm_for(event_id: str, *, row_id: str, algorithm: str) -> EntryArmAssignment:
    """Assign an event by the exact registered SHA-256 byte rule.

    ``event_id`` is the only runtime input.  In particular, do not normalize, case-fold, strip,
    salt with a timestamp, or rebalance assignments after this function returns.
    """
    if not isinstance(event_id, str):
        raise TypeError("event_id must be a string")
    prefix = algorithm.encode("utf-8") + b"\0"
    digest_bytes = hashlib.sha256(prefix + event_id.encode("utf-8")).digest()
    digest = digest_bytes.hex()
    arm = "maker" if digest_bytes[0] % 2 == 0 else "taker"
    return EntryArmAssignment(event_id, digest, arm, algorithm=algorithm, forward_row_id=row_id)


def assign_entry_arm(event_id: str) -> EntryArmAssignment:
    return assign_entry_arm_for(event_id, row_id=F22_ROW_ID, algorithm=ASSIGNMENT_ALGORITHM)


def assign_f23_entry_arm(event_id: str) -> EntryArmAssignment:
    return assign_entry_arm_for(event_id, row_id=F23_ROW_ID, algorithm=F23_ASSIGNMENT_ALGORITHM)


# Small aliases make the pure rule convenient at replay and reporting call sites while retaining
# one implementation and one version string.
f22_assignment = assign_entry_arm
f23_assignment = assign_f23_entry_arm
assignment_for_event = assign_entry_arm


def assignment_from_record(record: Mapping[str, object]) -> EntryArmAssignment:
    """Validate and restore a persisted assignment; contradictions fail closed."""
    row_id = record.get("forward_row_id", record.get("row_id", F22_ROW_ID))
    event_id = record.get("canonical_event_id", record.get("event_id"))
    digest = record.get("digest")
    arm = record.get("arm")
    algorithm = record.get("assignment_algorithm", record.get("algorithm", ASSIGNMENT_ALGORITHM))
    if row_id not in {F22_ROW_ID, F23_ROW_ID} or not isinstance(event_id, str) or not isinstance(digest, str) or not isinstance(arm, str):
        raise ValueError("incomplete experiment assignment record")
    expected = (assign_entry_arm if row_id == F22_ROW_ID else assign_f23_entry_arm)(event_id)
    if (algorithm != expected.algorithm or digest != expected.digest or arm != expected.arm):
        raise ValueError("contradictory F22 assignment record")
    return expected


def classify_outcome(*, wire: bool, provider_state: str | None = None,
                     execution_state: str | None = None, role_ok: bool | None = None,
                     persistence_ok: bool = True, reconciled: bool = True,
                     filled_contracts: float = 0.0, requested_contracts: float = 0.0) -> str:
    """Classify an execution without parsing human log text.

    The caller supplies authoritative structured facts.  Unknown or contradictory facts remain
    UNKNOWN/persistence failures; zero is never inferred from a missing answer.
    """
    if not persistence_ok or not reconciled:
        return "persistence_or_reconciliation_failure"
    if role_ok is False:
        return "role_violation"
    if not wire:
        return "local_or_risk_refused_no_wire"
    raw_state = provider_state or execution_state or ""
    state = str(getattr(raw_state, "value", raw_state)).upper()
    if state in {"UNKNOWN", "UNCONFIRMED", "UNKNOWN_PROVIDER_STATE", "TIMEOUT"}:
        return "unknown_provider_state"
    if state in {"REJECTED", "ORDER_REJECTED"} and filled_contracts <= 1e-9:
        return "provider_rejected_no_position"
    if filled_contracts <= 1e-9 and state in {"UNFILLED", "ORDER_UNFILLED", "CANCELED", "CANCELLED"}:
        return "accepted_terminal_zero_fill"
    if filled_contracts > 1e-9 and requested_contracts > 0 and filled_contracts + 1e-9 < requested_contracts:
        return "accepted_partial_fill"
    if filled_contracts > 1e-9:
        return "accepted_full_fill"
    return "unknown_provider_state"
