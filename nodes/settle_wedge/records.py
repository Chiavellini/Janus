#!/usr/bin/env python3
"""The audit trail: what was read, when, and what was concluded. Append-only, versioned by hash."""

from __future__ import annotations

import json
import time

from nodes.settle_wedge.equivalence import NotEquivalent, SettlementEquivalence
from nodes.settle_wedge.harvest import RulesRecord

RECORDS_DDL = """
CREATE TABLE IF NOT EXISTS settlement_records(
  rules_hash TEXT NOT NULL, venue TEXT NOT NULL, market_id TEXT NOT NULL, template_hash TEXT NOT NULL,
  source_type TEXT NOT NULL, source_url TEXT, provenance TEXT NOT NULL, retrieved_at REAL NOT NULL,
  settlement_sources TEXT, text TEXT NOT NULL, PRIMARY KEY(rules_hash, venue, market_id));
CREATE TABLE IF NOT EXISTS equivalence_records(
  id INTEGER PRIMARY KEY AUTOINCREMENT, seen_ts REAL NOT NULL, event_id TEXT NOT NULL,
  league TEXT NOT NULL, rules_hash_a TEXT NOT NULL, rules_hash_b TEXT NOT NULL,
  result TEXT NOT NULL, block_code TEXT, block_dimension TEXT, block_detail TEXT,
  template_a TEXT, template_b TEXT, dimensions_json TEXT, rates_json TEXT);
CREATE INDEX IF NOT EXISTS equivalence_records_event ON equivalence_records(event_id, seen_ts);
"""


def record_rules(store, rec: RulesRecord) -> None:
    store.ensure_ddl(RECORDS_DDL)
    store.con.execute(
        "INSERT OR IGNORE INTO settlement_records VALUES(?,?,?,?,?,?,?,?,?,?)",
        (rec.rules_hash, rec.venue, rec.market_id, rec.template_hash, rec.source_type, rec.source_url,
         rec.provenance, rec.retrieved_at, json.dumps(list(rec.settlement_sources)), rec.text))


def record_equivalence(store, *, event_id: str, league: str, rec_a: RulesRecord, rec_b: RulesRecord,
                       result: SettlementEquivalence | NotEquivalent, now: float | None = None) -> None:
    store.ensure_ddl(RECORDS_DDL)
    t = now or time.time()
    last = store.con.execute(
        "SELECT result, block_code, rules_hash_a, rules_hash_b FROM equivalence_records "
        "WHERE event_id=? ORDER BY id DESC LIMIT 1", (event_id,)).fetchone()
    if isinstance(result, SettlementEquivalence):
        row = ("EQUIVALENT", None, None, None, result.template_a, result.template_b,
               json.dumps({v.dimension: v.outcome for v in result.verdicts}, sort_keys=True),
               json.dumps(dict(result.rates), sort_keys=True))
    else:
        row = ("BLOCKED", result.code, result.dimension, result.detail[:400], None, None, None, None)
    if last is not None and (last[0], last[1], last[2], last[3]) == (row[0], row[1], rec_a.rules_hash, rec_b.rules_hash):
        return                                            # unchanged: append nothing
    store.con.execute(
        "INSERT INTO equivalence_records(seen_ts, event_id, league, rules_hash_a, rules_hash_b, result, "
        "block_code, block_dimension, block_detail, template_a, template_b, dimensions_json, rates_json) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (t, event_id, league, rec_a.rules_hash, rec_b.rules_hash, *row))
