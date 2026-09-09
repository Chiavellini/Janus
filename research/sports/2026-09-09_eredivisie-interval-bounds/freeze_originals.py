#!/usr/bin/env python3
"""Freeze L50 bounds from L49's hash-verified source audit, before outcomes."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
L49 = HERE.parent / '2026-09-09_eredivisie-original-schedule'
SPEC_SHA = '5288d1d4cd0d136977e001d527c918eaa278269814836dbe10fb05d71cad01f6'


def build() -> dict:
    if hashlib.sha256((HERE / 'spec.yaml').read_bytes()).hexdigest() != SPEC_SHA:
        raise ValueError('Immutable L50 spec changed')
    replay = subprocess.run(['python3', str(L49 / 'audit_originals.py')],
                            check=True, capture_output=True, text=True).stdout
    source_audit = json.loads(replay)
    recorded = json.loads((L49 / 'original_audit.json').read_text())
    if source_audit != recorded:
        raise ValueError('L49 offline source audit differs from preserved result')
    rows = []
    for row in source_audit['rows']:
        all_specific = [r for r in row['history'] if r['scheduled']]
        if not all_specific:
            raise ValueError('No fixture-specific original')
        if any(r['published'] >= r['scheduled'][:10] for r in all_specific):
            raise ValueError('Original source contains a post-match publication')
        dates = {r['scheduled'][:10] for r in all_specific}
        footnotes = []
        # Explicit earlier alternatives not necessarily emitted as table rows.
        if (row['home'], row['away']) == ('Heracles Almelo', 'Sparta Rotterdam'):
            dates.add('2025-09-27')
            footnotes.append('June R7: conditional Saturday Sep 27, time not yet specified')
        if (row['home'], row['away']) == ('AZ', 'FC Twente'):
            dates.add('2026-05-02')
            footnotes.append('Spring R32 ***: conditional Saturday May 2 at 21:00')
        # All other explicit calendar alternatives are either duplicate source
        # rows or later than the earliest retained date. Unknown same-day clocks
        # cannot precede midnight. Generic future-reschedule notices do not erase
        # their published baseline; eventual changes are measured against it.
        date = min(dates)
        rows.append({'home': row['home'], 'away': row['away'], 'round': row['round'],
                     'earliest_original_date': date, 'timezone': 'Europe/Amsterdam',
                     'earliest_original_local_clock': '00:00:00',
                     'conditional_first_publication': bool(row['reasons']),
                     'unbounded_earlier_alternative': False,
                     'candidate_calendar_dates': sorted(dates),
                     'footnote_alternatives': footnotes,
                     'source_history': row['history']})
    if len(rows) != 306:
        raise ValueError('Incomplete freeze')
    return {'id': 'L50', 'spec_sha256': SPEC_SHA, 'source_study': 'L49',
            'source_audit_sha256': hashlib.sha256((L49 / 'original_audit.json').read_bytes()).hexdigest(),
            'final_outcomes_read_before_freeze': False, 'rows': rows}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    data = json.dumps(build(), indent=2, ensure_ascii=False, sort_keys=True) + '\n'
    if args.output:
        with args.output.open('x') as stream:
            stream.write(data)
        print(hashlib.sha256(data.encode()).hexdigest())
    else:
        print(data, end='')
