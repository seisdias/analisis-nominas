"""Portable ingestion tests: synthetic models, mocked extraction, temporary SQLite."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.ingest_ineco import IngestionResult, main, run_ingestion
from src.models.nomina import Nomina
from src.services.database_service import DatabaseService
from src.services.ingestion_service import NoExtractableTextError, parse_nomina_pdf


def payroll() -> Nomina:
    return Nomina(id="2099-01-INECO", anio=2099, mes=1, periodo="2099-01",
                  empresa="Ing.y Econ.del Transporte", cif="A28220168",
                  total_devengado=100, total_deducir=10, liquido_percibir=90)


def test_counts_order_and_upsert(tmp_path: Path) -> None:
    directory = tmp_path / "input"
    directory.mkdir()
    for name in ("c.PDF", "a.pdf", "b.pdf"):
        (directory / name).touch()  # Extraction is mocked; no private documents.
    db = str(tmp_path / "test.sqlite")
    doc = payroll()
    with patch("scripts.ingest_ineco.parse_nomina_pdf", side_effect=[
        doc, NoExtractableTextError(), ValueError("Synthetic invalid payroll"),
    ]) as parse:
        assert run_ingestion(directory, db) == IngestionResult(1, 1, 1)
        assert [call.args[0].name for call in parse.call_args_list] == ["a.pdf", "b.pdf", "c.PDF"]
    assert len(DatabaseService(db).obtener_todos()) == 1
    doc.total_deducir, doc.liquido_percibir = 15, 85
    with patch("scripts.ingest_ineco.parse_nomina_pdf", side_effect=[
        doc, NoExtractableTextError(), ValueError("Synthetic invalid payroll"),
    ]):
        assert run_ingestion(directory, db) == IngestionResult(1, 1, 1)
    saved = DatabaseService(db).obtener_todos()
    assert len(saved) == 1
    assert saved[0]["liquido_percibir"] == 85


def test_empty_text_never_reaches_factory() -> None:
    page = MagicMock()
    page.extract_text.return_value = "  "
    with patch("src.services.ingestion_service.pdfplumber.open") as opened, patch(
        "src.services.ingestion_service.ParserFactory"
    ) as factory:
        opened.return_value.__enter__.return_value.pages = [page]
        with pytest.raises(NoExtractableTextError):
            parse_nomina_pdf("synthetic.pdf")
        factory.assert_not_called()


def test_wrong_company_not_saved(tmp_path: Path) -> None:
    (tmp_path / "synthetic.pdf").touch()
    doc = payroll()
    doc.cif = "TEST"
    db = str(tmp_path / "test.sqlite")
    with patch("scripts.ingest_ineco.parse_nomina_pdf", return_value=doc):
        assert run_ingestion(tmp_path, db) == IngestionResult(0, 0, 1)
    assert DatabaseService(db).obtener_todos() == []


def test_persistence_failure_is_not_success(tmp_path: Path) -> None:
    (tmp_path / "synthetic.pdf").touch()
    with patch("scripts.ingest_ineco.parse_nomina_pdf", return_value=payroll()), patch.object(
        DatabaseService, "guardar_documento", side_effect=RuntimeError("Synthetic DB failure")
    ):
        assert run_ingestion(tmp_path, str(tmp_path / "test.sqlite")) == IngestionResult(0, 0, 1)


def test_empty_directory_does_not_create_database(tmp_path: Path) -> None:
    db = tmp_path / "test.sqlite"
    with pytest.raises(ValueError, match="No hay PDFs"):
        run_ingestion(tmp_path, str(db))
    assert not db.exists()


@pytest.mark.parametrize(("result", "exit_code"), [(IngestionResult(1, 2, 0), 0),
                                                      (IngestionResult(0, 0, 1), 1)])
def test_cli_database_and_exit_status(result: IngestionResult, exit_code: int) -> None:
    with patch("scripts.ingest_ineco.run_ingestion", return_value=result) as run:
        assert main(["--db", "synthetic.sqlite"]) == exit_code
        run.assert_called_once_with(pdf_dir="data/test/ineco", db_path="synthetic.sqlite")


@pytest.mark.parametrize("directory", ["data/testdata/ineco", "data/test/ineco", "custom/input"])
def test_cli_explicit_input_directory(directory: str) -> None:
    with patch("scripts.ingest_ineco.run_ingestion", return_value=IngestionResult(1)) as run:
        assert main(["--pdf-dir", directory, "--db", "synthetic.sqlite"]) == 0
        run.assert_called_once_with(pdf_dir=directory, db_path="synthetic.sqlite")


def test_cli_defaults_and_invalid_directory() -> None:
    with patch("scripts.ingest_ineco.run_ingestion", return_value=IngestionResult()) as run:
        assert main([]) == 0
        run.assert_called_once_with(pdf_dir="data/test/ineco", db_path="data/runtime/nominas.sqlite")
    with patch("scripts.ingest_ineco.run_ingestion", side_effect=ValueError("Missing input")):
        assert main([]) == 1


@pytest.mark.parametrize("suffix", ["", "-EXTRA"])
def test_legacy_full_month_id_is_updated_not_duplicated(tmp_path: Path, suffix: str) -> None:
    from src.parsers.ineco_parser import InecoParser
    from tests.test_ineco_parser import OLD

    text = OLD if not suffix else OLD.replace("9001", "9033 Paga extra Navi 100,00\n9001")
    parsed = InecoParser().parse(text)
    db = str(tmp_path / "isolated.sqlite")
    service = DatabaseService(db)
    service.init_db()
    old = payroll()
    old.id = "2099-10-INECO" + suffix
    service.guardar_documento(old)
    (tmp_path / "input.pdf").touch()
    with patch("scripts.ingest_ineco.parse_nomina_pdf", return_value=parsed):
        assert run_ingestion(tmp_path, db) == IngestionResult(1)
    rows = service.obtener_todos()
    assert len(rows) == 1 and rows[0]["id"] == old.id
    assert rows[0]["total_devengado"] == parsed.total_devengado


def test_split_month_persists_both_periods_idempotently(tmp_path: Path) -> None:
    from src.parsers.ineco_parser import InecoParser
    from tests.test_ineco_parser import OLD

    docs = [InecoParser().parse(OLD.replace("31.10.2099", "09.10.2099")),
            InecoParser().parse(OLD.replace("01.10.2099", "10.10.2099"))]
    for name in ("a.pdf", "b.pdf"):
        (tmp_path / name).touch()
    db = str(tmp_path / "isolated.sqlite")
    with patch("scripts.ingest_ineco.parse_nomina_pdf", side_effect=docs * 2):
        assert run_ingestion(tmp_path, db) == IngestionResult(2)
        first = DatabaseService(db).obtener_todos()
        assert run_ingestion(tmp_path, db) == IngestionResult(2)
    assert DatabaseService(db).obtener_todos() == first
    assert len(first) == 2 and len({row["id"] for row in first}) == 2
    assert {row["fecha_inicio"] for row in first} == {"2099-10-01", "2099-10-10"}
