#!/usr/bin/env python3
"""L127 deterministic read-only production incident/maker-history measurement."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

from nodes.execution.legacy_incident_ack import _empty_admission_state, match_incident
from nodes.risk.flags import unresolved_flag_rows
from ops.box.clear_legacy_incident_latch import MATERIAL_FLAGS


TABLES = (
    "historical_legacy_incident_acknowledgements",
    "pm_post_only_orders",
    "pm_post_only_admission",
    "pm_post_only_violations",
    "orders",
    "executions",
    "capital_reservations",
    "lane_flags",
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def rows(con, table):
    cur = con.execute(f"SELECT * FROM {table} ORDER BY rowid")
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def attempt(fn):
    try:
        value = fn()
        return {"ok": True, "value": value}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--deployed-sha", required=True)
    args = ap.parse_args()
    db = Path(args.db).resolve()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

    schemas = {
        table: [list(row) for row in con.execute(f"PRAGMA table_info({table})")]
        for table in TABLES
    }
    table_rows = {table: rows(con, table) for table in TABLES}
    hashes = {
        table: hashlib.sha256(canonical(table_rows[table]).encode()).hexdigest()
        for table in TABLES
    }

    ack_rows = table_rows["historical_legacy_incident_acknowledgements"]
    ack = next(row for row in ack_rows if row["flag_id"] == 211)
    ack_record = json.loads(ack["record_json"])
    ack_time = float(ack_record["recorded_utc"])
    computed_record_sha = hashlib.sha256(canonical(ack_record).encode()).hexdigest()

    maker = table_rows["pm_post_only_orders"]
    activity = [
        max(float(row.get(name) or 0) for name in
            ("terminal_seen_utc", "cancel_deadline_utc", "cancel_attempt_utc"))
        for row in maker
    ]
    maker_summary = {
        "count": len(maker),
        "terminal_proved": sum(int(row["terminal_proved"] == 1) for row in maker),
        "violated": sum(int(row["violated"] == 1) for row in maker),
        "post_ack_activity_count": sum(ts > ack_time for ts in activity),
        "activity_utc_min": min(activity) if activity else None,
        "activity_utc_max": max(activity) if activity else None,
        "row_sha256": [
            hashlib.sha256(canonical(row).encode()).hexdigest() for row in maker
        ],
    }
    admission_exact = _empty_admission_state(table_rows["pm_post_only_admission"])
    global_quiet = {
        "orders": con.execute(
            "SELECT COUNT(*) FROM orders WHERE open IS NOT 0 OR settlement_pending IS NOT 0 "
            "OR state='UNCONFIRMED'"
        ).fetchone()[0],
        "unreleased_executions": con.execute(
            "SELECT COUNT(*) FROM executions WHERE released IS NOT 1"
        ).fetchone()[0],
        "materially_unhedged": con.execute(
            "SELECT COUNT(*) FROM executions WHERE released IS NOT 1 "
            "AND ABS(COALESCE(unhedged,0)) > 0.01"
        ).fetchone()[0],
        "unreleased_reservations": con.execute(
            "SELECT COUNT(*) FROM capital_reservations WHERE released_utc IS NULL"
        ).fetchone()[0],
    }
    unresolved = {
        flag: [int(row[0]) for row in unresolved_flag_rows(con, flag)]
        for flag in MATERIAL_FLAGS
    }
    unresolved = {flag: ids for flag, ids in unresolved.items() if ids}
    strict = attempt(lambda: match_incident(con, 211, require_idle=True))
    incident_only = attempt(lambda: match_incident(con, 211, require_idle=False))

    append_only_terminal = (
        computed_record_sha == ack["record_sha256"]
        and len(maker) > 0
        and all(row["terminal_proved"] == 1 and row["violated"] == 0 for row in maker)
        and admission_exact
        and len(table_rows["pm_post_only_violations"]) == 1
        and incident_only["ok"]
        and all(value == 0 for value in global_quiet.values())
        and not unresolved
    )
    result = {
        "schema": "janus.l127.post_ack_maker_history.v1",
        "database": str(db),
        "deployed_sha": args.deployed_sha,
        "ack": {
            "row_id": ack["id"],
            "recorded_utc": ack_record["recorded_utc"],
            "stored_record_sha256": ack["record_sha256"],
            "computed_record_sha256": computed_record_sha,
        },
        "schemas": schemas,
        "table_counts": {table: len(table_rows[table]) for table in TABLES},
        "table_row_sha256": hashes,
        "maker_orders": maker_summary,
        "admission_exact_empty": admission_exact,
        "violation_row_sha256": [
            hashlib.sha256(canonical(row).encode()).hexdigest()
            for row in table_rows["pm_post_only_violations"]
        ],
        "global_quiet": global_quiet,
        "unresolved_material_flags": unresolved,
        "match_require_idle_true": strict,
        "match_require_idle_false": incident_only,
        "classification": (
            "APPEND_ONLY_TERMINAL_HISTORY" if append_only_terminal else "MATERIAL_STOP"
        ),
    }
    print(canonical(result))


if __name__ == "__main__":
    main()
