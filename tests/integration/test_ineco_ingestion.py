"""Full private INECO ingestion into isolated SQLite; no runtime writes."""

import json
import math
from pathlib import Path

from scripts.ingest_ineco import IngestionResult, run_ingestion
from src.models.nomina import Nomina
from src.services.database_service import DatabaseService
from src.services.ingestion_service import parse_nomina_pdf
from tests.integration.test_ineco_parser import CORPUS, SCANNED, TEXTUAL, _check_inventory


def test_ineco_corpus_storage_and_idempotence(tmp_path: Path) -> None:
    _check_inventory()
    db = str(tmp_path / "ineco.sqlite")
    assert run_ingestion(CORPUS, db) == IngestionResult(60, 1, 0)
    first = {row["id"]: row for row in DatabaseService(db).obtener_todos()}
    assert len(first) == 60
    periods: dict[str, list[tuple[str, str | None, str | None]]] = {}
    fields = {"total_devengado": "total_devengado", "total_deducir": "total_deducciones",
              "liquido_percibir": "liquido_percibir", "irpf_porcentaje": "porcentaje_irpf",
              "irpf_importe": "importe_irpf", "base_irpf": "base_irpf"}
    for expected in TEXTUAL:
        doc = parse_nomina_pdf(CORPUS / expected["filename"])
        assert doc.id in first
        row = first[doc.id]
        payload = json.loads(row["payload"])
        # Covers every model field, including concepts, explicit absences and dates.
        if Nomina.from_dict(payload).to_dict() != doc.to_dict():
            raise AssertionError("INECO model/payload mismatch")
        for key in ("anio", "mes", "empresa", "cif", "fecha_inicio", "fecha_fin"):
            if row[key] != expected[key]:
                raise AssertionError(f"INECO persisted field mismatch: {key}")
        assert row["tipo"] == expected["tipo_documental"]
        for field, oracle_key in fields.items():
            actual, value = row[field], expected[oracle_key]
            if value is None:
                assert actual is None
            elif actual is None or not math.isfinite(actual) or not math.isfinite(value) or abs(actual - value) > .005:
                raise AssertionError(f"INECO persisted amount mismatch: {field}")
        periods.setdefault(doc.periodo, []).append((doc.id, doc.fecha_inicio, doc.fecha_fin))
    split = [entries for entries in periods.values() if len(entries) > 1]
    assert len(split) == 1 and len(split[0]) == 2
    assert len({entry[0] for entry in split[0]}) == 2
    assert len({(entry[1], entry[2]) for entry in split[0]}) == 2
    for scanned in SCANNED:
        assert not any(row["observaciones"] == f"Procesado desde {scanned['filename']}"
                       for row in first.values())
    assert run_ingestion(CORPUS, db) == IngestionResult(60, 1, 0)
    second = {row["id"]: row for row in DatabaseService(db).obtener_todos()}
    if first != second:
        raise AssertionError("INECO repeated ingestion changed persisted data")
