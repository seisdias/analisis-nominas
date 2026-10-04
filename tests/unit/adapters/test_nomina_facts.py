"""Synthetic legacy-model projection; never calculates payroll economics."""

from copy import deepcopy
from dataclasses import fields
from decimal import Decimal
from unittest.mock import PropertyMock, patch

import pytest

from src.canonical import CurrencyCode, ExactDecimal, ValueState
from src.models.nomina import ConceptoNomina, Nomina
from src.nomina_facts import adapt_nomina


def sample():
    return Nomina(id='synthetic', anio=2020, mes=6, periodo='June', empresa='Synthetic', cif='TEST')


def concept(amount=12.34, code='001', column='devengos'):
    return ConceptoNomina(code, 'original label', 'parser category', column, amount, '12,34',
                          atraso=True, porcentaje=3.5, unidades=2.0, precio=6.17, base=100.0)


def values(model, **kwargs):
    return {f.fact_key: f.value for f in adapt_nomina(model, **kwargs)}


def test_all_stored_nomina_fields_exported_without_derived_property():
    model = sample()
    with patch.object(Nomina, 'total_deducciones', new_callable=PropertyMock,
                      side_effect=AssertionError('Calculated property must never be accessed')):
        output = values(model)
    assert set(output) == {f'nomina.{f.name}' for f in fields(Nomina) if f.name != 'conceptos'}
    assert output['nomina.tipo'].value == 'NOMINA_ORDINARIA'
    assert output['nomina.anio'].value == ExactDecimal(2020, 0)
    assert output['nomina.es_procesable'].value == 'true'


@pytest.mark.parametrize('amount', [201.53, -201.53, 0.0])
def test_float_conversion_and_zero_preserve_candidate(amount):
    model = sample()
    model.total_devengado = amount
    result = values(model)['nomina.total_devengado']
    assert result.value == ExactDecimal.from_decimal(Decimal(str(amount)))
    assert result.currency is None
    assert result.state == (ValueState.UNRELIABLE if amount == 0 else ValueState.PRESENT)
    if amount == 0:
        assert result.reason_code == 'legacy.zero_origin_unknown'


def test_none_does_not_claim_missing_documentary_value():
    model = sample()
    model.salario_base = None
    result = values(model)['nomina.salario_base']
    assert result.state == ValueState.UNKNOWN
    assert result.value is None
    assert result.reason_code == 'legacy.absence_unspecified'


def test_no_currency_inference_and_explicit_currency_only_on_amount_fields():
    model = sample()
    assert values(model)['nomina.salario_base'].currency is None
    result = values(model, currency=CurrencyCode('EUR'))
    assert result['nomina.salario_base'].currency == CurrencyCode('EUR')
    assert result['nomina.irpf_porcentaje'].currency is None
    assert result['nomina.empresa'].currency is None


def test_deterministic_no_mutation_no_sums_or_reconciliation():
    model = sample()
    model.total_devengado, model.total_deducir, model.liquido_percibir = 100.0, 999.0, -3.0
    model.conceptos = [concept(9999.0), concept(-15.0)]
    before = deepcopy(model)
    first = adapt_nomina(model)
    assert first == adapt_nomina(model)
    assert model == before
    result = {f.fact_key: f.value for f in first}
    assert result['nomina.total_devengado'].value == ExactDecimal(100, 0)
    assert result['nomina.total_deducir'].value == ExactDecimal(999, 0)
    assert result['nomina.liquido_percibir'].value == ExactDecimal(-3, 0)
    assert not any('annual' in k or 'economic' in k or 'total_deducciones' in k for k in result)


def test_repeated_concepts_keep_all_fields_and_amount_is_not_identity():
    model = sample()
    model.conceptos = [concept(), concept(25.0), concept(3.0, column='deducciones')]
    first = adapt_nomina(model)
    concept_facts = [f for f in first if f.fact_key.startswith('nomina.conceptos.')]
    assert len(concept_facts) == 3 * (len(fields(ConceptoNomina)) + 1)  # source position too
    assert len({f.fact_key for f in concept_facts}) == len(concept_facts)
    model.conceptos[0].importe = 77.0
    assert [f.fact_key for f in first] == [f.fact_key for f in adapt_nomina(model)]
    result = values(model)
    assert any(k.endswith('.categoria') and v.value == 'parser category' for k, v in result.items())
    assert any(k.endswith('.importe_texto') and v.value == '12,34' for k, v in result.items())
    assert any(k.endswith('.atraso') and v.value == 'true' for k, v in result.items())


def test_unrelated_concept_insertion_does_not_rekey_existing_concepts():
    model = sample()
    model.conceptos = [concept(), concept(25.0)]
    original = {f.fact_key for f in adapt_nomina(model)}
    model.conceptos.insert(0, concept(code='unrelated'))
    assert original <= {f.fact_key for f in adapt_nomina(model)}


@pytest.mark.parametrize('amount', [float('nan'), float('inf'), 0.30000000000000004])
def test_unrepresentable_values_fail_without_rounding(amount):
    model = sample()
    model.total_devengado = amount
    with pytest.raises(ValueError):
        adapt_nomina(model)
