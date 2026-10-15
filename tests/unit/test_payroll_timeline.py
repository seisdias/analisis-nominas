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
