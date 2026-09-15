"""Pure, versioned entry-arm assignment and F22 outcome vocabulary.

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


def ensure_f22_decisions(store) -> None:
    """Create the additive F22 analysis table on the caller's existing store connection."""
    store.ensure_ddl(F22_DECISIONS_DDL)


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


def first_three_fills_reconciled(store) -> tuple[bool, str]:
    """Gate a fourth F22 admission until its first three actual fills are fully reconciled.

    The check is deliberately against durable structured rows only.  Zero fills do not consume
    this checkpoint, and a missing table/column or contradictory identity blocks rather than being
    interpreted as a successful reconciliation.
    """
    try:
        names = {r[0] for r in store.con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('f22_decisions','executions','execution_settlements')").fetchall()}
        if "f22_decisions" not in names or "executions" not in names:
            return True, "fewer than three F22 fills"
        duplicate = store.con.execute(
            "SELECT f.execution_id,COUNT(*) FROM f22_decisions f JOIN executions e ON e.execution_id=f.execution_id "
            "WHERE f.forward_row_id=? AND f.selected_quantity IS NOT NULL AND e.first_filled>1e-9 "
            "GROUP BY f.execution_id HAVING COUNT(*)<>1 LIMIT 1", (F22_ROW_ID,)).fetchone()
        if duplicate is not None:
            return False, f"F22 fill {duplicate[0]} is linked by {duplicate[1]} decisions"
        rows = store.con.execute(
            "SELECT f.id,f.event_id,f.assignment_algorithm,f.digest,f.arm,f.selected_quantity,"
            "e.execution_id,e.opportunity_id,e.event_id,e.league,e.mode,e.state,e.released,e.first_filled,e.quantity "
            "FROM f22_decisions f JOIN executions e ON e.execution_id=f.execution_id "
            "WHERE f.forward_row_id=? AND f.selected_quantity IS NOT NULL AND e.first_filled>1e-9 "
            "ORDER BY e.started_utc,f.id LIMIT 3", (F22_ROW_ID,)).fetchall()
        if len(rows) < 3:
            return True, f"{len(rows)} of first three F22 fills observed"
        if "execution_settlements" not in names:
            return False, "three F22 fills observed but settlement ledger is absent"
        for row in rows:
            _, f_event, algorithm, digest, arm, selected, exid, opp, event, league, mode, state, released, first_filled, quantity = row
            try:
                assignment_from_record({"forward_row_id": F22_ROW_ID, "assignment_algorithm": algorithm,
                                        "event_id": f_event, "digest": digest, "arm": arm})
            except (TypeError, ValueError):
                return False, f"first-three fill {exid} has contradictory F22 assignment"
            if f_event != event or mode != "LIMITED_LIVE" or abs(float(selected) - float(quantity)) > 1e-9:
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
        return True, "first three F22 fills are authoritatively reconciled"
    except Exception as exc:  # noqa: BLE001 -- malformed evidence is a block, never a pass
        return False, f"F22 reconciliation proof unreadable: {type(exc).__name__}: {exc}"


def record_f22_decision(store, *, assignment: Mapping[str, object], decision: Mapping[str, object],
                        selected_quantity: float | None, now: float | None = None) -> bool:
    """Persist one selected/common-sizing decision after its sizing row is durable.

    A missing or malformed lineage is rejected rather than repaired.  ``outcome`` starts NULL:
    report code treats that as unresolved until either an explicit pre-wire disposition or the
    structured execution/settlement records prove the terminal result.
    """
    ensure_f22_decisions(store)
    restored = assignment_from_record(assignment)
    ih = assignment.get("sizing_input_hash")
    occurrence = assignment.get("sizing_occurrence")
    epoch = assignment.get("sizing_book_epoch")
    if not isinstance(ih, str) or not ih or not isinstance(epoch, str) or not epoch or occurrence is None:
        raise ValueError("incomplete F22 sizing lineage")
    t = time.time() if now is None else float(now)
    cur = store.con.execute(
        "INSERT OR IGNORE INTO f22_decisions(event_id,forward_row_id,assignment_algorithm,digest,arm,"
        "sizing_input_hash,sizing_occurrence,sizing_book_epoch,selected_quantity,decision_json,created_utc,updated_utc) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (restored.event_id, restored.forward_row_id, restored.algorithm, restored.digest, restored.arm,
         ih, int(occurrence), epoch, selected_quantity,
         json.dumps(dict(decision), sort_keys=True, separators=(",", ":")), t, t),
    )
    return cur.rowcount == 1


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


@dataclass(frozen=True)
class EntryArmAssignment:
    """The immutable F22 identity for one canonical event."""

    event_id: str
    digest: str
    arm: str
    algorithm: str = ASSIGNMENT_ALGORITHM
    forward_row_id: str = F22_ROW_ID

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str):
            raise TypeError("event_id must be a string")
        if self.algorithm != ASSIGNMENT_ALGORITHM:
            raise ValueError(f"unsupported assignment algorithm: {self.algorithm}")
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


def assign_entry_arm(event_id: str) -> EntryArmAssignment:
    """Assign an event by the exact registered SHA-256 byte rule.

    ``event_id`` is the only runtime input.  In particular, do not normalize, case-fold, strip,
    salt with a timestamp, or rebalance assignments after this function returns.
    """
    if not isinstance(event_id, str):
        raise TypeError("event_id must be a string")
    digest_bytes = hashlib.sha256(_PREFIX + event_id.encode("utf-8")).digest()
    digest = digest_bytes.hex()
    arm = "maker" if digest_bytes[0] % 2 == 0 else "taker"
    return EntryArmAssignment(event_id, digest, arm)


# Small aliases make the pure rule convenient at replay and reporting call sites while retaining
# one implementation and one version string.
f22_assignment = assign_entry_arm
assignment_for_event = assign_entry_arm


def assignment_from_record(record: Mapping[str, object]) -> EntryArmAssignment:
    """Validate and restore a persisted assignment; contradictions fail closed."""
    row_id = record.get("forward_row_id", record.get("row_id", F22_ROW_ID))
    event_id = record.get("canonical_event_id", record.get("event_id"))
    digest = record.get("digest")
    arm = record.get("arm")
    algorithm = record.get("assignment_algorithm", record.get("algorithm", ASSIGNMENT_ALGORITHM))
    if row_id != F22_ROW_ID or not isinstance(event_id, str) or not isinstance(digest, str) or not isinstance(arm, str):
        raise ValueError("incomplete F22 assignment record")
    expected = assign_entry_arm(event_id)
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
