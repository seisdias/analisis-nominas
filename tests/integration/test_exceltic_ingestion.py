"""Real Exceltic PDFs -> isolated SQLite -> domain objects, using the private oracle."""
import json
from pathlib import Path

from scripts.ingest_exceltic import IngestionResult, run_ingestion
from src.models.nomina import Nomina
from src.services.database_service import DatabaseService
from src.services.ingestion_service import parse_nomina_pdf
from tests.integration.test_exceltic_parser import (
    CORPUS,
    MANIFEST,
    TEXTUAL,
    _inventory,
)
from tests.integration.test_exceltic_parser import (
    test_exceltic_private_document as verify_oracle_document,
)


def test_private_exceltic_double_ingestion_and_payload_roundtrip(tmp_path: Path) -> None:
    _inventory()
    manifest_before = (CORPUS.parents[1] / "private/exceltic-manifest.json").read_bytes()
    expected = {
        e["filename"]: parse_nomina_pdf(CORPUS / e["filename"])
        for e in TEXTUAL
    }
    db = str(tmp_path / "isolated-exceltic.sqlite")
    first_result = run_ingestion(CORPUS, db)
    assert first_result == IngestionResult(8, 8, 0, 0, 7, 7)
    service = DatabaseService(db)
    first = sorted(service.obtener_todos(), key=lambda r: r["id"])
    assert len(first) == 7 and len({r["id"] for r in first}) == 7
    recovered = {
        r["id"]: Nomina.from_dict(json.loads(r["payload"])) for r in first
    }
    recovered_by_file = {name: recovered[doc.id] for name, doc in expected.items()}
    for entry in TEXTUAL:
        name = entry["filename"]
        assert recovered_by_file[name] == expected[name]
        verify_oracle_document(entry, recovered_by_file)
    for row in first:
        doc = recovered[row["id"]]
        assert row["total_devengado"] == doc.total_devengado
        assert row["total_deducir"] == doc.total_deducir
        assert row["liquido_percibir"] == doc.liquido_percibir
        assert row["cif"] == doc.cif
    duplicate = MANIFEST["grupos_duplicados"][0]["archivos"]
    first_id, second_id = (expected[name].id for name in duplicate)
    assert first_id == second_id
    assert sum(r["id"] == first_id for r in first) == 1
    assert run_ingestion(CORPUS, db) == first_result
    assert sorted(service.obtener_todos(), key=lambda r: r["id"]) == first
    assert (CORPUS.parents[1] / "private/exceltic-manifest.json").read_bytes() == manifest_before
