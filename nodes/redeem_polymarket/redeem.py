#!/usr/bin/env python3
"""Durable Polymarket redemption state machine; venue I/O is behind a tiny adapter."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol, Sequence


DDL = """
CREATE TABLE IF NOT EXISTS pm_redemptions(
  condition_id TEXT PRIMARY KEY,
  metadata TEXT NOT NULL UNIQUE,
  state TEXT NOT NULL,
  expected_value TEXT NOT NULL,
  prepared_utc REAL NOT NULL,
  updated_utc REAL NOT NULL,
  transaction_id TEXT,
  transaction_hash TEXT,
  detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS pm_redemption_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  condition_id TEXT NOT NULL,
  seen_utc REAL NOT NULL,
  from_state TEXT,
  to_state TEXT NOT NULL,
  detail_json TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Position:
    condition_id: str
    size: str
    current_value: str
    redeemable: bool


@dataclass(frozen=True)
class Submission:
    transaction_id: str
    transaction_hash: str | None = None


@dataclass(frozen=True)
class Transaction:
    state: str  # PENDING | CONFIRMED | FAILED
    transaction_id: str
    transaction_hash: str | None = None
    detail: str = ""


class Adapter(Protocol):
    def positions(self) -> Sequence[Position]: ...
    def submit(self, condition_id: str, *, metadata: str) -> Submission: ...
    def transaction(self, transaction_id: str) -> Transaction: ...
    def recover(self, *, metadata: str) -> Submission | None: ...
    def close(self) -> None: ...


def _decimal(value: object) -> Decimal | None:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return out if out.is_finite() else None


def eligible_positions(rows: Sequence[Position], *, min_value: Decimal = Decimal("0.01")) -> dict[str, Decimal]:
    """Return one value per redeemable condition; losing zero-value remnants stay untouched."""
    out: dict[str, Decimal] = {}
    for row in rows:
        condition = str(row.condition_id or "").lower()
        size, value = _decimal(row.size), _decimal(row.current_value)
        if (not row.redeemable or len(condition) != 66 or not condition.startswith("0x")
                or any(ch not in "0123456789abcdef" for ch in condition[2:])
                or size is None or value is None or size <= 0 or value < min_value):
            continue
        out[condition] = out.get(condition, Decimal(0)) + value
    return out


class RedemptionStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path, timeout=30.0)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(DDL)
        self.con.commit()

    def row(self, condition_id: str):
        return self.con.execute("SELECT * FROM pm_redemptions WHERE condition_id=?", (condition_id,)).fetchone()

    def prepare(self, condition_id: str, value: Decimal, *, now: float) -> sqlite3.Row:
        metadata = f"janus:pm_redeem:{condition_id}"
        self.con.execute(
            "INSERT OR IGNORE INTO pm_redemptions(condition_id,metadata,state,expected_value,prepared_utc,updated_utc) "
            "VALUES(?,?,'PREPARED',?,?,?)", (condition_id, metadata, str(value), now, now))
        row = self.row(condition_id)
        if row is None:
            raise RuntimeError("redemption prepare did not persist")
        if row["state"] == "PREPARED" and float(row["prepared_utc"]) == now:
            self._event(condition_id, None, "PREPARED", {"expected_value": str(value)}, now)
        self.con.commit()
        return self.row(condition_id)

    def move(self, condition_id: str, to_state: str, *, now: float, detail: str = "",
             transaction_id: str | None = None, transaction_hash: str | None = None) -> None:
        row = self.row(condition_id)
        if row is None:
            raise RuntimeError("unknown redemption")
        old = row["state"]
        self.con.execute(
            "UPDATE pm_redemptions SET state=?,updated_utc=?,detail=?,"
            "transaction_id=COALESCE(?,transaction_id),transaction_hash=COALESCE(?,transaction_hash) WHERE condition_id=?",
            (to_state, now, detail[:500], transaction_id, transaction_hash, condition_id))
        self._event(condition_id, old, to_state, {"detail": detail[:500], "transaction_id": transaction_id,
                                                  "transaction_hash": transaction_hash}, now)
        self.con.commit()

    def _event(self, condition_id: str, old: str | None, new: str, detail: dict, now: float) -> None:
        self.con.execute(
            "INSERT INTO pm_redemption_events(condition_id,seen_utc,from_state,to_state,detail_json) VALUES(?,?,?,?,?)",
            (condition_id, now, old, new, json.dumps(detail, sort_keys=True, separators=(",", ":"))))

    def close(self) -> None:
        self.con.close()


class Redeemer:
    def __init__(self, adapter: Adapter, store: RedemptionStore, *, clock=time.time):
        self.adapter, self.store, self.clock = adapter, store, clock

    def run_once(self) -> dict[str, int]:
        now = self.clock()
        positions = eligible_positions(self.adapter.positions())
        counts = {"eligible": len(positions), "submitted": 0, "confirmed": 0,
                  "complete": 0, "pending": 0, "unknown": 0, "failed": 0}
        counts["failed"] = int(self.store.con.execute(
            "SELECT COUNT(*) FROM pm_redemptions WHERE state='FAILED'").fetchone()[0])

        # First reconcile every durable attempt. A PREPARED row may be the crash window after the
        # relayer accepted the wire but before Janus stored its transaction id; exact metadata is
        # the recovery key, and absence is never permission to submit again blindly.
        for row in self.store.con.execute(
                "SELECT * FROM pm_redemptions WHERE state NOT IN ('COMPLETE','FAILED') ORDER BY prepared_utc").fetchall():
            condition, state = row["condition_id"], row["state"]
            if condition not in positions:
                self.store.move(condition, "COMPLETE", now=now, detail="fresh positions read has no positive redeemable value")
                counts["complete"] += 1
                continue
            if state == "PREPARED" and not row["transaction_id"]:
                recovered = self.adapter.recover(metadata=row["metadata"])
                if recovered is None:
                    counts["pending"] += 1
                    counts["unknown"] += 1
                    continue
                self.store.move(condition, "SUBMITTED", now=now, detail="recovered exact relayer metadata",
                                transaction_id=recovered.transaction_id,
                                transaction_hash=recovered.transaction_hash)
                row = self.store.row(condition)
            if row and row["transaction_id"]:
                tx = self.adapter.transaction(row["transaction_id"])
                if tx.state == "FAILED":
                    self.store.move(condition, "FAILED", now=now, detail=tx.detail,
                                    transaction_hash=tx.transaction_hash)
                    counts["failed"] += 1
                elif tx.state == "CONFIRMED":
                    self.store.move(condition, "CONFIRMED_PENDING", now=now,
                                    detail="onchain confirmed; awaiting fresh position disappearance",
                                    transaction_hash=tx.transaction_hash)
                    counts["confirmed"] += 1
                else:
                    counts["pending"] += 1

        # Only conditions with no durable history are new. Existing PREPARED/FAILED/COMPLETE rows
        # are never implicitly retried; this keeps a lost relayer acknowledgement idempotent.
        for condition, value in positions.items():
            if self.store.row(condition) is not None:
                continue
            row = self.store.prepare(condition, value, now=now)
            try:
                submitted = self.adapter.submit(condition, metadata=row["metadata"])
            except Exception as exc:
                self.store.move(condition, "PREPARED", now=self.clock(),
                                detail=f"submit outcome unknown: {type(exc).__name__}: {str(exc)[:300]}")
                counts["pending"] += 1
                counts["unknown"] += 1
                continue
            self.store.move(condition, "SUBMITTED", now=self.clock(), detail="relayer accepted",
                            transaction_id=submitted.transaction_id,
                            transaction_hash=submitted.transaction_hash)
            counts["submitted"] += 1
        return counts


class SdkAdapter:
    """Pinned official unified SDK adapter. Imported lazily so offline tests need no SDK."""
    def __init__(self):
        import importlib.metadata
        if importlib.metadata.version("polymarket-client") != "0.9.0":
            raise RuntimeError("redemption requires reviewed polymarket-client==0.9.0")
        from polymarket import BuilderApiKey, SecureClient

        key_path = Path(os.environ.get("JANUS_PM_WALLET_KEY_PATH", ""))
        if not key_path.is_file() or key_path.stat().st_mode & 0o077:
            raise RuntimeError("JANUS_PM_WALLET_KEY_PATH must name a mode-600 file")
        names = ("JANUS_PM_FUNDER", "JANUS_PM_BUILDER_API_KEY", "JANUS_PM_BUILDER_SECRET",
                 "JANUS_PM_BUILDER_PASSPHRASE")
        missing = [name for name in names if not os.environ.get(name)]
        if missing:
            raise RuntimeError("missing redemption credentials: " + ", ".join(missing))
        api_key = BuilderApiKey(key=os.environ[names[1]], secret=os.environ[names[2]],
                                passphrase=os.environ[names[3]])
        self.client = SecureClient.create(private_key=key_path.read_text().strip(),
                                          wallet=os.environ[names[0]], api_key=api_key)

    def positions(self) -> list[Position]:
        rows = self.client.list_positions(redeemable=True, page_size=500).iter_items()
        return [Position(str(p.condition_id or ""), str(p.size or "0"),
                         str(p.current_value or "0"), bool(p.redeemable)) for p in rows]

    def submit(self, condition_id: str, *, metadata: str) -> Submission:
        handle = self.client.redeem_positions(condition_id=condition_id, metadata=metadata)
        txid = getattr(handle, "transaction_id", None)
        if not txid:
            raise RuntimeError("relayer returned no transaction id")
        return Submission(str(txid), str(handle.transaction_hash) if handle.transaction_hash else None)

    def transaction(self, transaction_id: str) -> Transaction:
        from polymarket._internal.actions.relayer.poll import fetch_gasless_transaction_sync
        tx = fetch_gasless_transaction_sync(self.client._ctx.relayer, transaction_id=transaction_id)
        state = str(tx.state).upper()
        normalized = "CONFIRMED" if state.endswith("CONFIRMED") else (
            "FAILED" if state.endswith("FAILED") or state.endswith("INVALID") else "PENDING")
        return Transaction(normalized, transaction_id,
                           str(tx.transaction_hash) if tx.transaction_hash else None,
                           str(tx.error_msg or ""))

    def recover(self, *, metadata: str) -> Submission | None:
        payload = self.client._ctx.relayer.get_json("/transactions")
        rows = payload if isinstance(payload, list) else []
        exact = [row for row in rows if isinstance(row, dict) and row.get("metadata") == metadata]
        if len(exact) > 1:
            raise RuntimeError("multiple relayer transactions share exact redemption metadata")
        if not exact:
            return None
        row = exact[0]
        txid = row.get("transactionID") or row.get("transaction_id")
        if not txid:
            raise RuntimeError("recovered relayer transaction has no id")
        txhash = row.get("transactionHash") or row.get("transaction_hash")
        return Submission(str(txid), str(txhash) if txhash else None)

    def close(self) -> None:
        self.client.close()
