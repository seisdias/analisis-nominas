"""Ordinary identified is an exact partial subset, never comparable fixed pay."""

from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from src.salary_reconstruction import Coverage, identified_ordinary
from tests.unit.test_salary_reconstruction import payroll, rebuild


def test_ordinary_subset_is_not_gross_minus_extra_or_fixed():
    e = payroll()
    r = identified_ordinary(e)
    assert r.amount is not None and r.amount.numerator == Decimal("2500")
    assert r.coverage == Coverage.PARTIAL and "parcial" in r.label
    assert len(r.participants) == 2 and "Suma" in r.formula and r.evidence


@pytest.mark.parametrize(
    "case",
    ["revision", "hash", "type", "difference", "unknown", "unreliable", "printed", "missing"],
)
def test_no_sum_without_reviewed_reconciled_earnings(case):
    from src.canonical.values import ValueState
    from tests.unit.test_breakdown_completeness import change

    e = payroll()
    if case == "revision":
        e = replace(e, extractor_revision="other")
    if case == "hash":
        e = replace(e, content_hash="other")
    if case == "type":
        e = rebuild(e, {"nomina.tipo": "PAGA_EXTRA"})
    if case == "difference":
        e = rebuild(e, {"nomina.total_devengado": 280001})
    if case in ("unknown", "unreliable"):
        e = change(
            e, ".importe", None, ValueState.UNKNOWN if case == "unknown" else ValueState.UNRELIABLE
        )
    if case == "printed":
        e = change(e, ".importe_texto", "100.00")
    if case == "missing":
        e = replace(e, concepts=e.concepts[:-1])
    assert identified_ordinary(e).amount is None


def test_unknown_function_does_not_become_residual_salary():
    e = payroll()
    c = next(c for c in e.concepts if c.get("codigo").fact.value.value == "9032")
    e = rebuild(e, {c.get("concepto").fact.fact_key: "Desconocido"})
    r = identified_ordinary(e)
    assert r.amount is not None and r.amount.numerator == Decimal("2500")
    assert r.coverage == Coverage.PARTIAL


def test_scalar_duplicate_and_month_do_not_change_sum():
    e = payroll()
    r = identified_ordinary(rebuild(e, {"nomina.mes": "1"}))
    assert r.amount == identified_ordinary(e).amount
    assert identified_ordinary(e).coverage == Coverage.PARTIAL


def test_decimal_precision_and_repeated_occurrences():
    with localcontext() as ctx:
        ctx.prec = 2
        amount = identified_ordinary(payroll()).amount
        assert amount is not None and amount.numerator == Decimal("2500")
