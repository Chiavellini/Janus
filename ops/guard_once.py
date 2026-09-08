#!/usr/bin/env python3
"""One pass of the position guard against the real venues, from a process of its own.

    sudo -u janus JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box .venv/bin/python3 ops/guard_once.py [--db PATH]

For the R2 proof (2026-09-08) and for any hour the lane is not running a real-order mode: builds
the real venue clients read-side (nothing here can submit: no clearance is ever minted), runs
`PositionGuard.fetch()` then `apply()` once against the lane's store, and prints the report. The
writes are the guard's own: adopted order rows, corrected execution rows, lane flags. Needs the
box's credentials in the environment (the lane's /etc/janus.env and /run/janus).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kernel.schema import Mode  # noqa: E402
from nodes.exec_kalshi.client import PROD_BASE, KalshiExecution  # noqa: E402
from nodes.exec_polymarket.client import PolymarketExecution, PyClobTransport  # noqa: E402
from nodes.execute.guard import PositionGuard  # noqa: E402
from nodes.execute.records import ExecutionRecords  # noqa: E402
from nodes.execution.journal import Journal  # noqa: E402
from nodes.risk.kill import KillSwitches  # noqa: E402
from nodes.risk.limits import load_limits  # noqa: E402
from nodes.store_tuples.store import DEFAULT_DB, TupleStore  # noqa: E402
from nodes.stream_kalshi.stream import load_private_key  # noqa: E402


def run_once(*, venues, store, journal, records, limits, kill, started_utc: float, log=print) -> dict:
    g = PositionGuard(venues=venues, journal=journal, records=records, store=store, limits=limits.protect,
                      started_utc=started_utc, kill=kill, log=log)
    snap = g.fetch()
    rep = g.apply(snap)
    for k, e in snap.errors.items():
        log(f"error {k}: {e}")
    for line in rep.findings:
        log(f"finding: {line}")
    log(f"unconfirmed after the poll: {snap.unconfirmed}")
    log(f"positions: " + "; ".join(f"{v}: " + (", ".join(f"{p.market_id[:14]} {p.side} {p.contracts:g}" for p in ps) if ps else
                                                 ("none" if ps == [] else f"unreadable ({getattr(venues.get(v), 'last_error', '')[:120]})"))
                                   for v, ps in snap.positions.items()))
    for v, venue in venues.items():
        bal = venue.balance() if hasattr(venue, "balance") else None
        log(f"balance {v}: {bal.available_usd if bal else 'unreadable'}")
    log(f"corrected={rep.corrected} to_protect={rep.to_protect} orphans={len(rep.orphans)} mismatches={len(rep.mismatches)} "
        f"fills_today={[(f.fill_id[:8], f.state.value, round(f.realized_usd, 4)) for f in rep.fills_today]}")
    return {"corrected": rep.corrected, "to_protect": rep.to_protect, "orphans": len(rep.orphans), "mismatches": rep.mismatches,
            "adopted": snap.adopted, "errors": snap.errors}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("JANUS_TUPLES_DB", str(DEFAULT_DB)))
    ap.add_argument("--since-hours", type=float, default=24.0, help="how far back the fills are read")
    a = ap.parse_args()
    # The lane may be running: our writes wait behind its lock through the busy handler (BEGIN
    # IMMEDIATE), never fail at once as a read-snapshot upgrade (the worker store's rule).
    store = TupleStore(a.db, isolation_level="IMMEDIATE")
    journal = Journal(store)
    records = ExecutionRecords(store)
    limits = load_limits()
    kill = KillSwitches()
    api_key, key_path = os.environ.get("JANUS_KALSHI_API_KEY"), os.environ.get("JANUS_KALSHI_PRIVATE_KEY_PATH")
    if not (api_key and key_path):
        print("JANUS_KALSHI_API_KEY / JANUS_KALSHI_PRIVATE_KEY_PATH are unset"); return 2
    venues = {"kalshi": KalshiExecution(api_key, load_private_key(key_path), journal, Mode.LIMITED_LIVE, base_url=PROD_BASE),
              "polymarket": PolymarketExecution(PyClobTransport(), journal, Mode.LIMITED_LIVE)}
    out = run_once(venues=venues, store=store, journal=journal, records=records, limits=limits, kill=kill,
                   started_utc=time.time() - a.since_hours * 3600.0)
    return 0 if not out["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
