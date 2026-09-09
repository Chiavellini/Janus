#!/usr/bin/env python3
"""L47: independent qualifying score, offline, only after the fresh L46 source passes."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("l47_source", HERE.parent / "2026-09-09_itf-delay-atomic/measure.py")
source = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(source)
scoring = source.scoring


class OfflineOnly:
    def get_json(self, *args, **kwargs):
        raise ValueError("ARCHIVE_INCOMPLETE_NETWORK_FORBIDDEN")


def verified_source_archive():
    path = source.HERE / "results.json"
    if not path.exists():
        raise ValueError("L46_HAS_NO_RESULT")
    result = json.loads(path.read_text())
    if result.get("gates") != "PASS" or not result.get("complete") or not result.get("fresh_archive"):
        raise ValueError("L46_DID_NOT_PASS")
    archive = Path(result["archive"]).resolve()
    expected = (scoring.ROOT / "data/research/L46_itf_delay").resolve()
    if archive.parent != expected or not archive.is_dir():
        raise ValueError("NOT_THE_FRESH_L46_ARCHIVE")
    if result.get("spec_sha256") != hashlib.sha256((source.HERE / "spec.yaml").read_bytes()).hexdigest():
        raise ValueError("L46_SPEC_HASH_MISMATCH")
    return archive


def main():
    if (HERE / "results.json").exists():
        raise SystemExit("Immutable L47 result exists")
    archive = verified_source_archive()  # no qualifying row is read until its source passes
    rows, counts, complete, error = {}, {"closed": 0, "open": 0}, False, None
    try:
        for closed in (True, False):
            for event in scoring.enumerate_events(OfflineOnly(), archive, closed=closed):
                counts["closed" if closed else "open"] += 1
                if not str(event.get("slug", "")).startswith("itf-"):
                    continue
                event_id = str(event["id"])
                row = scoring.classify(event, source_closed=closed, qualifying_population=True)
                if event_id in rows:
                    scoring.merge_transition(rows[event_id], row)
                else:
                    rows[event_id] = row
        complete = True
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    results = scoring.summarize(list(rows.values()), complete=complete, error=error)
    results.update(run=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), population="ITF qualifying singles",
                   tennis_events=counts, archive=str(archive), source=scoring.GAMMA, network_requests=0,
                   spec_sha256=hashlib.sha256((HERE / "spec.yaml").read_bytes()).hexdigest(), source_row="L46")
    source.atomic_json(archive / "L47_qualifying_rows.json", list(rows.values()))
    source.atomic_json(HERE / "results.json", results)
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0 if results["gates"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
