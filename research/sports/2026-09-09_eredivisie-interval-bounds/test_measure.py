"""Research-only semantic regressions; synthetic payloads require no network or raw disk."""
import copy
from datetime import datetime, timedelta
import importlib.util
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

HERE = Path(__file__).resolve().parent


def module(name):
    spec = importlib.util.spec_from_file_location('l50_' + name, HERE / (name + '.py'))
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


measure = module('measure')
review = module('review')


def summary():
    return {'header': {'id': '123', 'league': {'slug': 'ned.1'},
                       'season': {'year': 2025, 'type': 13484},
                       'competitions': [{'date': '2026-02-15T13:30:00Z',
                         'status': {'type': {'completed': True}},
                         'competitors': [{'homeAway': 'home', 'team': {'id': '151'}},
                                         {'homeAway': 'away', 'team': {'id': '147'}}]}]},
            'keyEvents': [{'type': {'type': 'end-regular-time'}, 'period': {'number': 2},
                           'wallclock': '2026-02-17T20:45:21Z'}]}


def test_actual_final_whistle_detects_long_suspension_with_unchanged_kickoff():
    started, finished = measure.final_whistle(summary(), '123', ('151', '147'))
    assert finished == datetime.fromisoformat('2026-02-17T20:45:21+00:00')
    assert measure.completion_delayed(started, finished)


@pytest.mark.parametrize('mutation', ['missing_clock', 'last_updated_only', 'wrong_period', 'duplicate_ending'])
def test_no_clock_fallback_or_ambiguous_final(mutation):
    payload = summary()
    if mutation in ('missing_clock', 'last_updated_only'):
        payload['keyEvents'][0].pop('wallclock')
        payload['lastUpdated'] = '2026-02-15T15:30:00Z'
    elif mutation == 'wrong_period':
        payload['keyEvents'][0]['period']['number'] = 1
    else:
        payload['keyEvents'] *= 2
    with pytest.raises(ValueError, match='final whistle'):
        measure.final_whistle(payload, '123', ('151', '147'))


@pytest.mark.parametrize('mutation', ['wrong_event', 'wrong_league', 'wrong_year', 'postseason',
                                     'wrong_team', 'duplicate_side', 'open', 'backward_clock', 'naive_clock'])
def test_summary_identity_population_and_terminal_gates(mutation):
    payload = summary()
    header = payload['header']
    competition = header['competitions'][0]
    if mutation == 'wrong_event': header['id'] = '124'
    if mutation == 'wrong_league': header['league']['slug'] = 'usa.1'
    if mutation == 'wrong_year': header['season']['year'] = 2026
    if mutation == 'postseason': header['season']['type'] = 13482
    if mutation == 'wrong_team': competition['competitors'][0]['team']['id'] = '139'
    if mutation == 'duplicate_side': competition['competitors'][0]['homeAway'] = 'away'
    if mutation == 'open': competition['status']['type']['completed'] = False
    if mutation == 'backward_clock': payload['keyEvents'][0]['wallclock'] = '2026-02-14T12:00:00Z'
    if mutation == 'naive_clock': payload['keyEvents'][0]['wallclock'] = '2026-02-17T20:45:21'
    with pytest.raises(ValueError):
        measure.final_whistle(payload, '123', ('151', '147'))


@pytest.mark.parametrize('season', [
    {'year': 2025, 'slug': 'unknown', 'type': 13484},
    {'year': 2025, 'slug': 'regular-season', 'type': 13482},
    {'year': 2024, 'slug': 'regular-season', 'type': 13484},
])
def test_unknown_inventory_phase_cannot_be_silently_excluded(season):
    with pytest.raises(ValueError, match='season/phase'):
        measure.regular_season({'season': season})


def test_explicit_playoffs_are_excluded_structurally():
    assert not measure.regular_season({'season': {'year': 2025, 'type': 13482,
                                                'slug': 'conference-league-playoffs---final'}})


def test_deadline_is_elapsed_utc_and_unknown_alternative_is_adverse():
    # Spring DST transition: two local calendar midnights span only 47 hours.
    original = datetime(2026, 3, 28, tzinfo=ZoneInfo('Europe/Amsterdam'))
    exact = datetime.fromisoformat('2026-03-30T00:00:00+01:00')
    assert not measure.completion_delayed(original, exact)
    assert measure.completion_delayed(original, exact + timedelta(seconds=1))
    assert measure.completion_delayed(original, original, unbounded=True)
    with pytest.raises(ValueError, match='Naive'):
        measure.completion_delayed(datetime(2026, 3, 28), exact)


def test_alternative_duplicates_and_earliest_dates_are_never_dropped():
    rows = json.loads((HERE / 'original_bounds.json').read_text())['rows']
    originals = {(r['home'], r['away']): r for r in rows}
    assert len(rows) == len(originals) == 306
    assert originals['AZ', 'PEC Zwolle']['candidate_calendar_dates'] == ['2025-08-24', '2025-09-24']
    assert originals['Feyenoord', 'Fortuna Sittard']['earliest_original_date'] == '2025-09-17'
    assert originals['AZ', 'FC Twente']['earliest_original_date'] == '2026-05-02'
    assert originals['Heracles Almelo', 'Sparta Rotterdam']['earliest_original_date'] == '2025-09-27'
    assert originals['AZ', 'Excelsior Rotterdam']['earliest_original_date'] == '2025-12-14'
    assert all(r['earliest_original_local_clock'] == '00:00:00' for r in rows)


def test_exact_confidence_bound_nonzero_and_binomial_examples():
    assert measure.upper95(0, 306) == pytest.approx(1 - 0.05 ** (1 / 306))
    assert measure.upper95(1, 2) == pytest.approx(math.sqrt(0.95))
    assert measure.upper95(306, 306) == 1
    for k, n in [(-1, 306), (307, 306), (0, 0)]:
        with pytest.raises(ValueError): measure.upper95(k, n)


def artifacts():
    return tuple(json.loads((HERE / name).read_text()) for name in
                 ('results.json', 'official_review.json', 'source_manifest.json'))


def test_full_official_review_still_cannot_register_without_independent_replay():
    result, reviewed, sources = artifacts()
    output = review.review_result(result, reviewed, sources)
    assert output['official_review_passed']
    assert output['verdict'] == 'BLOCKED_PENDING_INDEPENDENT_REPLAY'
    assert not output['independent_replay_passed']
    assert not output['registered_rates']


@pytest.mark.parametrize('mutation', ['missing_exception', 'extra_exception', 'wrong_team', 'wrong_day',
                                     'missing_suspension_completion', 'failed_source', 'unofficial', 'incomplete'])
def test_review_fails_closed(mutation):
    result, reviewed, sources = artifacts()
    event = reviewed['events']['741100']
    if mutation == 'missing_exception': reviewed['events'].pop('741100')
    if mutation == 'extra_exception': reviewed['events']['0'] = copy.deepcopy(event)
    if mutation == 'wrong_team': event['home'] = 'AZ'
    if mutation == 'wrong_day': event['final_date_local'] = '2025-12-03'
    if mutation == 'missing_suspension_completion': event.pop('completion_date_local')
    if mutation == 'failed_source': sources['sources']['ajax-completion']['status'] = 403
    if mutation == 'unofficial': sources['sources']['ajax-completion']['url'] = 'https://example.org/'
    if mutation == 'incomplete': result['final_whistles'] = 305
    with pytest.raises(ValueError): review.review_result(result, reviewed, sources)


def test_correction_is_append_only_and_only_adds_conservatism():
    corrections = module('apply_corrections')
    original = json.loads((HERE / 'original_bounds.json').read_text())
    change = json.loads((HERE / 'original_bounds_corrections.json').read_text())
    sources = json.loads((HERE / 'source_manifest.json').read_text())
    corrected = corrections.corrected_bounds(original, change, sources)
    before = next(r for r in original['rows'] if (r['home'], r['away']) == ('Heracles Almelo', 'FC Utrecht'))
    after = next(r for r in corrected['rows'] if (r['home'], r['away']) == ('Heracles Almelo', 'FC Utrecht'))
    assert before['earliest_original_date'] == '2026-03-07'
    assert after['earliest_original_date'] == '2026-03-06'
    assert after['candidate_calendar_dates'] == ['2026-03-06', '2026-03-07']
    assert after['post_freeze_corrections'][0]['published'] == '2026-02-02'
    change['corrections'][0]['new_lower_date'] = '2026-03-08'
    with pytest.raises(ValueError, match='strictly lower'):
        corrections.corrected_bounds(original, change, sources)


def test_corrected_review_retains_originally_required_exception():
    result = json.loads((HERE / 'results_corrected.json').read_text())
    reviewed = json.loads((HERE / 'official_review_corrected.json').read_text())
    sources = json.loads((HERE / 'source_manifest.json').read_text())
    advanced = next(r for r in result['rows'] if r['event_id'] == '741209')
    assert not advanced['review_required']
    assert advanced['initial_review_required']
    assert len(reviewed['events']) == 15
    assert review.review_result(result, reviewed, sources)['official_review_passed']
    reviewed['events'].pop('741209')
    with pytest.raises(ValueError, match='full exception'):
        review.review_result(result, reviewed, sources)
