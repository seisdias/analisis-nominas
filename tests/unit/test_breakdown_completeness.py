"""Reviewed-format completeness is independent from arithmetic equality."""

from dataclasses import replace
from decimal import Decimal

import pytest

from src.breakdown_completeness import (
    CONTRACTS,
    Completeness,
    Section,
    diagnose_breakdown,
    evaluate_completeness,
)
from src.canonical.serialization import canonical_sha256
from src.canonical.values import ExactDecimal, ValueState
from src.document_concepts import project_extraction
from src.salary_reconciliation import Status
from tests.unit.test_document_concepts import DOC, EXT, VER, fact


def source(
    rows=(("devengos", 10000), ("deducciones", 2000)),
    *,
    contract=0,
    gross=10000,
    deductions=2000,
    net=8000,
):
    fs = []
    for i, (column, amount) in enumerate(rows):
        prefix = (
            "nomina.conceptos." + canonical_sha256({"codigo": "X", "columna": column}) + f".{i}."
        )
        attrs = {
            "codigo": "X",
            "concepto": "Concepto sin homologar",
            "categoria": "otro",
            "columna": column,
            "importe": amount,
            "importe_texto": format(Decimal(amount) / 100, ".2f").replace(".", ","),
            "atraso": "false",
            "porcentaje": None,
            "unidades": None,
            "precio": None,
            "base": None,
            "source_position": ExactDecimal(i, 0),
        }
        for key, value in attrs.items():
            fs.append(
                fact(
                    prefix + key,
                    value,
                    state=ValueState.UNKNOWN if value is None else ValueState.PRESENT,
                )
            )
    fs += [
        fact("nomina.total_devengado", gross),
        fact("nomina.total_deducir", deductions),
        fact("nomina.liquido_percibir", net),
        fact("nomina.es_procesable", "true"),
    ]
    c = CONTRACTS[contract]
    return project_extraction(
        DOC,
        VER,
        EXT,
        fs,
        extractor_name=c.extractor_name,
        extractor_revision=c.extractor_revision,
        content_hash=canonical_sha256({f.fact_key: f.value for f in fs}),
    )


def change(e, suffix, value, state=ValueState.PRESENT):
    fs = [
        fact(f.fact.fact_key, value, state=state) if f.fact.fact_key.endswith(suffix) else f.fact
        for f in e.facts
    ]
    return project_extraction(
        e.document_id,
        e.version_id,
        e.extraction_id,
        fs,
        extractor_name=e.extractor_name,
        extractor_revision=e.extractor_revision,
        content_hash=canonical_sha256({f.fact_key: f.value for f in fs}),
    )


@pytest.mark.parametrize("contract", range(2))
def test_reviewed_contract_and_sections(contract):
    e = source(contract=contract)
    assert all(x.state == Completeness.ACCREDITED for x in evaluate_completeness(e))
    assert all(d.status == Status.RECONCILED for d in diagnose_breakdown(e).diagnostics)
    assert e.content_hash == source(contract=contract).content_hash


def test_equal_sums_never_prove_completeness():
    e = replace(source(), extractor_revision="unreviewed")
    assert all(x.state == Completeness.NOT_APPLICABLE for x in evaluate_completeness(e))
    assert all(d.difference is None for d in diagnose_breakdown(e).diagnostics)


def test_contract_requires_justification():
    with pytest.raises(ValueError):
        replace(CONTRACTS[0], justification="")


def test_partial_or_unverified_facts_fail_closed():
    e = source()
    for bad in (replace(e, content_hash=""), replace(e, facts=e.facts[:-1])):
        assert all(x.state == Completeness.PARTIAL for x in evaluate_completeness(bad))
        assert all(d.difference is None for d in diagnose_breakdown(bad).diagnostics)


def test_no_concepts_is_not_zero():
    e = source(rows=())
    assert all(x.state != Completeness.ACCREDITED for x in evaluate_completeness(e))
    assert all(d.calculated is None for d in diagnose_breakdown(e).diagnostics)


@pytest.mark.parametrize(
    "state", [ValueState.UNKNOWN, ValueState.UNRELIABLE, ValueState.NOT_PRESENT]
)
def test_unknown_amount_does_not_block_other_section(state):
    e = source()
    key = next(c.get("importe").fact.fact_key for c in e.concepts if c.group == "Deducciones")
    e = change(e, key, None, state)
    report = diagnose_breakdown(e)
    assert report.completeness[0].state == Completeness.ACCREDITED
    assert report.completeness[1].state == Completeness.NOT_ACCREDITED
    assert report.diagnostics[0].status == Status.RECONCILED
    assert report.diagnostics[1].difference is None
    assert report.diagnostics[2].difference is None


def test_unknown_accounting_column_blocks_both():
    e = change(source(), ".columna", "unknown")
    assert all(x.state != Completeness.ACCREDITED for x in evaluate_completeness(e))


@pytest.mark.parametrize("label", ["Bonus", "Paga extra", "Atrasos", "Función desconocida"])
def test_functional_category_does_not_gate_accounting_rows(label):
    e = change(source(), ".concepto", label)
    assert diagnose_breakdown(e).diagnostics[0].status == Status.RECONCILED


@pytest.mark.parametrize("column", ["bases", "informacion"])
def test_information_not_added(column):
    e = source(rows=(("devengos", 10000), ("deducciones", 2000), (column, 99999)))
    r = diagnose_breakdown(e)
    assert r.diagnostics[0].calculated == Decimal("100")
    assert len(r.diagnostics[0].participants) == 1
    assert r.completeness[0].excluded


def test_exact_difference_not_completeness_evidence():
    e = source(gross=10001)
    r = diagnose_breakdown(e)
    assert r.completeness[0].state == Completeness.ACCREDITED
    assert r.diagnostics[0].difference == Decimal("-0.01")
    assert r.diagnostics[0].status == Status.DIFFERENCE
    assert len(r.diagnostics[0].participants) == 1


def test_signed_negative_rows_preserved():
    e = source(
        rows=(("devengos", -10000), ("deducciones", -2000)),
        gross=-10000,
        deductions=-2000,
        net=-8000,
    )
    assert all(d.status == Status.RECONCILED for d in diagnose_breakdown(e).diagnostics)


def test_zero_is_not_absence():
    e = source(rows=(("devengos", 0), ("deducciones", 2000)), gross=0, net=-2000)
    assert diagnose_breakdown(e).diagnostics[0].difference == 0


def test_repeated_code_preserves_occurrences():
    e = source(rows=(("devengos", 5000), ("devengos", 5000), ("deducciones", 2000)))
    d = diagnose_breakdown(e).diagnostics[0]
    assert len(d.participants) == 2 and d.difference == 0


def test_lost_or_inconsistent_row_metadata_rejected():
    for suffix, value in ((".source_position", ExactDecimal(7, 0)), (".importe_texto", "wrong")):
        assert any(
            x.state != Completeness.ACCREDITED
            for x in evaluate_completeness(change(source(), suffix, value))
        )


def test_versions_and_extractions_not_combined():
    e = source()
    other = replace(e, concepts=(replace(e.concepts[0], version_id="other"), *e.concepts[1:]))
    assert all(d.status == Status.CONFLICT for d in diagnose_breakdown(other).diagnostics)


def test_deterministic_without_mutation():
    e = source()
    before = repr(e)
    assert diagnose_breakdown(e) == diagnose_breakdown(e)
    assert repr(e) == before
    assert {x.section for x in evaluate_completeness(e)} == {Section.EARNINGS, Section.DEDUCTIONS}


def test_altran_table_coverage_does_not_prove_participation_in_totals():
    e = source(contract=2)
    assert all("contract.total_scope_unverified" in x.reasons for x in evaluate_completeness(e))
    assert all(d.difference is None for d in diagnose_breakdown(e).diagnostics)


@pytest.mark.parametrize(
    "name,revision",
    [
        ("CoritelParser", "1"),
        ("InsisParser", "1"),
        ("alten-legacy-evidence", "alten-legacy-evidence/v1"),
        ("alten-economic-projection", "alten-economic-projection/v2"),
    ],
)
def test_unattested_formats_never_borrow_contracts(name, revision):
    e = replace(source(), extractor_name=name, extractor_revision=revision)
    assert all(x.state == Completeness.NOT_APPLICABLE for x in evaluate_completeness(e))


def test_missing_amount_is_independent_of_other_section():
    e = source()
    key = next(c.get("importe").fact.fact_key for c in e.concepts if c.group == "Deducciones")
    fs = [f.fact for f in e.facts if f.fact.fact_key != key]
    # Removing a persisted mandatory attribute invalidates the extraction contract.
    e = project_extraction(
        DOC,
        VER,
        EXT,
        fs,
        extractor_name=e.extractor_name,
        extractor_revision=e.extractor_revision,
        content_hash=canonical_sha256({f.fact_key: f.value for f in fs}),
    )
    assert all(x.state == Completeness.PARTIAL for x in evaluate_completeness(e))


def test_unknown_sign_contract_is_not_used(monkeypatch):
    import src.breakdown_completeness as module

    e = source()
    monkeypatch.setattr(
        module, "CONTRACTS", (replace(CONTRACTS[0], signs=module.SignConvention.UNKNOWN),)
    )
    assert all("contract.signs_unknown" in x.reasons for x in evaluate_completeness(e))
    assert all(d.calculated is None for d in diagnose_breakdown(e).diagnostics)


def test_currency_conflict_not_repaired():
    from src.canonical.values import CurrencyCode

    e = source()
    fs = [
        replace(f.fact, value=replace(f.fact.value, currency=CurrencyCode("USD")))
        if f.fact.fact_key == "nomina.total_devengado"
        else f.fact
        for f in e.facts
    ]
    e = project_extraction(
        DOC,
        VER,
        EXT,
        fs,
        extractor_name=e.extractor_name,
        extractor_revision=e.extractor_revision,
        content_hash=canonical_sha256({f.fact_key: f.value for f in fs}),
    )
    assert "section.incompatible_units" in evaluate_completeness(e)[0].reasons
    assert diagnose_breakdown(e).diagnostics[0].calculated is None


def test_scalar_duplicates_never_participate():
    e = source()
    fs = [f.fact for f in e.facts] + [
        fact("nomina.prorrata_pagas_extra", 10000),
        fact("nomina.salario_base", 10000),
    ]
    extended = project_extraction(
        DOC,
        VER,
        EXT,
        fs,
        extractor_name=e.extractor_name,
        extractor_revision=e.extractor_revision,
        content_hash=canonical_sha256({f.fact_key: f.value for f in fs}),
    )
    assert diagnose_breakdown(extended).diagnostics == diagnose_breakdown(e).diagnostics


def test_foreign_extraction_total_fails_closed():
    from src.canonical.serialization import deterministic_id

    e = source()
    fs = [
        fact(f.fact.fact_key, f.fact.value.value, ext=str(deterministic_id("extraction", "other")))
        if f.fact.fact_key == "nomina.total_devengado"
        else f.fact
        for f in e.facts
    ]
    e = replace(
        e,
        facts=tuple(replace(old, fact=new) for old, new in zip(e.facts, fs)),
        content_hash=canonical_sha256({f.fact_key: f.value for f in fs}),
    )
    assert all(x.state == Completeness.CONFLICT for x in evaluate_completeness(e))
    assert all(d.calculated is None for d in diagnose_breakdown(e).diagnostics)


def test_no_rounding_under_small_decimal_context():
    from decimal import localcontext

    e = source(gross=10001)
    with localcontext() as ctx:
        ctx.prec = 1
        assert diagnose_breakdown(e).diagnostics[0].difference == Decimal("-0.01")


def test_input_order_independent():
    e = source(rows=(("devengos", 5000), ("devengos", 5000), ("deducciones", 2000)))
    other = replace(e, facts=tuple(reversed(e.facts)), concepts=tuple(reversed(e.concepts)))
    assert diagnose_breakdown(e) == diagnose_breakdown(other)


def test_unreviewed_alternative_total_is_conflict():
    e = source()
    fs = [f.fact for f in e.facts] + [fact("payload/total_devengado", 10000)]
    e = project_extraction(
        DOC,
        VER,
        EXT,
        fs,
        extractor_name=e.extractor_name,
        extractor_revision=e.extractor_revision,
        content_hash=canonical_sha256({f.fact_key: f.value for f in fs}),
    )
    assert all(x.state == Completeness.CONFLICT for x in evaluate_completeness(e))


def test_approved_pipeline_revisions_match_reviewed_sources():
    from src.ingestion_processors import _revision
    from src.parsers.exceltic_parser import ExcelticParser
    from src.parsers.ineco_parser import InecoParser

    for contract, parser in zip(CONTRACTS, (InecoParser(), ExcelticParser())):
        assert contract.extractor_revision == _revision(parser)
