"""Coverage counts documents, never payroll amounts or alternative versions."""
from dataclasses import FrozenInstanceError, replace

import pytest

from src.analytic_dataset import DocumentCategory as Category
from src.documentary_coverage import Availability, CoverageDocument, summarize_coverage
from tests.unit.test_payroll_timeline import analytic


def document(identity='a', *, company='Empresa', year=2025, month=1,
             gross=Availability.CERTIFIED, net=Availability.CERTIFIED,
             category=Category.ORDINARY, restricted=False):
    model = replace(analytic(identity, category), company_text=company,
                    documentary_period=(year, month) if year and month else None)
    return CoverageDocument(model, company, year, month, gross, net, restricted)


def test_two_documents_one_month_and_empty_year():
    docs = (document(), document('extra', category=Category.EXTRA))
    report = summarize_coverage(docs, years=(2025, 2026))
    assert report.document_ids == ('a', 'extra')
    first, empty = report.groups
    assert first.document_ids == ('a', 'extra') and first.months == (1,)
    assert first.missing_months == tuple(range(2, 13)) and first.absence_certain
    assert empty.document_ids == () and empty.missing_months == tuple(range(1, 13))
    assert dict(report.categories)[Category.EXTRA] == ('extra',)


def test_unique_ids_deterministic_and_immutable():
    a, b = document(), document('b', month=3)
    result = summarize_coverage((a, b, a), years=(2025, 2025))
    assert result == summarize_coverage((b, a), years=(2025, 2025))
    assert result.document_ids == ('a', 'b')
    with pytest.raises(FrozenInstanceError):
        setattr(result, 'groups', ())
    with pytest.raises(ValueError, match='Conflicting'):
        summarize_coverage((a, replace(a, month=2)), years=(2025, 2025))


def test_certification_is_distinct_from_observation_and_analytic_availability():
    docs = (document(), document('missing', gross=Availability.NO_OBSERVATION),
            document('blocked', gross=Availability.NOT_CERTIFIED),
            document('competing', gross=Availability.AMBIGUOUS))
    report = summarize_coverage(docs, years=(2025, 2025))
    assert dict(report.gross)[Availability.CERTIFIED] == ('a',)
    assert dict(report.gross)[Availability.NO_OBSERVATION] == ('missing',)
    assert dict(report.gross)[Availability.NOT_CERTIFIED] == ('blocked',)
    assert dict(report.gross)[Availability.AMBIGUOUS] == ('competing',)
    assert report.analytic_gross == ()
    assert report.certified_both == ('a',)
    assert report.review_ids == ('blocked', 'competing', 'missing')


def test_restrictions_do_not_remove_coverage_or_create_economic_exclusions():
    restricted = document(restricted=True)
    report = summarize_coverage((restricted,), years=(2025, 2025))
    assert report.document_ids == report.restricted_ids == report.certified_both == ('a',)
    assert report.review_ids == ()  # presentation hold is separately reported
    assert report.groups[0].months == (1,)


def test_unknown_context_does_not_become_zero_or_prove_absence():
    docs = (document(), document('unknown-month', month=None),
            document('unknown-year', year=None), document('unknown-company', company=None))
    report = summarize_coverage(docs, years=(2025, 2025))
    group = next(g for g in report.groups if g.company == 'Empresa' and g.year == 2025)
    assert group.months == (1,) and not group.absence_certain
    assert len(report.document_ids) == 4
    assert set(report.review_ids) == {'unknown-month', 'unknown-year', 'unknown-company'}
    assert any(g.year is None and g.missing_months == () for g in report.groups)


def test_exact_company_and_year_filters_keep_unlocated_year_explicit():
    docs = (document(), document('other', company='empresa'), document('old', year=2024),
            document('undated', year=None))
    report = summarize_coverage(docs, years=(2025, 2025), company='Empresa')
    assert report.document_ids == ('a', 'undated')
    assert all(g.company == 'Empresa' for g in report.groups)


@pytest.mark.parametrize('years', [(2026, 2025), (0, 2025), (2025, 10000)])
def test_invalid_interval_rejected(years):
    with pytest.raises(ValueError):
        summarize_coverage((), years=years)


def test_empty_dataset_and_unclassified_are_explicit():
    assert summarize_coverage((), years=(2025, 2025)).groups == ()
    report = summarize_coverage((document(category=Category.UNCLASSIFIED),), years=(2025, 2025))
    assert dict(report.categories)[Category.UNCLASSIFIED] == ('a',)
    assert report.review_ids == ('a',)


def test_zero_counts_as_available_and_multiversion_is_not_an_unresolved_conflict():
    from src.analytic_dataset import VersionProvenance
    from src.canonical.values import CanonicalValue, ExactDecimal, ValueState
    zero = CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(0, 0))
    base = document()
    single = replace(base, document=replace(base.document, gross=zero, net=zero))
    multiversion = replace(document('b'), document=replace(document('b').document,
        provenance=(VersionProvenance('v1', 'f', 'a'*64, (1,), ('e1',)),
                    VersionProvenance('v2', 'f', 'a'*64, (2,), ('e2',)))))
    report = summarize_coverage((single, multiversion), years=(2025, 2025))
    assert report.certified_both == ('a', 'b')
    assert report.analytic_gross == report.analytic_net == ('a',)
    assert report.multiversion_ids == ('b',)
    assert report.review_ids == ()
    assert all(set(ids) <= set(report.document_ids) for _, ids in (*report.gross, *report.net, *report.categories))


def test_unknown_company_outside_company_filter_still_makes_gaps_uncertain():
    report = summarize_coverage((document(), document('unassigned', company=None, month=None)),
                                company='Empresa', years=(2025, 2025))
    assert report.document_ids == ('a',)
    assert not report.groups[0].absence_certain


def test_unknown_month_preserves_known_year_and_does_not_cover_twelve_months():
    report = summarize_coverage((document(month=None),), years=(2025, 2025))
    assert report.groups[0].months == ()
    assert report.groups[0].missing_months == tuple(range(1, 13))
    assert not report.groups[0].absence_certain
