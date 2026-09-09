#!/usr/bin/env python3
"""Register only the complete, reviewed, independently reproduced corrected population."""
from __future__ import annotations
import json
import math
from pathlib import Path

import manifest
import measure
import review

HERE = Path(__file__).resolve().parent


def registered_result(result: dict, replay: dict) -> dict:
    if (not result['official_review_passed'] or replay['verdict'] != 'PASS'
            or not replay['independent_implementation'] or replay['author_measurement_imported']
            or any(not replay[field] for field in ('full_initial_rows_reproduced',
                'full_frozen_source_histories_reproduced', 'full_corrected_original_rows_reproduced',
                'full_corrected_final_rows_reproduced'))
            or replay['corrected_rows'] != result['rows']
            or replay['counts'] != result['provisional_counts']):
        raise ValueError('Independent full-population replay gate failed')
    for key, value in result['provisional_upper95'].items():
        if not math.isclose(value, replay['upper95'][key], rel_tol=0, abs_tol=2e-14):
            raise ValueError('Independent confidence bound mismatch')
    output = json.loads(json.dumps(result))
    output.update({'verdict': 'REGISTERED', 'independent_replay_passed': True,
                   'registered_rates': {f'soccer.ere.{key}': value for key, value in result['provisional_upper95'].items()},
                   'research_population': 'ESPN ned.1 Eredivisie 2025/26 regular-season only',
                   'original_correction': 'original_bounds_corrections.json; initial frozen artifacts unchanged'})
    return output


def preserve(path: Path, content: dict) -> None:
    encoded = json.dumps(content, indent=2, sort_keys=True) + '\n'
    if path.exists():
        if path.read_text() != encoded:
            raise ValueError(f'Refuse to replace a prior registered artifact: {path}')
        return
    with path.open('x') as stream:
        stream.write(encoded)


if __name__ == '__main__':
    pinned = json.loads((HERE / 'source_manifest.json').read_text())
    manifest.verify(pinned)
    replay = json.loads((HERE / 'independent_replay.json').read_text())
    if (replay['source_manifest_sha256'] != manifest.digest(HERE / 'source_manifest.json')
            or replay['replay_code_sha256'] != manifest.digest(HERE / 'independent_replay.py')):
        raise ValueError('Independent replay code/source lineage changed')
    for name, sha in replay['corrected_artifact_hashes'].items():
        if manifest.digest(HERE / name) != sha:
            raise ValueError(f'Corrected artifact changed since replay: {name}')
    result = measure.measure(corrected=True)
    if result != json.loads((HERE / 'results_corrected.json').read_text()):
        raise ValueError('Corrected measurement failed reproduction')
    reviewed = review.review_result(result, json.loads((HERE / 'official_review_corrected.json').read_text()), pinned)
    registered = registered_result(reviewed, replay)
    registered['independent_replay_sha256'] = manifest.digest(HERE / 'independent_replay.json')
    registered['source_manifest_sha256'] = manifest.digest(HERE / 'source_manifest.json')
    preserve(HERE / 'results_registered.json', registered)
    names = ['spec.yaml', 'source_review.md', 'original_bounds.json', 'original_bounds_corrections.json',
             'original_bounds_corrected.json', 'official_review.json', 'official_review_corrected.json',
             'results.json', 'results_corrected.json', 'results_registered.json',
             'source_manifest.json', 'independent_replay.py', 'independent_replay.json',
             'freeze_originals.py', 'apply_corrections.py', 'measure.py', 'review.py', 'manifest.py', 'register.py']
    preserve(HERE / 'source_manifest_registered.json', {'id': 'L50', 'verdict': 'REGISTERED',
             'sources': pinned['sources'], 'preserved_failures': pinned['preserved_failures'],
             'artifact_sha256': {name: manifest.digest(HERE / name) for name in names}})
    print(json.dumps({key: value for key, value in registered.items() if key != 'rows'}, indent=2, sort_keys=True))
