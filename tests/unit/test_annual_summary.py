"""Documentary years never grant economic additivity."""

from dataclasses import replace

import pytest

from src.annual_summary import Additivity, annual_summary
from tests.unit.test_documentary_coverage import document


def report(records, **kwargs):
    return annual_summary(records, {}, {}, [], years=(2024, 2025), **kwargs)


def test_exact_names_logical_identity_and_deterministic_grouping():
    a = document("a", company="ALTEN", year=2024)
    b = document("b", company="Alten", year=2025)
    result = report((a, b, a))
    assert result == report((b, a))
    assert sum(len(g.documents) for g in result.groups) == 2
    assert {g.coverage.company for g in result.groups} == {"ALTEN", "Alten"}
    assert all(
        g.additivity == Additivity.UNACCREDITED and g.aggregate is None for g in result.groups
    )


def test_twelve_months_and_empty_year_do_not_make_salary_or_zero():
    records = tuple(document(str(m), year=2024, month=m) for m in range(1, 13))
    a, b = report(records).groups
    assert len(a.coverage.months) == 12 and not a.missing_months
    assert a.aggregate is None and b.aggregate is None
    assert len(b.missing_months) == 12 and not b.documents
    assert "contrato" in a.reason.lower()


def test_month_window_does_not_claim_outside_filter_missing():
    r = report((document(year=2025, month=3),), period=((2025, 3), (2025, 9)))
    g = next(g for g in r.groups if g.coverage.year == 2025)
    assert g.window_months == tuple(range(3, 10))
    assert g.missing_months == tuple(range(4, 10))


def test_unknown_month_and_company_preserve_uncertainty():
    result = report(
        (document(), document("unknown", month=None), document("company", company=None))
    )
    group = next(
        g for g in result.groups if g.coverage.company == "Empresa" and g.coverage.year == 2025
    )
    assert not group.coverage.absence_certain
    assert len(group.documents) == 2


def test_filtered_unknown_context_cannot_prove_absence():
    assert all(not g.coverage.absence_certain for g in report((document(),), uncertain=True).groups)


def test_conflicting_duplicate_identity_fails_closed():
    with pytest.raises(ValueError):
        report((document(), document(month=2)))


@pytest.mark.parametrize("eligibility", ["evidence_only", "candidate", "excluded"])
def test_no_eligibility_value_is_an_annual_contract(eligibility):
    from src.canonical.certification import EconomicEligibility

    d = document()
    d = replace(d, document=replace(d.document, eligibilities=(EconomicEligibility(eligibility),)))
    result = report((d,))
    assert all(
        g.aggregate is None and g.additivity == Additivity.UNACCREDITED for g in result.groups
    )


def test_restriction_never_removes_coverage():
    d = document(restricted=True)
    result = annual_summary((d,), {}, {"a": "Restricción local"}, [], years=(2025, 2025))
    item = result.groups[0].documents[0]
    assert item.exclusion == "Restricción local"
    assert result.groups[0].coverage.months == (1,)
    assert item.reconstruction is None


def test_components_and_totals_remain_distinct_no_sum():
    from src.documentary_coverage import Availability, CoverageDocument
    from tests.unit.test_income_evolution import fixture

    d, s, g = fixture()
    record = CoverageDocument(
        d, d.company_text, 2025, 6, Availability.CERTIFIED, Availability.CERTIFIED
    )
    result = annual_summary((record,), {d.document_id: s}, {}, [g], years=(2025, 2025))
    item = result.groups[0].documents[0]
    assert item.reconstruction is not None
    assert len(item.reconstruction.parts) == 3
    assert item.ordinary is not None and item.ordinary.amount is not None
    assert item.ordinary.amount.numerator == 2500
    assert result.groups[0].aggregate is None
    assert item.component_relation == Additivity.NON_ADDITIVE
    assert item.version_id == s.version_ids[0]


def test_unlinked_gross_does_not_borrow_components_for_composition():
    from src.documentary_coverage import Availability, CoverageDocument
    from tests.unit.test_income_evolution import fixture

    d, s, g = fixture()
    d = replace(d, observation_facts=(("obs", ("foreign",)),))
    record = CoverageDocument(
        d, d.company_text, 2025, 6, Availability.CERTIFIED, Availability.CERTIFIED
    )
    item = (
        annual_summary((record,), {d.document_id: s}, {}, [g], years=(2025, 2025))
        .groups[0]
        .documents[0]
    )
    assert item.reconstruction is None and item.ordinary is None


def test_independent_extra_is_document_not_an_extra_total_to_add():
    from src.analytic_dataset import DocumentCategory
    from src.annual_view import summary_rows

    rows = summary_rows(
        report((document("ordinary"), document("extra", category=DocumentCategory.EXTRA)))
    )
    row = next(r for r in rows if r["Ejercicio documental"] == "2025")
    assert row["Documentos"] == 2 and row["Extras independientes"] == 1
    assert row["Extras incluidas"] == 0 and row["Total anual"] == "No acreditado"


def test_immutable_results_do_not_modify_sources():
    from dataclasses import FrozenInstanceError

    d = document()
    result = report((d,))
    with pytest.raises(FrozenInstanceError):
        setattr(result.groups[0], "aggregate", 0)
    assert result.groups[-1].documents[0].record == d


def test_unknown_year_does_not_become_payment_year():
    result = report((document(year=None),))
    group = next(g for g in result.groups if g.coverage.year is None)
    assert not group.window_months and not group.missing_months
    assert group.aggregate is None


def test_year_range_preserves_empty_comparison_and_excludes_other_year():
    r = report((document("old", year=2023), document("current", year=2025)))
    assert sum(len(g.documents) for g in r.groups) == 1
    assert {g.coverage.year for g in r.groups} == {2024, 2025}


@pytest.mark.parametrize("state", ["unknown", "unreliable"])
def test_unusable_components_never_become_zero_or_annual_total(state):
    from src.canonical.values import ValueState
    from src.documentary_coverage import Availability, CoverageDocument
    from tests.unit.test_breakdown_completeness import change
    from tests.unit.test_income_evolution import fixture

    d, s, g = fixture()
    e = change(s.extractions[0], ".importe", None, ValueState(state))
    s = replace(s, extractions=(e,))
    record = CoverageDocument(
        d, d.company_text, 2025, 6, Availability.CERTIFIED, Availability.CERTIFIED
    )
    result = annual_summary((record,), {d.document_id: s}, {}, [g], years=(2025, 2025))
    item = result.groups[0].documents[0]
    assert result.groups[0].aggregate is None
    assert item.ordinary is None or item.ordinary.amount is None
    if item.reconstruction:
        assert any(p.amount is None for p in item.reconstruction.parts)


def test_month_intersection_is_enforced_and_unknown_context_keeps_uncertainty():
    result = report(
        (
            document("inside", month=5),
            document("outside", month=1),
            document("unknown", month=None),
        ),
        period=((2025, 3), (2025, 9)),
    )
    assert {d.record.document_id for g in result.groups for d in g.documents} == {"inside"}
    assert not next(g for g in result.groups if g.coverage.year == 2025).coverage.absence_certain


@pytest.mark.parametrize("period", [((2025, 9), (2025, 3)), ((2025, 0), (2025, 12))])
def test_invalid_month_window_is_not_silently_accepted(period):
    with pytest.raises(ValueError):
        report((document(),), period=period)


def test_individual_b1_components_count_even_without_linked_gross_composition():
    from src.annual_view import summary_rows
    from src.documentary_coverage import Availability, CoverageDocument
    from tests.unit.test_income_evolution import fixture

    d, s, g = fixture()
    d = replace(d, observation_facts=(("obs", ("foreign",)),))
    record = CoverageDocument(
        d, d.company_text, 2025, 6, Availability.CERTIFIED, Availability.CERTIFIED
    )
    result = annual_summary((record,), {d.document_id: s}, {}, [g], years=(2025, 2025))
    assert result.groups[0].documents[0].reconstruction is None
    assert summary_rows(result)[0]["Extras incluidas"] == 1
    assert result.groups[0].aggregate is None
