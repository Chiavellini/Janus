#!/usr/bin/env python3
"""Validate source activity and print its cent-exact reconciliation summary."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nodes.account_ledger.ledger import load_activities, summarize


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    args = ap.parse_args()
    rows, _ = load_activities(args.source)
    print(json.dumps(summarize(rows).as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
