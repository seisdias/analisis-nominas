"""Pure documentary occurrence reconstruction, without economic calculations."""
from dataclasses import replace

import pytest

from src.canonical.facts import DocumentaryFact, FactDraft
from src.canonical.serialization import deterministic_id
from src.canonical.values import CanonicalValue, ExactDecimal, ValueState
from src.concepts_view import concept_rows, reference_rows
from src.document_concepts import project_extraction

EXT = str(deterministic_id('extraction', 'synthetic'))
DOC = str(deterministic_id('document', 'synthetic'))
VER = str(deterministic_id('version', 'synthetic'))


def fact(key, value='same', *, state=ValueState.PRESENT, ext=EXT):
    raw = ExactDecimal(value, 2) if isinstance(value, int) else value
    return DocumentaryFact.from_draft(ext, FactDraft(key, CanonicalValue(
        state=state, value=raw, reason_code='test.uncertain' if state != ValueState.PRESENT else None)))


def project(facts, **kwargs):
    return project_extraction(DOC, VER, EXT, facts, **kwargs)


def test_empty_scalar_only_and_no_reconstruction():
    result = project([fact('nomina.irpf_importe', 1234)])
    assert result.concepts == ()
    assert len(result.references) == 1
    assert reference_rows(result)[0]['Valor documental'] == '12,34'


@pytest.mark.parametrize('prefix', ['payload/conceptos/0/', 'nomina.conceptos.' + 'a'*64 + '.0.'])
def test_one_occurrence_preserves_fields_pages_and_full_identity(prefix):
    facts = [fact(prefix+'codigo'), fact(prefix+'concepto', 'Bono'), fact(prefix+'importe', 123456)]
    result = project(facts, pages={facts[-1].fact_id: (2,)})
    row = result.concepts[0]
    assert (row.document_id, row.version_id, row.extraction_id) == (DOC, VER, EXT)
    assert row.occurrence == prefix[:-1]
    assert row.get('importe').fact is facts[-1]
    assert row.get('importe').pages == (2,)
    rendered = concept_rows(result.concepts)
    assert rendered[0]['Importe documental'] == '1.234,56'
    assert 'Código original' in rendered[0] and 'Unidades' not in rendered[0]
    assert 'EUR' not in str(rendered)


def test_repeated_codes_labels_values_and_columns_remain_occurrences():
    facts = []
    for i, amount in enumerate([100, 100, 200]):
        facts += [fact(f'payload/conceptos/{i}/codigo', 'same'),
                  fact(f'payload/conceptos/{i}/concepto', 'same'),
                  fact(f'payload/conceptos/{i}/columna', 'deducciones' if i==2 else 'devengos'),
                  fact(f'payload/conceptos/{i}/importe', amount)]
    a = project(facts)
    assert len(a.concepts) == 3
    assert project(list(reversed(facts))) == a
    assert project(facts + facts) == a
    assert [r['Importe documental'] for r in concept_rows(a.concepts)] == ['1,00','1,00','2,00']
    assert {c.group for c in a.concepts} == {'Devengos','Deducciones'}


@pytest.mark.parametrize('state', list(ValueState))
def test_every_state_preserved_without_fabricated_amount(state):
    value = 0 if state in (ValueState.PRESENT, ValueState.UNRELIABLE) else None
    f = fact('payload/conceptos/0/importe', value, state=state)
    result = project([f])
    assert result.concepts[0].get('importe').fact.value.state == state
    row = concept_rows(result.concepts)[0]
    assert row['Denominación original'] == 'Denominación no registrada'
    if state != ValueState.PRESENT:
        assert '0,00' not in row['Importe documental']
    assert row['Estado del importe']


def test_percentage_without_amount_units_not_days_and_scalar_is_reference():
    result = project([fact('payload/conceptos/0/porcentaje', 470),
        fact('payload/conceptos/0/unidades', 3000),
        fact('payload/conceptos/0/columna', 'base'),
        fact('payload/irpf_porcentaje', 470)])
    row = concept_rows(result.concepts)[0]
    assert row['Porcentaje'] == '4,7'
    assert row['Unidades'] == '30'
    assert row['Importe documental'] == 'Campo no registrado'
    assert result.concepts[0].group == 'Otros / grupo desconocido'
    assert len(result.references) == 1
    assert 'días' not in str(row)


def test_cross_extraction_rejected_and_conflicting_duplicate_rejected():
    f = fact('payload/conceptos/0/importe', 100)
    with pytest.raises(ValueError):
        project([f, fact(f.fact_key, 200, ext=str(deterministic_id('extraction','other')))])
    with pytest.raises(ValueError):
        project([f, replace(f, value=CanonicalValue(state=ValueState.PRESENT,value=ExactDecimal(2,0)))])


def test_prefixes_do_not_merge_or_alias_and_malformed_keys_stay_technical():
    fs=[fact('payload/conceptos/0/importe',100),
        fact('nomina.conceptos.'+'a'*64+'.0.importe',100),
        fact('nomina.conceptos.bad.importe',200),
        fact('payload/conceptos/01/importe',200)]
    result=project(fs)
    assert len(result.concepts)==2
    assert len(result.facts)==4
    assert result.references==()


def test_extraction_and_version_boundaries_are_not_merged():
    key='payload/conceptos/0/importe'
    first=project([fact(key,100)])
    ext=str(deterministic_id('extraction','second'))
    version=str(deterministic_id('version','second'))
    second=project_extraction(DOC,version,ext,[fact(key,200,ext=ext)])
    assert first.concepts[0].occurrence==second.concepts[0].occurrence
    assert first.concepts[0].extraction_id!=second.concepts[0].extraction_id
    assert first.concepts[0].version_id!=second.concepts[0].version_id
    left, right = first.concepts[0].get('importe'), second.concepts[0].get('importe')
    assert left is not None and right is not None
    assert left.fact.fact_id != right.fact.fact_id


def test_same_amount_scalar_and_occurrence_are_separate_reference_not_payment():
    result=project([fact('payload/conceptos/0/importe',100),
                    fact('payload/conceptos/0/concepto','P.P. Extra Verano'),
                    fact('payload/conceptos/0/columna','devengos'),
                    fact('payload/prorrata_pagas_extra',100)])
    assert len(result.concepts)==len(result.references)==1
    assert result.concepts[0].group=='Devengos'
    assert 'referencia' in reference_rows(result)[0]['Campo de referencia']
    assert not hasattr(result,'total')


def test_optional_absent_fields_preserved_in_trace_without_empty_columns():
    f=fact('payload/conceptos/0/porcentaje',None,state=ValueState.UNKNOWN)
    result=project([f,fact('payload/conceptos/0/concepto','Original')])
    assert result.concepts[0].get('porcentaje').fact is f
    assert 'Porcentaje' not in concept_rows(result.concepts)[0]


def test_explicit_currency_is_preserved_and_not_relabelled():
    from src.canonical.values import CurrencyCode
    f=fact('payload/conceptos/0/importe',1234)
    f=replace(f,value=replace(f.value,currency=CurrencyCode('USD')))
    assert concept_rows(project([f]).concepts)[0]['Importe documental']=='12,34 USD'
