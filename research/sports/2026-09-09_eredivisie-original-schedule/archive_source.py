#!/usr/bin/env python3
"""Preserve one public L49 source without ever replacing earlier bytes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path('/Volumes/Kilos/janus/research/eredivisie-L49')


def archive(url: str, label: str) -> dict:
    if not label.replace('-', '').replace('_', '').isalnum():
        raise ValueError('Use a simple label')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    ROOT.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={'User-Agent': 'Janus-L49-research/1.0'})
    try:
        response = urlopen(request, timeout=35)
    except HTTPError as exc:
        response = exc
    with response:
        raw = response.read()
        meta = {'url': url, 'final_url': response.url, 'acquired_at': stamp,
                'status': response.status, 'content_type': response.headers.get('Content-Type'),
                'last_modified': response.headers.get('Last-Modified'),
                'etag': response.headers.get('ETag'), 'bytes': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest()}
    suffix = '.pdf' if raw.startswith(b'%PDF-') else '.html'
    path = ROOT / f'{label}-{stamp}{suffix}'
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    meta['path'] = str(path)
    with path.with_suffix('.meta.json').open('x') as stream:
        json.dump(meta, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    return meta


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label')
    parser.add_argument('url')
    args = parser.parse_args()
    print(json.dumps(archive(args.url, args.label), sort_keys=True))
