"""Synthetic chart projection: no aggregation across documents or versions."""

from dataclasses import replace

import pytest

from src.analytic_dataset import DocumentCategory, VersionProvenance
from src.document_concepts import DocumentConcepts
from src.income_evolution import project_income
from tests.unit.test_payroll_timeline import analytic
from tests.unit.test_salary_reconstruction import payroll, rebuild


def fixture():
    e = payroll()
    d = replace(
        analytic(e.document_id, DocumentCategory.ORDINARY),
        documentary_period=(2025, 6),
        provenance=(VersionProvenance(e.version_id, "file", "a" * 64, (), (e.extraction_id,)),),
    )
    target = next(f for f in e.facts if f.fact.fact_key == "nomina.total_devengado")
    d = replace(d, observation_facts=(("obs", (target.fact.fact_id,)),))
    s = DocumentConcepts(e.document_id, (e.version_id,), (e,))
    gross = {
        "Documento": e.document_id,
        "Serie": "Bruto",
        "Fecha": "2025-06-01",
        "Empresa": d.company_text,
        "Importe": 2800.0,
        "Importe exacto": "2.800,00 €",
        "Observación": "obs",
        "Categoría": "Nóminas ordinarias",
    }
    return d, s, gross


def test_visible_ordinary_extra_and_original_gross():
    d, s, g = fixture()
    r = project_income((d,), {d.document_id: s}, {}, [g])
    rows = r.rows
    assert {x["Componente"] for x in rows} == {
        "Bruto documental",
        "Ordinario identificado (parcial)",
        "Extras identificadas",
    }
    ordinary = next(x for x in rows if x["Componente"].startswith("Ordinario"))
    assert ordinary["Importe"] == 2500 and ordinary["Importe exacto"] == "2.500,00"
    assert ordinary["Hecho"] and ordinary["Fórmula"] and "parcial" in ordinary["Cobertura"].lower()
    assert next(x for x in rows if x["Componente"] == "Bruto documental")["Importe"] == g["Importe"]
    assert r.diagnostics[0]["Explicación"] == "Desglose explicado completamente"


@pytest.mark.parametrize(
    "case", ["multi", "extractions", "withheld", "identity", "context", "currency", "duplicate"]
)
def test_guards_do_not_select_or_relax(case):
    d, s, g = fixture()
    blocked = {}
    if case == "multi":
        d = replace(d, provenance=d.provenance + (replace(d.provenance[0], version_id="other"),))
    if case == "extractions":
        s = replace(s, extractions=s.extractions + s.extractions)
    if case == "withheld":
        blocked = {d.document_id: "Restricción local"}
    if case == "identity":
        s = replace(s, document_id="other")
    if case == "context":
        d = replace(d, documentary_period=None)
    if case == "currency":
        from src.canonical.values import CurrencyCode

        e = s.extractions[0]
        facts = tuple(
            replace(
                f, fact=replace(f.fact, value=replace(f.fact.value, currency=CurrencyCode("USD")))
            )
            if f.fact.fact_key.endswith(".importe")
            else f
            for f in e.facts
        )
        s = replace(s, extractions=(replace(e, facts=facts),))
    docs = [d, d] if case == "duplicate" else [d]
    r = project_income(docs, {d.document_id: s}, blocked, [])
    assert not r.rows and r.diagnostics


def test_unknown_and_unreconciled_remain_partial_no_inferred_residue():
    d, s, g = fixture()
    e = s.extractions[0]
    extra = next(c for c in e.concepts if c.get("codigo").fact.value.value == "9032")
    unknown = rebuild(e, {extra.get("concepto").fact.fact_key: "Unknown"})
    r = project_income((d,), {d.document_id: replace(s, extractions=(unknown,))}, {}, [g])
    assert r.diagnostics[0]["Explicación"] == "Desglose explicado parcialmente"
    bad = rebuild(e, {"nomina.total_devengado": 280001})
    r = project_income((d,), {d.document_id: replace(s, extractions=(bad,))}, {}, [g])
    assert not any(x["Componente"].startswith("Ordinario") for x in r.rows)
    assert next(x for x in r.rows if x["Componente"] == "Bruto documental")["Importe"] == 2800


def test_temporal_order_empty_subset_no_interpolation():
    from src.income_evolution import visible_income

    d, s, g = fixture()
    r = project_income((d,), {d.document_id: s}, {}, [g])
    assert visible_income(r.rows, ()) == []
    assert len(visible_income(r.rows, ("Ordinario identificado (parcial)",))) == 1
    assert {x["Fecha"] for x in r.rows} == {"2025-06-01"}
    assert project_income((), {}, {}, []).rows == []


def test_comparison_does_not_borrow_total_from_other_extraction():
    d, s, g = fixture()
    d = replace(d, observation_facts=(("obs", ("foreign_fact",)),))
    r = project_income((d,), {d.document_id: s}, {}, [g])
    assert not any(x["Componente"].startswith("Ordinario") for x in r.rows)
    assert any("soporte del bruto" in x.get("Limitación", "") for x in r.diagnostics)


@pytest.mark.parametrize(
    "code,label,category,arrears,series",
    [
        ("9025", "pago de benefiatra.", "beneficios", "true", "Atrasos y ajustes identificados"),
        (
            "9RPE",
            "r. pext dic 2012",
            "regularizaciones",
            "false",
            "Atrasos y ajustes identificados",
        ),
        ("9033", "paga extra navi", "paga_extra_incluida", "false", "Extras identificadas"),
    ],
)
def test_ineco_exceptions_are_individual_not_ordinary(code, label, category, arrears, series):
    d, s, g = fixture()
    e = s.extractions[0]
    c = next(c for c in e.concepts if c.get("codigo").fact.value.value == "9032")
    changes = {
        c.get(k).fact.fact_key: v
        for k, v in [
            ("codigo", code),
            ("concepto", label),
            ("categoria", category),
            ("atraso", arrears),
        ]
    }
    e = rebuild(e, changes)
    r = project_income((d,), {d.document_id: replace(s, extractions=(e,))}, {}, [g])
    assert any(x["Componente"] == series and x["Importe"] == 300 for x in r.rows)
    assert next(x for x in r.rows if x["Componente"].startswith("Ordinario"))["Importe"] == 2500
    assert len([x for x in r.rows if x["Componente"] == series]) == 1


def test_exceltic_proration_separate_from_ordinary_no_annual_claim():
    from src.breakdown_completeness import CONTRACTS

    d, s, g = fixture()
    e = s.extractions[0]
    labels = {
        "9001": ("SALARIO BASE", "salario_base"),
        "9004": ("MEJORA VOLUNTARIA", "complemento_salarial"),
        "9032": ("P.P.EXTRA", "paga_extra_incluida"),
    }
    changes = {}
    for c in e.concepts:
        code = c.get("codigo").fact.value.value
        if code not in labels:
            continue
        for key, value in [
            ("codigo", "1"),
            ("concepto", labels[code][0]),
            ("categoria", labels[code][1]),
        ]:
            changes[c.get(key).fact.fact_key] = value
    e = replace(
        rebuild(e, changes),
        extractor_name=CONTRACTS[1].extractor_name,
        extractor_revision=CONTRACTS[1].extractor_revision,
    )
    r = project_income((d,), {d.document_id: replace(s, extractions=(e,))}, {}, [g])
    assert any(x["Componente"] == "Prorratas salariales identificadas" for x in r.rows)
    assert next(x for x in r.rows if x["Componente"].startswith("Ordinario"))["Importe"] == 2500
    assert "No determinable" in r.diagnostics[0]["Fijo equivalente"]


def test_unexplained_stays_visible_as_gross():
    d, s, g = fixture()
    e = s.extractions[0]
    changes = {c.get("concepto").fact.fact_key: "Unknown" for c in e.concepts}
    e = rebuild(e, changes)
    r = project_income((d,), {d.document_id: replace(s, extractions=(e,))}, {}, [g])
    assert [x["Componente"] for x in r.rows] == ["Bruto documental"]
    assert r.diagnostics[0]["Explicación"] == "Sin explicación suficiente"


def test_independent_extra_uses_existing_total_not_ordinary_sum():
    d, s, g = fixture()
    d = replace(d, category=DocumentCategory.EXTRA)
    r = project_income((d,), {d.document_id: s}, {}, [g])
    assert (
        len(r.rows) == 1
        and r.rows[0]["Componente"] == "Extras identificadas (documento independiente)"
    )


def test_duplicate_totals_not_selected_and_input_is_not_mutated():
    d, s, g = fixture()
    before = repr((d, s, g))
    r = project_income((d,), {d.document_id: s}, {}, [g, g])
    assert not any(x["Componente"] == "Bruto documental" for x in r.rows)
    assert not any(x["Componente"].startswith("Ordinario") for x in r.rows)
    assert repr((d, s, g)) == before


def test_negative_adjustment_keeps_sign_and_original_month():
    from tests.unit.test_economic_components import example

    d, s = example(
        parser="InecoParser",
        code="9RPE",
        label="r. pext dic 2012",
        category="regularizaciones",
        amount=-12345,
    )
    r = project_income((d,), {d.document_id: s}, {}, [])
    assert len(r.rows) == 1 and r.rows[0]["Importe"] == -123.45
    assert r.rows[0]["Periodo del documento"] == "01/2025"


@pytest.mark.parametrize("state", ["unknown", "unreliable"])
def test_unreliable_component_not_zero(state):
    from src.canonical.values import ValueState
    from tests.unit.test_economic_components import example

    d, s = example(state=ValueState(state))
    assert not project_income((d,), {d.document_id: s}, {}, []).rows


def test_two_companies_and_units_are_faceted_not_merged():
    from src.income_view import income_chart

    d, s, g = fixture()
    r = project_income((d,), {d.document_id: s}, {}, [g])
    rows = r.rows + [dict(r.rows[0], Empresa="Empresa distinta", **{"Moneda canónica": "EUR"})]
    spec = income_chart(rows).to_dict()
    assert spec["facet"]["row"]["field"] == "Empresa"
    assert spec["spec"]["mark"]["type"] == "point"
    assert len(spec["data"]["values"]) == len(rows)


def test_tooltip_preserves_more_than_two_decimal_places():
    from src.canonical.values import ExactDecimal

    d, s, g = fixture()
    e = s.extractions[0]
    base = next(c for c in e.concepts if c.get("codigo").fact.value.value == "9001")
    e = rebuild(
        e,
        {
            base.get("importe").fact.fact_key: ExactDecimal.from_text("2000.1234"),
            base.get("importe_texto").fact.fact_key: "2.000,1234",
            "nomina.total_devengado": ExactDecimal.from_text("2800.1234"),
            "nomina.liquido_percibir": ExactDecimal.from_text("2780.1234"),
        },
    )
    g = dict(g, Importe=2800.1234, **{"Importe exacto": "2.800,1234 €"})
    target = next(f for f in e.facts if f.fact.fact_key == "nomina.total_devengado")
    d = replace(d, observation_facts=(("obs", (target.fact.fact_id,)),))
    r = project_income((d,), {d.document_id: replace(s, extractions=(e,))}, {}, [g])
    ordinary = next(x for x in r.rows if x["Componente"].startswith("Ordinario"))
    assert ordinary["Importe exacto"] == "2.500,1234"
