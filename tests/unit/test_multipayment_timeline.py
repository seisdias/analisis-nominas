"""Separate documentary points do not assert additivity or resolve evidence."""
from copy import deepcopy
from dataclasses import replace

import pytest

from src.analytic_dataset import DocumentCategory as C
from src.analytic_dataset import VersionProvenance
from src.canonical.facts import DocumentaryFact, FactDraft
from src.canonical.serialization import deterministic_id
from src.canonical.values import CanonicalValue, CurrencyCode, ExactDecimal, ValueState
from src.payroll_timeline import category_average, category_chart, classified_timeline
from tests.unit.test_payroll_timeline import analytic, record, year_records

TYPES = {C.ORDINARY: 'NOMINA_ORDINARIA', C.EXTRA: 'PAGA_EXTRA', C.SETTLEMENT: 'FINIQUITO'}


def documented(identity, category, interval=None):
    extraction = deterministic_id('extraction', identity)
    values = {'tipo': TYPES.get(category, 'unknown')}
    if interval:
        values.update(zip(('fecha_inicio', 'fecha_fin'), interval))
    facts = tuple(DocumentaryFact.from_draft(extraction, FactDraft('nomina.' + key,
                  CanonicalValue(state=ValueState.PRESENT, value=value)))
                  for key, value in values.items())
    return replace(analytic(identity, category), original_document_type=values['tipo'],
                   context_facts=facts,
                   provenance=(VersionProvenance('v1', 'file', 'a'*64, (1,), (extraction,)),))


def plot(rows, docs, **kwargs):
    return classified_timeline(rows, docs, years=(2025, 2025), **kwargs)


def test_ordinary_extra_individual_exact_stable_no_mutation():
    rows = [record('a'), record('b')]
    rows[1]['value']['amount'] = ExactDecimal(987654321, 5)
    docs = [documented('a', C.ORDINARY), documented('b', C.EXTRA)]
    before = deepcopy(rows)
    result = plot(rows, docs)
    assert len(result.points) == 2 and result.ambiguous_periods == 0
    assert {p['Documento'] for p in result.points} == {'a', 'b'}
    assert result.points[1]['Importe exacto'] == '9.876,54321 €'
    assert all(p['Multipago'] for p in result.points)
    assert all(r['Elegibilidad'] == 'evidence_only' for r in result.table)
    assert rows == before
    assert plot(list(reversed(rows)), list(reversed(docs))) == result
    assert plot(rows + [deepcopy(rows[0])], docs) == result


def test_disjoint_documented_intervals_preserved_not_assumed_full_month():
    docs = [documented('a', C.SETTLEMENT, ('2025-01-01', '2025-01-09')),
            documented('b', C.SETTLEMENT, ('2025-01-10', '2025-01-31'))]
    result = plot([record('a'), record('b')], docs)
    assert len(result.points) == 2
    assert [p['Intervalo documental'] for p in result.points] == [
        '2025-01-01 → 2025-01-09', '2025-01-10 → 2025-01-31']
    assert all(r['Versiones del soporte'] == 'v1' for r in result.table)


@pytest.mark.parametrize('interval', [None, ('2025-01-09', '2025-01-31'),
    ('2025-01-31', '2025-01-10'), ('bad', '2025-01-31')])
def test_same_category_missing_overlapping_invalid_interval_blocks(interval):
    docs = [documented('a', C.ORDINARY, ('2025-01-01', '2025-01-09')),
            documented('b', C.ORDINARY, interval)]
    assert not plot([record('a'), record('b')], docs).points


def test_competing_observations_and_unresolved_versions_block():
    rows = [record('a'), record('b')]
    docs = [documented('a', C.ORDINARY), documented('b', C.EXTRA)]
    other = deepcopy(rows[0])
    other['observation_id'] = 'alternative'
    assert not plot(rows + [other], docs).points
    rows[0]['version_ids'] = ('v1', 'v2')
    assert not plot(rows, docs).points


@pytest.mark.parametrize('change', ['uncertified', 'currency', 'company', 'period'])
def test_existing_value_and_context_guards_retained(change):
    rows = [record('a'), record('b')]
    if change == 'uncertified':
        rows[0]['value']['status'] = 'not_certified'
    elif change == 'currency':
        rows[0]['value']['currency'] = CurrencyCode('USD')
    elif change == 'company':
        rows[0]['company_text'] = None
    else:
        rows[0]['month'] = None
    result = plot(rows, [documented('a', C.ORDINARY), documented('b', C.EXTRA)])
    assert not any(p['Documento'] == 'a' for p in result.points)


def test_category_filter_does_not_hide_multipayment_or_ambiguity():
    rows = [record('a'), record('b')]
    docs = [documented('a', C.ORDINARY), documented('b', C.EXTRA)]
    result = plot(rows, docs, categories=('Nóminas ordinarias',))
    assert len(result.points) == 1 and result.points[0]['Multipago']
    assert not plot(rows, [documented('a', C.ORDINARY), documented('b', C.UNCLASSIFIED)],
                    categories=('Nóminas ordinarias',)).points


def test_multipayment_markers_break_lines_and_average_even_after_filter():
    rows = year_records() + [record('extra', month=6)]
    docs = [documented(f'd{m}', C.ORDINARY) for m in range(1, 13)] + [documented('extra', C.EXTRA)]
    result = plot(rows, docs)
    assert len(result.points) == 25
    assert category_average(result.points, rows, classified=True) == []
    ordinary = plot(rows, docs, categories=('Nóminas ordinarias',))
    assert category_average(ordinary.points, rows, classified=True) == []
    spec = category_chart(result.points, '2025-01-01', '2025-12-01', []).to_dict()
    lines, markers, _ = spec['layer']
    assert not any(p['Fecha'] == '2025-06-01' for p in lines['data']['values'])
    assert len(markers['data']['values']) == 3
    gross = [p for p in lines['data']['values'] if p['Serie'] == 'Bruto']
    assert gross[4]['Tramo'] != gross[5]['Tramo']
    assert 'transform' not in spec


def test_missing_or_uncertain_type_support_cannot_unlock_month():
    docs = [documented('a', C.ORDINARY), documented('b', C.EXTRA)]
    docs[1] = replace(docs[1], context_facts=())
    assert not plot([record('a'), record('b')], docs).points
    base = documented('b', C.EXTRA)
    fact = base.context_facts[0]
    unknown = replace(fact, value=CanonicalValue(state=ValueState.UNKNOWN))
    docs[1] = replace(base, context_facts=(unknown,))
    assert not plot([record('a'), record('b')], docs).points


def test_same_observation_id_with_incompatible_content_is_not_deduplicated():
    rows = [record('a'), record('b')]
    conflict = deepcopy(rows[0])
    conflict['value']['amount'] = ExactDecimal(42, 0)
    assert not plot(rows + [conflict], [documented('a', C.ORDINARY), documented('b', C.EXTRA)]).points


def test_explicit_presentation_hold_only_blocks_never_reclassifies():
    rows = [record('a'), record('b')]
    docs = [documented('a', C.ORDINARY), documented('b', C.EXTRA)]
    result = plot(rows, docs, withheld_document_ids=frozenset({'b'}),
                  categories=('Nóminas ordinarias',))
    assert not result.points and result.ambiguous_periods == 1
    assert result.table[0]['Representación'] == 'Revisión pendiente: restricción de presentación'
    assert docs[1].category == C.EXTRA and rows[1]['eligibility'] == 'evidence_only'
    assert plot(rows, docs, withheld_document_ids=frozenset({'unrelated'})) == plot(rows, docs)


def test_local_presentation_holds_configuration(tmp_path, monkeypatch):
    from src.cli_config import ConfigurationError, load_config
    monkeypatch.setattr('src.cli_config.REPOSITORY_ROOT', tmp_path)
    monkeypatch.delenv('ANALISIS_NOMINAS_CANONICAL_DB', raising=False)
    config = tmp_path / 'config.toml'
    config.write_text('[paths]\ndatabase="synthetic.sqlite"\n[presentation]\nwithheld_document_ids=["a","b"]\n')
    assert load_config().withheld_document_ids == ('a', 'b')
    config.write_text('[paths]\ndatabase="synthetic.sqlite"\n[presentation]\nwithheld_document_ids=true\n')
    with pytest.raises(ConfigurationError, match='withheld_document_ids'):
        load_config()


@pytest.mark.parametrize(('boundary', 'value'), [
    (0, '20250101'), (0, '2025-W01-3'),
    (1, '20250109'), (1, '2025-W02-4'),
])
def test_noncanonical_dates_cannot_unlock_multipayment(boundary, value):
    interval = ['2025-01-01', '2025-01-09']
    interval[boundary] = value
    docs = [documented('a', C.SETTLEMENT, tuple(interval)),
            documented('b', C.SETTLEMENT, ('2025-01-10', '2025-01-31'))]
    result = plot([record('a'), record('b')], docs)
    assert result.points == []
    assert result.ambiguous_periods == 1


@pytest.mark.parametrize('padding', [' ', '\t', '\n'])
@pytest.mark.parametrize('leading', [True, False])
def test_withheld_ids_reject_surrounding_whitespace(tmp_path, monkeypatch, padding, leading):
    import json

    from src.cli_config import ConfigurationError, load_config
    monkeypatch.setattr('src.cli_config.REPOSITORY_ROOT', tmp_path)
    monkeypatch.delenv('ANALISIS_NOMINAS_CANONICAL_DB', raising=False)
    identity = str(deterministic_id('document', 'synthetic'))
    value = padding + identity if leading else identity + padding
    (tmp_path / 'config.toml').write_text(
        '[paths]\ndatabase="synthetic.sqlite"\n[presentation]\nwithheld_document_ids='
        + json.dumps([value]) + '\n')
    with pytest.raises(ConfigurationError, match='withheld_document_ids'):
        load_config()
