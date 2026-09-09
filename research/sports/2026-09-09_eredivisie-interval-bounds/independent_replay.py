#!/usr/bin/env python3
"""Offline independent L50 audit. No imports from either author's research code.

Re-extracts the three archived PDFs, validates every raw acquisition, and joins
the complete ordered-pair population to ESPN terminal play-by-play. The official
footnote/exception decisions below were independently read against archived
documents; text assertions pin the passages, not a claim of automated semantics.
Run without arguments to inspect; --output creates a new artifact exclusively.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
ZONE = ZoneInfo('Europe/Amsterdam')
CLUBS = dict(zip(
    ['Ajax', 'AZ', 'NAC Breda', 'Feyenoord', 'Fortuna Sittard', 'FC Groningen',
     'sc Heerenveen', 'N.E.C.', 'PSV', 'Sparta Rotterdam', 'FC Twente', 'FC Utrecht',
     'PEC Zwolle', 'Excelsior Rotterdam', 'FC Volendam', 'Go Ahead Eagles',
     'Heracles Almelo', 'Telstar'],
    ['139', '140', '141', '142', '143', '145', '146', '147', '148', '151', '152',
     '153', '2565', '2566', '2727', '3706', '3708', '3735']))
MONTHS = dict(zip('januari februari maart april mei juni juli augustus september oktober november december'.split(), range(1, 13)))
PUBS = {'definitive': '2025-06-24', 'autumn': '2025-09-10', 'spring': '2025-12-23'}
FOOTNOTES = {
    ('Heracles Almelo', 'Sparta Rotterdam'): [('definitive', 4, '2025-09-27')],
    ('FC Groningen', 'Feyenoord'): [('definitive', 4, '2025-09-28')],
    ('PSV', 'Fortuna Sittard'): [('autumn', 4, '2025-11-01')],
    ('Ajax', 'sc Heerenveen'): [('autumn', 4, '2025-11-01')],
    ('Feyenoord', 'FC Volendam'): [('autumn', 4, '2025-11-01')],
    ('FC Utrecht', 'Telstar'): [('spring', 6, '2026-04-12')],
    ('FC Groningen', 'Go Ahead Eagles'): [('spring', 6, '2026-04-12')],
    ('FC Utrecht', 'NAC Breda'): [('spring', 7, '2026-05-03')],
    ('N.E.C.', 'Telstar'): [('spring', 7, '2026-05-03')],
    ('AZ', 'FC Twente'): [('spring', 7, '2026-05-02')],
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def utc(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(result.utcoffset() is not None, f'Naive timestamp: {value}')
    return result


def source_text(item):
    soup = BeautifulSoup(Path(item['path']).read_bytes(), 'html.parser')
    for node in soup(['script', 'style', 'nav', 'footer', 'header']):
        node.decompose()
    return ' '.join(soup.get_text(' ', strip=True).split())


def exact_upper(k, n):
    # Independent binomial-CDF inversion, using integer binomial coefficients
    # rather than the author's log-gamma coefficients or its zero-event branch.
    low, high = 0.0, 1.0
    for _ in range(100):
        p = (low + high) / 2
        cdf = math.fsum(math.comb(n, j) * p**j * (1-p)**(n-j) for j in range(k+1))
        if cdf > 0.05:
            low = p
        else:
            high = p
    return high


def replay():
    manifest = json.loads((HERE / 'source_manifest.json').read_text())
    sources = manifest['sources']
    for label, item in sources.items():
        require(sha(item['path']) == item['sha256'], f'Raw digest: {label}')
        require(Path(item['path']).stat().st_size == item['bytes'], f'Raw size: {label}')
        require(sha(item['metadata_path']) == item['metadata_sha256'], f'Metadata digest: {label}')
        metadata = json.loads(Path(item['metadata_path']).read_text())
        require(metadata == {k: v for k, v in item.items() if k not in {'metadata_path', 'metadata_sha256'}}, f'Metadata fields: {label}')
        require(item['url'].startswith('https://'), f'Non-HTTPS provenance: {label}')
    for filename, key in [('spec.yaml', 'spec_sha256'), ('original_bounds.json', 'original_bounds_sha256'),
                          ('results.json', 'initial_results_sha256'), ('official_review.json', 'official_review_sha256')]:
        require(sha(HERE / filename) == manifest[key], f'Artifact digest: {filename}')
    failures = sorted(label for label, item in sources.items() if item['status'] != 200)
    require(failures == sorted(manifest['preserved_failures']) == ['inventory'], 'Unaccounted acquisition failure')
    require(sources['inventory']['status'] == 403, 'Unexpected failure disposition')

    names = '|'.join(re.escape(name) for name in sorted(CLUBS, key=len, reverse=True))
    row_pattern = re.compile(rf'^\s*(\d{{1,2}})\s+(.+?)\s+({names})\s+({names})(?:\s+(.*?))?\s*$')
    exact_date = re.compile(r'^(?:maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag) (\d{1,2}) ([a-z]+) (202[56])$')
    history = defaultdict(list)
    pdf_counts = {}
    pdf_pages = {}
    for label, publication in PUBS.items():
        pages = subprocess.check_output(['pdftotext', '-layout', sources[label]['path'], '-'], text=True).split('\f')
        pdf_pages[label] = pages
        count = 0
        for page_no, page in enumerate(pages, 1):
            for line_no, line in enumerate(page.splitlines(), 1):
                if not re.match(r'^\s*\d{1,2}\s', line):
                    continue
                match = row_pattern.fullmatch(line)
                require(match is not None, f'Unparsed fixture row {label}:{page_no}:{line_no}: {line}')
                round_no, day_text, home, away, tail = match.groups()
                tail = ' '.join((tail or '').split())
                clock = re.search(r'\b\d\d:\d\d\b', tail)
                calendar = exact_date.fullmatch(day_text.strip())
                scheduled = None
                if calendar:
                    require(clock is not None, f'Exact date without clock: {line}')
                    day, month, year = calendar.groups()
                    scheduled = datetime.combine(date(int(year), MONTHS[month], int(day)), datetime.strptime(clock.group(), '%H:%M').time(), ZONE).isoformat()
                require(home != away and 1 <= int(round_no) <= 34, 'Invalid original identity/round')
                history[home, away].append({'home': home, 'away': away, 'round': int(round_no),
                    'source': label, 'published': publication, 'pdf_page': page_no, 'text_line': line_no,
                    'date_text': day_text.strip(), 'time_text': tail, 'scheduled': scheduled,
                    'conditional': '*' in tail})
                count += 1
        pdf_counts[label] = count
    expected = {(home, away) for home in CLUBS for away in CLUBS if home != away}
    require(set(history) == expected and len(expected) == 306, 'Original round-robin population')
    original_rows = [r for rows in history.values() for r in rows if r['source'] == 'definitive']
    require(len(original_rows) == 309 and {(r['home'], r['away']) for r in original_rows} == expected, 'June coverage')
    june_counts = Counter((r['home'], r['away']) for r in original_rows)
    duplicates = {key: count for key, count in june_counts.items() if count != 1}
    require(duplicates == {('AZ', 'PEC Zwolle'): 2, ('FC Utrecht', 'Excelsior Rotterdam'): 2, ('Feyenoord', 'Fortuna Sittard'): 2}, 'Unexpected duplicates')
    require(set(Counter(x for key in expected for x in key).values()) == {34}, 'Club denominator')
    # Pin all date-changing PDF footnotes to the actual pages reviewed visually/textually.
    for label, page, phrase in [('definitive', 4, 'HER-SPA naar zaterdag'), ('autumn', 4, 'PSV-FOR gaat naar za 16:30'),
        ('spring', 6, 'zondag 12 april'), ('spring', 7, 'zaterdag 2 mei'), ('spring', 7, 'zondag 3 mei')]:
        require(phrase in pdf_pages[label][page-1], f'Footnote passage changed: {label}:{page}')

    frozen = {(r['home'], r['away']): r for r in json.loads((HERE / 'original_bounds.json').read_text())['rows']}
    require(set(frozen) == expected, 'Frozen denominator')
    originals = {}
    first_publications = Counter()
    conditional = 0
    for key, rows in history.items():
        rounds = {r['round'] for r in rows}
        require(len(rounds) == 1, f'Round lineage: {key}')
        dated = [r for r in rows if r['scheduled']]
        require(bool(dated), f'No fixture-specific original: {key}')
        first_pub = min(r['published'] for r in dated)
        first = [r for r in dated if r['published'] == first_pub]
        first_publications[first_pub] += 1
        was_conditional = len(first) > 1 or any(r['conditional'] for r in first)
        conditional += was_conditional
        dates = {r['scheduled'][:10] for r in dated}
        dates.update(item[2] for item in FOOTNOTES.get(key, []))
        lower = min(dates)
        original = frozen[key]
        require(rows == original['source_history'], f'Full source-history mismatch: {key}')
        require(lower == original['earliest_original_date'], f'Lower-bound mismatch: {key}')
        require(original['conditional_first_publication'] == was_conditional, f'Conditional mismatch: {key}')
        require(original['timezone'] == 'Europe/Amsterdam' and original['earliest_original_local_clock'] == '00:00:00', f'Midnight clock: {key}')
        require(original['unbounded_earlier_alternative'] is False, f'Unexpected ambiguity flag: {key}')
        originals[key] = {'round': rounds.pop(), 'lower': lower, 'all_pdf_candidate_dates': sorted(dates)}
    require(dict(first_publications) == {'2025-06-24': 126, '2025-09-10': 81, '2025-12-23': 99} and conditional == 47, 'First-publication population')

    base_url = 'https://site.api.espn.com/apis/site/v2/sports/soccer/ned.1/'
    require(sources['inventory-default-agent']['url'] == base_url + 'scoreboard?dates=20250801-20260630&limit=1000', 'Inventory URL')
    inventory = json.loads(Path(sources['inventory-default-agent']['path']).read_text())['events']
    inv_ids = [event['id'] for event in inventory]
    require(len(set(inv_ids)) == len(inv_ids) == 309 and all(inv_ids), 'Inventory IDs')
    phases = {'regular-season': 13484, 'conference-league-playoffs---semifinals': 13483, 'conference-league-playoffs---final': 13482}
    inverse = {v: k for k, v in CLUBS.items()}
    final = {}
    excluded = []
    for event in inventory:
        phase = event['season']
        require(phase['year'] == 2025 and phase['slug'] in phases and phase['type'] == phases[phase['slug']], 'Unknown season/phase')
        event_id = event['id']
        item = sources['summary-' + event_id]
        require(item['status'] == 200 and item['url'] == base_url + 'summary?event=' + event_id, 'Summary request identity')
        summary = json.loads(Path(item['path']).read_text())
        head = summary['header']
        require(head['id'] == event_id and head['league']['slug'] == 'ned.1' and head['season']['year'] == 2025 and head['season']['type'] == phase['type'], 'Summary population')
        if phase['type'] != 13484:
            excluded.append({'id': event_id, 'season': phase})
            continue
        require(len(event['competitions']) == len(head['competitions']) == 1, 'Competition multiplicity')
        icomp, comp = event['competitions'][0], head['competitions'][0]
        require(icomp['id'] == comp['id'] == event_id, 'Competition identity')
        def side_ids(competition):
            people = competition['competitors']
            require(len(people) == 2, 'Competitor cardinality')
            sides = {p['homeAway']: str(p['team']['id']) for p in people}
            require(set(sides) == {'home', 'away'} and sides['home'] != sides['away'], 'Competitor sides')
            return sides['home'], sides['away']
        ids = side_ids(comp)
        require(ids == side_ids(icomp), 'Summary/inventory competitors')
        key = tuple(inverse[i] for i in ids)
        require(key in expected and key not in final, 'Missing/duplicate original join')
        status = comp['status']['type']
        require(status['completed'] is True and status['state'] == 'post' and status['name'] == 'STATUS_FULL_TIME', 'Not a played terminal match')
        ends = [play for play in summary.get('keyEvents', []) if play.get('type', {}).get('type') == 'end-regular-time' and play.get('period', {}).get('number') == 2]
        require(len(ends) == 1 and ends[0].get('wallclock') and ends[0]['clock']['value'] >= 5400, 'Final-whistle provenance')
        start, completion = utc(comp['date']), utc(ends[0]['wallclock'])
        require(start == utc(event['date']) == utc(icomp['date']) and completion > start, 'Completion chronology')
        lower = datetime.combine(date.fromisoformat(originals[key]['lower']), datetime.min.time(), ZONE)
        hours = (completion.astimezone(timezone.utc) - lower.astimezone(timezone.utc)).total_seconds()/3600
        kickoff_changed = start.astimezone(ZONE).date() != lower.date()
        completion_changed = completion.astimezone(ZONE).date() != lower.date()
        final[key] = {'event_id': event_id, 'home': key[0], 'away': key[1], 'home_id': ids[0], 'away_id': ids[1],
            'round': originals[key]['round'], 'original_lower_bound': lower.isoformat(), 'unbounded_earlier_alternative': False,
            'actual_start': start.isoformat(), 'actual_completion': completion.isoformat(), 'completion_hours_after_lower_bound': hours,
            'delay_adverse': hours > 48, 'cancelled': False, 'kickoff_date_changed': kickoff_changed,
            'completion_date_changed': completion_changed, 'review_required': kickoff_changed or completion_changed}
    require(set(final) == expected, 'Final denominator')
    rows = sorted(final.values(), key=lambda r: (r['home_id'], r['away_id']))
    initial = json.loads((HERE / 'results.json').read_text())
    require(rows == initial['rows'] and excluded == initial['excluded_nonregular'], 'Full final-row replay mismatch')
    exceptions = {row['event_id']: row for row in rows if row['review_required']}
    official = json.loads((HERE / 'official_review.json').read_text())['events']
    require(set(exceptions) == set(official) and len(exceptions) == 15, 'Official review denominator')
    for event_id, row in exceptions.items():
        decision = official[event_id]
        require((decision['home'], decision['away']) == (row['home'], row['away']) and decision['original_lower_date'] == row['original_lower_bound'][:10], 'Review fixture identity')
        require(decision['final_date_local'] == utc(row['actual_completion']).astimezone(ZONE).date().isoformat(), 'Review completion day')
        require(decision['sources'] and all(sources[label]['status'] == 200 for label in decision['sources']), 'Missing official source')
    # Independently read official article bodies, including all resumed games.
    passages = {
        'ajax-completion': ['02.12.2025', 'remainder of the home fixture', 'Ajax - FC Groningen 2-0'],
        'ajax-resumption': ['1 december 2025', 'dinsdag 2 december, 14.30 uur'],
        'august-decision': ['15 augustus 2025', 'Woensdag 24 september', 'Zaterdag 27 september'],
        'december-announcement': ['23 december 2025', 'zondag 14 december', 'woensdag 21 januari', 'zondag 25 januari', 'woensdag 11 februari'],
        'december-reschedule': ['13 november 2025', 'Vrijdag 19 december', 'Zaterdag 20 december', 'Zondag 21 december'],
        'excelsior-reschedule': ['23 december 2025', '17 januari 2026, 20:00 uur', '21 januari 2026, 18:45 uur'],
        'march-reschedule': ['2 februari 2026', 'vrijdag 6 maart', 'zondag 8 maart', 'Heracles Almelo - FC Utrecht van 7 maart naar vrijdagavond 6 maart'],
        'nac-completion': ['11 mei 2026', 'tweede deel van de wedstrijd vindt maandag in Friesland plaats', 'De stand blijft zoals deze gisteren in Breda op het scorebord stond: 2-0'],
        'nec-january-reschedule': ['16 januari 2026', 'woensdag 11 februari om 21:00 uur', '18:45 uur'],
        'september-announcement': ['10 september 2025', 'Heracles Almelo – Feyenoord Zat. 18 oktober Zon. 19 oktober'],
        'sparta-completion': ['17 februari 2026', 'restant van dit affiche uitgespeeld', '1-1'],
        'sparta-suspension': ['15 februari 2026', 'dinsdagavond 17 februari om 20.00 uur'],
    }
    for label, phrases in passages.items():
        body = source_text(sources[label])
        require(all(phrase in body for phrase in phrases), f'Official review passage: {label}')
    az_soup = BeautifulSoup(Path(sources['az-results']['path']).read_bytes(), 'html.parser')
    for local_date, opponent, score in [('24 sep 2025', 'PEC Zwolle', '2 - 2'), ('21 jan 2026', 'Excelsior', '1 - 1'), ('3 mei 2026', 'Twente', '2 - 2')]:
        node = az_soup.find(string=lambda text: text and local_date in text)
        require(node is not None, f'AZ result date: {local_date}')
        card = node.parent.parent.parent.get_text(' ', strip=True)
        require(all(term in card for term in [score, 'VriendenLoterij Eredivisie 25-26', 'Thuis Team: AZ', 'Uit Team: ' + opponent]), f'AZ official result card: {local_date}')

    counts = {'cancelled': sum(r['cancelled'] for r in rows), 'delay_adverse': sum(r['delay_adverse'] for r in rows)}
    bounds = {'cancelled_rate': exact_upper(counts['cancelled'], len(rows)), 'postponed_gt48h_rate': exact_upper(counts['delay_adverse'], len(rows))}
    require(counts == initial['provisional_counts'] == {'cancelled': 0, 'delay_adverse': 7}, 'Adverse counts')
    require(all(math.isclose(v, initial['provisional_upper95'][k], abs_tol=1e-14) for k, v in bounds.items()), 'Exact confidence bounds')
    advanced = final['Heracles Almelo', 'FC Utrecht']
    conservative_lower = datetime(2026, 3, 6, tzinfo=ZONE)
    corrected_hours = (utc(advanced['actual_completion']) - conservative_lower.astimezone(timezone.utc)).total_seconds()/3600
    require(advanced['event_id'] == '741209' and corrected_hours < 48 and not advanced['delay_adverse'], 'Advance correction changes result')
    correction_document = json.loads((HERE / 'original_bounds_corrections.json').read_text())
    require(correction_document['frozen_original_sha256'] == sha(HERE / 'original_bounds.json')
            and correction_document['discovered_after_initial_outcome_measurement'] is True, 'Correction lineage')
    corrections = correction_document['corrections']
    require(len(corrections) == 1, 'Unexpected post-outcome correction')
    correction = corrections[0]
    expected_correction = {'home': 'Heracles Almelo', 'away': 'FC Utrecht', 'round': 26,
        'old_lower_date': '2026-03-07', 'new_lower_date': '2026-03-06', 'published': '2026-02-02',
        'scheduled': '2026-03-06T20:00:00+01:00', 'source_label': 'march-reschedule',
        'source_url': sources['march-reschedule']['url'], 'source_sha256': sources['march-reschedule']['sha256']}
    require({k: correction[k] for k in expected_correction} == expected_correction, 'Correction disagrees with independently read official announcement')
    corrected_originals = json.loads((HERE / 'original_bounds_corrected.json').read_text())
    require(corrected_originals['frozen_original_sha256'] == sha(HERE / 'original_bounds.json')
            and corrected_originals['corrections_sha256'] == sha(HERE / 'original_bounds_corrections.json'), 'Corrected original pins')
    expected_corrected_originals = deepcopy(frozen)
    amended_original = expected_corrected_originals['Heracles Almelo', 'FC Utrecht']
    amended_original['earliest_original_date'] = '2026-03-06'
    amended_original['candidate_calendar_dates'] = ['2026-03-06', '2026-03-07']
    amended_original['post_freeze_corrections'] = corrections
    require({(r['home'], r['away']): r for r in corrected_originals['rows']} == expected_corrected_originals, 'Full corrected original rows mismatch')
    corrected_rows = deepcopy(rows)
    for row in corrected_rows:
        row['initial_review_required'] = row['review_required']
        if row['event_id'] == '741209':
            row.update({'original_lower_bound': conservative_lower.isoformat(),
                'completion_hours_after_lower_bound': corrected_hours, 'kickoff_date_changed': False,
                'completion_date_changed': False, 'review_required': False,
                'post_freeze_original_corrections': corrections})
    corrected_results = json.loads((HERE / 'results_corrected.json').read_text())
    require(corrected_rows == corrected_results['rows'] and corrected_results['failures'] == []
            and corrected_results['provisional_counts'] == counts, 'Full corrected final rows mismatch')
    require(all(math.isclose(v, corrected_results['provisional_upper95'][k], abs_tol=1e-14) for k, v in bounds.items()), 'Corrected confidence bounds')
    corrected_review = json.loads((HERE / 'official_review_corrected.json').read_text())
    require(corrected_review['initial_review_sha256'] == sha(HERE / 'official_review.json')
            and corrected_review['corrections_sha256'] == sha(HERE / 'original_bounds_corrections.json'), 'Corrected review pins')
    require(set(corrected_review['events']) == set(exceptions), 'Correction silently removes required initial exception')
    for event_id, decision in corrected_review['events'].items():
        if event_id != '741209':
            require(decision == official[event_id], 'Unrelated review correction')
        else:
            require(decision['original_lower_date'] == '2026-03-06' and decision['final_date_local'] == '2026-03-06', 'Corrected review dates')
    first_request = min(utc(sources[label]['started_at']) for label in ['inventory', 'inventory-default-agent'])
    # Local filesystem birth times corroborate chronology, but cannot authenticate
    # absence of earlier unarchived observations or an exact ledger append time.
    births = {name: datetime.fromtimestamp((HERE / name).stat().st_birthtime, timezone.utc)
              for name in ['spec.yaml', 'original_bounds.json']}
    require(births['spec.yaml'] < births['original_bounds.json'] < first_request, 'Recorded prereg/freeze/request chronology')
    return {'id': 'L50', 'independent_implementation': True, 'author_measurement_imported': False,
        'source_manifest_sha256': sha(HERE / 'source_manifest.json'), 'replay_code_sha256': sha(__file__),
        'sources_verified': len(sources), 'preserved_failures': failures, 'pdf_fixture_rows': pdf_counts,
        'original_fixtures': 306, 'clubs': 18, 'matches_per_club': 34,
        'duplicate_alternative_pairs': [{'home': k[0], 'away': k[1], 'rows': v} for k, v in sorted(duplicates.items())],
        'first_publications': dict(first_publications), 'conditional_first_publications': conditional,
        'unbounded_alternatives': 0, 'full_frozen_source_histories_reproduced': True, 'full_initial_rows_reproduced': True,
        'full_corrected_original_rows_reproduced': True, 'full_corrected_final_rows_reproduced': True,
        'corrected_artifact_hashes': {name: sha(HERE / name) for name in ['original_bounds_corrections.json',
            'original_bounds_corrected.json', 'official_review_corrected.json', 'results_corrected.json']},
        'recorded_chronology': {**{name + '_local_birth': value.isoformat() for name, value in births.items()},
            'first_final_inventory_request': first_request.isoformat(), 'ledger_exact_append_timestamp_independently_available': False},
        'final_regular_season_fixtures': len(rows), 'final_whistles': len(rows), 'excluded_nonregular': excluded,
        'official_exceptions_reviewed': len(exceptions), 'counts': counts, 'upper95': bounds,
        'delay_event_ids': sorted(r['event_id'] for r in rows if r['delay_adverse']),
        'official_review_findings': [{'event_id': '741209', 'finding': 'Later official pre-match announcement lowers March 7 to March 6. Resolved by independently reproduced append-only correction; frozen artifacts and all fifteen initial reviews preserved.',
            'frozen_lower_bound': advanced['original_lower_bound'], 'conservative_lower_bound': conservative_lower.isoformat(),
            'corrected_completion_hours': corrected_hours, 'adverse_unchanged': True, 'source': 'march-reschedule'}],
        'verdict': 'PASS',
        'limitations': ['Offline timestamps/hash pins corroborate the recorded acquisition order, not an independently timestamped preregistration service.',
            'ESPN event start is the resumption start for three suspended games; actual second-half final whistles and official completion reviews preserve their original-delay exposure.',
            'Generic possible future rescheduling is not a fixture-specific alternative original; explicit earlier PDF alternatives retained, later alternatives cannot raise a bound.',
            'One historical regular season only; no transfer to playoffs, other leagues, or a profitability claim.'],
        'rows': rows,
        'corrected_rows': corrected_rows,
        'original_candidate_dates': [{'home': key[0], 'away': key[1], **originals[key]} for key in sorted(originals)]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = replay()
    if args.output:
        with args.output.open('x') as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k not in {'rows', 'corrected_rows', 'original_candidate_dates'}}, indent=2, sort_keys=True))
