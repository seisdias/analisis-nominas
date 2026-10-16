"""Documentary plotting never aggregates, selects candidates or fills months."""
from src.canonical.values import CurrencyCode, ExactDecimal
from src.payroll_timeline import prepare_timeline


def record(doc='a', year=2025, month=1, company='Empresa', series='Bruto',
           status='certified', currency=None, versions=('v1',)):
    return dict(document_id=doc, company_text=company, year=year, month=month,
                series=series, observation_id=doc+series, version_ids=versions,
                source_version_ids=versions[:1], eligibility='evidence_only', document_status=status,
                value={'status': status, 'amount': ExactDecimal(123456, 2), 'currency': currency})


def test_order_series_and_gap_without_fabricated_records():
    result = prepare_timeline([record(month=3), record(), record(series='Neto')], years=(2006, 2025))
    assert [p['Fecha'] for p in result.points] == ['2025-01-01', '2025-01-01', '2025-03-01']
    gross = [p for p in result.points if p['Serie'] == 'Bruto']
    assert gross[0]['Tramo'] != gross[1]['Tramo']
    assert len(result.table) == 3
    assert result.table[0]['Importe'] == '1.234,56 €'


def test_combined_filters_and_incomplete_rows():
    rows = [record(), record(doc='b', year=2024), record(doc='c', company='Otra'),
            record(doc='d', month=None), record(doc='e', year=None)]
    result = prepare_timeline(rows, company='Empresa', years=(2025, 2025), series=('Bruto',))
    assert len(result.points) == 1
    assert len(result.table) == 3
    assert prepare_timeline(rows, years=(2006, 2025), series=()).points == []


def test_same_month_different_documents_never_combined_even_if_equal():
    result = prepare_timeline([record(), record(doc='b')], years=(2006, 2025))
    assert result.points == []
    assert result.ambiguous_periods == 1
    assert len(result.table) == 2
    assert all('ambiguo' in row['Representación'] for row in result.table)


def test_candidates_multiversion_and_resolved_observation():
    unresolved = record(status='no_observation', versions=('v1', 'v2'))
    assert prepare_timeline([unresolved], years=(2006, 2025)).ambiguous_periods == 1
    resolved = record(versions=('v1', 'v2'))
    assert len(prepare_timeline([resolved], years=(2006, 2025)).points) == 1
    candidates = [record(status='ambiguous'), record(status='ambiguous')]
    assert prepare_timeline(candidates, years=(2006, 2025)).points == []


def test_currency_null_states_and_company_isolation():
    rows = [record(), record(doc='b', company='Otra', currency=CurrencyCode('USD')),
            record(doc='c', month=2, status='not_certified'),
            record(doc='d', month=3, status='no_observation'), record(doc='e', month=4, company=None)]
    result = prepare_timeline(rows, years=(2006, 2025))
    assert len(result.points) == 1
    assert len(result.table) == 5
    assert any('Inconsistencia' in r['Importe'] for r in result.table)
    assert prepare_timeline([record(currency=CurrencyCode('EUR'))], years=(2006, 2025)).points
    assert prepare_timeline([], years=(2006, 2006)).table == []


def year_records():
    return [record(doc=f'd{month}', month=month, series=series)
            for month in range(1, 13) for series in ('Bruto', 'Neto')]


def averages(rows):
    from src.payroll_timeline import moving_average
    return moving_average(prepare_timeline(rows, years=(2025, 2026)).points, rows)


def test_twelve_month_mean_separate_series_preserves_originals():
    from copy import deepcopy
    rows = year_records()
    for row in rows:
        row['value']['amount'] = ExactDecimal(row['month'] * (100 if row['series'] == 'Bruto' else 50), 0)
    before = deepcopy(rows)
    result = averages(rows)
    assert {r['Serie']: r['Importe'] for r in result} == {
        'Bruto · Media móvil de 12 meses': 650, 'Neto · Media móvil de 12 meses': 325}
    assert all(r['Fecha'] == '2025-12-01' for r in result)
    assert rows == before


def test_short_missing_ambiguous_and_extraordinary_months_block_mean():
    rows = year_records()
    assert averages(rows[:-2]) == []
    assert averages([r for r in rows if r['month'] != 6]) == []
    assert averages(rows + [record(doc='extra', month=6)]) == []
    rows[10]['document_status'] = 'ambiguous'
    assert averages(rows) == []


def test_companies_currencies_and_incomplete_periods_are_not_combined():
    rows = year_records()
    for row in rows[12:]:
        row['company_text'] = 'Otra'
    assert averages(rows) == []
    rows = year_records()
    rows[10]['value']['currency'] = CurrencyCode('USD')
    assert [r['Serie'] for r in averages(rows)] == ['Neto · Media móvil de 12 meses']
    assert averages(year_records() + [record(doc='unknown', month=None)]) == []


def test_resolved_versions_not_added_and_gap_requires_new_twelve_months():
    rows = year_records()
    for row in rows:
        row['version_ids'] = ('v1', 'v2', 'v3')
    assert len(averages(rows)) == 2
    rows += [record(doc='next', year=2026, month=1), record(doc='gap', year=2026, month=3)]
    result = averages(rows)
    assert [r['Fecha'] for r in result].count('2026-01-01') == 1
    assert not any(r['Fecha'] == '2026-03-01' for r in result)


def test_null_eur_and_missing_amount_are_independent():
    rows = year_records()
    rows[0]['value']['currency'] = CurrencyCode('EUR')
    assert len(averages(rows)) == 2
    rows[10]['value']['amount'] = None
    assert [r['Serie'] for r in averages(rows)] == ['Neto · Media móvil de 12 meses']
    rows[11]['value']['status'] = 'not_certified'
    assert averages(rows) == []
