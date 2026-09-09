#!/usr/bin/env python3
"""Independent offline corrected-code replay; never overwrite the collector's immutable result."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("l46_replay_source", HERE / "measure.py")
source = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(source)
scoring = source.scoring


class OfflineOnly:
    def get_json(self, *args, **kwargs):
        raise ValueError("ARCHIVE_INCOMPLETE_NETWORK_FORBIDDEN")


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def main():
    path = HERE / "results.json"
    original_bytes = path.read_bytes()
    original = json.loads(original_bytes)
    archive = Path(original["archive"]).resolve()
    if archive.parent != (scoring.ROOT / "data/research/L46_itf_delay").resolve():
        raise ValueError("NOT_THE_FRESH_L46_ARCHIVE")
    rows, counts = {}, {"closed": 0, "open": 0}
    for closed in (True, False):
        for event in scoring.enumerate_events(OfflineOnly(), archive, closed=closed):
            counts["closed" if closed else "open"] += 1
            if not str(event.get("slug", "")).startswith("itf-"):
                continue
            event_id = str(event["id"])
            row = scoring.classify(event, source_closed=closed)
            if event_id in rows:
                scoring.merge_transition(rows[event_id], row)
            else:
                rows[event_id] = row
    result = scoring.summarize(list(rows.values()), complete=True, error=None)
    result.update(run=original["run"], tennis_events=counts, archive=str(archive), source=scoring.GAMMA,
                  fresh_archive=True, http_stats=original["http_stats"],
                  spec_sha256=hashlib.sha256((HERE / "spec.yaml").read_bytes()).hexdigest())
    replay_bytes = encoded(result)
    rows_bytes = (archive / "rows.json").read_bytes()
    replay_rows = encoded(list(rows.values()))
    # These compare actual serialized bytes, not rounded numerical fields or selected totals.
    result_identical = original_bytes == replay_bytes
    rows_identical = rows_bytes == replay_rows
    manifest = [(p.name, hashlib.sha256(p.read_bytes()).hexdigest())
                for p in sorted(archive.glob("*.json.gz"))]
    verification = {
        "status": "PASS" if result_identical and rows_identical and result["gates"] == "PASS" else "FAIL",
        "results_byte_identical": result_identical, "rows_byte_identical": rows_identical,
        "original_results_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "replayed_results_sha256": hashlib.sha256(replay_bytes).hexdigest(),
        "original_rows_sha256": hashlib.sha256(rows_bytes).hexdigest(),
        "replayed_rows_sha256": hashlib.sha256(replay_rows).hexdigest(),
        "archive_manifest_sha256": hashlib.sha256(encoded(manifest)).hexdigest(),
        "raw_page_count": len(manifest), "network_requests": 0, "tennis_events": counts,
        "scorer_sha256": hashlib.sha256(Path(scoring.__file__).read_bytes()).hexdigest(),
        "correction": "Total authoritative-close absence fails even if all candidates are actually open.",
    }
    source.atomic_json(HERE / "verification.json", verification)
    print(json.dumps(verification, indent=2))
    return 0 if verification["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
