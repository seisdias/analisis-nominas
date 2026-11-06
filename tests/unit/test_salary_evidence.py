"""Salary guarantees are independent; repetition and reconciliation are not contracts."""

from dataclasses import replace

import pytest

from src.salary_evidence import assess_salary, evidence_rows
from src.salary_reconstruction import Coverage
from tests.unit.test_salary_reconstruction import contracts, payroll, rebuild


def month(e=None, end="2025-06-30"):
    from src.canonical.serialization import canonical_sha256
    from src.document_concepts import project_extraction
    from tests.unit.test_document_concepts import fact

    e = e or payroll()
    facts = [f.fact for f in e.facts] + [
        fact("nomina.fecha_inicio", "2025-06-01"),
        fact("nomina.fecha_fin", end),
    ]
    return project_extraction(
        e.document_id,
        e.version_id,
        e.extraction_id,
        facts,
        extractor_name=e.extractor_name,
        extractor_revision=e.extractor_revision,
        content_hash=canonical_sha256({f.fact_key: f.value for f in facts}),
    )


def test_accounting_and_civil_month_do_not_accredit_fixed_pay():
    e = month()
    report = assess_salary(e)
    checks = {c.key: c for c in report.requirements}
    assert checks["calendar"].satisfied and checks["accounting"].satisfied
    assert not checks["recurrence"].satisfied and not checks["fixed"].satisfied
    assert not checks["payment"].satisfied and not checks["annual"].satisfied
    assert report.ordinary.amount is not None and report.ordinary.coverage == Coverage.PARTIAL
    assert report.reconstruction.monthly.amount is None
    assert "complemento" in checks["recurrence"].reason.lower()
    assert "convenio" in checks["annual"].needed.lower()
    assert checks["calendar"].facts and checks["recurrence"].facts


@pytest.mark.parametrize("end", ["2025-06-29", "2025-07-01", "invalid"])
def test_partial_or_invalid_interval_is_not_whole_month(end):
    report = assess_salary(month(end=end))
    assert not next(c for c in report.requirements if c.key == "calendar").satisfied
    assert report.ordinary.amount is not None


def test_missing_dates_are_not_invented():
    report = assess_salary(payroll())
    assert not next(c for c in report.requirements if c.key == "calendar").satisfied


def test_reviewed_contracts_use_existing_engine_without_new_certifications():
    e = month()
    report = assess_salary(e, *contracts(e))
    assert all(c.satisfied for c in report.requirements)
    assert report.reconstruction.fixed.amount is not None
    assert report.reconstruction.annual.amount is not None
    assert report.reconstruction.monthly.amount is not None
    assert report.reconstruction.fixed.amount.numerator == 2500
    assert report.reconstruction.annual.amount.numerator == 30600
    assert report.reconstruction.monthly.amount.divisor == 12
    assert report.ordinary.coverage == Coverage.PARTIAL


@pytest.mark.parametrize("case", ["foreign", "partial", "declared", "extra_partial"])
def test_unverified_guarantees_stay_separate(case):
    e = month()
    f, p, a = contracts(e)
    if case == "foreign":
        f = replace(
            f, evidence=replace(f.evidence, scope=replace(f.evidence.scope, version_id="other"))
        )
    if case == "partial":
        f = replace(f, complete=False)
    if case == "declared":
        p = replace(p, accredited=False)
    if case == "extra_partial":
        a = replace(a, full_extra_composition=False)
    report = assess_salary(e, f, p, a)
    assert report.reconstruction.annual.amount is None
    assert not next(c for c in report.requirements if c.key == "annual").satisfied


@pytest.mark.parametrize("case", ["unknown", "unreliable", "difference", "hash", "revision"])
def test_failed_evidence_remains_visible_not_zero(case):
    from src.canonical.values import ValueState
    from tests.unit.test_breakdown_completeness import change

    e = month()
    if case in ("unknown", "unreliable"):
        e = change(e, ".importe", None, ValueState(case))
    if case == "difference":
        e = rebuild(e, {"nomina.total_devengado": 280001})
    if case == "hash":
        e = replace(e, content_hash="bad")
    if case == "revision":
        e = replace(e, extractor_revision="new")
    r = assess_salary(e)
    assert not next(c for c in r.requirements if c.key == "accounting").satisfied
    assert r.ordinary.amount is None and r.reconstruction.fixed.amount is None


def test_same_composition_and_value_do_not_create_recurrence():
    e = month()
    a = assess_salary(e)
    b = assess_salary(e)
    assert a == b
    assert not any(
        c.satisfied for c in a.requirements if c.key in ("recurrence", "fixed", "payment", "annual")
    )
    assert evidence_rows(a) == evidence_rows(b)
    assert all("Qué falta" in row for row in evidence_rows(a))


def test_unknown_concept_report_preserves_occurrence_and_original():
    e = month()
    c = next(c for c in e.concepts if c.get("codigo").fact.value.value == "9032")
    e = rebuild(e, {c.get("concepto").fact.fact_key: "UNKNOWN"})
    before = e
    report = assess_salary(e)
    assert report.unresolved == (c.occurrence,)
    assert e == before and report.reconstruction.fixed.amount is None
    assert "sin clasificar" in next(c for c in report.requirements if c.key == "fixed").reason


def test_full_civil_month_does_not_accredit_full_salary_month():
    e = month()
    report = assess_salary(e)
    assert not next(c for c in report.requirements if c.key == "salary_month").satisfied
    f, p, a = contracts(e)
    incomplete = assess_salary(e, replace(f, full_month=False), p, a)
    assert incomplete.reconstruction.fixed.amount is not None
    assert not next(c for c in incomplete.requirements if c.key == "salary_month").satisfied
    assert incomplete.reconstruction.monthly.amount is None


def test_calendar_does_not_accredit_a_tampered_snapshot():
    report = assess_salary(replace(month(), content_hash="tampered"))
    assert not next(c for c in report.requirements if c.key == "calendar").satisfied


def test_requirements_reject_other_extractions_scenario():
    from src.salary_evidence import describe_salary

    e = month()
    report = assess_salary(e)
    with pytest.raises(ValueError, match="scope"):
        describe_salary(replace(e, extraction_id="other"), report.reconstruction, report.ordinary)


def test_exceltic_proration_is_evidence_not_automatic_twelve_payments():
    from src.breakdown_completeness import CONTRACTS
    from src.salary_reconstruction import (
        AnnualContract,
        AnnualTerm,
        ContractEvidence,
        FixedContract,
        PaymentContract,
        PaymentMode,
        scope_for,
    )

    e = month()
    changes = {}
    mapping = {
        "9001": ("1", "SALARIO BASE", "salario_base"),
        "9004": ("1", "MEJORA VOLUNTARIA", "complemento_salarial"),
        "9032": ("1", "P.P.EXTRA", "paga_extra_incluida"),
    }
    for c in e.concepts:
        values = mapping.get(c.get("codigo").fact.value.value)
        if values:
            for field, value in zip(("codigo", "concepto", "categoria"), values, strict=True):
                changes[c.get(field).fact.fact_key] = value
    e = replace(
        rebuild(e, changes),
        extractor_name="ExcelticParser",
        extractor_revision=CONTRACTS[1].extractor_revision,
    )
    r = assess_salary(e)
    assert r.ordinary.amount is not None
    assert r.reconstruction.monthly.amount is None
    modality = next(q for q in r.requirements if q.key == "payment")
    assert not modality.satisfied and "P.P.EXTRA" in modality.reason
    assert modality.facts and "Acuerdo de prorrateo" in modality.needed
    evidence = ContractEvidence(
        scope_for(e), "Synthetic reviewed annual salary agreement", (2025, 6)
    )
    fixed_ids = tuple(
        p.source.source.occurrence
        for p in r.reconstruction.parts
        if p.bucket.value.startswith("Salario base")
    )
    fixed = FixedContract(evidence, fixed_ids, True, True, True, True)
    payment = PaymentContract(evidence, PaymentMode.PRORATED, True)
    annual = AnnualContract(
        evidence,
        tuple(AnnualTerm(p.source.source.occurrence, 12) for p in r.reconstruction.parts),
        (2025, 6),
        (2025, 6),
        True,
    )
    accredited = assess_salary(e, fixed, payment, annual)
    assert accredited.reconstruction.annual.amount is not None
    assert accredited.reconstruction.annual.amount.numerator == 33600
    assert accredited.reconstruction.monthly.amount is not None
    assert accredited.reconstruction.monthly.amount.display() == "2.800,00"
    assert scope_for(e) == r.reconstruction.scope == accredited.reconstruction.scope
