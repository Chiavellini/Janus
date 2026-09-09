"""The MLS source cannot silently turn kickoff/update time into match completion."""
import importlib.util
import math
from datetime import datetime
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[3] / 'research/sports/2026-09-09_mls-original-schedule/measure.py'
_SPEC = importlib.util.spec_from_file_location('mls_settlement_measure', _PATH)
measure = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(measure)


def summary():
    return {'header': {'id': '123', 'competitions': [
        {'date': '2025-07-04T23:30:00Z', 'status': {'type': {'completed': True}}}]},
        'keyEvents': [{'type': {'type': 'end-regular-time'}, 'period': {'number': 2},
                       'wallclock': '2025-07-08T01:30:00Z'}]}


def test_final_whistle_preserves_long_suspension_despite_original_kickoff():
    finished = measure.final_whistle(summary(), '123')
    assert finished == datetime.fromisoformat('2025-07-08T01:30:00+00:00')
    assert measure.completion_delayed(datetime.fromisoformat('2025-07-04T19:30:00-04:00'), finished)


def test_missing_final_whistle_cannot_fall_back_to_update_or_kickoff():
    payload = summary()
    payload['keyEvents'][0].pop('wallclock')
    payload['meta'] = {'lastUpdatedAt': '2025-07-05T01:30:00Z', 'lastPlayWallClock': '2025-07-05T01:30:00Z'}
    with pytest.raises(ValueError, match='final-whistle'):
        measure.final_whistle(payload, '123')


def test_wrong_event_and_open_game_fail_closed():
    with pytest.raises(ValueError, match='Wrong summary'):
        measure.final_whistle(summary(), '124')
    payload = summary()
    payload['header']['competitions'][0]['status']['type']['completed'] = False
    with pytest.raises(ValueError, match='non-final'):
        measure.final_whistle(payload, '123')


def test_duplicate_final_whistle_is_ambiguous():
    payload = summary()
    payload['keyEvents'] *= 2
    with pytest.raises(ValueError, match='ambiguous'):
        measure.final_whistle(payload, '123')


def test_two_day_boundary_is_conservative_and_uses_eastern_day():
    original = datetime.fromisoformat('2025-07-04T23:30:00-04:00')
    # Only 24.5 elapsed hours, but two Eastern calendar dates: counted conservatively.
    assert measure.completion_delayed(original, datetime.fromisoformat('2025-07-06T00:00:00-04:00'))
    assert not measure.completion_delayed(original, datetime.fromisoformat('2025-07-06T00:00:00+00:00'))


def test_upper_bound_is_never_zero_and_matches_exact_binomial_examples():
    assert measure.upper95(0, 510) == pytest.approx(1 - 0.05 ** (1 / 510))
    assert measure.upper95(1, 1) == 1
    assert measure.upper95(1, 2) == pytest.approx(math.sqrt(0.95))
    with pytest.raises(ValueError):
        measure.upper95(0, 0)


def test_registration_requires_every_exception_and_completion_gate():
    row = {'event_id': '123', 'actual_start': '2025-07-08T01:30:00+00:00',
           'finished': '2025-07-08T03:30:00+00:00',
           'kickoff_date_changed': True, 'moved_gt48h_conservative': True}
    result = {'rows': [row], 'failures': [], 'gates': {'original_complete': True,
              'final_complete_unique_join': True, 'suspensions_detected_via_final_whistle': True,
              'official_date_mismatch_review': False}, 'upper95_provisional': {'cancelled_rate': 0.1}}
    with pytest.raises(ValueError, match='full exception'):
        measure.reviewed_result(result, {'events': {}})
    review = {'events': {'123': {'final_date_eastern': '2025-07-07', 'source': 'https://www.mlssoccer.com/example'}}}
    assert measure.reviewed_result(result, review)['verdict'] == 'REGISTERED'
    result['gates']['suspensions_detected_via_final_whistle'] = False
    with pytest.raises(ValueError, match='incomplete population'):
        measure.reviewed_result(result, review)


def test_suspension_only_move_needs_official_completion_not_kickoff_confirmation():
    row = {'event_id': '123', 'actual_start': '2025-07-05T01:30:00+00:00',
           'finished': '2025-07-08T03:30:00+00:00',
           'kickoff_date_changed': False, 'moved_gt48h_conservative': True}
    result = {'rows': [row], 'failures': [], 'gates': {'original_complete': True,
              'final_complete_unique_join': True, 'suspensions_detected_via_final_whistle': True,
              'official_date_mismatch_review': False}, 'upper95_provisional': {}}
    review = {'events': {'123': {'final_date_eastern': '2025-07-04',
                                'source': 'https://www.mlssoccer.com/example'}}}
    with pytest.raises(ValueError, match='official completion date'):
        measure.reviewed_result(result, review)
    review['events']['123']['completion_date_eastern'] = '2025-07-07'
    assert measure.reviewed_result(result, review)['verdict'] == 'REGISTERED'


def mls_records():
    from nodes.settle_wedge.harvest import harvest_kalshi, harvest_polymarket
    from nodes.settle_wedge.policy import KALSHI_MLS_GAME_V1, POLYMARKET_SOCCER_GAME_V3
    kt, pt = KALSHI_MLS_GAME_V1, POLYMARKET_SOCCER_GAME_V3
    k = harvest_kalshi({'ticker': 't', 'rules_primary': kt.sample_text.split('\n')[0],
                        'rules_secondary': kt.sample_text.split('\n', 1)[1]},
                       participants=kt.sample_participants, retrieved_at=1800000000)
    p = harvest_polymarket({'slug': 's', 'description': pt.sample_text},
                           participants=pt.sample_participants, retrieved_at=1800000000)
    return k, p


MLS_POPULATION = {'source': 'espn', 'game_id': 'espn:mls:761787', 'league': 'mls',
                  'season_slug': 'regular-season'}


def test_mls_certifies_from_own_registered_bounds_and_charges_each_once():
    from nodes.entities.leagues import enablement
    from nodes.settle_wedge.equivalence import SettlementEquivalence, certify
    from nodes.settle_wedge.evidence import EVIDENCE
    proof = certify(*mls_records(), league='mls', population=MLS_POPULATION)
    assert isinstance(proof, SettlementEquivalence)
    assert enablement('mls') == []
    assert proof.as_record()['evidence_population'] == 'regular-season'
    assert proof.as_record()['schedule_game_id'] == 'espn:mls:761787'
    assert set(proof.rates) == {'soccer.mls.cancelled_rate', 'soccer.mls.postponed_gt48h_rate'}
    assert proof.settlement_buffer([('kalshi', 0.3), ('polymarket', 0.5)]) == pytest.approx(
        0.5 * (measure.upper95(0, 510) + measure.upper95(13, 510)))
    for key in proof.rates:
        assert EVIDENCE[key].research_ref.endswith('2026-09-09_mls-original-schedule/spec.yaml')


@pytest.mark.parametrize('population', [
    None, {}, 'regular-season', {**MLS_POPULATION, 'season_slug': ''},
    {**MLS_POPULATION, 'season_slug': 'post-season'},
    {**MLS_POPULATION, 'season_slug': 'preseason'},
    {**MLS_POPULATION, 'source': 'venue_structured'},
    {**MLS_POPULATION, 'league': 'epl'},
    {**MLS_POPULATION, 'game_id': 'espn:epl:761787'},
    {**MLS_POPULATION, 'game_id': 'espn:mls:'},
])
def test_mls_missing_unknown_or_wrong_population_fails_closed_even_with_rates(population):
    from nodes.settle_wedge.equivalence import NotEquivalent, certify
    proof = certify(*mls_records(), league='mls', population=population,
                    rates={'soccer.mls.cancelled_rate': 0, 'soccer.mls.postponed_gt48h_rate': 0})
    assert isinstance(proof, NotEquivalent)
    assert proof.code == 'EVIDENCE_POPULATION_MISMATCH'


def test_mls_spec_population_reaches_recertification_and_legacy_spec_blocks():
    from nodes.settle_wedge.equivalence import NotEquivalent, SettlementEquivalence
    from nodes.settle_wedge.pair import certify_from_spec
    from nodes.settle_wedge.policy import KALSHI_MLS_GAME_V1, POLYMARKET_SOCCER_GAME_V3
    kt, pt = KALSHI_MLS_GAME_V1, POLYMARKET_SOCCER_GAME_V3
    spec = {'game_id': 'espn:mls:761787', 'league': 'mls', 'rules': {
        'kalshi': {'market': {'ticker': 't', 'rules_primary': kt.sample_text},
                   'participants': kt.sample_participants},
        'polymarket': {'market': {'slug': 's', 'description': pt.sample_text},
                       'participants': pt.sample_participants}}}
    assert isinstance(certify_from_spec(spec, 'mls'), NotEquivalent)
    spec['schedule_population'] = MLS_POPULATION
    assert isinstance(certify_from_spec(spec, 'mls'), SettlementEquivalence)
    spec['game_id'] = 'espn:mls:761788'
    assert isinstance(certify_from_spec(spec, 'mls'), NotEquivalent)
    spec['game_id'] = 'espn:mls:761787'
    spec['schedule_population'] = {**MLS_POPULATION, 'season_slug': 'post-season'}
    assert isinstance(certify_from_spec(spec, 'mls'), NotEquivalent)


def test_shared_population_adapter_does_not_invent_missing_season_classification():
    from dataclasses import replace
    from nodes.schedule_espn.espn import ScheduledGame
    from nodes.settle_wedge.pair import population_from_schedule
    game = ScheduledGame('espn:mls:761787', 'mls', 1800000000, '1', '2', 'Home', 'Away',
                         'in', False, False, False, 'regular-season', 'A @ H', 'A @ H')
    assert population_from_schedule(game) == MLS_POPULATION
    assert population_from_schedule(replace(game, season_slug=''))['season_slug'] == ''
    assert population_from_schedule(replace(game, season_slug='post-season'))['season_slug'] == 'post-season'


def test_mls_paper_allowance_does_not_change_outer_event_or_day_limits():
    from nodes.risk.limits import load_limits
    limits = load_limits()
    assert limits.league_cap('mls') == 200
    assert limits.max_event_notional_usd == 200
    assert limits.max_daily_realized_loss_usd == 25
