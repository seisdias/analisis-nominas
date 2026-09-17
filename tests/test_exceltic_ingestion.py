"""Synthetic extraction, real temporary SQLite: no private corpus values."""
import json
import sqlite3
from dataclasses import replace
from unittest.mock import patch

import pytest

from scripts.ingest_exceltic import IngestionResult, main, run_ingestion
from src.models.nomina import Nomina
from src.parsers.exceltic_parser import ExcelticParser
from src.services.database_service import DatabaseService
from src.services.ingestion_service import NoExtractableTextError
from tests.test_exceltic_parser import SAMPLE


def documents():
    full = ExcelticParser().parse(SAMPLE)
    partial = ExcelticParser().parse(SAMPLE.replace(
        "Del 01 de 02 al 28 de 02 de 2098", "Del 11 de 05 al 31 de 05 de 2098",
    ))
    return full, partial


def inputs(tmp_path, names=("z.PDF", "a.pdf", "b.pdf")):
    directory = tmp_path / "input"
    directory.mkdir()
    for name in names:
        (directory / name).touch()
    (directory / "ignored.txt").touch()
    (directory / "subdirectory.pdf").mkdir()
    return directory


def test_physical_files_economic_ids_idempotence_and_full_roundtrip(tmp_path, capsys):
    directory = inputs(tmp_path)
    full, partial = documents()
    db = str(tmp_path / "isolated.sqlite")
    parsed = [full, replace(full), partial]
    with patch("scripts.ingest_exceltic.parse_nomina_pdf", side_effect=parsed * 2) as parse:
        assert run_ingestion(directory, db) == IngestionResult(3, 3, 0, 0, 2, 2)
        first = DatabaseService(db).obtener_todos()
        assert run_ingestion(directory, db) == IngestionResult(3, 3, 0, 0, 2, 2)
    assert [c.args[0].name for c in parse.call_args_list] == ["a.pdf", "b.pdf", "z.PDF"] * 2
    assert DatabaseService(db).obtener_todos() == first
    assert len(first) == 2
    expected = {d.id: d for d in (full, partial)}
    for row in first:
        recovered = Nomina.from_dict(json.loads(row["payload"]))
        assert recovered == expected[row["id"]]
        assert recovered.base_at_ep == 2100
        assert recovered.prorrata_pagas_extra is None
        assert recovered.descuento_seguridad_social is None
        assert recovered.otras_deducciones is None
        assert len(recovered.conceptos) == 11
        assert {c.columna for c in recovered.conceptos} == {"devengos", "deducciones"}
    assert partial.id == "2098-05-EXCELTIC-2098-05-11_2098-05-31"
    assert (partial.fecha_inicio, partial.fecha_fin) == ("2098-05-11", "2098-05-31")
    out = capsys.readouterr().out
    assert "procesados=3" in out and "documentos_economicos=2" in out and "filas_finales=2" in out


def test_legacy_full_month_upsert_and_final_count_scope(tmp_path):
    directory = inputs(tmp_path, ("payroll.pdf",))
    full, _ = documents()
    db = str(tmp_path / "legacy.sqlite")
    service = DatabaseService(db)
    service.init_db()
    service.guardar_documento(replace(full, base_at_ep=None, conceptos=[]))
    service.guardar_documento(replace(full, id="other-company", cif="TEST", empresa="Synthetic"))
    service.guardar_documento(replace(full, id="existing-exceltic", mes=1))
    with patch("scripts.ingest_exceltic.parse_nomina_pdf", return_value=full):
        assert run_ingestion(directory, db) == IngestionResult(1, 1, 0, 0, 1, 2)
    rows = service.obtener_todos()
    assert len(rows) == 3
    saved = next(r for r in rows if r["id"] == full.id)
    assert Nomina.from_dict(json.loads(saved["payload"])) == full


def test_omission_real_failure_and_exit_one(tmp_path):
    directory = inputs(tmp_path)
    db = str(tmp_path / "isolated.sqlite")
    full, _ = documents()
    with patch("scripts.ingest_exceltic.parse_nomina_pdf", side_effect=[
        full, NoExtractableTextError(), ValueError("Synthetic invalid document"),
    ]):
        assert main(["--pdf-dir", str(directory), "--db", db]) == 1
    assert len(DatabaseService(db).obtener_todos()) == 1


def test_omission_is_not_failure(tmp_path):
    directory = inputs(tmp_path, ("scan.pdf",))
    with patch("scripts.ingest_exceltic.parse_nomina_pdf", side_effect=NoExtractableTextError()):
        assert main(["--pdf-dir", str(directory), "--db", str(tmp_path / "scan.sqlite")]) == 0


def test_wrong_company_fails_without_persisting(tmp_path):
    directory = inputs(tmp_path, ("other.pdf",))
    full, _ = documents()
    db = str(tmp_path / "isolated.sqlite")
    with patch("scripts.ingest_exceltic.parse_nomina_pdf", return_value=replace(full, cif="TEST")):
        assert run_ingestion(directory, db) == IngestionResult(1, 0, 0, 1, 0, 0)


def test_real_sqlite_write_failure_is_counted(tmp_path):
    directory = inputs(tmp_path, ("payroll.pdf",))
    db = str(tmp_path / "isolated.sqlite")
    service = DatabaseService(db)
    service.init_db()
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TRIGGER reject_write BEFORE INSERT ON documentos "
                     "BEGIN SELECT RAISE(ABORT, 'synthetic write rejection'); END")
    with patch("scripts.ingest_exceltic.parse_nomina_pdf", return_value=documents()[0]):
        assert run_ingestion(directory, db) == IngestionResult(1, 0, 0, 1, 0, 0)
    with sqlite3.connect(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.rollback()


@pytest.mark.parametrize("args,expected", [
    ([], {"pdf_dir": "data/test/exceltic", "db_path": "data/runtime/nominas.sqlite"}),
    (["--pdf-dir", "custom/input", "--db", "custom.sqlite"],
     {"pdf_dir": "custom/input", "db_path": "custom.sqlite"}),
])
def test_cli_paths(args, expected):
    with patch("scripts.ingest_exceltic.run_ingestion", return_value=IngestionResult()) as run:
        assert main(args) == 0
        run.assert_called_once_with(**expected)


@pytest.mark.parametrize("error", [ValueError("input"), OSError("filesystem"), sqlite3.OperationalError("db")])
def test_cli_setup_failure(error):
    with patch("scripts.ingest_exceltic.run_ingestion", side_effect=error):
        assert main([]) == 1


@pytest.mark.parametrize("missing", [True, False])
def test_missing_or_empty_input_does_not_create_database(tmp_path, missing):
    directory = tmp_path / "input"
    if not missing:
        directory.mkdir()
    db = tmp_path / "never-created.sqlite"
    assert main(["--pdf-dir", str(directory), "--db", str(db)]) == 1
    assert not db.exists()


def test_memory_database_connection_closed(tmp_path):
    directory = inputs(tmp_path, ("payroll.pdf",))
    service = DatabaseService(":memory:")
    with patch("scripts.ingest_exceltic.DatabaseService", return_value=service), patch(
        "scripts.ingest_exceltic.parse_nomina_pdf", return_value=documents()[0],
    ):
        assert run_ingestion(directory, ":memory:") == IngestionResult(1, 1, 0, 0, 1, 1)
    assert service._shared_conn is not None
    with pytest.raises(sqlite3.ProgrammingError):
        service._shared_conn.execute("SELECT 1")
