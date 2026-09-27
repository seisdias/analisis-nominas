# -*- coding: utf-8 -*-

from pathlib import Path

import pdfplumber
import pytest

from src.models.documento_laboral import TipoDocumento
from src.parsers.coritel_parser import CoritelParser

CORITEL_DIR = Path("data/test/coritel")


EXPECTED = {
    "200604_coritel.pdf": (2006, 4, TipoDocumento.NOMINA_ORDINARIA, 900.01, 105.01, 795.00),
    "200605_coritel.pdf": (2006, 5, TipoDocumento.NOMINA_ORDINARIA, 964.29, 114.29, 850.00),
    "200606_coritel.pdf": (2006, 6, TipoDocumento.NOMINA_ORDINARIA, 964.29, 114.29, 850.00),
    "200607_2_coritel.pdf": (2006, 7, TipoDocumento.PAGA_EXTRA, 482.16, 22.16, 460.00),
    "200607_coritel.pdf": (2006, 7, TipoDocumento.NOMINA_ORDINARIA, 964.29, 114.29, 850.00),
    "200608_coritel.pdf": (2006, 8, TipoDocumento.NOMINA_ORDINARIA, 964.29, 114.29, 850.00),
    "200609_coritel.pdf": (2006, 9, TipoDocumento.NOMINA_ORDINARIA, 964.29, 114.29, 850.00),
    "200610_coritel.pdf": (2006, 10, TipoDocumento.NOMINA_ORDINARIA, 1142.86, 157.86, 985.00),
    "200611_coritel.pdf": (2006, 11, TipoDocumento.NOMINA_ORDINARIA, 1542.86, 227.86, 1315.00),
    "200612_2_coritel.pdf": (2006, 12, TipoDocumento.PAGA_EXTRA, 1142.86, 107.86, 1035.00),
    "200612_coritel.pdf": (2006, 12, TipoDocumento.NOMINA_ORDINARIA, 1142.86, 192.86, 950.00),
    "200701_coritel.pdf": (2007, 1, TipoDocumento.NOMINA_ORDINARIA, 1462.86, 252.86, 1210.00),
    "200702_coritel.pdf": (2007, 2, TipoDocumento.NOMINA_ORDINARIA, 1142.86, 217.86, 925.00),
    "200703_coritel.pdf": (2007, 3, TipoDocumento.NOMINA_ORDINARIA, 1529.84, 264.84, 1265.00),
    "200704_coritel.pdf": (2007, 4, TipoDocumento.NOMINA_ORDINARIA, 1142.86, 217.86, 925.00),
    "200705_coritel.pdf": (2007, 5, TipoDocumento.NOMINA_ORDINARIA, 1521.31, 276.31, 1245.00),
    "200706_coritel.pdf": (2007, 6, TipoDocumento.NOMINA_ORDINARIA, 1142.86, 232.86, 910.00),
}


def get_coritel_pdfs() -> list[Path]:
    return sorted(CORITEL_DIR.glob("*.pdf"))


@pytest.mark.skipif(
    not get_coritel_pdfs(),
    reason="No hay PDFs en data/test/coritel/",
)
@pytest.mark.parametrize("pdf_path", get_coritel_pdfs())
def test_parse_coritel_pdf(pdf_path: Path) -> None:
    parser = CoritelParser()

    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    nomina = parser.parse(text, filename=pdf_path.name)

    (
        expected_year,
        expected_month,
        expected_type,
        expected_gross,
        expected_deductions,
        expected_net,
    ) = EXPECTED[pdf_path.name]

    assert nomina.anio == expected_year
    assert nomina.mes == expected_month
    assert nomina.tipo == expected_type
    assert nomina.total_devengado == pytest.approx(expected_gross, abs=0.01)
    assert nomina.total_deducir == pytest.approx(expected_deductions, abs=0.01)
    assert nomina.liquido_percibir == pytest.approx(expected_net, abs=0.01)
