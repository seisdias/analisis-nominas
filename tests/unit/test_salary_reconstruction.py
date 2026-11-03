"""Synthetic remuneration contracts, never inferred from matching totals."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext

import pytest

from src.canonical.serialization import canonical_sha256
from src.canonical.values import ValueState
from src.document_concepts import project_extraction
from src.salary_reconstruction import (
    AnnualContract,
    AnnualTerm,
    Bucket,
    ContractEvidence,
    Coverage,
    FixedContract,
    PaymentContract,
    PaymentMode,
    reconstruct,
    scope_for,
)
from tests.unit.test_breakdown_completeness import source
from tests.unit.test_document_concepts import fact
from tests.unit.test_economic_components import example


def payroll():
    e = source(
        rows=(
            ("devengos", 200000),
            ("devengos", 50000),
            ("devengos", 30000),
            ("deducciones", 2000),
        ),
        gross=280000,
        net=278000,
    )
    fs = []
    for f in e.facts:
        key = f.fact.fact_key
        value = f.fact.value
        if "conceptos" in key:
            index = int(key.split(".")[-2])
            attrs = [
                dict(codigo="9001", concepto="salario base", categoria="salario_base"),
                dict(codigo="9004", concepto="comp.salarial", categoria="complementos"),
                dict(codigo="9032", concepto="paga extra vera", categoria="paga_extra_incluida"),
                {},
            ][index]
            if key.split(".")[-1] in attrs:
                value = replace(value, value=attrs[key.split(".")[-1]])
        fs.append(replace(f.fact, value=value))
    fs += [
        fact("nomina.anio", "2025"),
        fact("nomina.mes", "6"),
        fact("nomina.tipo", "NOMINA_ORDINARIA"),
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


def contracts(e, mode=PaymentMode.SEPARATE):
    evidence = ContractEvidence(
        scope_for(e), "Synthetic reviewed remuneration agreement", (2025, 6)
    )
    rows = {c.get("codigo").fact.value.value: c.occurrence for c in e.concepts}
    fixed = FixedContract(
        evidence, (rows["9001"], rows["9004"]), True, True, True, signed_amounts=True
    )
    payment = PaymentContract(evidence, mode, True)
    annual = AnnualContract(
        evidence,
        (AnnualTerm(rows["9001"], 12), AnnualTerm(rows["9004"], 12), AnnualTerm(rows["9032"], 2)),
        (2025, 1),
        (2025, 12),
        True,
    )
    return fixed, payment, annual


def test_partial_components_do_not_claim_fixed_salary():
    result = reconstruct(payroll())
    assert len(result.parts) == 3
    assert sum(p.bucket == Bucket.FIXED_CANDIDATE for p in result.parts) == 2
    assert result.fixed.coverage == Coverage.PARTIAL and result.fixed.amount is None
    assert result.annual.amount is None and result.monthly.amount is None
    assert result.earnings.difference == 0


def test_explicit_fixed_and_unequal_extras_annual_contract():
    e = payroll()
    result = reconstruct(e, *contracts(e))
    assert (
        result.fixed.amount is not None
        and result.annual.amount is not None
        and result.monthly.amount is not None
    )
    assert result.fixed.amount.numerator == Decimal("2500")
    assert result.annual.amount.numerator == Decimal("30600")
    assert result.monthly.amount.numerator == Decimal("30600")
    assert result.monthly.amount.divisor == 12
    assert result.fixed.coverage == Coverage.COMPLETE
    assert result.annual.formula and result.annual.evidence
    assert result.annual.amount.display() == "30.600,00"


@pytest.mark.parametrize(
    "case",
    [
        "missing_fixed",
        "partial",
        "full_month",
        "unit",
        "signs",
        "payment",
        "declared",
        "annual",
        "period",
        "revision",
        "foreign_version",
        "duplicate",
        "extra_partial",
        "interval",
        "missing_extra",
        "double_proration",
    ],
)
def test_complete_calculation_rejects_missing_guarantees(case):
    e = payroll()
    f, p, a = contracts(e)
    if case == "missing_fixed":
        f = None
    if case == "partial":
        f = replace(f, complete=False)
    if case == "full_month":
        f = replace(f, full_month=False)
    if case == "unit":
        f = replace(f, common_unit=False)
    if case == "signs":
        f = replace(f, signed_amounts=False)
    if case == "payment":
        p = None
    if case == "declared":
        p = replace(p, accredited=False)
    if case == "annual":
        a = None
    if case == "period":
        e = replace(e, facts=tuple(x for x in e.facts if x.fact.fact_key != "nomina.mes"))
    if case == "revision":
        e = replace(e, extractor_revision="other")
    if case == "foreign_version":
        e = replace(e, version_id="other")
    if case == "duplicate":
        a = replace(a, terms=a.terms + a.terms[:1])
    if case == "extra_partial":
        a = replace(a, full_extra_composition=False)
    if case == "interval":
        a = replace(a, valid_until=(2025, 5))
    if case == "missing_extra":
        a = replace(a, terms=a.terms[:2])
    if case == "double_proration":
        p = replace(p, mode=PaymentMode.PRORATED)
    r = reconstruct(e, f, p, a)
    assert r.annual.amount is None and r.monthly.amount is None


def test_exact_recurring_division_and_presentation_only_rounding():
    from src.salary_reconstruction import ExactAmount

    with localcontext() as ctx:
        ctx.prec = 2
        value = ExactAmount(Decimal("28000"), 12)
        assert value.display() == "2.333,33"
        assert value.numerator == Decimal("28000") and value.divisor == 12


@pytest.mark.parametrize(
    "args,bucket",
    [
        ({}, Bucket.VARIABLE),
        ({"code": "9030", "label": "Bono/Variable", "category": "variable"}, Bucket.VARIABLE),
        (
            {
                "parser": "ExcelticParser",
                "code": "1",
                "label": "P.P.EXTRA",
                "category": "paga_extra_incluida",
            },
            Bucket.PRORATION,
        ),
        (
            {
                "parser": "InecoParser",
                "code": "9RPE",
                "label": "r. pext dic 2012",
                "category": "regularizaciones",
            },
            Bucket.ADJUSTMENT,
        ),
        (
            {
                "parser": "InecoParser",
                "code": "9025",
                "label": "pago de benefiatra.",
                "category": "beneficios",
                "arrears": "true",
            },
            Bucket.ADJUSTMENT,
        ),
        ({"code": "?", "label": "unknown"}, Bucket.UNKNOWN),
    ],
)
def test_documented_roles_reuse_catalog(args, bucket):
    _, d = example(**args)
    r = reconstruct(d.extractions[0])
    assert r.parts[0].bucket == bucket
    assert r.parts[0].amount == Decimal("123.45")
    assert r.fixed.amount is None
    amount = r.parts[0].source.source.get("importe")
    assert amount is not None and amount.pages == (2,)


@pytest.mark.parametrize(
    "state", [ValueState.UNKNOWN, ValueState.UNRELIABLE, ValueState.NOT_PRESENT]
)
def test_unusable_amount_never_zero(state):
    _, d = example(state=state)
    r = reconstruct(d.extractions[0])
    assert r.parts[0].amount is None and r.fixed.amount is None


def test_repeated_codes_preserved_negative_documented():
    _, d = example(count=2, amount=-100)
    r = reconstruct(d.extractions[0])
    assert len(r.parts) == 2 and all(p.amount == Decimal("-1") for p in r.parts)
    assert len({p.source.source.occurrence for p in r.parts}) == 2


def test_mixed_scope_and_truncated_occurrences_block_projection():
    e = payroll()
    for bad in (
        replace(e, concepts=e.concepts[:-1]),
        replace(e, concepts=e.concepts + e.concepts[:1]),
        replace(e, concepts=(replace(e.concepts[0], extraction_id="foreign"), *e.concepts[1:])),
    ):
        r = reconstruct(bad)
        assert not r.parts and r.fixed.amount is None and r.issues


def test_immutable_deterministic_no_canonical_mutation():
    e = payroll()
    before = repr(e)
    r = reconstruct(e)
    assert r == reconstruct(
        replace(e, concepts=tuple(reversed(e.concepts)), facts=tuple(reversed(e.facts)))
    )
    with pytest.raises(FrozenInstanceError):
        setattr(r, "parts", ())
    assert repr(e) == before


def rebuild(e, changes):
    fs = [
        fact(f.fact.fact_key, changes[f.fact.fact_key]) if f.fact.fact_key in changes else f.fact
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


def test_twelve_payments_use_proration_once():
    e = payroll()
    extra = next(c for c in e.concepts if c.get("codigo").fact.value.value == "9032")
    # Use the existing ALTEN proration rule, and existing fixed rules for that format.
    changes = {}
    mapping = {
        "9001": ("9001", "Salario Base Convenio", "salario_base"),
        "9004": ("9004", "A Cuenta Convenio", "complemento_salarial"),
        "9032": ("9016", "P.P. Extra Verano", "paga_extra_incluida"),
    }
    for c in e.concepts:
        code = c.get("codigo").fact.value.value
        if code in mapping:
            for field, value in zip(("codigo", "concepto", "categoria"), mapping[code]):
                changes[c.get(field).fact.fact_key] = value
    e = replace(rebuild(e, changes), extractor_name="alten-legacy-evidence")
    evidence = ContractEvidence(scope_for(e), "Synthetic reviewed twelve-pay structure", (2025, 6))
    ids = tuple(
        c.occurrence for c in e.concepts if c.get("codigo").fact.value.value in ("9001", "9004")
    )
    f = FixedContract(evidence, ids, True, True, True, signed_amounts=True)
    p = PaymentContract(evidence, PaymentMode.PRORATED, True)
    a = AnnualContract(
        evidence,
        tuple(AnnualTerm(i, 12) for i in (*ids, extra.occurrence)),
        (2025, 1),
        (2025, 12),
        True,
    )
    r = reconstruct(e, f, p, a)
    assert r.annual.amount is not None
    assert r.annual.amount.numerator == Decimal("33600")
    assert r.monthly.amount is not None
    assert r.monthly.amount.display() == "2.800,00"
    assert r.fixed.amount is not None
    assert r.fixed.amount.numerator == Decimal("2500")
    assert (
        r.earnings.calculated is None
    )  # independent remuneration coverage, not borrowed accounting


def test_incomplete_fixed_contract_can_report_partial_accredited_sum():
    e = payroll()
    f, _, _ = contracts(e)
    r = reconstruct(e, replace(f, occurrences=f.occurrences[:1], complete=False))
    assert r.fixed.amount is not None
    assert r.fixed.amount.numerator == Decimal("2000") and r.fixed.coverage == Coverage.PARTIAL
    assert r.annual.amount is None


@pytest.mark.parametrize(
    "case",
    [
        "unknown",
        "unreliable",
        "bonus",
        "arrears",
        "missing_candidate",
        "duplicate_fixed",
        "type_extra",
        "hash",
        "unit_mixed",
    ],
)
def test_fixed_contract_cannot_promote_invalid_components(case):
    e = payroll()
    f, p, a = contracts(e)
    if case == "missing_candidate":
        f = replace(f, occurrences=f.occurrences[:1])
    elif case == "duplicate_fixed":
        f = replace(f, occurrences=f.occurrences + f.occurrences[:1])
    elif case == "hash":
        e = replace(e, content_hash="invalid")
    else:
        c = next(c for c in e.concepts if c.occurrence == f.occurrences[0])
        if case == "type_extra":
            e = rebuild(e, {"nomina.tipo": "PAGA_EXTRA"})
        elif case == "arrears":
            e = rebuild(e, {c.get("atraso").fact.fact_key: "true"})
        elif case == "bonus":
            e = rebuild(e, {c.get("categoria").fact.fact_key: "bono"})
        else:
            from src.canonical.values import CurrencyCode

            field = c.get("importe").fact.fact_key
            fs = []
            for v in e.facts:
                if v.fact.fact_key != field:
                    fs.append(v.fact)
                elif case == "unit_mixed":
                    fs.append(
                        replace(v.fact, value=replace(v.fact.value, currency=CurrencyCode("USD")))
                    )
                else:
                    fs.append(
                        fact(
                            field,
                            None,
                            state=ValueState.UNKNOWN
                            if case == "unknown"
                            else ValueState.UNRELIABLE,
                        )
                    )
            e = project_extraction(
                e.document_id,
                e.version_id,
                e.extraction_id,
                fs,
                extractor_name=e.extractor_name,
                extractor_revision=e.extractor_revision,
                content_hash=canonical_sha256({v.fact_key: v.value for v in fs}),
            )
        evidence = replace(f.evidence, scope=scope_for(e))
        f = replace(f, evidence=evidence)
    r = reconstruct(e, f, p, a)
    assert r.fixed.amount is None


def test_independent_extra_is_reference_not_added_to_breakdown():
    e = rebuild(payroll(), {"nomina.tipo": "PAGA_EXTRA"})
    r = reconstruct(e)
    assert len(r.independent_extras) == 1 and len(r.parts) == 3
    assert all(
        amount.fact.fact_id != r.independent_extras[0].fact.fact_id
        for p in r.parts
        if (amount := p.source.source.get("importe")) is not None
    )
    assert r.fixed.amount is None


def test_scalars_information_and_absence_never_become_extra_income():
    e = payroll()
    fs = [v.fact for v in e.facts] + [
        fact("nomina.salario_base", 200000),
        fact("nomina.prorrata_pagas_extra", 99999),
    ]
    enriched = project_extraction(
        e.document_id, e.version_id, e.extraction_id, fs, extractor_name=e.extractor_name
    )
    assert reconstruct(enriched).parts == reconstruct(e).parts
    empty = project_extraction(e.document_id, e.version_id, e.extraction_id, fs[-2:])
    assert not reconstruct(empty).parts and reconstruct(empty).fixed.amount is None


def test_negative_amount_never_reassigned_to_bonus_or_fixed():
    e = payroll()
    c = next(c for c in e.concepts if c.get("codigo").fact.value.value == "9032")
    r = reconstruct(rebuild(e, {c.get("importe").fact.fact_key: -12345}))
    assert any(p.bucket == Bucket.EXTRA and p.amount == Decimal("-123.45") for p in r.parts)
    assert r.fixed.amount is None


def test_payment_modality_independent_but_not_sufficient():
    e = payroll()
    _, p, _ = contracts(e)
    r = reconstruct(e, payment=p)
    assert r.payment_mode == PaymentMode.SEPARATE and r.annual.amount is None


def test_contract_validity_is_structure_not_actual_yearly_pay():
    e = payroll()
    f, p, a = contracts(e)
    a = replace(a, valid_from=(2025, 6), valid_until=(2025, 6))
    r = reconstruct(e, f, p, a)
    assert r.annual.amount is not None
    assert "no es el total cobrado" in r.annual.reason


def test_other_extraction_and_version_require_new_contracts():
    e = payroll()
    for other in (replace(e, extraction_id="another"), replace(e, version_id="another")):
        assert reconstruct(other, *contracts(e)).annual.amount is None


def test_difference_is_preserved_and_never_fabricates_fixed():
    r = reconstruct(rebuild(payroll(), {"nomina.total_devengado": 280001}))
    assert r.earnings.difference == Decimal("-.01")
    assert r.fixed.amount is None and not r.functional_exhaustive


def test_exact_sum_not_ambient_decimal_context():
    e = payroll()
    with localcontext() as ctx:
        ctx.prec = 2
        r = reconstruct(e, *contracts(e))
    assert r.annual.amount is not None
    assert r.annual.amount.numerator == Decimal("30600")


def test_annual_contract_cannot_invent_multiplicity_or_add_duplicate_proration():
    e = payroll()
    f, p, a = contracts(e)
    for repetitions in (0, -1, True, 1.5):
        bad = replace(a, terms=(replace(a.terms[0], repetitions=repetitions), *a.terms[1:]))
        assert reconstruct(e, f, p, bad).annual.amount is None


def test_no_month_or_amount_heuristic_and_documentary_period_only():
    e = payroll()
    changed = rebuild(
        e, {"nomina.anio": "2023", "nomina.mes": "1", "nomina.total_devengado": 99999999}
    )
    r = reconstruct(changed)
    assert r.period == (2023, 1)
    assert [p.bucket for p in r.parts] == [p.bucket for p in reconstruct(e).parts]
    assert r.annual.amount is None


def test_compensation_not_fixed_and_informational_rows_not_components():
    _, d = example(parser="ExcelticParser", code="1", label="AYUDA COMIDA", category="ayuda_comida")
    assert reconstruct(d.extractions[0]).parts[0].bucket == Bucket.OTHER
    for column in ("bases", "informacion", "deducciones"):
        _, d = example(column=column)
        assert reconstruct(d.extractions[0]).parts == ()


def test_annual_unknown_periodicity_does_not_follow_accounting_equality():
    e = payroll()
    r = reconstruct(e)
    assert r.earnings.status.value == "Conciliado con evidencia suficiente"
    assert r.fixed.amount is None and r.monthly.amount is None
    assert not r.functional_exhaustive


def test_complete_functional_decomposition_reuses_exact_earnings_diagnosis():
    e = payroll()
    r = reconstruct(e, *contracts(e))
    assert r.functional_exhaustive
    assert r.earnings.calculated == Decimal("2800")
    assert len({p.source.source.occurrence for p in r.parts}) == len(r.parts)


def test_documentary_total_absence_does_not_hide_explicit_bonus():
    _, d = example()
    r = reconstruct(d.extractions[0])
    assert r.earnings.calculated is None and r.parts[0].bucket == Bucket.VARIABLE


def test_local_presentation_restriction_not_lifted_by_reconstruction():
    from tests.unit.test_economic_components import run

    doc, d = example()
    r = reconstruct(d.extractions[0])
    assert r.parts  # documentary inspection is not graph authorization
    assert not run(doc, d, {doc.document_id: "Restricción local"}).points
    assert not doc.observations


def test_b1_remains_separate_from_multiversion_diagnostic():
    from tests.unit.test_economic_components import run

    doc, d = example()
    before = run(doc, d)
    reconstruct(d.extractions[0])
    assert run(doc, d) == before
    other = replace(
        doc, provenance=doc.provenance + (replace(doc.provenance[0], version_id="other"),)
    )
    assert not run(other, d).points
