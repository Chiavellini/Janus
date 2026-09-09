#!/usr/bin/env python3
"""Pin and verify both raw bytes and request provenance; retain failed acquisitions."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOTS = (Path('/Volumes/Kilos/janus/research/eredivisie-L49'),
         Path('/Volumes/Kilos/janus/research/eredivisie-L50'))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict:
    sources = {}
    for root in ROOTS:
        for path in sorted(root.glob('*.meta.json')):
            metadata = json.loads(path.read_text())
            raw = Path(metadata['path'])
            if raw.parent != root or not metadata['url'].startswith('https://'):
                raise ValueError(f'Unexpected source path/URL: {path}')
            if digest(raw) != metadata['sha256'] or raw.stat().st_size != metadata['bytes']:
                raise ValueError(f'Acquisition integrity failed: {raw}')
            label = metadata.get('label') or re.sub(r'-\d{8}T\d{12}Z$', '', raw.stem)
            if label in sources:
                raise ValueError(f'Duplicate source label: {label}')
            sources[label] = {**metadata, 'metadata_path': str(path), 'metadata_sha256': digest(path)}
    return {'id': 'L50', 'sources': sources,
            'preserved_failures': [label for label, item in sources.items() if item['status'] != 200],
            'spec_sha256': digest(HERE / 'spec.yaml'),
            'original_bounds_sha256': digest(HERE / 'original_bounds.json'),
            'initial_results_sha256': digest(HERE / 'results.json'),
            'official_review_sha256': digest(HERE / 'official_review.json')}


def verify(manifest: dict) -> None:
    for label, item in manifest['sources'].items():
        if digest(Path(item['path'])) != item['sha256']:
            raise ValueError(f'Raw hash changed: {label}')
        if digest(Path(item['metadata_path'])) != item['metadata_sha256']:
            raise ValueError(f'Request metadata hash changed: {label}')
        metadata = json.loads(Path(item['metadata_path']).read_text())
        if any(metadata[key] != value for key, value in item.items()
               if key not in ('metadata_path', 'metadata_sha256')):
            raise ValueError(f'Request metadata disagrees: {label}')
    for name, key in [('spec.yaml', 'spec_sha256'), ('original_bounds.json', 'original_bounds_sha256'),
                      ('results.json', 'initial_results_sha256'), ('official_review.json', 'official_review_sha256')]:
        if digest(HERE / name) != manifest[key]:
            raise ValueError(f'Pinned research artifact changed: {name}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output:
        result = build()
        with args.output.open('x') as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write('\n')
        print(digest(args.output))
    else:
        result = json.loads((HERE / 'source_manifest.json').read_text())
        verify(result)
        print(json.dumps({'sources_verified': len(result['sources']), 'preserved_failures': result['preserved_failures']}))
