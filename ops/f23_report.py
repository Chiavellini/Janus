#!/usr/bin/env python3
"""Read-only report for the fresh F23 maker-versus-taker cohort.

F23 is intentionally backed by ``f23_decisions`` and never includes F22 rows.  The shared
strict report implementation keeps the same executable-role, fee, settlement and identity
checks while selecting F23's registered caps and assignment lineage.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from kernel.paths import DB
from ops.f22_report import report as _report


def report(db: Path = DB, *, hours: float | None = None) -> dict:
    return _report(db, hours=hours, row_id="F23")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--hours", type=float, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    print(json.dumps(report(args.db, hours=args.hours), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
