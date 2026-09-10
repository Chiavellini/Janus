#!/usr/bin/env python3
"""One automatic Polymarket redemption pass."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from nodes.redeem_polymarket.redeem import Redeemer, RedemptionStore, SdkAdapter


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=Path(os.environ.get(
        "JANUS_REDEMPTION_DB", "/srv/janus/redemptions/redemptions.sqlite")))
    a = ap.parse_args()
    adapter, store = SdkAdapter(), RedemptionStore(a.db)
    try:
        counts = Redeemer(adapter, store).run_once()
    finally:
        adapter.close()
        store.close()
    print("pm redemption " + " ".join(f"{key}={value}" for key, value in counts.items()))
    # A PREPARED attempt with no recoverable relayer transaction has an unknown wire outcome.
    # Keep the durable row pending, but fail the oneshot so the watchdog cannot call it healthy.
    return 1 if counts["failed"] or counts["unknown"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
