"""Synthetic layout inputs and isolated SQLite; no private payroll values."""
import json
import sqlite3
from dataclasses import replace
from unittest.mock import patch

import pytest

from scripts.ingest_altran import IngestionResult, main, run_ingestion
from src.extraction import ExtractedDocument
from src.models.nomina import Nomina
from src.services.database_service import DatabaseService
from tests.synthetic.parsers.test_altran_parser import structured

CERTIFICATE = ExtractedDocument(
    "Certificado de retenciones e ingresos a cuenta del Impuesto sobre la Renta "
    "de las Personas Físicas\nDatos correspondientes al ejercicio 2098"
)


def inputs(tmp_path, names=("z.PDF", "a.pdf", "b.pdf")):
    directory = tmp_path / "input"
    directory.mkdir()
    for name in names:
        (directory / name).touch()
    (directory / "ignored.txt").touch()
    (directory / "directory.pdf").mkdir()
    return directory


def sample():
    return structured(extra_rows=[
        ("ATR.", "700", "Cotización Desempleo y FP", "0,00", "0,0000", "0,00", None),
    ])


def test_roundtrip_duplicates_idempotence_and_order(tmp_path):
    directory = inputs(tmp_path)
    evidence = sample()
    partial = replace(evidence, text=evidence.text.replace("Del01al28", "Del07al28"))
    assert partial.text != evidence.text
    db = str(tmp_path / "isolated.sqlite")
    with patch("scripts.ingest_altran.extract_pdf_document",
               side_effect=[evidence, evidence, partial] * 2) as extract:
        assert run_ingestion(directory, db) == IngestionResult(3, 3, 0, 0, 2, 2)
        first = sorted(DatabaseService(db).obtener_todos(), key=lambda r: r["id"])
        assert run_ingestion(directory, db) == IngestionResult(3, 3, 0, 0, 2, 2)
    assert [c.args[0].name for c in extract.call_args_list] == ["a.pdf", "b.pdf", "z.PDF"] * 2
    assert sorted(DatabaseService(db).obtener_todos(), key=lambda r: r["id"]) == first
    from src.parsers.altran_parser import AltranParser
    expected = {d.id: d for d in (
        AltranParser().parse_extracted(evidence), AltranParser().parse_extracted(partial)
    )}
    assert len(first) == len(expected) == 2
    assert "2098-02-ALTRAN-2098-02-07_2098-02-28" in expected
    for row in first:
        restored = Nomina.from_dict(json.loads(row["payload"]))
        assert restored == expected[row["id"]]
        assert restored.descuento_seguridad_social is None
        assert restored.conceptos[-1].atraso is True
        assert restored.conceptos[-1].base == 0
        assert restored.conceptos[-1].unidades is None
        assert restored.conceptos[-1].importe == 0
        assert restored.conceptos[-1].columna == "devengos"


def test_certificate_and_scan_never_reach_parser(tmp_path, capsys):
    directory = inputs(tmp_path, ("payroll-looking.pdf", "anything.pdf"))
    db = str(tmp_path / "isolated.sqlite")
    with patch("scripts.ingest_altran.extract_pdf_document",
               side_effect=[CERTIFICATE, ExtractedDocument("")]), patch(
        "scripts.ingest_altran.ParserFactory"
    ) as factory:
        assert run_ingestion(directory, db) == IngestionResult(2, 0, 2, 0, 0, 0)
        factory.assert_not_called()
    assert DatabaseService(db).obtener_todos() == []
    output = capsys.readouterr().out
    assert "certificado" in output and "sin texto" in output
    assert "OMITIDO" in output


@pytest.mark.parametrize("evidence", [
    ExtractedDocument("documento textual inválido"),
    ExtractedDocument("Certificado de retenciones e ingresos a cuenta"),
    ExtractedDocument(CERTIFICATE.text + "\nPeriodo Código Concepto Cantidad/Base Precio/% Devengos Deducciones"),
])
def test_real_failure_exit_one(tmp_path, evidence):
    directory = inputs(tmp_path, ("nomina.pdf",))
    db = str(tmp_path / "isolated.sqlite")
    with patch("scripts.ingest_altran.extract_pdf_document", return_value=evidence):
        assert main(["--pdf-dir", str(directory), "--db", db]) == 1
    assert DatabaseService(db).obtener_todos() == []


def test_processing_continues_after_error(tmp_path):
    directory = inputs(tmp_path)
    with patch("scripts.ingest_altran.extract_pdf_document",
               side_effect=[ValueError("synthetic failure"), sample(), CERTIFICATE]):
        assert run_ingestion(directory, str(tmp_path / "db.sqlite")) == IngestionResult(3, 1, 1, 1, 1, 1)


def test_omissions_exit_zero(tmp_path):
    directory = inputs(tmp_path, ("scan.pdf",))
    with patch("scripts.ingest_altran.extract_pdf_document", return_value=ExtractedDocument("")):
        assert main(["--pdf-dir", str(directory), "--db", str(tmp_path / "db.sqlite")]) == 0


@pytest.mark.parametrize("args,expected", [
    ([], {"pdf_dir": "data/test/altran", "db_path": "data/runtime/nominas.sqlite"}),
    (["--pdf-dir", "custom/input", "--db", "isolated.sqlite"],
     {"pdf_dir": "custom/input", "db_path": "isolated.sqlite"}),
])
def test_cli(args, expected):
    with patch("scripts.ingest_altran.run_ingestion", return_value=IngestionResult()) as run:
        assert main(args) == 0
        run.assert_called_once_with(**expected)


@pytest.mark.parametrize("missing", [True, False])
def test_missing_or_empty_directory(tmp_path, missing):
    directory = tmp_path / "missing"
    if not missing:
        directory.mkdir()
    db = tmp_path / "not-created.sqlite"
    assert main(["--pdf-dir", str(directory), "--db", str(db)]) == 1
    assert not db.exists()


def test_sqlite_failure_counted_and_connection_released(tmp_path):
    directory = inputs(tmp_path, ("sample.pdf",))
    db = str(tmp_path / "isolated.sqlite")
    DatabaseService(db).init_db()
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TRIGGER reject_write BEFORE INSERT ON documentos "
                     "BEGIN SELECT RAISE(ABORT, 'synthetic rejection'); END")
    with patch("scripts.ingest_altran.extract_pdf_document", return_value=sample()):
        assert run_ingestion(directory, db) == IngestionResult(1, 0, 0, 1, 0, 0)
    with sqlite3.connect(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.rollback()


def test_memory_connection_closed(tmp_path):
    directory = inputs(tmp_path, ("sample.pdf",))
    service = DatabaseService(":memory:")
    with patch("scripts.ingest_altran.DatabaseService", return_value=service), patch(
        "scripts.ingest_altran.extract_pdf_document", return_value=sample()
    ):
        assert run_ingestion(directory, ":memory:") == IngestionResult(1, 1, 0, 0, 1, 1)
    assert service._shared_conn is not None
    with pytest.raises(sqlite3.ProgrammingError):
        service._shared_conn.execute("SELECT 1")
