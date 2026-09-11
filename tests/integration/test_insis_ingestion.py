"""Real INSIS4 corpus into temporary SQLite, never the runtime database."""

import math
from pathlib import Path

from scripts.ingest_insis import IngestionResult, run_ingestion
from src.services.database_service import DatabaseService
from tests.integration.test_insis_parser import INSIS_DIR, SCANNED, TEXTUAL, _check_inventory


def test_insis_corpus_persistence_and_idempotence(tmp_path: Path) -> None:
    _check_inventory()
    db_path = str(tmp_path / "insis.sqlite")
    assert run_ingestion(INSIS_DIR, db_path) == IngestionResult(23, 2, 0)
    service = DatabaseService(db_path)
    first = {row["id"]: row for row in service.obtener_todos()}
    assert len(first) == 23
    for expected in TEXTUAL:
        key = f"insis4-{expected['anio']:04d}-{expected['mes']:02d}-{expected['tipo'].lower()}"
        assert key in first
        row = first[key]
        assert row["empresa"] == "INTELIGENCIA SISTEMATICA 4, S.L."
        assert row["cif"] == "B84225283"
        for field, value in expected.items():
            if field == "filename":
                assert row["observaciones"] == f"Procesado desde {value}"
            elif isinstance(value, (float, int)):
                assert math.isfinite(row[field]) and math.isfinite(value)
                assert math.isclose(row[field], value, rel_tol=0, abs_tol=0.005), field
            else:
                assert row[field] == value, field
    for extra in (entry for entry in TEXTUAL if entry["tipo"] == "PAGA_EXTRA"):
        prefix = f"insis4-{extra['anio']:04d}-{extra['mes']:02d}"
        assert prefix + "-nomina_ordinaria" in first
        assert prefix + "-paga_extra" in first
    for scanned in SCANNED:
        assert all(row["observaciones"] != f"Procesado desde {scanned['filename']}"
                   for row in first.values())
    assert run_ingestion(INSIS_DIR, db_path) == IngestionResult(23, 2, 0)
    second = {row["id"]: row for row in service.obtener_todos()}
    assert second == first
