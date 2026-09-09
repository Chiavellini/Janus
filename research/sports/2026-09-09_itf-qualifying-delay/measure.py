#!/usr/bin/env python3
"""L45: offline qualifying-only replay of L44's immutable venue-page archive."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("l44_qualifying_helper", HERE.parent / "2026-09-09_itf-settlement-delay-keyset/measure.py")
l44 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(l44)


class OfflineOnly:
    def get_json(self, *args, **kwargs):
        raise ValueError("ARCHIVE_INCOMPLETE_NETWORK_FORBIDDEN")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    archive = args.archive.resolve()
    if not archive.is_dir():
        raise SystemExit("The L44 archive does not exist")
    if (HERE / "results.json").exists():
        raise SystemExit("Immutable results already exist")
    rows, counts, complete, error = {}, {"closed": 0, "open": 0}, False, None
    try:
        for closed in (True, False):
            for event in l44.enumerate_events(OfflineOnly(), archive, closed=closed):
                counts["closed" if closed else "open"] += 1
                if not str(event.get("slug", "")).startswith("itf-"):
                    continue
                row = l44.classify(event, source_closed=closed, qualifying_population=True)
                event_id = str(event["id"])
                if event_id in rows:
                    l44.merge_transition(rows[event_id], row)
                else:
                    rows[event_id] = row
        complete = True
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    results = l44.summarize(list(rows.values()), complete=complete, error=error)
    results.update(population="ITF qualifying singles", tennis_events=counts, archive=str(archive),
                   source=l44.GAMMA, network_requests=0,
                   run=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
                   spec_sha256=hashlib.sha256((HERE / "spec.yaml").read_bytes()).hexdigest())
    with (archive / "L45_qualifying_rows.json").open("x") as fh:
        json.dump(list(rows.values()), fh, indent=2, sort_keys=True)
    with (HERE / "results.json").open("x") as fh:
        json.dump(results, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0 if results["gates"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
