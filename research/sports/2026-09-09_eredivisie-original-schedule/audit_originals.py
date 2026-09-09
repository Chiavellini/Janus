#!/usr/bin/env python3
"""L49 stage-one source audit. This module never requests final outcomes.

It inventories official schedule rows and preserves all original alternatives.
No probability can be emitted by this program. The results are source completeness
diagnostics, not settlement outcomes or a measured rate.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = Path('/Volumes/Kilos/janus/research/eredivisie-L49')
SPEC_SHA256 = '7d7308fdd6884fbc3c7cb4bbc583f4b15ec601ac07485034a873249c4cdb473e'
SOURCES = (
    ('definitive-20260909T083844312697Z.pdf', '2025-06-24', 'definitive'),
    ('autumn-20260909T083844427667Z.pdf', '2025-09-10', 'autumn'),
    ('spring-20260909T083844358435Z.pdf', '2025-12-23', 'spring'),
)
MONTHS = {name: i for i, name in enumerate(
    ('januari februari maart april mei juni juli augustus september oktober november december').split(), 1)}
TEAM_NAMES = frozenset((
    'Ajax', 'AZ', 'Excelsior Rotterdam', 'FC Groningen', 'FC Twente', 'FC Utrecht',
    'FC Volendam', 'Feyenoord', 'Fortuna Sittard', 'Go Ahead Eagles', 'Heracles Almelo',
    'NAC Breda', 'N.E.C.', 'PEC Zwolle', 'PSV', 'sc Heerenveen', 'Sparta Rotterdam', 'Telstar',
))


def parse_schedule(text: str, source: str, published: str) -> list[dict]:
    if "seizoen 2025/'26" not in text:
        raise ValueError('Wrong/missing official season label')
    rows = []
    for page_no, page in enumerate(text.split('\f'), 1):
        for line_no, line in enumerate(page.splitlines(), 1):
            if not re.match(r'^\s*\d{1,2}\s{2,}', line):
                continue
            columns = re.split(r'\s{2,}', line.strip())
            if len(columns) < 4:
                raise ValueError(f'{source}: malformed fixture row {line!r}')
            round_no = int(columns[0])
            if not 1 <= round_no <= 34:
                raise ValueError(f'{source}: unknown round {round_no}')
            date_text, home, away = columns[1:4]
            if home not in TEAM_NAMES or away not in TEAM_NAMES or home == away:
                raise ValueError(f'{source}: unknown/invalid team: {home!r}, {away!r}')
            time_text = ' '.join(columns[4:])
            exact = re.fullmatch(r'(\w+) (\d{1,2}) (\w+) (2025|2026)', date_text)
            clock = re.match(r'^(\d{2}):(\d{2})(?:\s|$)', time_text)
            scheduled = None
            if exact and clock:
                weekday, day, month, year = exact.groups()
                scheduled = datetime(int(year), MONTHS[month], int(day),
                                     int(clock[1]), int(clock[2]),
                                     tzinfo=ZoneInfo('Europe/Amsterdam')).isoformat()
            rows.append({'round': round_no, 'home': home, 'away': away,
                         'date_text': date_text, 'time_text': time_text,
                         'scheduled': scheduled, 'conditional': '*' in time_text,
                         'source': source, 'published': published,
                         'pdf_page': page_no, 'text_line': line_no})
    if not rows:
        raise ValueError(f'{source}: no fixture rows')
    return rows


def audit(populations: list[list[dict]]) -> dict:
    originals = populations[0]
    grouped = defaultdict(list)
    for row in originals:
        grouped[(row['home'], row['away'])].append(row)
    keys = set(grouped)
    expected_keys = {(home, away) for home in TEAM_NAMES for away in TEAM_NAMES if home != away}
    if keys != expected_keys:
        raise ValueError(f'Original identity population incomplete: {len(keys)}/306')
    counts = Counter(team for key in keys for team in key)
    if set(counts.values()) != {34}:
        raise ValueError('Wrong original per-club counts')
    all_rows = defaultdict(list)
    for population in populations:
        for row in population:
            if (row['home'], row['away']) not in expected_keys:
                raise ValueError('Unknown fixture in update')
            all_rows[(row['home'], row['away'])].append(row)
    result_rows = []
    for key in sorted(keys):
        initial = grouped[key]
        history = all_rows[key]
        # A date window is not a confirmed kickoff. The first publication giving
        # any precise kickoff remains the timing candidate, including its caveats.
        candidate_publication = next(
            (r['published'] for r in history if r['scheduled'] is not None), None)
        candidates = [r for r in history if r['published'] == candidate_publication]
        reasons = []
        if not candidates:
            reasons.append('NO_FIXTURE_SPECIFIC_KICKOFF')
        elif len(candidates) != 1:
            reasons.append('MULTIPLE_CONDITIONAL_ORIGINALS')
        elif candidates[0]['conditional']:
            reasons.append('CONDITIONAL_ORIGINAL_REQUIRES_DATED_DECISION')
        candidate = candidates[0] if len(candidates) == 1 else None
        if candidate and candidate['scheduled'] and candidate['published'] >= candidate['scheduled'][:10]:
            reasons.append('ORIGINAL_NOT_PUBLISHED_BEFORE_FIXTURE')
        result_rows.append({'home': key[0], 'away': key[1], 'round': initial[0]['round'],
                            'status': 'BLOCKED' if reasons else 'PRECISE_ORIGINAL_CANDIDATE',
                            'reasons': reasons, 'candidates': candidates, 'history': history})
    blocked = [r for r in result_rows if r['reasons']]
    return {
        'id': 'L49', 'stage': 'original_schedule_only',
        'verdict': 'BLOCKED_ORIGINAL_LINEAGE' if blocked else 'AWAITING_INDEPENDENT_ORIGINAL_REVIEW',
        'source_rows': {p[0]['source']: len(p) for p in populations},
        'original_unique_fixtures': len(keys), 'original_raw_fixture_rows': len(originals),
        'clubs': len(counts), 'matches_per_club': dict(sorted(counts.items())),
        'duplicate_original_fixture_keys': [list(k) for k, rows in sorted(grouped.items()) if len(rows) > 1],
        'first_precise_publication': dict(sorted(Counter(
            r['candidates'][0]['source'] for r in result_rows if r['candidates']).items())),
        'precise_unconditional_candidates': len(result_rows) - len(blocked),
        'fixtures_requiring_original_decision_review': len(blocked),
        'blocker_counts': dict(sorted(Counter(reason for r in blocked for reason in r['reasons']).items())),
        'final_inventory_requested': False, 'outcome_distribution_scored': False,
        'registered_evidence_keys': [], 'rows': result_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='New immutable output file; default stdout')
    args = parser.parse_args()
    if hashlib.sha256((HERE / 'spec.yaml').read_bytes()).hexdigest() != SPEC_SHA256:
        raise ValueError('Immutable L49 spec changed')
    populations = []
    for name, published, label in SOURCES:
        path = ROOT / name
        metadata = json.loads(path.with_suffix('.meta.json').read_text())
        if metadata['status'] != 200 or hashlib.sha256(path.read_bytes()).hexdigest() != metadata['sha256']:
            raise ValueError(f'Archived source failed integrity: {name}')
        text = subprocess.run(['pdftotext', '-layout', str(path), '-'],
                              check=True, text=True, capture_output=True).stdout
        populations.append(parse_schedule(text, label, published))
    result = audit(populations)
    content = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + '\n'
    if args.output:
        with args.output.open('x') as stream:
            stream.write(content)
        print(json.dumps({key: value for key, value in result.items() if key != 'rows'}, sort_keys=True))
    else:
        print(content, end='')


if __name__ == '__main__':
    main()
