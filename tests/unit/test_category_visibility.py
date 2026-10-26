"""Visibility never changes documentary decisions or statistical inputs."""
from copy import deepcopy

from src.analytic_dataset import DocumentCategory as C
from src.payroll_timeline import (
    CATEGORIES,
    CATEGORY_LABELS,
    category_average,
    category_chart,
    visible_timeline,
)
from tests.unit.test_multipayment_timeline import documented, plot
from tests.unit.test_payroll_timeline import record, year_records


def test_categories_have_distinct_labels_and_shapes():
    assert len(CATEGORY_LABELS) == len(C) == len(CATEGORIES) == 8
    assert CATEGORY_LABELS[C.VARIABLE_BONUS] == 'Variables / bonus'
    spec = category_chart([], '2025-01-01', '2025-12-01', []).to_dict()
    scale = spec['layer'][1]['encoding']['shape']['scale']
    assert len(set(scale['range'])) == len(scale['domain']) == 8


def test_visibility_keeps_full_context_multipayment_lines_and_traceability():
    rows = year_records() + [record('bonus', month=6)]
    docs = [documented(f'd{m}', C.ORDINARY) for m in range(1, 13)] + [documented('bonus', C.VARIABLE_BONUS)]
    full = plot(rows, docs)
    before = deepcopy(full)
    ordinary = visible_timeline(full, ('Nóminas ordinarias',))
    assert full == before
    assert len(full.points) == 25 and len(ordinary.points) == 24
    assert all(p in full.points for p in ordinary.points)
    assert category_average(full.points, rows, classified=True) == []
    assert category_average(ordinary.points, rows, classified=True) == []
    assert visible_timeline(full, ()).points == []
    assert visible_timeline(full, CATEGORIES) == full
    spec = category_chart(full.points, '2025-01-01', '2025-12-01', []).to_dict()
    assert not any(p['Fecha'] == '2025-06-01' for p in spec['layer'][0]['data']['values'])
    assert len(spec['layer'][1]['data']['values']) == 3
    assert 'transform' not in spec


def test_visibility_cannot_remove_hold_or_resolve_ambiguous_month():
    rows = [record('a'), record('b')]
    docs = [documented('a', C.ORDINARY), documented('b', C.EXTRA)]
    for full in (plot(rows, docs, withheld_document_ids=frozenset({'b'})),
                 plot(rows, [docs[0], documented('b', C.UNCLASSIFIED)])):
        selected = visible_timeline(full, ('Nóminas ordinarias',))
        assert not selected.points
        assert selected.ambiguous_periods == full.ambiguous_periods == 1
        assert selected.table[0] in full.table
