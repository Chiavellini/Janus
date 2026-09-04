#!/usr/bin/env python3
"""Cancel every resting Kalshi order on the production account, routed to each order's shard.
THE OPERATOR RUNS THIS. Read-only without --confirm: it lists what rests and where.

    set -a; . /Volumes/Kilos/janus/credentials/track_b.env; set +a
    python3 ops/kalshi_cancel_all.py            # list
    python3 ops/kalshi_cancel_all.py --confirm  # cancel

Exists because the 2026-09-04 proof's resting bid was cancelled on the wrong shard (a bare DELETE
defaults to shard 0; the market sits on 3) and stayed open. The adapter now routes cancels; this
is the hand tool for anything already resting.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kernel.schema import Mode  # noqa: E402
from nodes.exec_kalshi.client import API, PROD_BASE, KalshiExecution  # noqa: E402
from nodes.execution.journal import Journal  # noqa: E402
from nodes.store_tuples.store import TupleStore  # noqa: E402
from nodes.stream_kalshi.stream import load_private_key  # noqa: E402
from kernel.paths import PROOF_DB  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--confirm", action="store_true", help="actually send the cancels")
    ap.add_argument("--db", type=Path, default=PROOF_DB)
    a = ap.parse_args()
    key, path = os.environ.get("JANUS_KALSHI_API_KEY"), os.environ.get("JANUS_KALSHI_PRIVATE_KEY_PATH")
    if not (key and path):
        print("source the credentials env first (JANUS_KALSHI_API_KEY / JANUS_KALSHI_PRIVATE_KEY_PATH)", file=sys.stderr)
        return 2
    v = KalshiExecution(key, load_private_key(path), Journal(TupleStore(a.db)), Mode.LIMITED_LIVE, base_url=PROD_BASE)
    p = f"{API}/portfolio/orders"
    d = v.client.get_json(v.base_url + p, params={"status": "resting", "limit": 200}, use_cache=False, headers=v._headers("GET", p))
    orders = d.get("orders") or []
    for o in orders:
        print(f"[resting] {o.get('ticker')} {o.get('order_id')} {o.get('side')} {o.get('remaining_count_fp')} @ {o.get('yes_price_dollars')} "
              f"shard {v.shard_of(o.get('ticker'))}")
    if not orders:
        print("nothing resting")
        return 0
    if not a.confirm:
        print(f"{len(orders)} resting; re-run with --confirm to cancel")
        return 0
    n = v.cancel_all()
    print(f"[cancel] sent {n} of {len(orders)}" + (f"; last error {v.last_error}" if v.last_error else ""))
    d = v.client.get_json(v.base_url + p, params={"status": "resting", "limit": 200}, use_cache=False, headers=v._headers("GET", p))
    left = d.get("orders") or []
    print(f"[after ] {len(left)} still resting" + (": " + ", ".join(o.get("order_id", "?") for o in left) if left else ""))
    return 0 if not left else 1


if __name__ == "__main__":
    raise SystemExit(main())
