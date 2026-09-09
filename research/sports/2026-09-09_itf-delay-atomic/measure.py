#!/usr/bin/env python3
"""L46: fresh exhaustive ITF catalog; final page names can only contain durable complete JSON."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("l46_scoring", HERE.parent / "2026-09-09_itf-settlement-delay-keyset/measure.py")
scoring = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scoring)


def atomic_json(path, value, *, compressed=False):
    """Write/fsync a unique temporary file, rename only after complete, then fsync its directory.

    This fresh archive has a single writer. Existing final paths refuse; a failed write leaves
    only a uniquely named .pending artifact for diagnosis, never a partial final JSON page.
    """
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    raw = json.dumps(value, ensure_ascii=False, indent=None if compressed else 2,
                     separators=(",", ":") if compressed else None).encode()
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".pending", dir=path.parent)
    with os.fdopen(fd, "wb") as fh:
        if compressed:
            with gzip.GzipFile(fileobj=fh, mode="wb", compresslevel=1, mtime=0) as packed:
                packed.write(raw)
        else:
            fh.write(raw + b"\n")
        fh.flush()
        os.fsync(fh.fileno())
    if path.exists():
        raise FileExistsError(path)
    os.rename(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def enumerate_events(client, archive, *, closed, limit=500):
    seen_ids, seen_cursors = set(), set()
    cursor, page_no = None, 0
    while True:
        params = {"tag_slug": "tennis", "closed": "true" if closed else "false", "limit": limit,
                  "order": "id", "ascending": "true"}
        if cursor:
            params["after_cursor"] = cursor
        response = client.get_json(scoring.GAMMA, params=params, use_cache=False)
        if not isinstance(response, dict) or not isinstance(response.get("events"), list):
            raise ValueError("INVALID_KEYSET_RESPONSE")
        raw = json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode()
        envelope = {"url": scoring.GAMMA, "params": params, "sha256": hashlib.sha256(raw).hexdigest(),
                    "response": response}
        path = archive / f"{'closed' if closed else 'open'}_{page_no:06d}.json.gz"
        atomic_json(path, envelope, compressed=True)
        page = response["events"]
        print(json.dumps({"closed": closed, "page": page_no, "rows": len(page), "unique_before_page": len(seen_ids)}), flush=True)
        for event in page:
            raw_id = event.get("id")
            if isinstance(raw_id, bool) or not isinstance(raw_id, (str, int)) or str(raw_id).strip() == "":
                raise ValueError("MISSING_OR_INVALID_ID")
            event_id = str(raw_id)
            if event_id in seen_ids:
                raise ValueError(f"DUPLICATED_ID:{event_id}")
            seen_ids.add(event_id)
            yield event
        next_cursor = response.get("next_cursor")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise ValueError("INVALID_OR_LOOPING_CURSOR")
        if not page or not next_cursor:
            return
        if not isinstance(next_cursor, str) or next_cursor in seen_cursors:
            raise ValueError("INVALID_OR_LOOPING_CURSOR")
        seen_cursors.add(next_cursor)
        cursor, page_no = next_cursor, page_no + 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-root", type=Path, default=scoring.ROOT / "data/research/L46_itf_delay")
    args = parser.parse_args()
    if (HERE / "results.json").exists():
        raise SystemExit("Immutable result exists; no rerun or overwrite")
    run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = args.archive_root.resolve() / run
    archive.mkdir(parents=True, exist_ok=False)
    client = scoring.Client("l46-itf-delay", rate=2, burst=2)
    rows, counts, complete, error = {}, {"closed": 0, "open": 0}, False, None
    try:
        for closed in (True, False):
            for event in enumerate_events(client, archive, closed=closed):
                counts["closed" if closed else "open"] += 1
                if not str(event.get("slug", "")).startswith("itf-"):
                    continue
                event_id = str(event["id"])
                row = scoring.classify(event, source_closed=closed)
                if event_id in rows:
                    scoring.merge_transition(rows[event_id], row)
                else:
                    rows[event_id] = row
        complete = True
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    results = scoring.summarize(list(rows.values()), complete=complete, error=error)
    results.update(run=run, tennis_events=counts, archive=str(archive), source=scoring.GAMMA,
                   fresh_archive=True, http_stats=client.stats,
                   spec_sha256=hashlib.sha256((HERE / "spec.yaml").read_bytes()).hexdigest())
    atomic_json(archive / "rows.json", list(rows.values()))
    atomic_json(HERE / "results.json", results)
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0 if results["gates"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
