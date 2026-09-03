#!/usr/bin/env python3
"""Kalshi exchange shards: see where the collateral sits, and move it. THE OPERATOR RUNS --move.

    python3 ops/kalshi_shards.py --show                       # balances per shard, and which shard each game series is on
    python3 ops/kalshi_shards.py --move --to 3 --usd 20       # plan only
    python3 ops/kalshi_shards.py --move --to 3 --usd 20 --confirm

Kalshi split its exchange into shards (2026-08-24: baseball, crypto and tennis on dedicated
instances; 2026-09-10: new basketball markets on shard 3). "Programmatic traders must preallocate
collateral on a given exchange shard before order placement": an order for a market on shard 3
from an account whose balance sits on shard 0 is refused `user_not_found` (measured on the first
armed proof, 2026-09-03). The transfer is POST /portfolio/intra_exchange_instance_transfer, amount
in CENTICENTS, processed asynchronously. Moving money is the operator's command; without
--confirm this prints the plan and sends nothing.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kernel.execution_protocol import OrderRequest  # noqa: E402,F401  (import order: kernel first)
from kernel.fetch import Client  # noqa: E402
from kernel.schema import Mode  # noqa: E402
from nodes.entities.leagues import LEAGUES  # noqa: E402
from nodes.exec_kalshi.client import API, PROD_BASE, KalshiExecution  # noqa: E402
from nodes.execution.journal import Journal  # noqa: E402
from nodes.store_tuples.store import TupleStore  # noqa: E402
from nodes.stream_kalshi.stream import load_private_key  # noqa: E402

PROOF_DB = Path("/Volumes/Kilos/janus/tuples/proofs.sqlite")


def venue_from_env(db: Path = PROOF_DB) -> KalshiExecution | None:
    api_key, key_path = os.environ.get("JANUS_KALSHI_API_KEY"), os.environ.get("JANUS_KALSHI_PRIVATE_KEY_PATH")
    if not (api_key and key_path):
        print("source the credentials env first (JANUS_KALSHI_API_KEY / JANUS_KALSHI_PRIVATE_KEY_PATH)", file=sys.stderr)
        return None
    # DEMO_EXECUTION is the lowest mode the adapter accepts; nothing here submits an order.
    return KalshiExecution(api_key, load_private_key(key_path), Journal(TupleStore(db)), Mode.DEMO_EXECUTION, base_url=PROD_BASE)


def series_shards(cl: Client) -> dict[str, int | None]:
    """league -> the exchange_index of the first open market of its game series (None if none open)."""
    out: dict[str, int | None] = {}
    for code, lg in LEAGUES.items():
        try:
            ms = cl.get_json(f"{PROD_BASE}{API}/markets", params={"series_ticker": lg.kalshi_series, "status": "open", "limit": 1},
                             use_cache=False).get("markets") or []
            out[code] = int(ms[0]["exchange_index"]) if ms and ms[0].get("exchange_index") is not None else None
        except Exception:  # noqa: BLE001
            out[code] = None
    return out


def show(venue: KalshiExecution, cl: Client) -> int:
    by = venue.balances_by_shard()
    if by is None:
        print(f"balance could not be read: {venue.last_error}", file=sys.stderr)
        return 2
    total = venue.balance()
    print(f"balances by shard: {by}  (total {total.available_usd:.2f})" if total else f"balances by shard: {by}")
    for code, idx in series_shards(cl).items():
        print(f"  {code:5s} {LEAGUES[code].kalshi_series:22s} shard {idx if idx is not None else '— (no open market)'}"
              + ("" if idx is None else f"  funded {by.get(idx, 0.0):.2f}"))
    return 0


def move(venue: KalshiExecution, *, to: int, usd: float, source: int, confirm: bool) -> int:
    by = venue.balances_by_shard() or {}
    have = by.get(source, 0.0)
    print(f"[plan] move {usd:.2f} USD from shard {source} (holds {have:.2f}) to shard {to} (holds {by.get(to, 0.0):.2f})")
    if usd <= 0 or have < usd:
        print("nothing to move: amount must be positive and within the source shard's balance", file=sys.stderr)
        return 2
    if not confirm:
        print("plan only: re-run with --confirm to send the transfer (it is your money moving between your own shards)")
        return 0
    path = f"{API}/portfolio/intra_exchange_instance_transfer"
    body = {"source": "event_contract", "destination": "event_contract", "amount": int(round(usd * 10_000)),
            "source_exchange_shard": int(source), "destination_exchange_shard": int(to)}
    d = venue.client.post_json_once(venue.base_url + path, body, headers=venue._headers("POST", path))
    print(f"[sent] transfer_id {d.get('transfer_id') if isinstance(d, dict) else d}; processed asynchronously — run --show in a minute")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--move", action="store_true")
    ap.add_argument("--to", type=int, help="destination exchange shard index")
    ap.add_argument("--from", dest="source", type=int, default=0, help="source shard (default 0)")
    ap.add_argument("--usd", type=float)
    ap.add_argument("--confirm", action="store_true", help="actually send the transfer")
    ap.add_argument("--db", type=Path, default=PROOF_DB)
    a = ap.parse_args()
    venue = venue_from_env(a.db)
    if venue is None:
        return 2
    if a.move:
        if a.to is None or a.usd is None:
            ap.error("--move needs --to and --usd")
        return move(venue, to=a.to, usd=a.usd, source=a.source, confirm=a.confirm)
    return show(venue, Client("kalshi-shards", rate=4, burst=8, cache_dir=None))


if __name__ == "__main__":
    raise SystemExit(main())
