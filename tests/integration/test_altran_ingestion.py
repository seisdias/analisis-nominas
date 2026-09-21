"""Private Altran corpus -> isolated SQLite -> complete domain round-trip."""
import json
from pathlib import Path
from unittest.mock import patch

from scripts.ingest_altran import IngestionResult, run_ingestion
from src.models.nomina import Nomina
from src.parsers.parser_factory import ParserFactory
from src.services.database_service import DatabaseService
from tests.integration.test_altran_parser import CORPUS, MANIFEST
from tests.integration.test_altran_parser import documents as documents
from tests.integration.test_altran_parser import oracle as oracle
from tests.integration.test_altran_parser import test_exhaustive_quantities as verify_quantities
from tests.integration.test_altran_parser import test_payroll as verify_payroll


def test_complete_corpus_double_ingestion(tmp_path: Path, request):
    oracle_data = request.getfixturevalue("oracle")
    parsed = request.getfixturevalue("documents")
    before = MANIFEST.read_bytes()
    db = str(tmp_path / "isolated-altran.sqlite")
    service = DatabaseService(db)
    with patch("scripts.ingest_altran.ParserFactory", wraps=ParserFactory) as factory:
        first_result = run_ingestion(CORPUS, db)
        assert factory.call_count == 73  # Certificates and scanned PDF never reach a parser.
    assert first_result == IngestionResult(78, 73, 5, 0, 71, 71)
    first = sorted(service.obtener_todos(), key=lambda r: r["id"])
    assert len(first) == len({r["id"] for r in first}) == 71
    expected = {doc.id: doc for doc in parsed.values()}
    restored = {r["id"]: Nomina.from_dict(json.loads(r["payload"])) for r in first}
    assert restored == expected
    by_file = {name: restored[doc.id] for name, doc in parsed.items()}
    for index in range(73):
        verify_payroll(index, oracle_data, by_file)
    verify_quantities(oracle_data, by_file)
    for row in first:
        doc = restored[row["id"]]
        assert row["cif"] == doc.cif
        assert row["tipo"] == doc.tipo.value == "NOMINA_ORDINARIA"
        assert row["total_devengado"] == doc.total_devengado
        assert row["total_deducir"] == doc.total_deducir
        assert row["liquido_percibir"] == doc.liquido_percibir
    assert "2016-03-ALTRAN-2016-03-07_2016-03-31" in restored
    for group in oracle_data["duplicate_groups"]:
        pair = [parsed[name] for name in group["filenames"]]
        assert pair[0] == pair[1]
        assert sum(r["id"] == pair[0].id for r in first) == 1
        # Reversing UPSERT order must preserve even non-economic payload fields.
        for doc in reversed(pair):
            service.guardar_documento(doc)
        assert sorted(service.obtener_todos(), key=lambda r: r["id"]) == first
    assert run_ingestion(CORPUS, db) == first_result
    second = sorted(service.obtener_todos(), key=lambda r: r["id"])
    assert second == first
    assert MANIFEST.read_bytes() == before
