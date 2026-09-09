#!/usr/bin/env python3
"""L43: immutable preseason fixtures joined to observed final-whistle wallclocks.

Raw downloaded evidence lives on the data volume. No live system is touched.
Publication of a rate requires the preregistered gates and separate source review.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import time
from urllib.request import urlopen
from zoneinfo import ZoneInfo

DATA = Path('/Volumes/Kilos/janus/research/mls-L43')
HERE = Path(__file__).resolve().parent
EASTERN = ZoneInfo('America/New_York')
TEAM_IDS = {
    'Atlanta United': '18418', 'Austin FC': '20906', 'CF Montreal': '9720',
    'Charlotte FC': '21300', 'Chicago Fire': '182', 'Colorado Rapids': '184',
    'Columbus Crew': '183', 'D.C. United': '193', 'FC Cincinnati': '18267',
    'FC Dallas': '185', 'Houston Dynamo': '6077', 'Inter Miami CF': '20232',
    'LA Galaxy': '187', 'Los Angeles FC': '18966', 'Minnesota United FC': '17362',
    'Nashville SC': '18986', 'New England Revolution': '189', 'New York City FC': '17606',
    'New York Red Bulls': '190', 'Orlando City SC': '12011', 'Philadelphia Union': '10739',
    'Portland Timbers': '9723', 'Real Salt Lake': '4771', 'San Diego FC': '22529',
    'San Jose Earthquakes': '191', 'Seattle Sounders FC': '9726',
    'Sporting Kansas City': '186', 'St. Louis CITY SC': '21812', 'Toronto FC': '7318',
    'Vancouver Whitecaps': '9727',
}
FIXTURE = re.compile(
    r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+'
    r'(January|February|March|April|May|June|July|August|September|October|November|December)'
    r'\s+(\d{1,2})\s+(.+?)\s+vs\.\s+(.+?),\s+(\d{1,2}(?::\d{2})?)\s+([ap])\.m\.')


def originals(text: str) -> list[dict]:
    schedule = text.split('2025 MAJOR LEAGUE SOCCER SCHEDULE', 1)[1]
    if 'As of Jan. 6, 2025.' not in schedule[:250]:
        raise ValueError('Preseason original-date label absent')
    out = []
    for month, day, home, away, clock, am_pm in FIXTURE.findall(schedule):
        home, away = home.strip(), away.strip()
        hour, minute = (clock.split(':') + ['0'])[:2] if ':' not in clock else clock.split(':')
        hour = int(hour) % 12 + (12 if am_pm == 'p' else 0)
        date = datetime.strptime(f'2025 {month} {day}', '%Y %B %d').replace(
            hour=hour, minute=int(minute), tzinfo=EASTERN)
        out.append({'home_id': TEAM_IDS[home], 'away_id': TEAM_IDS[away],
                    'home': home, 'away': away, 'scheduled': date.isoformat()})
    counts = Counter(t for f in out for t in (f['home_id'], f['away_id']))
    if len(out) != 510 or len(counts) != 30 or set(counts.values()) != {34}:
        raise ValueError(f'Incomplete original schedule: {len(out)} matches; per club {dict(counts)}')
    keys = [(f['home_id'], f['away_id']) for f in out]
    if len(set(keys)) != len(keys):
        raise ValueError('Repeated home/away fixture requires explicit adjudication')
    return out


def final_whistle(summary: dict, event_id: str) -> datetime:
    """Require an actual full-time play wallclock, never a lastUpdated or kickoff proxy."""
    header = summary.get('header', {})
    if str(header.get('id')) != str(event_id):
        raise ValueError(f'Wrong summary event {event_id}')
    competitions = header.get('competitions', [])
    if len(competitions) != 1 or not competitions[0].get('status', {}).get('type', {}).get('completed'):
        raise ValueError(f'{event_id}: non-final game')
    finals = [p for p in summary.get('keyEvents', [])
              if p.get('type', {}).get('type') == 'end-regular-time'
              and p.get('period', {}).get('number') == 2 and p.get('wallclock')]
    if len(finals) != 1:
        raise ValueError(f'{event_id}: missing/ambiguous final-whistle wallclock')
    dt = datetime.fromisoformat(finals[0]['wallclock'].replace('Z', '+00:00'))
    start = datetime.fromisoformat(competitions[0]['date'].replace('Z', '+00:00'))
    if dt <= start:
        raise ValueError(f'{event_id}: final whistle precedes start')
    return dt


def upper95(k: int, n: int) -> float:
    """Exact one-sided Clopper-Pearson binomial upper limit (stdlib only)."""
    if not 0 <= k <= n or n <= 0:
        raise ValueError('Invalid binomial counts')
    if k == n:
        return 1.0
    if k == 0:
        return -math.expm1(math.log(0.05) / n)
    lo, hi = k / n, 1.0
    coeffs = [math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
              for i in range(k + 1)]
    for _ in range(80):
        p = (lo + hi) / 2
        cdf = sum(math.exp(c + i * math.log(p) + (n - i) * math.log1p(-p))
                  for i, c in enumerate(coeffs))
        if cdf > 0.05:
            lo = p
        else:
            hi = p
    return hi


def completion_delayed(original: datetime, finished: datetime) -> bool:
    """The registered conservative two-day boundary, in the schedule's Eastern zone."""
    return (finished.astimezone(EASTERN).date() - original.astimezone(EASTERN).date()).days >= 2


def fetch_summary(event_id: str) -> None:
    path = DATA / f'espn-summary-{event_id}.json'
    if path.exists():
        return
    url = f'https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/summary?event={event_id}'
    for attempt in range(3):
        try:
            with urlopen(url, timeout=30) as response:
                raw = response.read()
            parsed = json.loads(raw)
            if str(parsed.get('header', {}).get('id')) != event_id:
                raise ValueError(f'Wrong event payload: {event_id}')
            path.write_bytes(raw)
            return
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def source_url(path: Path) -> str:
    if path.name.startswith('official-review-'):
        event_id = path.stem.split('-')[-1]
        return json.loads((HERE / 'official_review.json').read_text())['events'][event_id]['source']
    if path.name.startswith('espn-summary-'):
        return 'https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/summary?event=' + path.stem.split('-')[-1]
    if path.name == 'espn-2025-final.json':
        return 'https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard?dates=20250201-20251019&limit=1000'
    if path.name.startswith('espn-plays-'):
        event_id = path.stem.split('-')[-1]
        return f'https://sports.core.api.espn.com/v2/sports/soccer/leagues/usa.1/events/{event_id}/competitions/{event_id}/plays?limit=1000'
    if path.name.startswith('2025-mls-official'):
        return 'https://images.mlssoccer.com/image/private/fl_attachment/mls/lcq7kwlyhdgd4qnpfnqy.pdf'
    if path.name.startswith('2025-mls-fact-book'):
        return 'https://nyc3.digitaloceanspaces.com/sportsarchive-documents/prod/67b3cfa34e31f/2025%20MLS%20Fact%20and%20Record%20Book_FINAL.pdf'
    return ''


def reviewed_result(result: dict, review: dict) -> dict:
    """Apply the independently written source review without changing measured counts."""
    exceptions = {r['event_id']: r for r in result['rows']
                  if r['kickoff_date_changed'] or r['moved_gt48h_conservative']}
    if set(exceptions) != set(review['events']):
        raise ValueError('Review does not cover exactly the full exception population')
    for event_id, row in exceptions.items():
        reviewed = review['events'][event_id]
        actual_start = datetime.fromisoformat(row['actual_start'])
        finished = datetime.fromisoformat(row['finished'])
        actual_day = actual_start.astimezone(EASTERN).date().isoformat()
        if actual_day != reviewed['final_date_eastern'] or not reviewed['source'].startswith('https://'):
            raise ValueError(f'Unreconciled official date/source for {event_id}')
        # A kickoff-date announcement does not corroborate the end of a suspended match.
        # Require a separate official completion date if the game took more than a day,
        # or if only its completion (not its kickoff date) moved across the risk boundary.
        if ((finished - actual_start).total_seconds() > 86400
                or (row['moved_gt48h_conservative'] and not row['kickoff_date_changed'])):
            completed_day = finished.astimezone(EASTERN).date().isoformat()
            if reviewed.get('completion_date_eastern') != completed_day:
                raise ValueError(f'Unreconciled official completion date for suspended event {event_id}')
    if result['failures'] or not all(v for k, v in result['gates'].items() if k != 'official_date_mismatch_review'):
        raise ValueError('Cannot register an incomplete population')
    return {**result, 'gates': {**result['gates'], 'official_date_mismatch_review': True},
            'verdict': 'REGISTERED', 'official_review': 'official_review.json',
            'registered_rates': result['upper95_provisional']}


def measure() -> dict:
    scheduled = originals((DATA / '2025-mls-official.txt').read_text())
    events = [e for e in json.loads((DATA / 'espn-2025-final.json').read_text())['events']
              if e.get('season', {}).get('slug') == 'regular-season']
    final = {}
    for event in events:
        competitors = event['competitions'][0]['competitors']
        teams = {c['homeAway']: str(c['team']['id']) for c in competitors}
        key = (teams['home'], teams['away'])
        if key in final:
            raise ValueError(f'Ambiguous final fixture {key}')
        final[key] = event
    expected = {(f['home_id'], f['away_id']) for f in scheduled}
    if len(events) != 510 or set(final) != expected:
        raise ValueError(f'Final inventory mismatch: n={len(events)}, missing={expected - set(final)}, extra={set(final) - expected}')
    rows, failures = [], []
    for fixture in scheduled:
        event = final[(fixture['home_id'], fixture['away_id'])]
        event_id = str(event['id'])
        try:
            whistle = final_whistle(json.loads((DATA / f'espn-summary-{event_id}.json').read_text()), event_id)
        except (ValueError, OSError) as exc:
            failures.append(str(exc))
            continue
        original = datetime.fromisoformat(fixture['scheduled'])
        current_start = datetime.fromisoformat(event['date'].replace('Z', '+00:00'))
        rows.append({**fixture, 'event_id': event_id, 'actual_start': current_start.isoformat(),
                     'finished': whistle.isoformat(), 'completion_delay_hours': (whistle - original).total_seconds() / 3600,
                     'kickoff_date_changed': current_start.astimezone(EASTERN).date() != original.date(),
                     'moved_gt48h_conservative': completion_delayed(original, whistle)})
    moved = sum(r['moved_gt48h_conservative'] for r in rows)
    return {'row': 'L43', 'source_directory': str(DATA), 'original_matches': len(scheduled),
            'final_matches': len(events), 'final_whistles': len(rows), 'failures': failures,
            'gates': {'original_complete': True, 'final_complete_unique_join': True,
                      'suspensions_detected_via_final_whistle': not failures,
                      'official_date_mismatch_review': False},
            'counts': {'cancelled': 0, 'moved_gt48h_conservative': moved},
            'upper95_provisional': {'cancelled_rate': upper95(0, 510),
                                    'postponed_gt48h_rate': upper95(moved, 510)} if not failures else None,
            'rows': rows,
            'verdict': 'BLOCKED_PENDING_OFFICIAL_DATE_MISMATCH_REVIEW' if not failures else 'BLOCKED_INCOMPLETE_COMPLETION_EVIDENCE'}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--review', action='store_true')
    parser.add_argument('--fetch-reviews', action='store_true')
    args = parser.parse_args()
    if args.fetch_reviews:
        reviews = json.loads((HERE / 'official_review.json').read_text())['events']
        def fetch_review(item):
            event_id, entry = item
            path = DATA / f'official-review-{event_id}.html'
            if not path.exists():
                with urlopen(entry['source'], timeout=30) as response:
                    raw = response.read()
                if len(raw) < 1000:
                    raise ValueError(f'Empty official source for {event_id}')
                path.write_bytes(raw)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(fetch_review, reviews.items()))
    if args.fetch:
        events = json.loads((DATA / 'espn-2025-final.json').read_text())['events']
        ids = [str(e['id']) for e in events if e.get('season', {}).get('slug') == 'regular-season']
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(fetch_summary, event_id) for event_id in ids]
            for n, f in enumerate(as_completed(futures), 1):
                f.result()
                if n % 50 == 0:
                    print(f'Fetched {n}/{len(ids)}', flush=True)
    result = measure()
    target = HERE / ('results_registered.json' if args.review else 'results.json')
    if args.review:
        result = reviewed_result(result, json.loads((HERE / 'official_review.json').read_text()))
    serialized = json.dumps(result, indent=2) + '\n'
    if target.exists() and target.read_text() != serialized:
        raise ValueError(f'Immutable result changed; use a new dated result: {target}')
    target.write_text(serialized)
    manifest = [{'path': str(p), 'bytes': p.stat().st_size,
                 'url': source_url(p),
                 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in sorted(DATA.glob('*')) if p.suffix in {'.json', '.pdf', '.txt', '.html'}]
    manifest_path = HERE / ('source_manifest_registered.json' if args.review else 'source_manifest.json')
    manifest_text = json.dumps(manifest, indent=2) + '\n'
    if manifest_path.exists() and manifest_path.read_text() != manifest_text:
        raise ValueError(f'Immutable manifest changed; use a new dated manifest: {manifest_path}')
    manifest_path.write_text(manifest_text)
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, indent=2))
    print(json.dumps([r for r in result['rows'] if r['kickoff_date_changed'] or r['moved_gt48h_conservative']], indent=2))


if __name__ == '__main__':
    main()
