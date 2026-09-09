"""L58 offline source audit. A full-time publication bounds completion from above."""
from collections import Counter
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import runpy
import subprocess
import unicodedata
from zoneinfo import ZoneInfo

DATA = Path('/Volumes/Kilos/janus/research/ucl-settlement-bounds')
HERE = Path(__file__).resolve().parent
EASTERN = ZoneInfo('America/New_York')
TEAMS = {
    'Real Madrid C.F.': '86', 'Manchester City': '382', 'FC Bayern München': '132',
    'Paris Saint-Germain': '160', 'Liverpool FC': '364', 'FC Internazionale Milano': '110',
    'Borussia Dortmund': '124', 'RB Leipzig': '11420', 'FC Barcelona': '83',
    'Bayer 04 Leverkusen': '131', 'Atlético de Madrid': '1068', 'Atalanta BC': '105',
    'Juventus': '111', 'SL Benfica': '1929', 'Arsenal FC': '359', 'Club Brugge KV': '570',
    'FC Shakhtar Donetsk': '493', 'AC Milan': '103', 'Feyenoord': '142',
    'Sporting Clube de Portugal': '2250', 'PSV Eindhoven': '148', 'GNK Dinamo': '597',
    'FC Salzburg': '2790', 'LOSC Lille': '166', 'FK Crvena Zvezda': '2290',
    'BSC Young Boys': '2722', 'Celtic FC': '256', 'ŠK Slovan Bratislava': '521',
    'AS Monaco': '174', 'AC Sparta Praha': '433', 'Aston Villa FC': '362',
    'Bologna FC 1909': '107', 'Girona FC': '9812', 'VfB Stuttgart': '134',
    'SK Sturm Graz': '3746', 'Stade Brestois 29': '6997',
}


def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s).casefold() if c.isalnum())


def pdf_text(path):
    return subprocess.check_output(['pdftotext', '-raw', str(path), '-'], text=True)


def originals(text):
    names = {norm(name): name for name in TEAMS}
    owner = None
    all_rows = []
    for line in text.splitlines():
        if norm(line) in names:
            owner = names[norm(line)]
            continue
        match = re.fullmatch(r'(\d{1,2})\s*([A-Za-z]+)\s*(202[45])\s+(\d\d:\d\d)\s+(.+?)\s*\(([HA])\)', line.strip())
        if not match:
            continue
        if owner is None:
            raise ValueError('Fixture without club heading')
        day, month, year, clock, opponent, side = match.groups()
        opponent = names[norm(opponent)]
        # UEFA labels CET even in summer. UTC+2 is the earliest plausible original;
        # final report uses UTC+1 below, the latest plausible completion upper bound.
        scheduled = datetime.strptime(f'{year} {month} {day} {clock}', '%Y %B %d %H:%M').replace(tzinfo=timezone(timedelta(hours=2)))
        home, away = (owner, opponent) if side == 'H' else (opponent, owner)
        all_rows.append((home, away, scheduled.isoformat()))
    counts = Counter(all_rows)
    if len(all_rows) != 288 or len(counts) != 144 or set(counts.values()) != {2}:
        raise ValueError('Original population must have 144 reciprocal unique fixtures')
    appearances = Counter(t for home, away, _ in counts for t in (home, away))
    if len(appearances) != 36 or set(appearances.values()) != {8}:
        raise ValueError('Original population must contain 36 clubs with eight games each')
    return [{'home': h, 'away': a, 'original_lower': d, 'home_id': TEAMS[h], 'away_id': TEAMS[a]} for h, a, d in sorted(counts)]


def report(text, fixtures):
    if 'Full Time Report' not in text:
        raise ValueError('Not a full-time report')
    header = text.split('Full Time Report', 1)[1][:650]
    matches = [f for f in fixtures if norm(f['home'] + f['away']) in norm(header)]
    if len(matches) != 1:
        raise ValueError(f'Ambiguous report fixture: {len(matches)}')
    dates = re.findall(r'(\d\d:\d\d:\d\d)\s*CET\s*\n(\d{1,2} [A-Za-z]{3} 202[45])', header)
    if len(dates) != 1:
        raise ValueError('Missing unique full-time publication timestamp')
    clock, date = dates[0]
    latest = datetime.strptime(date + ' ' + clock, '%d %b %Y %H:%M:%S').replace(tzinfo=timezone(timedelta(hours=1)))
    played = re.findall(r'Matchday (\d+) - [A-Za-z]+ (\d{1,2} [A-Za-z]+ 202[45])', header)
    if len(played) != 1 or not 1 <= int(played[0][0]) <= 8:
        raise ValueError('Not a uniquely dated league-phase report')
    actual_date = datetime.strptime(played[0][1], '%d %B %Y').date()
    return matches[0], latest, actual_date


def delayed(original, upper):
    return upper - original > timedelta(hours=48) or (upper.astimezone(EASTERN).date() - original.astimezone(EASTERN).date()).days >= 2


def upper95(k, n):
    if not 0 <= k <= n or n <= 0:
        raise ValueError('Invalid counts')
    if k == n:
        return 1.0
    if k == 0:
        return -math.expm1(math.log(0.05) / n)
    lo, hi = k / n, 1.0
    for _ in range(80):
        p = (lo + hi) / 2
        cdf = sum(math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * math.log(p) + (n-i) * math.log1p(-p)) for i in range(k + 1))
        if cdf > .05:
            lo = p
        else:
            hi = p
    return hi


def source_manifest(data):
    """Validate the exact source population, not merely the sidecars found on disk."""
    expected = dict(runpy.run_path(str(HERE / 'collect.py'))['SOURCES'])
    validated = {}
    seen_paths = set()

    def validate(name, url):
        path = data / name
        sidecar = data / (name + '.meta.json')
        if not path.is_file() or not sidecar.is_file():
            raise ValueError(f'Missing source or metadata sidecar: {name}')
        try:
            meta = json.loads(sidecar.read_text())
            if meta['path'] != str(path) or path.is_symlink() or sidecar.is_symlink():
                raise ValueError(f'Source path mismatch: {name}')
            if meta['path'] in seen_paths:
                raise ValueError(f'Duplicate source path: {name}')
            seen_paths.add(meta['path'])
            if meta['url'] != url or meta['status'] != 200 or not isinstance(meta['headers'], dict):
                raise ValueError(f'Source request metadata mismatch: {name}')
            if datetime.fromisoformat(meta['retrieved_at']).utcoffset() is None:
                raise ValueError(f'Source retrieval timezone missing: {name}')
            raw = path.read_bytes()
            if len(raw) != meta['bytes'] or hashlib.sha256(raw).hexdigest() != meta['sha256']:
                raise ValueError(f'Source hash/size mismatch: {name}')
            validated[name] = meta
            return raw
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f'Invalid source sidecar: {name}') from exc

    # Roots must be verified before they determine the expected descendant source IDs.
    roots = {name: validate(name, url) for name, url in expected.items()}
    event_ids = [str(e['id']) for e in json.loads(roots['espn-scoreboard.json'])['events']]
    section = roots['uefa-results.html'].decode().split('League phase </h2>', 1)[1].split('</article>', 1)[0]
    report_ids = re.findall(r'/match/(\d+)', section)
    if (len(event_ids) != 144 or len(set(event_ids)) != 144
            or not all(re.fullmatch(r'[0-9]+', i) for i in event_ids)
            or len(report_ids) != 144 or len(set(report_ids)) != 144):
        raise ValueError('Expected exactly 144 unique ESPN IDs and UEFA report IDs')
    expected.update({f'summary-{i}.json': f'https://site.web.api.espn.com/apis/site/v2/sports/soccer/uefa.champions/summary?event={i}' for i in event_ids})
    expected.update({f'uefa-report-{i}.pdf': f'https://www.uefa.com/newsfiles/UCL/2025/{i}_FR.pdf' for i in report_ids})
    source_names, sidecar_names = set(), set()
    for path in data.iterdir():
        # These are known generated artifacts, never source evidence.
        if (re.fullmatch(r'audit-[0-9a-f]{64}\.json', path.name)
                or path.name in {'pot-page1.png', 'report-sample.png'}):
            continue
        if path.name.endswith('.meta.json'):
            sidecar_names.add(path.name)
        else:
            source_names.add(path.name)
    if len(expected) != 294 or source_names != set(expected):
        raise ValueError('Missing or orphan source file; require exact 294-source population')
    if sidecar_names != {name + '.meta.json' for name in expected}:
        raise ValueError('Missing or orphan metadata sidecar; require exact 294-source population')
    for name, url in expected.items():
        if name not in validated:
            validate(name, url)
    return [{k: validated[name][k] for k in ('path', 'url', 'sha256', 'bytes', 'retrieved_at')}
            for name in sorted(validated)]


def measure():
    manifest = source_manifest(DATA)
    fixtures = originals(pdf_text(DATA / 'original-2024-pot.pdf'))
    info = subprocess.check_output(['pdfinfo', str(DATA / 'original-2024-pot.pdf')], text=True)
    if 'UCL_BYPOT_WFIX_GLOBAL-20240831T112049' not in info:
        raise ValueError('Original dated publication identity changed')
    publication = (DATA / 'uefa-draw-publication.html').read_text()
    original_meta = json.loads((DATA / 'original-2024-pot.pdf.meta.json').read_text())
    if ('31 August' not in publication or '18:45 CET or 21:00 CET' not in publication
            or original_meta['headers'].get('Last-Modified') != 'Sat, 31 Aug 2024 10:51:57 GMT'):
        raise ValueError('Official pre-event calendar publication provenance missing')
    scoreboard = json.loads((DATA / 'espn-scoreboard.json').read_text())
    events = {}
    for event in scoreboard['events']:
        comp = event['competitions'][0]
        sides = {c['homeAway']: str(c['team']['id']) for c in comp['competitors']}
        key = (sides['home'], sides['away'])
        if key in events or event['season']['slug'] != 'league-phase' or not event['status']['type']['completed']:
            raise ValueError('Incomplete or ambiguous final event population')
        events[key] = event
    if len(events) != 144:
        raise ValueError('Incomplete ESPN final population')
    rows, failures, seen = [], [], set()
    for path in sorted(DATA.glob('uefa-report-*.pdf')):
        try:
            fixture, completed_by, played_date = report(pdf_text(path), fixtures)
            key = (fixture['home_id'], fixture['away_id'])
            if key in seen:
                raise ValueError('Duplicate report fixture')
            seen.add(key)
            event = events[key]
            original = datetime.fromisoformat(fixture['original_lower'])
            if completed_by <= original:
                raise ValueError('Publication precedes original fixture')
            suspended = bool(event['competitions'][0].get('wasSuspended'))
            row = {**fixture, 'event_id': event['id'], 'report': path.name,
                   'completed_by': completed_by.isoformat(), 'played_date': played_date.isoformat(),
                   'was_suspended': suspended,
                   'delayed_conservative': delayed(original, completed_by) or suspended,
                   'date_changed': played_date != original.date()}
            rows.append(row)
        except (ValueError, KeyError) as exc:
            failures.append({'report': path.name, 'error': str(exc)})
    if len(rows) != 144 or len(seen) != 144:
        failures.append({'error': 'Not every original fixture has one valid terminal report', 'joined': len(rows)})
    exceptions = [r for r in rows if r['date_changed'] or r['delayed_conservative']]
    # Every exception needs separate source adjudication: preserve failure, never auto-register.
    if exceptions:
        failures.append({'error': 'Schedule/completion exceptions require explicit source review', 'events': [r['event_id'] for r in exceptions]})
    result = {'row': 'L58', 'population': '2024-25 UCL league-phase', 'original_n': len(fixtures),
              'joined_n': len(rows), 'failures': failures, 'rows': rows, 'manifest': manifest,
              'verdict': 'COMPLETE_SOURCE_AUDIT' if not failures else 'INCOMPLETE',
              'rates': {} if failures else {'soccer.ucl.cancelled_rate': upper95(0, 144),
                         'soccer.ucl.postponed_gt48h_rate': upper95(sum(r['delayed_conservative'] for r in rows), 144)}}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', action='store_true')
    args = parser.parse_args()
    result = measure()
    raw = (json.dumps(result, indent=2, sort_keys=True) + '\n').encode()
    if args.archive:
        digest = hashlib.sha256(raw).hexdigest()
        path = DATA / f'audit-{digest}.json'
        if path.exists():
            assert path.read_bytes() == raw
        else:
            with path.open('xb') as out:
                out.write(raw)
        print(json.dumps({k: v for k, v in result.items() if k not in ('manifest', 'rows')} | {
            'audit_path': str(path), 'audit_sha256': digest, 'source_count': len(result['manifest'])}, indent=2))
    else:
        print(raw.decode(), end='')
