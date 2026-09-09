#!/usr/bin/env python3
"""Materialize the stopped L49 result/manifest, with no outcomes or rate estimates."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path('/Volumes/Kilos/janus/research/eredivisie-L49')


def preserve(path: Path, value: dict) -> None:
    data = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + '\n'
    if path.exists():
        if path.read_text() != data:
            raise ValueError(f'Refuse changed prior artifact: {path}')
        return
    with path.open('x') as stream:
        stream.write(data)


if __name__ == '__main__':
    audit_bytes = (HERE / 'original_audit.json').read_bytes()
    audit = json.loads(audit_bytes)
    if audit['verdict'] != 'BLOCKED_ORIGINAL_LINEAGE' or audit['outcome_distribution_scored']:
        raise ValueError('Not the stopped L49 audit')
    preserve(HERE / 'results.json', {**{key: value for key, value in audit.items() if key != 'rows'},
                                    'row_artifact': 'original_audit.json',
                                    'row_artifact_sha256': hashlib.sha256(audit_bytes).hexdigest()})
    sources = []
    for path in sorted(ROOT.glob('*.meta.json')):
        meta = json.loads(path.read_text())
        if hashlib.sha256(Path(meta['path']).read_bytes()).hexdigest() != meta['sha256']:
            raise ValueError('L49 raw integrity failed')
        sources.append({**meta, 'metadata_path': str(path),
                        'metadata_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    preserve(HERE / 'source_manifest.json', {'id': 'L49', 'sources': sources,
             'spec_sha256': hashlib.sha256((HERE / 'spec.yaml').read_bytes()).hexdigest(),
             'original_audit_sha256': hashlib.sha256(audit_bytes).hexdigest()})
    print(json.dumps({'verdict': audit['verdict'], 'official_sources': len(sources),
                      'outcomes_scored': False, 'registered_rates': {}}))
