"""Intersection and context, without economic arithmetic or implicit selections."""
from dataclasses import replace

import pytest

from src.analysis_context import ContextFilters, build_context, parse_period
from src.documentary_coverage import Availability
from tests.unit.test_documentary_coverage import document


@pytest.mark.parametrize('text,expected', [('', None), ('2015', ((2015, 1), (2015, 12))),
    ('09/2022', ((2022, 9), (2022, 9))), ('03/2015 – 09/2015', ((2015, 3), (2015, 9))),
    ('2015-2016', ((2015, 1), (2016, 12))), ('01/2015 - 06/2016', ((2015, 1), (2016, 6)))])
def test_period(text, expected):
    assert parse_period(text) == expected


@pytest.mark.parametrize('text', ['13/2025', '2026-2025', 'abc', '0000', '02/2025-01/2025'])
def test_invalid_period_never_broadens(text):
    with pytest.raises(ValueError):
        parse_period(text)


def corpus():
    return (document('a', year=2015, month=3), document('b', year=2015, month=9),
            document('c', year=2016, month=1), document('other', company='empresa', year=2015),
            document('unknown', year=None, month=None), document('no-company', company=None, year=2015))


def test_history_company_intersection_and_no_duplicates():
    rows = corpus()
    history = build_context(rows + rows, ContextFilters())
    assert len(history.documents) == 6 and history.level == 'history'
    assert history == build_context(tuple(reversed(rows)), ContextFilters())
    company = build_context(rows, ContextFilters(company='Empresa'))
    assert len(company.documents) == 4 and company.level == 'company'
    year = build_context(rows, ContextFilters(period=parse_period('2015')))
    assert len(year.documents) == 4 and year.level == 'period'
    interval = build_context(rows, ContextFilters(company='Empresa', period=parse_period('03/2015-01/2016')))
    assert [d.document_id for d in interval.documents] == ['a', 'b', 'c']
    assert len(interval.missing_months) == 8
    assert interval.gaps_uncertain
    assert not build_context(rows, ContextFilters(company='Nobody')).documents


def test_document_selection_and_only_stale_document_is_cleared():
    filters = ContextFilters(company='Empresa', period=parse_period('2015'), document_id='b')
    context = build_context(corpus(), filters)
    assert context.level == 'document' and context.selected_id == 'b'
    assert len(context.candidates) == 2 and len(context.documents) == 1
    stale = build_context(corpus(), replace(filters, period=parse_period('03/2015')))
    assert stale.stale_selection and stale.selected_id is None and stale.level == 'month'
    assert [d.document_id for d in stale.documents] == ['a']
    assert filters.document_id == 'b'  # pure, caller owns state


def test_empty_month_and_incomplete_context_are_distinct():
    empty = build_context(corpus(), ContextFilters(period=parse_period('02/2015')))
    assert not empty.documents and empty.missing_months == ((2015, 2),)
    unknown = build_context(corpus(), ContextFilters(incomplete_only=True))
    assert {d.document_id for d in unknown.documents} == {'unknown', 'no-company'}
    scoped = build_context(corpus(), ContextFilters(incomplete_only=True, period=parse_period('2015')))
    assert [d.document_id for d in scoped.documents] == ['no-company']


def test_same_month_multiversion_states_and_restrictions_remain():
    from src.analytic_dataset import DocumentCategory
    a = document('a', restricted=True)
    b = document('b', category=DocumentCategory.EXTRA, gross=Availability.AMBIGUOUS)
    result = build_context((a, b), ContextFilters(period=parse_period('01/2025')))
    assert len(result.documents) == 2 and result.level == 'month' and result.selected_id is None
    assert result.report.restricted_ids == ('a',)
    assert result.report.certified_both == ('a',)
    assert dict(result.report.categories)[DocumentCategory.EXTRA] == ('b',)
    with pytest.raises(ValueError):
        build_context((a, replace(a, month=3)), ContextFilters())


def test_document_focus_cannot_bypass_multipayment_or_hold():
    from src.analysis_panel import PanelSnapshot, context_timeline
    from src.analytic_dataset import DocumentCategory as C
    from src.payroll_timeline import category_average
    from tests.unit.test_multipayment_timeline import documented
    from tests.unit.test_payroll_timeline import record
    docs = [documented('ordinary', C.ORDINARY), documented('extra', C.EXTRA)]
    coverage = tuple(replace(document(d.document_id), document=d) for d in docs)
    snapshot = PanelSnapshot(coverage, {}, [record('ordinary'), record('extra')])
    filters = ContextFilters(period=parse_period('01/2025'), document_id='ordinary')
    context = build_context(coverage, filters)
    timeline = context_timeline(snapshot, context, filters)
    assert len(timeline.points) == 1 and timeline.points[0]['Multipago']
    assert not category_average(timeline.points, snapshot.timeline, classified=True)
    assert not context_timeline(snapshot, context, filters, ('extra',)).points
    assert len(context.documents) == 1 and len(context.candidates) == 2


def test_panel_context_tracks_multiversion_without_changing_availability():
    from src.analytic_dataset import VersionProvenance
    a = document('a')
    a = replace(a, document=replace(a.document, provenance=(
        VersionProvenance('v1', 'f', 'a'*64, (1,), ('e1',)),
        VersionProvenance('v2', 'f', 'b'*64, (1,), ('e2',)))))
    result = build_context((a,), ContextFilters())
    assert result.report.multiversion_ids == ('a',)
    assert result.report.certified_both == ('a',)
    assert len(result.documents) == 1
