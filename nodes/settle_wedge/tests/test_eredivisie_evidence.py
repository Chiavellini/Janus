"""L50's own population and rates enable Eredivisie; wording alone never does."""
import json
from pathlib import Path

import pytest

from nodes.settle_wedge.equivalence import NotEquivalent, SettlementEquivalence, certify


POPULATION = {'source': 'espn', 'game_id': 'espn:ere:741100', 'league': 'ere',
              'season_slug': 'regular-season'}
RESEARCH = Path(__file__).resolve().parents[3] / 'research/sports/2026-09-09_eredivisie-interval-bounds'


def records():
    from nodes.settle_wedge.harvest import harvest_kalshi, harvest_polymarket
    from nodes.settle_wedge.policy import KALSHI_ERE_GAME_V1, POLYMARKET_SOCCER_GAME_V3
    kt, pt = KALSHI_ERE_GAME_V1, POLYMARKET_SOCCER_GAME_V3
    return (harvest_kalshi({'ticker': 't', 'rules_primary': kt.sample_text},
                           participants=kt.sample_participants, retrieved_at=1800000000),
            harvest_polymarket({'slug': 's', 'description': pt.sample_text},
                               participants=pt.sample_participants, retrieved_at=1800000000))


def slate():
    from nodes.settle_wedge.policy import KALSHI_ERE_GAME_V1, POLYMARKET_SOCCER_GAME_V3
    kt, pt = KALSHI_ERE_GAME_V1, POLYMARKET_SOCCER_GAME_V3
    return {'game_id': POPULATION['game_id'], 'league': 'ere', 'schedule_population': dict(POPULATION),
            'rules': {'kalshi': {'market': {'ticker': 't', 'rules_primary': kt.sample_text},
                                 'participants': kt.sample_participants},
                      'polymarket': {'market': {'slug': 's', 'description': pt.sample_text},
                                     'participants': pt.sample_participants}}}


def test_registered_rates_have_complete_independent_population_and_nonzero_cancel_bound():
    from nodes.entities.leagues import default_leagues, enablement
    from nodes.settle_wedge.evidence import EVIDENCE
    result = json.loads((RESEARCH / 'results_registered.json').read_text())
    assert result['verdict'] == 'REGISTERED'
    assert result['independent_replay_passed'] and result['official_review_passed']
    assert result['original_fixtures'] == result['final_whistles'] == 306
    assert not result['failures']
    assert result['provisional_counts'] == {'delay_adverse': 7, 'cancelled': 0}
    for key, value in result['registered_rates'].items():
        evidence = EVIDENCE[key]
        assert evidence.value == value > 0
        assert evidence.n == 306
        assert evidence.research_ref.endswith('2026-09-09_eredivisie-interval-bounds/spec.yaml')
    assert enablement('ere') == [] and 'ere' in default_leagues()


def test_every_dimension_ruled_and_each_registered_rate_charged_once():
    from nodes.settle_wedge.policy import DIMENSIONS
    proof = certify(*records(), league='ere', population=POPULATION)
    assert isinstance(proof, SettlementEquivalence)
    assert {v.dimension for v in proof.verdicts} == set(DIMENSIONS)
    assert {v.evidence_key for v in proof.verdicts if v.outcome == 'BOUNDED'} == set(proof.rates)
    assert set(proof.rates) == {'soccer.ere.cancelled_rate', 'soccer.ere.postponed_gt48h_rate'}
    assert proof.as_record()['evidence_population'] == 'regular-season'
    assert proof.as_record()['schedule_game_id'] == POPULATION['game_id']
    assert proof.settlement_buffer([('kalshi', 0.3), ('polymarket', 0.5)]) == pytest.approx(
        0.5 * (0.009742208949783377 + 0.04253671926053953))
    suspended = next(v for v in proof.verdicts if v.dimension == 'suspended')
    assert suspended.outcome == 'SAME' and suspended.evidence_key is None
    assert 'L50' in suspended.detail


@pytest.mark.parametrize('population', [
    None, {}, 'regular-season',
    {**POPULATION, 'source': 'venue_structured'},
    {**POPULATION, 'league': 'mls'},
    {**POPULATION, 'game_id': 'espn:mls:741100'},
    {**POPULATION, 'game_id': 'espn:ere:'},
    {**POPULATION, 'game_id': 'espn:ere:741100:other'},
    {**POPULATION, 'season_slug': ''},
    {**POPULATION, 'season_slug': 'pre-season'},
    {**POPULATION, 'season_slug': 'post-season'},
    {**POPULATION, 'season_slug': 'conference-league-playoffs---semifinals'},
    {**POPULATION, 'season_slug': 'conference-league-playoffs---final'},
])
def test_wrong_unknown_or_playoff_population_blocks_even_with_injected_rates(population):
    proof = certify(*records(), league='ere', population=population,
                    rates={'soccer.ere.cancelled_rate': 0, 'soccer.ere.postponed_gt48h_rate': 0})
    assert isinstance(proof, NotEquivalent)
    assert proof.code == 'EVIDENCE_POPULATION_MISMATCH'


def test_slate_population_must_name_the_exact_game_and_survive_recertification():
    from nodes.settle_wedge.pair import certify_from_spec
    spec = slate()
    assert isinstance(certify_from_spec(spec, 'ere'), SettlementEquivalence)
    spec['game_id'] = 'espn:ere:741101'
    assert certify_from_spec(spec, 'ere').code == 'EVIDENCE_POPULATION_MISMATCH'
    spec.pop('schedule_population')
    assert certify_from_spec(spec, 'ere').code == 'EVIDENCE_POPULATION_MISMATCH'


def test_no_other_league_or_partial_evidence_can_substitute(monkeypatch):
    from nodes.entities.leagues import enablement
    from nodes.settle_wedge.evidence import EVIDENCE
    # Both MLS rates remain present; they cannot fill the missing Eredivisie key.
    monkeypatch.delitem(EVIDENCE, 'soccer.ere.cancelled_rate')
    assert enablement('ere') == ['EVIDENCE_UNMEASURED:soccer.ere.cancelled_rate']
    proof = certify(*records(), league='ere', population=POPULATION)
    assert isinstance(proof, NotEquivalent) and proof.code == 'EVIDENCE_UNMEASURED'
    assert enablement('mls') == []
