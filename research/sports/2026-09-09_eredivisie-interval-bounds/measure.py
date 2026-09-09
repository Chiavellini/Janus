#!/usr/bin/env python3
"""L50 offline authoritative-completion join; no network and no auto-registration."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = Path('/Volumes/Kilos/janus/research/eredivisie-L50')
FROZEN_SHA = '10aaaf0b3b9fed76d21990887e72b8403dc79ea2e89327e94f5d6c3fb45ff647'
CORRECTED_SHA = '9ff4c668218a56ab8fb8a72d32459e6f7db78fc1700cc38b0258800cb2c62970'
AMSTERDAM = ZoneInfo('Europe/Amsterdam')
TEAM_IDS = {'Ajax': '139', 'AZ': '140', 'NAC Breda': '141', 'Feyenoord': '142',
            'Fortuna Sittard': '143', 'FC Groningen': '145', 'sc Heerenveen': '146',
            'N.E.C.': '147', 'PSV': '148', 'Sparta Rotterdam': '151', 'FC Twente': '152',
            'FC Utrecht': '153', 'PEC Zwolle': '2565', 'Excelsior Rotterdam': '2566',
            'FC Volendam': '2727', 'Go Ahead Eagles': '3706', 'Heracles Almelo': '3708',
            'Telstar': '3735'}


def raw(label: str) -> dict:
    path = ROOT / f'{label}.json'
    data = path.read_bytes()
    meta = json.loads(path.with_suffix('.meta.json').read_text())
    if meta['status'] != 200 or hashlib.sha256(data).hexdigest() != meta['sha256']:
        raise ValueError(f'Archive integrity/HTTP failure: {label}')
    expected_url = ('https://site.api.espn.com/apis/site/v2/sports/soccer/ned.1/summary?event=' + label.removeprefix('summary-')
                    if label.startswith('summary-') else
                    'https://site.api.espn.com/apis/site/v2/sports/soccer/ned.1/scoreboard?dates=20250801-20260630&limit=1000')
    if meta['url'] != expected_url:
        raise ValueError(f'Wrong source URL: {label}')
    return json.loads(data)


def ids(competition: dict) -> tuple[str, str]:
    competitors = competition['competitors']
    if len(competitors) != 2:
        raise ValueError('Wrong competitor cardinality')
    mapping = {c['homeAway']: str(c['team']['id']) for c in competitors}
    if set(mapping) != {'home', 'away'} or mapping['home'] == mapping['away']:
        raise ValueError('Unknown/duplicate competitor side')
    return mapping['home'], mapping['away']


def final_whistle(summary: dict, event_id: str, expected_ids: tuple[str, str]) -> tuple[datetime, datetime]:
    header = summary['header']
    if str(header['id']) != event_id or header['league']['slug'] != 'ned.1':
        raise ValueError('Wrong event/league summary')
    if header['season']['year'] != 2025 or header['season']['type'] != 13484:
        raise ValueError('Wrong regular-season population in summary')
    competitions = header['competitions']
    if len(competitions) != 1 or ids(competitions[0]) != expected_ids:
        raise ValueError('Wrong summary competitors')
    comp = competitions[0]
    if not comp['status']['type']['completed']:
        raise ValueError('Nonterminal fixture needs authoritative disposition')
    endings = [p for p in summary.get('keyEvents', [])
               if p.get('type', {}).get('type') == 'end-regular-time'
               and p.get('period', {}).get('number') == 2 and p.get('wallclock')]
    if len(endings) != 1:
        raise ValueError(f'Expected exactly one second-half final whistle; found {len(endings)}')
    finished = datetime.fromisoformat(endings[0]['wallclock'].replace('Z', '+00:00'))
    started = datetime.fromisoformat(comp['date'].replace('Z', '+00:00'))
    if not finished.tzinfo or not started.tzinfo or finished <= started:
        raise ValueError('Invalid final-whistle chronology')
    return started, finished


def upper95(k: int, n: int) -> float:
    if not 0 <= k <= n or n <= 0:
        raise ValueError('Invalid binomial counts')
    if k == n:
        return 1.0
    if k == 0:
        return -math.expm1(math.log(0.05) / n)
    lo, hi = k / n, 1.0
    coefficients = [math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
                    for i in range(k + 1)]
    for _ in range(80):
        p = (lo + hi) / 2
        cdf = sum(math.exp(c + i * math.log(p) + (n - i) * math.log1p(-p))
                  for i, c in enumerate(coefficients))
        if cdf > 0.05:
            lo = p
        else:
            hi = p
    return hi


def regular_season(event: dict) -> bool:
    """Unknown phases cannot masquerade as either regular season or a safe exclusion."""
    season = event['season']
    known = {'regular-season': 13484,
             'conference-league-playoffs---semifinals': 13483,
             'conference-league-playoffs---final': 13482}
    if (season['year'] != 2025 or season['slug'] not in known
            or season['type'] != known[season['slug']]):
        raise ValueError('Unexpected season/phase in final inventory')
    return season['slug'] == 'regular-season'


def completion_delayed(lower: datetime, finished: datetime, *, unbounded: bool = False) -> bool:
    if lower.utcoffset() is None or finished.utcoffset() is None:
        raise ValueError('Naive clock cannot bound the deadline')
    return unbounded or (finished.astimezone(timezone.utc) - lower.astimezone(timezone.utc)).total_seconds() > 48 * 3600


def measure(*, corrected: bool = False) -> dict:
    frozen_data = (HERE / ('original_bounds_corrected.json' if corrected else 'original_bounds.json')).read_bytes()
    if hashlib.sha256(frozen_data).hexdigest() != (CORRECTED_SHA if corrected else FROZEN_SHA):
        raise ValueError('Original freeze changed')
    originals = json.loads(frozen_data)['rows']
    expected = {(TEAM_IDS[r['home']], TEAM_IDS[r['away']]): r for r in originals}
    if len(expected) != 306:
        raise ValueError('Original identity gate failed')
    inventory = raw('inventory-default-agent')['events']
    excluded = []
    final = {}
    for event in inventory:
        if not regular_season(event):
            excluded.append({'id': str(event['id']), 'season': event['season']})
            continue
        competitions = event['competitions']
        if len(competitions) != 1:
            raise ValueError('Ambiguous competition')
        key = ids(competitions[0])
        if key in final:
            raise ValueError(f'Duplicate regular-season fixture {key}')
        final[key] = event
    if set(final) != set(expected):
        raise ValueError(f'Final inventory mismatch: missing={set(expected)-set(final)}, extra={set(final)-set(expected)}')
    initial_rows = ({r['event_id']: r for r in json.loads((HERE / 'results.json').read_text())['rows']}
                    if corrected else {})
    rows, failures = [], []
    for key, original in sorted(expected.items()):
        event = final[key]
        event_id = str(event['id'])
        lower = datetime.fromisoformat(original['earliest_original_date']).replace(tzinfo=AMSTERDAM)
        row = {'event_id': event_id, 'home': original['home'], 'away': original['away'],
               'home_id': key[0], 'away_id': key[1], 'round': original['round'],
               'original_lower_bound': lower.isoformat(),
               'unbounded_earlier_alternative': original['unbounded_earlier_alternative']}
        try:
            started, finished = final_whistle(raw(f'summary-{event_id}'), event_id, key)
            if datetime.fromisoformat(event['date'].replace('Z', '+00:00')) != started:
                raise ValueError('Inventory/summary start disagreement')
            delay_hours = (finished.astimezone(timezone.utc) - lower.astimezone(timezone.utc)).total_seconds() / 3600
            row.update({'actual_start': started.isoformat(), 'actual_completion': finished.isoformat(),
                        'completion_hours_after_lower_bound': delay_hours,
                        'delay_adverse': completion_delayed(lower, finished, unbounded=original['unbounded_earlier_alternative']),
                        'cancelled': False,
                        'kickoff_date_changed': started.astimezone(AMSTERDAM).date() != lower.date(),
                        'completion_date_changed': finished.astimezone(AMSTERDAM).date() != lower.date(),
                        'review_required': (started.astimezone(AMSTERDAM).date() != lower.date()
                                            or finished.astimezone(AMSTERDAM).date() != lower.date())})
        except (OSError, ValueError, KeyError) as exc:
            row['failure'] = str(exc)
            failures.append({'event_id': event_id, 'reason': str(exc)})
        if corrected:
            initial = initial_rows[event_id]
            row['initial_review_required'] = initial['review_required']
            if 'post_freeze_corrections' in original:
                row['post_freeze_original_corrections'] = original['post_freeze_corrections']
            if initial.get('delay_adverse') and not row.get('delay_adverse'):
                raise ValueError('Correction may not reduce an adverse observation')
        rows.append(row)
    delays = sum(r.get('delay_adverse', False) for r in rows)
    return {'id': 'L50', 'verdict': 'BLOCKED_INCOMPLETE_COMPLETIONS' if failures else 'BLOCKED_PENDING_OFFICIAL_EXCEPTION_REVIEW',
            'original_fixtures': len(originals), 'final_regular_season_fixtures': len(final),
            'final_whistles': len(rows) - len(failures), 'failures': failures,
            'excluded_nonregular': excluded, 'provisional_counts': {'cancelled': 0, 'delay_adverse': delays},
            'provisional_upper95': None if failures else {'cancelled_rate': upper95(0, 306), 'postponed_gt48h_rate': upper95(delays, 306)},
            'official_review_passed': False, 'independent_replay_passed': False,
            'registered_rates': {}, 'rows': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--corrected', action='store_true')
    args = parser.parse_args()
    result = measure(corrected=args.corrected)
    content = json.dumps(result, indent=2, sort_keys=True) + '\n'
    if args.output:
        with args.output.open('x') as stream:
            stream.write(content)
        print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, indent=2))
        print(json.dumps([r for r in result['rows'] if r.get('review_required') or r.get('failure')], indent=2))
    else:
        print(content, end='')
