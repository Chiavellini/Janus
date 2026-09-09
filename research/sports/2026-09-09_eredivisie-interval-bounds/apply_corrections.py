#!/usr/bin/env python3
"""Append-only correction of the frozen table; only strictly earlier official dates."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
FROZEN_SHA = '10aaaf0b3b9fed76d21990887e72b8403dc79ea2e89327e94f5d6c3fb45ff647'


def corrected_bounds(frozen: dict, corrections: dict, sources: dict) -> dict:
    output = json.loads(json.dumps(frozen))
    rows = {(r['home'], r['away']): r for r in output['rows']}
    seen = set()
    for correction in corrections['corrections']:
        key = correction['home'], correction['away']
        if key in seen or key not in rows:
            raise ValueError('Unknown/duplicate correction key')
        seen.add(key)
        row = rows[key]
        if (row['earliest_original_date'] != correction['old_lower_date']
                or row['round'] != correction['round']
                or correction['new_lower_date'] >= correction['old_lower_date']
                or correction['scheduled'][:10] != correction['new_lower_date']
                or correction['published'] >= correction['new_lower_date']):
            raise ValueError('Correction must strictly lower an audited original with a pre-match source')
        source = sources['sources'][correction['source_label']]
        if (source['url'] != correction['source_url'] or source['sha256'] != correction['source_sha256']
                or source['status'] != 200):
            raise ValueError('Correction source identity/integrity failed')
        row['earliest_original_date'] = correction['new_lower_date']
        row['candidate_calendar_dates'] = sorted(set(row['candidate_calendar_dates']) | {correction['new_lower_date']})
        row['post_freeze_corrections'] = [correction]
    output['frozen_original_sha256'] = FROZEN_SHA
    output['later_official_corrections_after_initial_outcomes'] = True
    return output


def build() -> dict:
    raw = (HERE / 'original_bounds.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != FROZEN_SHA:
        raise ValueError('Frozen original changed')
    corrections_raw = (HERE / 'original_bounds_corrections.json').read_bytes()
    corrections = json.loads(corrections_raw)
    if corrections['frozen_original_sha256'] != FROZEN_SHA:
        raise ValueError('Wrong correction parent')
    import manifest
    sources = json.loads((HERE / 'source_manifest.json').read_text())
    manifest.verify(sources)
    output = corrected_bounds(json.loads(raw), corrections, sources)
    output['corrections_sha256'] = hashlib.sha256(corrections_raw).hexdigest()
    return output


def corrected_review() -> dict:
    review = json.loads((HERE / 'official_review.json').read_text())
    corrections = json.loads((HERE / 'original_bounds_corrections.json').read_text())
    for correction in corrections['corrections']:
        matches = [row for row in review['events'].values()
                   if (row['home'], row['away']) == (correction['home'], correction['away'])]
        if len(matches) != 1 or matches[0]['original_lower_date'] != correction['old_lower_date']:
            raise ValueError('Review correction identity mismatch')
        row = matches[0]
        row['initial_original_lower_date'] = row['original_lower_date']
        row['original_lower_date'] = correction['new_lower_date']
        row['initial_note'] = row['note']
        row['note'] = correction['note']
    review['initial_review_sha256'] = hashlib.sha256((HERE / 'official_review.json').read_bytes()).hexdigest()
    review['corrections_sha256'] = hashlib.sha256((HERE / 'original_bounds_corrections.json').read_bytes()).hexdigest()
    return review


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--review', action='store_true')
    args = parser.parse_args()
    output = json.dumps(corrected_review() if args.review else build(), indent=2, ensure_ascii=False, sort_keys=True) + '\n'
    if args.output:
        with args.output.open('x') as stream:
            stream.write(output)
        print(hashlib.sha256(output.encode()).hexdigest())
    else:
        print(output, end='')
