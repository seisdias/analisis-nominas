"""Synthetic classification contracts, independently of amount/period/company."""

from dataclasses import replace

import pytest

from src.economic_classification import Function, Nature, Periodicity, Relation, classify_extraction
from tests.unit.test_document_concepts import fact, project
from tests.unit.test_economic_components import example


@pytest.mark.parametrize(
    "kwargs,role",
    [
        ({}, Function.BONUS),
        (
            {
                "parser": "InecoParser",
                "code": "9001",
                "label": "salario base",
                "category": "salario_base",
            },
            Function.FIXED,
        ),
        (
            {
                "parser": "InecoParser",
                "code": "9004",
                "label": "comp.salarial",
                "category": "complementos",
            },
            Function.COMPLEMENT,
        ),
        (
            {
                "parser": "InecoParser",
                "code": "9032",
                "label": "paga extra vera",
                "category": "paga_extra_incluida",
            },
            Function.EXTRA,
        ),
        (
            {
                "parser": "ExcelticParser",
                "code": "1",
                "label": "P.P.EXTRA",
                "category": "paga_extra_incluida",
            },
            Function.PRORATION,
        ),
        (
            {
                "parser": "AltranParser",
                "code": "R1X",
                "label": "Parte Proporcional Pagas Extras",
                "category": "paga_extra_incluida",
                "arrears": "true",
                "column": "deducciones",
            },
            Function.PRORATION,
        ),
        (
            {
                "parser": "InecoParser",
                "code": "90RG",
                "label": "regulariz.salar",
                "category": "regularizaciones",
            },
            Function.ADJUSTMENT,
        ),
        (
            {
                "parser": "InecoParser",
                "code": "9025",
                "label": "pago de benefiatra.",
                "category": "beneficios",
                "arrears": "true",
            },
            Function.BENEFITS,
        ),
        (
            {
                "code": "/401",
                "label": "Retención a cta. IRPF",
                "category": "irpf",
                "column": "deducciones",
            },
            Function.TAX,
        ),
        (
            {
                "code": "/350",
                "label": "Trab.cont.comunes",
                "category": "cotizacion_contingencias_comunes",
                "column": "deducciones",
            },
            Function.CONTRIBUTION,
        ),
    ],
)
def test_exact_roles_preserve_evidence(kwargs, role):
    _, s = example(**kwargs)
    c = classify_extraction(s.extractions[0]).concepts[0]
    assert c.function == role
    assert c.source is s.extractions[0].concepts[0]
    assert c.periodicity == Periodicity.UNKNOWN
    assert c.arrears == (kwargs.get("arrears", "false") == "true")
    assert c.nature == (
        Nature.DEDUCTION if kwargs.get("column") == "deducciones" else Nature.EARNING
    )


def test_unknown_and_repeated_occurrences_not_inferred_from_amount():
    _, s = example(count=2, label="Salario probable", amount=999999)
    result = classify_extraction(s.extractions[0])
    assert len(result.concepts) == 2 and all(
        c.function == Function.UNKNOWN for c in result.concepts
    )
    assert len({c.source.occurrence for c in result.concepts}) == 2
    assert result.issues


def test_references_are_never_additional_components_and_extra_is_documented():
    e = project(
        [
            fact("nomina.salario_base", 100),
            fact("nomina.base_ss_comunes", 200),
            fact("nomina.prorrata_pagas_extra", 300),
            fact("nomina.total_devengado", 400),
            fact("nomina.tipo", "PAGA_EXTRA"),
        ]
    )
    e = replace(e, extractor_name="InecoParser")
    r = classify_extraction(e)
    refs = {x.source.fact.fact_key: x for x in r.references}
    assert refs["nomina.salario_base"].relation == Relation.REFERENCE
    assert refs["nomina.base_ss_comunes"].nature == Nature.BASE
    assert refs["nomina.prorrata_pagas_extra"].function == Function.INFORMATIONAL_PRORATION
    assert refs["nomina.total_devengado"].function == Function.INDEPENDENT_EXTRA
    assert refs["nomina.total_devengado"].relation == Relation.TOTAL
    assert r.concepts == ()


@pytest.mark.parametrize("state", ["unknown", "unreliable", "not_present", "not_extracted"])
def test_role_and_value_availability_are_independent(state):
    from src.canonical.values import ValueState

    _, s = example(state=ValueState(state))
    c = classify_extraction(s.extractions[0]).concepts[0]
    assert c.function == Function.BONUS
    amount = c.source.get("importe")
    assert amount is not None and amount.fact.value.state == ValueState(state)


def test_b1_catalog_is_the_single_source_and_context_does_not_reclassify():
    from src.economic_components import project_components

    _, s = example()
    a = classify_extraction(s.extractions[0])
    assert a.concepts[0].function == Function.BONUS
    altered = replace(s.extractions[0], extractor_name="unknown-parser")
    assert classify_extraction(altered).concepts[0].function == Function.UNKNOWN
    assert project_components((), {}, {}).points == ()


def test_missing_label_and_code_are_not_identity_or_classification():
    _, s = example(count=2)
    e = s.extractions[0]
    concepts = tuple(
        replace(
            c, attributes=tuple((k, v) for k, v in c.attributes if k not in ("concepto", "codigo"))
        )
        for c in e.concepts
    )
    result = classify_extraction(replace(e, concepts=concepts))
    assert len(result.concepts) == 2
    assert all(c.function == Function.UNKNOWN for c in result.concepts)


def test_scalar_conflict_is_reported_but_never_corrected_or_added():
    _, s = example(
        parser="InecoParser",
        code="9001",
        label="salario base",
        category="salario_base",
        amount=10000,
    )
    e = s.extractions[0]
    scalar = project([fact("payload/salario_base", 20000)]).facts[0]
    r = classify_extraction(replace(e, facts=e.facts + (scalar,)))
    assert any("discrepancia" in reason for reason in r.issues)
    assert len(r.concepts) == 1 and len(r.references) == 1
    assert r.references[0].relation == Relation.REFERENCE
    from src.canonical.values import ExactDecimal

    amount = r.concepts[0].source.get("importe")
    assert amount is not None and amount.fact.value.value == ExactDecimal(10000, 2)
