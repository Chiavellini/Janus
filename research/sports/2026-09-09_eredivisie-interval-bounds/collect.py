#!/usr/bin/env python3
"""L50 public archive, refusing to collect before the immutable original freeze."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
ROOT = Path('/Volumes/Kilos/janus/research/eredivisie-L50')
FROZEN_SHA = '10aaaf0b3b9fed76d21990887e72b8403dc79ea2e89327e94f5d6c3fb45ff647'
INVENTORY_URL = 'https://site.api.espn.com/apis/site/v2/sports/soccer/ned.1/scoreboard?dates=20250801-20260630&limit=1000'
INVENTORY_LABEL = 'inventory-default-agent'


def verify_freeze() -> None:
    if hashlib.sha256((HERE / 'original_bounds.json').read_bytes()).hexdigest() != FROZEN_SHA:
        raise ValueError('Original freeze missing/changed')


def archive(label: str, url: str) -> dict:
    verify_freeze()
    ROOT.mkdir(parents=True, exist_ok=True)
    if not label.replace('-', '').replace('_', '').isalnum():
        raise ValueError('Invalid label')
    path = ROOT / f'{label}.json'
    meta_path = ROOT / f'{label}.meta.json'
    if path.exists():
        if not meta_path.exists():
            raise ValueError(f'Incomplete prior archive: {label}')
        metadata = json.loads(meta_path.read_text())
        if metadata['url'] != url or metadata['sha256'] != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError('Prior archive integrity/URL mismatch')
        if metadata['status'] != 200:
            raise ValueError(f'Prior HTTP failure retained: {label}')
        return metadata
    started = datetime.now(timezone.utc).isoformat()
    try:
        response = urlopen(url, timeout=35)
    except HTTPError as exc:
        response = exc
    with response:
        raw = response.read()
        metadata = {'label': label, 'url': url, 'final_url': response.url,
                    'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
                    'status': response.status, 'bytes': len(raw),
                    'sha256': hashlib.sha256(raw).hexdigest(), 'path': str(path)}
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    with meta_path.open('x') as stream:
        json.dump(metadata, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    if metadata['status'] != 200:
        raise ValueError(f'HTTP failure retained: {metadata}')
    json.loads(raw)
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('inventory', 'summaries'))
    args = parser.parse_args()
    if args.mode == 'inventory':
        print(json.dumps(archive(INVENTORY_LABEL, INVENTORY_URL), sort_keys=True))
    else:
        metadata = archive(INVENTORY_LABEL, INVENTORY_URL)
        events = json.loads(Path(metadata['path']).read_text())['events']
        jobs = [(str(event['id']), f"https://site.api.espn.com/apis/site/v2/sports/soccer/ned.1/summary?event={event['id']}")
                for event in events]
        errors = []
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(archive, f'summary-{event_id}', url): event_id for event_id, url in jobs}
            for i, future in enumerate(as_completed(futures), 1):
                try:
                    future.result()
                except Exception as exc:
                    errors.append({'event_id': futures[future], 'error': str(exc)})
                if i % 25 == 0 or i == len(futures):
                    print(json.dumps({'completed_requests': i, 'expected_requests': len(futures), 'errors': errors}), flush=True)
        if errors:
            raise SystemExit(1)
