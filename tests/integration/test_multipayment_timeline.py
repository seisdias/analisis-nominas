"""C.3 uses persisted synthetic evidence, never a private corpus or SQL repair."""
from src.analytic_dataset import load_analytic_dataset
from src.canonical.facts import DocumentaryFact, FactDraft
from src.canonical.values import CanonicalValue, ValueState
from src.canonical_inspection import open_inspector
from src.payroll_timeline import classified_timeline
from src.persistence import connect
from src.persistence.economics import EconomicRepository
from tests.integration.persistence.test_analytic_dataset import add_document, dataset

__all__ = ['dataset']


def test_persisted_intervals_read_only_end_to_end(dataset):
    path = dataset[0]
    first = add_document(dataset, 'first-interval', 1)
    second = add_document(dataset, 'second-interval', 1)
    with connect(path, mode='read_write') as conn:
        repo = EconomicRepository(conn)
        for identity, dates in ((first, ('2025-01-01', '2025-01-09')),
                                (second, ('2025-01-10', '2025-01-31'))):
            version = repo.get_document_versions(identity)[0]
            extraction = conn.execute('SELECT extraction_id FROM extractions WHERE version_id=?',
                                      (version.version_id,)).fetchone()[0]
            for key, value in zip(('fecha_inicio', 'fecha_fin'), dates, strict=True):
                repo.register_fact(DocumentaryFact.from_draft(extraction, FactDraft('nomina.' + key,
                    CanonicalValue(state=ValueState.PRESENT, value=value))))
    before = path.read_bytes()
    with open_inspector(path) as inspector:
        rows = inspector.timeline_records()
    docs = load_analytic_dataset(path)
    result = classified_timeline(rows, docs, years=(2025, 2025), company='Synthetic employer')
    assert len(result.points) == 4
    assert result.ambiguous_periods == 0
    assert {r['Documento'] for r in result.points} == {first, second}
    assert all(r['Importe'] == 0 for r in result.points)
    assert all(r['Intervalo documental'] != 'No disponible' for r in result.table)
    assert len({r['Observación'] for r in result.points}) == 4
    assert all(r['Elegibilidad'] == 'evidence_only' for r in result.table)
    assert path.read_bytes() == before


def test_screen_applies_local_hold_without_mutating_database(dataset, monkeypatch):
    from src.cli_config import Configuration
    from tests.integration.test_payroll_timeline import page

    path = dataset[0]
    identity = add_document(dataset, 'withheld', 1)
    monkeypatch.setattr('src.payroll_timeline.load_config', lambda: Configuration(
        path, None, 'synthetic', (identity,)))
    before = path.read_bytes()
    app = page()
    assert not app.exception
    assert any('restricciones locales' in message.value for message in app.info)
    table = app.dataframe[0].value
    pending = table[table['Representación'] == 'Revisión pendiente: restricción de presentación']
    assert len(pending) == 2
    assert path.read_bytes() == before
