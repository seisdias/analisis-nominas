"""Private documentary persistence: all versions retained, none economically published."""
import json
from collections import Counter

from scripts.ingest_alten import IngestionResult, run_ingestion
from src.models.nomina import Nomina
from src.services.database_service import DatabaseService
from tests.private.test_alten_parser import CORPUS, MANIFEST
from tests.private.test_alten_parser import extracted as extracted
from tests.private.test_alten_parser import oracle as oracle
from tests.private.test_alten_parser import parsed as parsed
from tests.private.test_alten_parser import test_all_versions_retained as verify_versions
from tests.private.test_alten_parser import (
    test_documentary_discrepancies_are_not_corrected as verify_discrepancies,
)
from tests.private.test_alten_parser import test_quantitative_coverage as verify_quantities
from tests.private.test_alten_parser import test_version as verify_version


def test_full_documentary_corpus_twice(tmp_path, request):
    oracle_data = request.getfixturevalue("oracle")
    documents = request.getfixturevalue("extracted")
    parsed_docs = request.getfixturevalue("parsed")
    manifest_before = MANIFEST.read_bytes()
    path = str(tmp_path / 'isolated-alten-evidence.sqlite')
    db = DatabaseService(path)
    first = run_ingestion(CORPUS, path)
    assert first == IngestionResult(
        found=55, payroll_pdfs=52, certificates=3, versions=78, periods=52,
        stored_versions=78, new_versions=78, idempotent_versions=0, failed=0,
    )
    periods = db.obtener_periodos_documentales()
    versions = db.obtener_versiones_documentales()
    assert len(periods) == 52 and len(versions) == 78
    assert {p['resolution_status'] for p in periods} == {'UNRESOLVED'}
    assert all(p[k] is None for p in periods for k in (
        'resolution_kind', 'selected_version_key', 'economic_payload',
        'resolution_note', 'resolution_evidence', 'resolved_at',
    ))
    counts = Counter(v['period_key'] for v in versions)
    assert Counter(counts.values()) == {1: 27, 2: 24, 3: 1}
    assert next(p for p in periods if counts[p['period_key']] == 3)['fecha_inicio'] == '2025-10-01'
    expected = {e['version_key']: e for e in oracle_data['payroll_versions']}
    assert {v['version_key'] for v in versions} == set(expected)
    restored = {v['version_key']: Nomina.from_dict(json.loads(v['payload'])) for v in versions}
    assert restored == parsed_docs
    for v in versions:
        e = expected[v['version_key']]
        assert (v['period_key'], v['pdf_sha256'], v['page_number'], v['source_filename']) == (
            e['period_key'], e['sha256_pdf'], e['pagina'], e['filename'],
        )
    # Reuse the independent oracle_data comparisons, not just equality with parser output.
    for index in range(78):
        verify_version(index, oracle_data, restored, documents)
    verify_quantities(oracle_data, restored, documents)
    verify_versions(oracle_data, restored)
    verify_discrepancies(oracle_data, restored)
    counts_by_pdf = Counter(v['pdf_sha256'] for v in versions)
    assert sorted(n for n in counts_by_pdf.values() if n > 1) == [2, 13, 14]
    assert len(counts_by_pdf) == 52
    assert db.obtener_todos() == []
    assert db.obtener_certificados() == []
    assert all(db.obtener_documentos_por_empresa(n.empresa) == [] for n in restored.values())
    assert run_ingestion(CORPUS, path) == IngestionResult(
        found=55, payroll_pdfs=52, certificates=3, versions=78, periods=52,
        stored_versions=78, new_versions=0, idempotent_versions=78, failed=0,
    )
    assert db.obtener_versiones_documentales() == versions
    assert db.obtener_periodos_documentales() == periods
    assert db.obtener_todos() == []
    assert MANIFEST.read_bytes() == manifest_before
