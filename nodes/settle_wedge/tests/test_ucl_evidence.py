"""UCL reserves require a complete, independently anchored league-phase population."""
import importlib.util
import math
import hashlib
import json
import runpy
from datetime import datetime
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[3] / 'research/sports/2026-09-09_ucl-settlement-bounds/measure.py'
_SPEC = importlib.util.spec_from_file_location('ucl_settlement_measure', _PATH)
measure = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(measure)

POPULATION = {'source': 'espn', 'league': 'ucl', 'game_id': 'espn:ucl:720437', 'season_slug': 'league-phase'}
KEYS = {'soccer.ucl.cancelled_rate', 'soccer.ucl.postponed_gt48h_rate'}


def records():
    from nodes.settle_wedge.harvest import harvest_kalshi, harvest_polymarket
    from nodes.settle_wedge.policy import KALSHI_UCL_GAME_V1, POLYMARKET_SOCCER_GAME_V3
    k, p = KALSHI_UCL_GAME_V1, POLYMARKET_SOCCER_GAME_V3
    return (harvest_kalshi({'ticker': 't', 'rules_primary': k.sample_text},
                         participants=k.sample_participants, retrieved_at=1800000000),
            harvest_polymarket({'slug': 's', 'description': p.sample_text},
                               participants=p.sample_participants, retrieved_at=1800000000))


@pytest.mark.parametrize('population', [
    None, {}, 'league-phase', {**POPULATION, 'season_slug': ''},
    {**POPULATION, 'season_slug': 'group-stage'}, {**POPULATION, 'season_slug': 'qualifying'},
    {**POPULATION, 'season_slug': 'round-of-16'}, {**POPULATION, 'season_slug': 'regular-season'},
    {**POPULATION, 'source': 'venue_structured'}, {**POPULATION, 'league': 'epl'},
    {**POPULATION, 'game_id': 'espn:epl:720437'}, {**POPULATION, 'game_id': 'espn:ucl:'},
    {**POPULATION, 'game_id': 'espn:ucl:720437:other'},
])
def test_population_blocks_even_if_rates_supplied(population):
    from nodes.settle_wedge.equivalence import NotEquivalent, certify
    result = certify(*records(), league='ucl', population=population, rates={k: 0 for k in KEYS})
    assert isinstance(result, NotEquivalent)
    assert result.code == 'EVIDENCE_POPULATION_MISMATCH'


@pytest.mark.parametrize('rates', [{}, {'soccer.epl.cancelled_rate': 0, 'soccer.epl.postponed_gt48h_rate': 0},
                                  {'soccer.ucl.cancelled_rate': .02}, {'soccer.ucl.postponed_gt48h_rate': .02}])
def test_missing_ucl_bound_blocks_and_other_league_cannot_substitute(rates, monkeypatch):
    from nodes.settle_wedge.equivalence import NotEquivalent, certify
    from nodes.settle_wedge.evidence import EVIDENCE
    for key in KEYS:
        monkeypatch.delitem(EVIDENCE, key)
    result = certify(*records(), league='ucl', population=POPULATION, rates=rates)
    assert isinstance(result, NotEquivalent)
    assert result.code == 'EVIDENCE_UNMEASURED'


def test_registered_ucl_proof_binds_population_and_reserves_each_dimension():
    from nodes.entities.leagues import enablement
    from nodes.settle_wedge.equivalence import SettlementEquivalence, certify
    from nodes.settle_wedge.evidence import EVIDENCE
    result = certify(*records(), league='ucl', population=POPULATION)
    assert isinstance(result, SettlementEquivalence)
    assert enablement('ucl') == []
    assert set(result.rates) == KEYS
    assert result.as_record()['evidence_population'] == 'league-phase'
    assert result.as_record()['schedule_game_id'] == POPULATION['game_id']
    assert result.settlement_buffer([('kalshi', .3), ('polymarket', .5)]) == pytest.approx(measure.upper95(0, 144))
    for key in KEYS:
        assert EVIDENCE[key].value > 0
        assert EVIDENCE[key].n == 144
        assert EVIDENCE[key].research_ref.endswith('2026-09-09_ucl-settlement-bounds/spec.yaml')


def test_upper_bound_zero_observations_is_positive_and_exact():
    assert measure.upper95(0, 144) == pytest.approx(1 - .05 ** (1 / 144))
    assert measure.upper95(1, 2) == pytest.approx(math.sqrt(.95))
    with pytest.raises(ValueError):
        measure.upper95(0, 0)


def test_completion_deadline_is_conservative_in_eastern_calendar_and_elapsed_time():
    original = datetime.fromisoformat('2024-09-17T23:00:00-04:00')
    assert not measure.delayed(original, datetime.fromisoformat('2024-09-18T23:59:59-04:00'))
    assert measure.delayed(original, datetime.fromisoformat('2024-09-19T00:00:00-04:00'))
    assert measure.delayed(original, datetime.fromisoformat('2024-09-20T00:00:00-04:00'))


def report_text():
    return ('Full Time Report\nMatchday 4 - Wednesday 6 November 2024\n'
            'FC Bayern München SL Benfica\n00:51:07CET\n07 Nov 2024 C Captain')


def test_actual_terminal_report_bounds_completion_and_preserves_next_day():
    fixtures = [{'home': 'FC Bayern München', 'away': 'SL Benfica'}]
    _, upper, date = measure.report(report_text(), fixtures)
    assert upper == datetime.fromisoformat('2024-11-07T00:51:07+01:00')
    assert date.isoformat() == '2024-11-06'


@pytest.mark.parametrize('text', [
    report_text().replace('Full Time Report', 'Half Time Report'),
    report_text().replace('00:51:07CET', '00:51:07'),
    report_text().replace('Matchday 4', 'Quarter-final'),
    report_text().replace('SL Benfica', 'Other Club'),
])
def test_unknown_nonterminal_or_wrong_fixture_report_blocks(text):
    with pytest.raises(ValueError):
        measure.report(text, [{'home': 'FC Bayern München', 'away': 'SL Benfica'}])


def test_population_must_survive_recertification_with_exact_game_id():
    from nodes.settle_wedge.equivalence import NotEquivalent, SettlementEquivalence
    from nodes.settle_wedge.pair import certify_from_spec
    from nodes.settle_wedge.policy import KALSHI_UCL_GAME_V1, POLYMARKET_SOCCER_GAME_V3
    k, p = KALSHI_UCL_GAME_V1, POLYMARKET_SOCCER_GAME_V3
    spec = {'league': 'ucl', 'game_id': POPULATION['game_id'], 'schedule_population': POPULATION,
            'rules': {'kalshi': {'market': {'ticker': 't', 'rules_primary': k.sample_text}, 'participants': k.sample_participants},
                      'polymarket': {'market': {'slug': 's', 'description': p.sample_text}, 'participants': p.sample_participants}}}
    assert isinstance(certify_from_spec(spec, 'ucl'), SettlementEquivalence)
    spec['game_id'] = 'espn:ucl:720438'
    assert isinstance(certify_from_spec(spec, 'ucl'), NotEquivalent)


@pytest.fixture
def frozen_source_set(tmp_path):
    sources = dict(runpy.run_path(str(_PATH.with_name('collect.py')))['SOURCES'])
    sources.update({f'summary-{i}.json': f'https://site.web.api.espn.com/apis/site/v2/sports/soccer/uefa.champions/summary?event={i}' for i in range(144)})
    sources.update({f'uefa-report-{i}.pdf': f'https://www.uefa.com/newsfiles/UCL/2025/{i}_FR.pdf' for i in range(144)})
    for name, url in sources.items():
        raw = b'synthetic source'
        if name == 'espn-scoreboard.json':
            raw = json.dumps({'events': [{'id': str(i)} for i in range(144)]}).encode()
        if name == 'uefa-results.html':
            raw = ('League phase </h2>' + ''.join(f'/match/{i} ' for i in range(144)) + '</article>').encode()
        path = tmp_path / name
        path.write_bytes(raw)
        (tmp_path / (name + '.meta.json')).write_text(json.dumps({
            'path': str(path), 'url': url, 'status': 200, 'headers': {},
            'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
            'retrieved_at': '2026-09-09T22:00:00+00:00'}))
    return tmp_path


def test_exact_frozen_source_set_has_294_verified_unique_entries(frozen_source_set):
    manifest = measure.source_manifest(frozen_source_set)
    assert len(manifest) == len({m['path'] for m in manifest}) == 294


@pytest.mark.parametrize('name', ['uefa-report-0.pdf', 'uefa-report-0.pdf.meta.json',
                                 'summary-0.json', 'original-2024-pot.pdf.meta.json'])
def test_missing_source_or_sidecar_fails_closed(frozen_source_set, name):
    # Rename only synthetic test fixtures; no deletion or mutation of frozen evidence.
    path = frozen_source_set / name
    path.rename(frozen_source_set.parent / ('removed-' + name))
    with pytest.raises(ValueError, match='Missing'):
        measure.source_manifest(frozen_source_set)


def test_tampered_source_hash_fails_closed(frozen_source_set):
    (frozen_source_set / 'uefa-report-0.pdf').write_bytes(b'tampered source')
    with pytest.raises(ValueError, match='hash/size mismatch'):
        measure.source_manifest(frozen_source_set)


@pytest.mark.parametrize('name', ['orphan.pdf', 'orphan.pdf.meta.json'])
def test_orphan_source_or_sidecar_fails_closed(frozen_source_set, name):
    (frozen_source_set / name).write_text('{}')
    with pytest.raises(ValueError, match='orphan'):
        measure.source_manifest(frozen_source_set)


@pytest.mark.parametrize('field,value', [('path', 'duplicate'), ('url', 'https://example.com/wrong'),
                                      ('status', 404), ('retrieved_at', '2026-09-09')])
def test_wrong_source_metadata_fails_closed(frozen_source_set, field, value):
    path = frozen_source_set / 'uefa-report-0.pdf.meta.json'
    metadata = json.loads(path.read_text())
    metadata[field] = str(frozen_source_set / 'uefa-report-1.pdf') if value == 'duplicate' else value
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError):
        measure.source_manifest(frozen_source_set)
