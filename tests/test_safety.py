"""Synthetic regression tests for the public bootstrap's safety boundaries."""

import pytest

from src.models import Nomina
from src.parsers.alten_parser import AltenParser
from src.parsers.altran_parser import AltranParser
from src.parsers.coritel_parser import CoritelParser
from src.parsers.exceltic_parser import ExcelticParser
from src.parsers.ineco_parser import InecoParser
from src.parsers.insis_parser import InsisParser
from src.parsers.parser_factory import ParserFactory
from src.services.database_service import DatabaseService


@pytest.mark.parametrize("parser", [AltenParser(), AltranParser(), ExcelticParser(), InecoParser(), InsisParser()])
def test_missing_period_is_rejected(parser):
    with pytest.raises(ValueError, match="period"):
        parser.parse("", filename="synthetic.pdf")


def test_coritel_never_fabricates_payroll() -> None:
    with pytest.raises(
        ValueError,
        match="Missing Coritel payroll period",
    ):
        CoritelParser().parse(
            "Synthetic unsupported document",
            "synthetic.pdf",
        )


@pytest.mark.parametrize("text", ["unknown company", "alten altran"])
def test_factory_rejects_unknown_or_ambiguous(text):
    with pytest.raises(ValueError):
        ParserFactory().obtener_parser(text)


@pytest.mark.parametrize("company", ["alten", "altran", "exceltic", "ineco", "insis", "coritel"])
def test_factory_explicit_registry(company):
    assert ParserFactory().obtener_parser(company) is not None


def test_storage_preserves_details_and_updates_duplicates():
    service = DatabaseService(":memory:")
    service.init_db()
    assert service.obtener_todos() == []
    doc = Nomina(id="synthetic", anio=2099, mes=1, periodo="2099-01",
                 empresa="Synthetic", cif="TEST", complementos=12.5,
                 irpf_porcentaje=10, base_irpf=100)
    service.guardar_documento(doc)
    saved = service.obtener_todos()[0]
    assert saved["complementos"] == 12.5
    assert saved["irpf_porcentaje"] == 10

    doc.complementos = 25.0
    service.guardar_documento(doc)

    saved_docs = service.obtener_todos()

    assert len(saved_docs) == 1
    assert saved_docs[0]["id"] == "synthetic"
    assert saved_docs[0]["complementos"] == 25.0

    assert len(service.obtener_todos()) == 1


def test_alten_missing_totals_is_rejected():
    with pytest.raises(ValueError, match="totals"):
        AltenParser().parse("LIQUIDO A PERCIBIR 100,00", "209901_synthetic.pdf")


def test_insis_unknown_month_is_rejected():
    with pytest.raises(ValueError):
        InsisParser().parse("Período DE UNKNOWN DE 2099", "synthetic.pdf")
